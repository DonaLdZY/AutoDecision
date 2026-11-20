"""Evidence-backed delivery copies; never mutate a historical search workspace."""
from __future__ import annotations

import hashlib
from contextlib import contextmanager
import importlib.util
import json
import math
from pathlib import Path
import re
import shutil
import subprocess
import os
import threading
import time
import uuid
import zipfile

from fastapi import HTTPException
from local_product import (CONTRACT_FILES, SolutionTrial, execute_trial, export_solution_bundle,
                           fingerprint, inspect_source_solution, safe_file, solution_files,
                           contract_sources, CONTRACT_MAX_BYTES, CONTRACT_TOTAL_BYTES)
from local_product import stop_process_tree

LOCK = threading.RLock()
BUSY_TASKS: set[str] = set()


def _random_state(value):
    match = re.search(r"\brandom[_ -]?state\s*[:=]\s*(\d+)\b", str(value or ""), re.IGNORECASE)
    return int(match.group(1)) if match else None


def split_seed_check(g, task, workspace=None):
    execution = getattr(task, 'execution_config', None) or task.config
    automl = execution.get('auto_ml', {}) if isinstance(execution, dict) else getattr(execution, 'auto_ml', None)
    configured_eval = automl.get('eval', '') if isinstance(automl, dict) else getattr(automl, 'eval', '')
    configured_seed = _random_state(configured_eval)

    contract_paths = []
    if workspace is not None:
        contract_paths.append(Path(workspace) / 'input/realize_report/evaluation_contract_report.json')
    for run_dir in g._candidate_task_run_dirs(task):
        contract_paths.extend((
            run_dir / 'autorealize/realize_report/evaluation_contract_report.json',
            run_dir / 'realize_report/evaluation_contract_report.json',
        ))
    contract = {}
    for path in contract_paths:
        if path.is_file():
            contract = g.safe_read_json(path, {})
            if contract:
                break
    final_contract = contract.get('final') if isinstance(contract, dict) else {}
    frozen_seed = _random_state(final_contract.get('validation_protocol', '')) if isinstance(final_contract, dict) else None
    if configured_seed is None or frozen_seed is None:
        status = 'unverified'
    else:
        status = 'matched' if configured_seed == frozen_seed else 'mismatch'
    return {
        'status': status,
        'configured_random_state': configured_seed,
        'contract_random_state': frozen_seed,
    }


def inference_repair_record(g, workspace, original):
    """Expose a source-bound regression receipt without promoting it to a blind evaluation."""
    root = Path(workspace) / 'best_solution'
    manifest = g.safe_read_json(root / 'solution_manifest.json', {})
    revision = manifest.get('inference_revision') or {}
    if not revision:
        return None
    try:
        provenance = json.loads(safe_file(root, root / revision['provenance']).read_text(encoding='utf-8'))
        validation = json.loads(safe_file(root, root / revision['validation']).read_text(encoding='utf-8'))
        evaluation = json.loads(safe_file(root, root / 'inference_repair_evaluation.json').read_text(encoding='utf-8'))
        source = safe_file(root, root / manifest['implementation_path'])
        model_spec = safe_file(root, root / 'model_path.txt').read_text(encoding='utf-8').strip()
        model = safe_file(root, root / model_spec)
        source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
        model_hash = hashlib.sha256(model.read_bytes()).hexdigest()
        if (source_hash != revision['source_sha256'] or source_hash != validation['source_sha256']
                or model_hash != validation['model_sha256'] or model_hash != provenance['repaired_model_sha256']
                or revision['parent_frozen_source_sha256'] != original.get('executed_code_sha256')):
            raise ValueError('修复记录与当前实现、模型或原始评估来源不一致')
        metrics = evaluation.get('metrics')
        if (validation.get('status') != 'passed' or evaluation.get('status') != 'completed'
                or not isinstance(metrics, dict) or not metrics or metrics != validation.get('metrics')
                or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in metrics.values())):
            raise ValueError('修复复验记录未完成或指标无效')
        return {'status': 'recorded', 'metrics': metrics, 'prior_holdout_exposure': True,
            'source_sha256': source_hash, 'model_sha256': model_hash,
            'checks': validation.get('checks', {}),
            'scope': '修复后的回归复验记录，已核对实现与模型指纹；测试集此前已查看，不属于新的盲测。'}
    except (OSError, ValueError, KeyError, TypeError, HTTPException) as exc:
        return {'status': 'unavailable', 'issues': [str(getattr(exc, 'detail', exc))]}


def final_evaluation_status(g, task):
    log = g._pick_local_automl_log_dir(task)
    workspace = g._pick_local_automl_workspace_dir(task, log.name if log else None)
    if not workspace or not (Path(workspace)/'final_evaluation/status.json').is_file():
        return {'status': 'not_started', 'can_repair_loading': False,
                'split_seed_check': split_seed_check(g, task, workspace)}
    workspace = Path(workspace)
    path = safe_file(workspace, workspace/'final_evaluation/status.json')
    raw = path.read_bytes()
    result = json.loads(raw)
    execution = workspace/'final_evaluation/execution.log'
    text = safe_file(workspace, execution).read_text(encoding='utf-8') if execution.is_file() else ''
    repairable = (result.get('status') == 'failed' and not (workspace/'final_evaluation/result.json').exists()
        and "AttributeError: Can't get attribute" in text and "on <module '__main__'" in text
        and ('pickle.py' in text or 'numpy_pickle.py' in text))
    result['can_repair_loading'] = repairable and task.status != 'running'
    result['status_sha256'] = hashlib.sha256(raw).hexdigest()
    result['split_seed_check'] = split_seed_check(g, task, workspace)
    repair = inference_repair_record(g, workspace, result)
    if repair is not None:
        result['inference_repair'] = repair
    metrics = workspace/'final_evaluation/result.json'
    if metrics.is_file():
        result['result'] = json.loads(safe_file(workspace, metrics).read_text(encoding='utf-8'))
    return result


def retry_final_loading(g, task, expected_status_sha256):
    if task.status == 'running':
        raise HTTPException(409, '任务运行中，不能重试最终评估')
    current = final_evaluation_status(g, task)
    if not current['can_repair_loading'] or current['status_sha256'] != expected_status_sha256:
        raise HTTPException(409, '最终评估状态已变化或不属于可修复的模型加载失败')
    log = g._pick_local_automl_log_dir(task)
    workspace = Path(g._pick_local_automl_workspace_dir(task, log.name))
    journal = safe_file(log, log/'journal.json')
    settings = g.get_global_settings()
    env = os.environ.copy()
    for key in list(env):
        if any(word in key.upper() for word in ('API_KEY', 'APIKEY', 'TOKEN', 'SECRET')):
            env.pop(key)
    env.update(OMP_NUM_THREADS='4', MKL_NUM_THREADS='4', OPENBLAS_NUM_THREADS='4', CUDA_VISIBLE_DEVICES='')
    log_path = workspace/'final-recovery-process.log'
    with log_path.open('ab') as stream:
        process = subprocess.Popen([str(settings.python.get('executable') or g.sys.executable),
            str(g.ALGOEVOLVE_DIR/'retry_final_evaluation.py'), '--workspace', str(workspace),
            '--journal', str(journal), '--expected-status-sha256', expected_status_sha256],
            cwd=g.ALGOEVOLVE_DIR, env=env, stdout=stream, stderr=stream,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        try:
            process.wait(timeout=660)
        except subprocess.TimeoutExpired:
            stop_process_tree(process)
            raise HTTPException(504, '最终评估恢复超时，已保留运行记录，请核查状态')
    if process.returncode:
        raise HTTPException(409, '最终评估恢复失败，原始尝试及恢复记录已保留')
    return final_evaluation_status(g, task)


@contextmanager
def operation(task_id):
    """Claim before checking project membership; archive cannot race this operation."""
    with LOCK:
        if task_id in BUSY_TASKS:
            raise HTTPException(409, '该任务正在整理、验证或发布交付，请等待完成')
        BUSY_TASKS.add(task_id)
    try:
        yield
    finally:
        with LOCK:
            BUSY_TASKS.discard(task_id)


def helper(g):
    # Trusted stdlib-only packaging utility; candidate modules are never imported here.
    path = g.ALGOEVOLVE_DIR / 'engine/solution_package.py'
    spec = importlib.util.spec_from_file_location('autodecision_delivery_tools', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def source_fingerprint(task, root):
    files, _ = solution_files(root)
    inventory = []
    for path, name in files:
        stat = path.stat()
        row = [name, stat.st_size, stat.st_mtime_ns]
        if path.suffix in {'.py', '.json', '.txt', '.md'}:
            row.append(hashlib.sha256(path.read_bytes()).hexdigest())
        inventory.append(row)
    for name, path, mode in contract_sources(task, root):
        inventory.append(['contract/' + name, str(path), mode, hashlib.sha256(path.read_bytes()).hexdigest()])
    return fingerprint(inventory)


def area(g, task_id):
    return g.STATE_DIR / 'deliveries' / task_id


def current(g, task_id):
    path = area(g, task_id) / 'current.json'
    if not path.is_file():
        return None
    try:
        metadata = json.loads(safe_file(area(g, task_id), path).read_text(encoding='utf-8'))
        if not isinstance(metadata, dict) or not re.fullmatch(r'[a-f0-9]{32}', str(metadata.get('id', ''))):
            raise ValueError('invalid identity')
        if not all(k in metadata for k in ('source_fingerprint', 'sha256', 'fingerprint', 'contract_sha256')):
            raise ValueError('incomplete metadata')
        return metadata
    except (ValueError, OSError) as exc:
        raise HTTPException(409, '交付副本记录损坏，请重新生成交付包') from exc


def save_current(g, task_id, metadata):
    directory = area(g, task_id)
    temporary = directory / ('.current-' + uuid.uuid4().hex + '.tmp')
    try:
        g.write_json(temporary, metadata, sensitive=True)
        temporary.replace(directory / 'current.json')
    finally:
        temporary.unlink(missing_ok=True)


def prepared_root(g, task_id, metadata):
    root = area(g, task_id) / metadata['id'] / 'best_solution'
    if not re.fullmatch(r'[a-f0-9]{32}', metadata['id']):
        raise HTTPException(409, '交付副本标识无效')
    return root


def hashes(root):
    result = {}
    for path, name in solution_files(root)[0]:
        with safe_file(root, path).open('rb') as stream:
            result[name] = hashlib.file_digest(stream, 'sha256').hexdigest()
    return result


def normalized_source_sha256(path: Path) -> str:
    """Hash Python source with canonical newlines for legacy Windows exports."""
    text = Path(path).read_text(encoding='utf-8-sig')
    normalized = text.replace('\r\n', '\n').replace('\r', '\n')
    return hashlib.sha256(normalized.encode('utf-8')).hexdigest()


def verify_copy(root, metadata):
    if hashes(root) != metadata['sha256'] or contract_hashes(root.parent) != metadata['contract_sha256']:
        raise HTTPException(409, '交付副本文件发生变化，请重新生成并核对')


def contract_hashes(workspace):
    result = {}
    total = 0
    for name in CONTRACT_FILES:
        path = workspace / 'input' / name
        if path.is_file():
            path = safe_file(workspace, path)
            size = path.stat().st_size
            total += size
            if size > CONTRACT_MAX_BYTES or total > CONTRACT_TOTAL_BYTES:
                raise HTTPException(413, '合同超过单文件16 MiB或合计64 MiB交付上限')
            result[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def resolve_prepared(g, task, source_info, source_root):
    metadata = current(g, task.id)
    if not metadata:
        return None
    if not source_root or source_info.get('issues') or source_fingerprint(task, source_root) != metadata['source_fingerprint']:
        raise HTTPException(409, '来源产物或冻结合同已变化，需要重新生成交付副本')
    root = prepared_root(g, task.id, metadata)
    verify_copy(root, metadata)
    info, _ = inspect_source_solution(g, task, package_root=root)
    info['delivery_id'] = metadata['id']
    return info, root


def status(g, task):
    info, source = inspect_source_solution(g, task)
    try:
        metadata = current(g, task.id)
        prepared = resolve_prepared(g, task, info, source) if task.status != 'running' else None
    except HTTPException as exc:
        return {'status': 'needs_rebuild', 'structure_ready': False, 'draft': None, 'issues': [str(exc.detail)],
                'verification': {'status': 'not_run'}, 'source_preserved': True}
    if prepared:
        info, root = prepared
        draft = json.loads((root / 'delivery_contract.json').read_text(encoding='utf-8'))
        report = report_readiness(g, task, metadata)
        return {**report, 'status': 'prepared', 'structure_ready': bool(info.get('trial_ready')), 'delivery_id': metadata['id'],
                'draft': draft, 'issues': [*info.get('issues', []), *report.get('report_issues', [])], 'verification': metadata.get('verification', {'status': 'not_run'}),
                'source_node_id': info['node_id'], 'source_preserved': True}
    draft = None
    if source and (source / 'delivery_contract.json').is_file():
        draft = json.loads(safe_file(source, source / 'delivery_contract.json').read_text(encoding='utf-8'))
    issues = list(info.get('issues', []))
    if metadata and task.status != 'running':
        issues.append('来源产物或冻结合同已变化，需要重新生成交付副本')
    if info.get('available') and not info.get('trial_ready') and not issues:
        issues.append('缺少实现引用或指纹，可尝试生成兼容交付副本')
    return {**report_readiness(g, task, metadata), 'status': 'source_changed' if metadata else 'ready' if info.get('trial_ready') else 'needs_preparation',
            'structure_ready': bool(info.get('trial_ready')), 'draft': draft, 'issues': issues,
            'verification': {'status': 'not_run'}, 'source_preserved': True}


def identify_legacy_source(g, task, info, root):
    manifest = info['manifest']
    node_id = manifest['node_id']
    # A completed final model may pickle custom classes under this exact module name.
    state_path = root.parent / 'final_evaluation/status.json'
    if state_path.is_file():
        state = json.loads(safe_file(root.parent, state_path).read_text(encoding='utf-8'))
        if state.get('selection', {}).get('node_id') != node_id:
            raise HTTPException(409, '最终评估身份与选定方案不一致，不能自动迁移')
        if state.get('status') == 'completed':
            source = safe_file(root.parent, root.parent / 'final_evaluation/selected_solution.py')
            if state.get('executed_code_sha256') != normalized_source_sha256(source):
                raise HTTPException(409, '最终实现指纹无法核对，不能自动迁移')
            return source, state['serialization_module'], 'final_evaluation.executed_code_sha256'
        if state.get('status') == 'invalid_result_fields':
            result_path = state_path.with_name('result.json')
            result = json.loads(safe_file(root.parent, result_path).read_text(encoding='utf-8')) if result_path.is_file() else {}
            errors = state.get('result_field_errors')
            error_detail = '；'.join(str(item) for item in errors) if isinstance(errors, list) else ''
            if isinstance(result, dict) and result.get('status') == 'completed' and isinstance(result.get('metrics'), dict) and result['metrics']:
                detail = '最终评估代码已运行并返回指标，但结果字段校验未通过；指标尚未被 runner 接受，不能作为已验证交付'
            else:
                detail = '最终评估结果未通过字段校验，不能作为已验证交付'
            if error_detail:
                detail += '：' + error_detail
            raise HTTPException(409, detail)
        if state.get('status') not in {'not_applicable', 'not_provided'}:
            raise HTTPException(409, '最终评估未完成，需先核对失败或中断状态')
    log = g._pick_local_automl_log_dir(task)
    if log is None:
        raise HTTPException(409, '缺少原搜索日志，无法核对选定实现；请人工核查来源')
    journal = json.loads(safe_file(log, log / 'journal.json').read_text(encoding='utf-8'))
    node = next((n for n in journal.get('nodes', []) if n.get('id') == node_id), None)
    source = safe_file(root, root / 'solution.py')
    if not node or source.read_text(encoding='utf-8-sig') != str(node.get('code', '')).replace('\r\n', '\n'):
        raise HTTPException(409, '当前代码与原选定节点不一致，不能自动生成兼容交付')
    return source, 'autodecision_delivery_' + re.sub(r'\W', '_', node_id), 'journal.selected_node.code'


def _report_snapshot(g, task):
    latest = g.store.get(task.id)
    if latest.status != 'running' or latest.phase != 'report':
        raise HTTPException(409, '报告阶段已结束或任务发生变化')
    return latest.model_copy(deep=True, update={'status': 'completed'})


def prepare(g, task, *, report_stage=False):
    temporary = None
    response = None
    try:
        if report_stage:
            task = _report_snapshot(g, task)
        if task.status == 'running':
            raise HTTPException(409, '任务运行中，停止或完成后再整理交付')
        info, source_root = inspect_source_solution(g, task)
        if not info.get('exportable'):
            raise HTTPException(409, '；'.join(info.get('issues', ['尚无选定产物'])))
        signature = source_fingerprint(task, source_root)
        try:
            old = current(g, task.id)
            if old and old['source_fingerprint'] == signature:
                verify_copy(prepared_root(g, task.id, old), old)
                return status(g, task)
        except HTTPException as exc:
            if exc.status_code != 409:
                raise
            # Rebuild from the original evidence; keep the damaged revision for audit.
        tools = helper(g)
        identified = identify_legacy_source(g, task, info, source_root) if not info.get('trial_ready') else None
        response = export_solution_bundle(g, task, info, source_root)
        delivery_id = uuid.uuid4().hex
        temporary = area(g, task.id) / delivery_id
        root = temporary / 'best_solution'; root.mkdir(parents=True)
        with zipfile.ZipFile(response.path) as archive:
            for name in archive.namelist():
                if not (root / name).resolve().is_relative_to(root.resolve()):
                    raise HTTPException(409, '导出包包含越界路径')
            archive.extractall(root)
        # Freeze only the original experiment contracts, never today's project files.
        if (root / 'contract').is_dir():
            shutil.copytree(root / 'contract', temporary / 'input')
        if identified:
            source, module_name, evidence = identified
            if evidence == 'journal.selected_node.code':
                source = root / 'solution.py'
            else:
                copied_source = root / 'final_evaluation/selected_solution.py'
                copied_source.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, copied_source)
                if (
                    not copied_source.is_file()
                    or normalized_source_sha256(copied_source) != normalized_source_sha256(source)
                ):
                    raise HTTPException(409, '最终实现副本与身份记录不一致')
                source = copied_source
            tools.package_inference_source(root, source, module_name)
        else:
            evidence = 'existing_implementation_sha256'
            tools.draft_delivery_contract(root)
        prepared_info, _ = inspect_source_solution(g, task, package_root=root)
        if not prepared_info.get('trial_ready'):
            raise HTTPException(409, '交付结构检查未通过：' + '；'.join(prepared_info.get('issues', [])))
        sha256 = hashes(root)
        # The original inventory predates the compatibility wrapper; replace it only in the new copy.
        (root / 'package_inventory.json').write_text(json.dumps({'schema_version': 'autodecision.delivery.inventory.v1',
            'task_id': task.id, 'node_id': info['node_id'], 'sha256': {k: v for k, v in sha256.items() if k != 'package_inventory.json'},
            'source_evidence': evidence}, ensure_ascii=False, indent=2), encoding='utf-8')
        sha256 = hashes(root)
        latest = _report_snapshot(g, task) if report_stage else g.store.get(task.id)
        if latest.status == 'running' or source_fingerprint(latest, source_root) != signature:
            raise HTTPException(409, '整理期间来源任务发生变化，请停止并重新核对')
        metadata = {'id': delivery_id, 'task_id': task.id, 'source_node_id': info['node_id'],
            'source_fingerprint': signature, 'source_evidence': evidence, 'created_at': time.time(),
            'sha256': sha256, 'contract_sha256': contract_hashes(temporary),
            'fingerprint': fingerprint(sha256), 'verification': {'status': 'not_run'}}
        save_current(g, task.id, metadata)
        temporary = None  # Retain immutable revision; old revisions are also retained.
        return status(g, task)
    except (ValueError, SyntaxError, KeyError, OSError) as exc:
        raise HTTPException(409, '交付整理无法完成：' + str(exc)) from exc
    finally:
        if response:
            Path(response.path).unlink(missing_ok=True)
        if temporary:
            if temporary.resolve().is_relative_to(area(g, task.id).resolve()):
                shutil.rmtree(temporary)


def verify(g, task, payload, delivery_id):
    info, source_root = inspect_source_solution(g, task)
    prepared = resolve_prepared(g, task, info, source_root)
    metadata = current(g, task.id)
    if task.status == 'running' or not prepared or metadata['id'] != delivery_id:
        raise HTTPException(409, '交付副本不存在或已变化，请先重新整理')
    try:
        result = execute_trial(g, task, SolutionTrial(input_mode=payload.input_mode, data_json=payload.data_json,
            csv_path=payload.csv_path, timeout_seconds=payload.timeout_seconds), inspected=prepared,
            expected_hashes=metadata['sha256'], dataframes=[d.model_dump() for d in payload.dataframes], persist_trial=False)
        check = {'status': 'passed', 'checked_at': time.time(), 'delivery_id': delivery_id,
            'package_fingerprint': metadata['fingerprint'], 'trial': result,
            'scope': '仅证明本次输入的本地推理成功，不代表业务或独立评估通过。'}
    except HTTPException as exc:
        check = {'status': 'failed', 'checked_at': time.time(), 'delivery_id': delivery_id,
                 'package_fingerprint': metadata['fingerprint'], 'error': str(exc.detail)}
    with LOCK:
        latest = current(g, task.id)
        if not latest or latest['id'] != delivery_id:
            raise HTTPException(409, '试算期间交付副本发生变化，请重新核对')
        info, source_root = inspect_source_solution(g, g.store.get(task.id))
        resolve_prepared(g, g.store.get(task.id), info, source_root)
        check['input_mode'] = payload.input_mode
        check['dataframes'] = [d.model_dump() for d in payload.dataframes] if payload.input_mode == 'json' else []
        latest['verification'] = check
        save_current(g, task.id, latest)
    return check


REPORT_DOCUMENTS = ('delivery_contract.json', 'DELIVERY.md', 'REPORT.md', 'report_provenance.json')


def report_readiness(g, task, metadata=None):
    attempt = g.safe_read_json(area(g, task.id) / 'report_attempt.json', {})
    ready = bool(metadata and metadata.get('report_run_id') and
        (not attempt or attempt.get('report_run_id') == metadata['report_run_id']))
    issues = attempt.get('issues', []) if not ready else []
    failed = task.phase == 'report_failed'
    return {'report_ready': ready, 'report_issues': issues,
        'report_status': 'ready' if ready else 'generating' if task.status == 'running' and task.phase == 'report'
            else 'failed' if failed else 'blocked' if issues else 'not_generated',
        'report_run_id': metadata.get('report_run_id') if ready else attempt.get('report_run_id')}


def begin_report(g, task, report_dir):
    """Freeze delivery input once; no candidate code is imported or executed."""
    receipt = {'schema_version': 'autodecision.report_delivery_source.v1', 'report_run_id': uuid.uuid4().hex,
        'task_id': task.id, 'status': 'blocked', 'created_at': time.time()}
    with operation(task.id):
        try:
            snapshot = _report_snapshot(g, task)
            prepare(g, snapshot, report_stage=True)
            metadata = current(g, task.id)
            root = prepared_root(g, task.id, metadata)
            verify_copy(root, metadata)
            receipt.update(status='prepared', delivery_id=metadata['id'], package_dir=str(root),
                source_node_id=metadata['source_node_id'], source_fingerprint=metadata['source_fingerprint'],
                package_fingerprint=metadata['fingerprint'], verification=metadata.get('verification', {'status': 'not_run'}))
            # Reuse reviewed input bindings only from a published package with identical
            # frozen implementation and model bytes. Never infer a binding from filenames.
            from decision_studio import database, verify_package
            manifest = json.loads((root / 'solution_manifest.json').read_text(encoding='utf-8'))
            with database(g) as db:
                packages = [row for row in db.rows('packages') if row['task_id'] == task.id]
                for package in packages:
                    identity_files = [manifest['implementation_path']]
                    if manifest.get('artifact_required'):
                        identity_files.append(manifest['artifact_path'])
                    if package.get('input_binding') and all(package['sha256'].get(name) == metadata['sha256'].get(name) for name in identity_files):
                        verify_package(g, package)
                        project = db.get('projects', package['project_id'])
                        receipt['confirmed_input_binding'] = package['input_binding']
                        receipt['binding_root'] = project['input_root']
                        receipt['prior_published_input_schema'] = package.get('input_schema', {})
                        break
        except HTTPException as exc:
            if exc.status_code not in {400, 409, 413}:
                raise
            receipt.update(status='blocked', issues=[str(exc.detail)])
        g.write_json(area(g, task.id) / 'report_attempt.json', receipt)
        g.write_json(Path(report_dir) / 'delivery_source.json', receipt)
    return receipt


def import_report(g, task, report_dir, receipt):
    """Adopt AutoReport documents into a new immutable delivery revision."""
    from decision_studio import validate_schema_document, validate_dataframe_contract, DataFrameInput
    report_dir = Path(report_dir)
    contract_path = safe_file(report_dir, report_dir / 'delivery_contract.json')
    contract = json.loads(contract_path.read_text(encoding='utf-8'))
    article = safe_file(report_dir, report_dir / 'report.md').read_bytes()
    report = json.loads(safe_file(report_dir, report_dir / 'report.json').read_text(encoding='utf-8'))
    required_identity = {key: receipt[key] for key in ('report_run_id', 'delivery_id', 'source_fingerprint', 'package_fingerprint') if key in receipt}
    if contract.get('generator') != 'AutoReport' or contract.get('source') != required_identity or report.get('delivery') != contract:
        raise HTTPException(409, 'AutoReport 交付文档与本次报告来源不一致')
    if contract.get('report_markdown_sha256') != hashlib.sha256(article).hexdigest():
        raise HTTPException(409, 'AutoReport 正文与交付说明指纹不一致')
    if receipt['status'] != 'prepared' or contract.get('status') == 'blocked':
        g.write_json(area(g, task.id) / 'report_attempt.json', {**receipt, 'status': 'blocked',
            'issues': contract.get('issues', receipt.get('issues', ['交付材料未准备完成']))})
        return
    validate_schema_document(contract.get('input_schema'))
    frames = [DataFrameInput.model_validate(frame) for frame in contract.get('dataframes', [])]
    validate_dataframe_contract(contract['input_schema'], frames)
    temporary = None
    with operation(task.id):
        snapshot = _report_snapshot(g, task)
        attempt = g.safe_read_json(area(g, task.id) / 'report_attempt.json', {})
        if attempt.get('report_run_id') != receipt['report_run_id']:
            raise HTTPException(409, '本次报告已被更新的生成请求替代')
        metadata = current(g, task.id)
        if not metadata or metadata['id'] != receipt['delivery_id'] or metadata['fingerprint'] != receipt['package_fingerprint']:
            raise HTTPException(409, '报告生成期间交付副本已变化')
        info, source = inspect_source_solution(g, snapshot)
        resolve_prepared(g, snapshot, info, source)
        root = prepared_root(g, task.id, metadata)
        manifest = json.loads((root / 'solution_manifest.json').read_text(encoding='utf-8'))
        if (contract.get('node_id') != metadata['source_node_id'] or contract.get('entrypoint') != manifest['entrypoint']
                or contract.get('implementation_sha256') != manifest['implementation_file_sha256']
                or contract.get('manifest_sha256') != metadata['sha256']['solution_manifest.json']):
            raise HTTPException(409, 'AutoReport 调用合同与冻结模型身份不一致')
        try:
            new_id = uuid.uuid4().hex
            temporary = area(g, task.id) / new_id
            shutil.copytree(root.parent, temporary, ignore=shutil.ignore_patterns('__pycache__', '*.pyc', 'runtime'))
            target = temporary / 'best_solution'
            for name in ('delivery_contract.json', 'DELIVERY.md'):
                shutil.copyfile(safe_file(report_dir, report_dir / name), target / name)
            (target / 'REPORT.md').write_bytes(article)
            provenance = {'schema_version': 'autodecision.report_delivery.v1', **required_identity,
                'report_markdown_sha256': contract['report_markdown_sha256'],
                'report_audit_status': contract['report_audit_status'], 'generator': 'AutoReport',
                'source_node_id': metadata['source_node_id']}
            g.write_json(target / 'report_provenance.json', provenance)
            inventory = hashes(target)
            g.write_json(target / 'package_inventory.json', {'schema_version': 'autodecision.delivery.inventory.v1',
                'task_id': task.id, 'node_id': metadata['source_node_id'],
                'sha256': {k: v for k, v in inventory.items() if k != 'package_inventory.json'},
                'source_evidence': metadata['source_evidence'], 'report_run_id': receipt['report_run_id']})
            sha256 = hashes(target)
            # Recorded trials remain tied to their original revision, never relabel them.
            verification = dict(metadata.get('verification', {'status': 'not_run'}))
            if verification.get('status') in {'passed', 'failed'}:
                verification['reuse_basis'] = 'document_only_revision; implementation, model and frozen inputs unchanged'
                verification['verified_delivery_id'] = verification.get('delivery_id', metadata['id'])
            updated = {**metadata, 'id': new_id, 'created_at': time.time(), 'parent_delivery_id': metadata['id'],
                'sha256': sha256, 'fingerprint': fingerprint(sha256), 'verification': verification,
                'report_run_id': receipt['report_run_id'], 'report_provenance': provenance}
            _report_snapshot(g, task)
            if source_fingerprint(snapshot, source) != receipt['source_fingerprint']:
                raise HTTPException(409, '报告生成期间源实现或冻结合同发生变化')
            verify_copy(root, metadata)
            save_current(g, task.id, updated)
            temporary = None
        finally:
            if temporary and temporary.resolve().is_relative_to(area(g, task.id).resolve()):
                shutil.rmtree(temporary)
