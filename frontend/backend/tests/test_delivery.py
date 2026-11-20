"""Delivery migration, immutable provenance and real inference regressions."""
import hashlib
import io
import json
from pathlib import Path
from types import SimpleNamespace
import zipfile

import pytest
from fastapi.testclient import TestClient

import app
import delivery
import local_product


def digest_tree(root):
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob('*') if p.is_file()}


@pytest.fixture
def legacy(tmp_path, monkeypatch):
    monkeypatch.setattr(app, 'STATE_DIR', tmp_path / 'state')
    monkeypatch.setattr(app, 'TASKS_FILE', tmp_path / 'state/tasks.json')
    monkeypatch.setattr(app, 'store', app.TaskStore())
    monkeypatch.setattr(app.replay_recorder, 'observe_task', lambda *a: None)
    monkeypatch.setattr(app, 'get_global_settings', lambda: app.GlobalSettingsModel(python={'executable': app.sys.executable}, llm={}))
    monkeypatch.delenv('AUTODECISION_API_TOKEN', raising=False)
    data = tmp_path / 'data'; data.mkdir()
    (data / 'rows.csv').write_text('value\n3\n4\n')
    task = app.store.create(app.TaskConfigPayload(task_name='legacy', input_root=str(data), output_root=str(tmp_path / 'runs')))
    ws = tmp_path / 'workspace'; root = ws / 'best_solution'; root.mkdir(parents=True)
    (ws / 'input').mkdir(); (ws / 'input/description.md').write_text('frozen task contract')
    logs = tmp_path / 'logs'; logs.mkdir()
    code = "def predict(model_path, data):\n    return {'answer': data['value'] * 2}\ndef train(*args):\n    raise RuntimeError('training must not run')\n"
    (root / 'solution.py').write_text(code, encoding='utf-8')
    manifest = {'node_id': 'selected-1', 'entrypoint': 'predict', 'artifact_required': False}
    (root / 'solution_manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
    (logs / 'journal.json').write_text(json.dumps({'nodes': [{'id': 'selected-1', 'code': code}]}), encoding='utf-8')
    task.auto_ml_workspace_dir = str(ws); task.auto_ml_log_dir = str(logs); task.status = 'completed'
    client = TestClient(app.app)
    response = client.post('/api/studio/import-tasks', json={'task_ids': [task.id]})
    assert response.status_code == 200, response.text
    project = client.get('/api/studio/state').json()['projects'][0]
    return SimpleNamespace(client=client, task=task, project=project, root=root, ws=ws, logs=logs,
                           url=f'/api/studio/tasks/{task.id}/delivery', manifest=manifest, code=code, data=data)


def prepare(case):
    response = case.client.post(case.url, json={'confirm': True})
    assert response.status_code == 200, response.text
    result = response.json()
    assert result['structure_ready'], result
    return result


def verify(case, prepared, data='{"value":7}', **extra):
    return case.client.post(case.url + '/verify', json={'confirm': True, 'delivery_id': prepared['delivery_id'],
                           'data_json': data, **extra})


def test_legacy_prepare_trial_publish_and_call_preserve_originals(legacy):
    c = legacy; before = digest_tree(c.ws); log_before = digest_tree(c.logs)
    assert c.client.get(c.url).json()['status'] == 'needs_preparation'
    prepared = prepare(c)
    assert prepared['draft']['input_schema'] == {}
    assert prepared['draft']['observed_input_fields'] == ['value']
    assert prepared['draft']['observed_output_fields'] == ['answer']
    assert prepared['verification']['status'] == 'not_run'
    assert prepare(c)['delivery_id'] == prepared['delivery_id']
    check = verify(c, prepared)
    assert check.status_code == 200, check.text
    assert check.json()['status'] == 'passed' and check.json()['trial']['result'] == {'answer': 14}
    assert c.client.get(c.url).json()['verification']['trial']['input_sha256'] == hashlib.sha256(b'{"value":7}').hexdigest()
    publish = c.client.post('/api/studio/packages', json={'project_id': c.project['id'], 'task_id': c.task.id,
        'name': 'compatible', 'delivery_id': prepared['delivery_id'], 'description': 'twice', 'output_description': 'answer'})
    assert publish.status_code == 200, publish.text
    package = publish.json()
    assert package['verification']['delivery']['status'] == 'passed'
    bundle = c.client.get(f"/api/studio/packages/{package['id']}/bundle")
    with zipfile.ZipFile(io.BytesIO(bundle.content)) as archive:
        assert len(archive.namelist()) == len(set(archive.namelist())), 'duplicate contract entries'
        assert archive.read('contract/description.md') == b'frozen task contract'
        assert json.loads(archive.read('capability.json'))['delivery_id'] == prepared['delivery_id']
        assert json.loads(archive.read('delivery_verification.json'))['trial']['result'] == {'answer': 14}
        assert {'DELIVERY.md', 'delivery_contract.json', 'generated_solution.py'} <= set(archive.namelist())
    invoked = c.client.post('/api/studio/invocations', json={'project_id': c.project['id'], 'request_id': 'migrated',
        'steps': [{'package_id': package['id'], 'data_json': '{"value":9}'}], 'confirm': True})
    assert invoked.status_code == 200 and invoked.json()['status'] == 'completed', invoked.text
    assert invoked.json()['result'] == {'answer': 18}
    assert digest_tree(c.ws) == before and digest_tree(c.logs) == log_before


def test_delivery_reports_autoreport_failure_as_its_own_status(legacy):
    c = legacy
    c.task.status, c.task.phase = 'failed', 'report_failed'

    result = c.client.get(c.url).json()

    assert result['report_ready'] is False
    assert result['report_status'] == 'failed'


@pytest.mark.parametrize(
    ('configured_seed', 'contract_seed', 'expected'),
    [(20260907, 20240517, 'mismatch'), (20240517, 20240517, 'matched'), (None, 20240517, 'unverified')],
)
def test_final_evaluation_exposes_split_seed_consistency(legacy, configured_seed, contract_seed, expected):
    c = legacy
    c.task.execution_config = {'auto_ml': {'eval': f'random_state={configured_seed}' if configured_seed else ''}}
    realize = c.ws / 'input' / 'realize_report'
    realize.mkdir()
    (realize / 'evaluation_contract_report.json').write_text(json.dumps({
        'final': {'validation_protocol': f'stratified split random_state={contract_seed}'}
    }), encoding='utf-8')

    check = delivery.split_seed_check(app, c.task, c.ws)

    assert check['status'] == expected
    assert check['configured_random_state'] == configured_seed
    assert check['contract_random_state'] == contract_seed


@pytest.mark.parametrize('problem', ['journal_mismatch', 'journal_missing', 'final_identity', 'final_failed', 'model_missing', 'running', 'unsupported_signature'])
def test_cannot_invent_evidence_or_repair_missing_model(legacy, problem):
    c = legacy
    if problem == 'journal_mismatch':
        (c.logs / 'journal.json').write_text('{"nodes": []}')
    elif problem == 'journal_missing':
        (c.logs / 'journal.json').unlink()
    elif problem in {'final_identity', 'final_failed'}:
        (c.ws / 'final_evaluation').mkdir()
        (c.ws / 'final_evaluation/status.json').write_text(json.dumps({'status': 'failed' if problem == 'final_failed' else 'completed',
            'selection': {'node_id': 'selected-1' if problem == 'final_failed' else 'other'}}))
    elif problem == 'model_missing':
        (c.root / 'solution_manifest.json').write_text(json.dumps({**c.manifest, 'artifact_required': True, 'artifact_path': 'missing.pkl'}))
    elif problem == 'running':
        c.task.status = 'running'
        c.task.run_started_at = app.now_ts()
    else:
        code = 'def predict(model, data, extra): return data'
        (c.root / 'solution.py').write_text(code)
        (c.logs / 'journal.json').write_text(json.dumps({'nodes': [{'id': 'selected-1', 'code': code}]}))
    before = digest_tree(c.ws)
    response = c.client.post(c.url, json={'confirm': True})
    assert response.status_code == 409, response.text
    assert digest_tree(c.ws) == before
    assert not (delivery.area(app, c.task.id) / 'current.json').exists()
    assert c.task.id not in delivery.BUSY_TASKS


def test_invalid_final_result_error_explains_returned_metrics_and_field_failure(legacy):
    c = legacy
    final = c.ws / 'final_evaluation'
    final.mkdir()
    (final / 'status.json').write_text(json.dumps({
        'status': 'invalid_result_fields',
        'selection': {'node_id': 'selected-1'},
        'result_field_errors': ['inference_checks: expected an object or an array of objects'],
    }))
    (final / 'result.json').write_text(json.dumps({
        'status': 'completed',
        'metrics': {'holdout_mae': 0.08},
        'inference_checks': ['malformed'],
    }))

    response = c.client.post(c.url, json={'confirm': True})

    assert response.status_code == 409
    assert '已运行并返回指标' in response.json()['detail']
    assert 'runner 接受' in response.json()['detail']
    assert 'inference_checks' in response.json()['detail']


@pytest.mark.parametrize('target', ['solution.py', 'contract/description.md', '../input/description.md', 'current.json'])
def test_damaged_copy_is_blocked_and_can_be_rebuilt_from_source(legacy, target):
    c = legacy; prepared = prepare(c)
    metadata = delivery.current(app, c.task.id)
    copy = delivery.prepared_root(app, c.task.id, metadata)
    path = delivery.area(app, c.task.id) / target if target == 'current.json' else copy / target
    path.write_text('changed', encoding='utf-8')
    assert c.client.get(f'/api/tasks/{c.task.id}/solution').status_code == 409
    assert c.client.get(c.url).json()['status'] == 'needs_rebuild'
    rebuilt = prepare(c)
    assert rebuilt['delivery_id'] != prepared['delivery_id']
    assert copy.exists(), 'damaged revision is preserved for audit'
    assert rebuilt['verification']['status'] == 'not_run'


def test_source_changed_requires_new_review_and_keeps_old_revision(legacy):
    c = legacy; old = prepare(c)
    (c.ws / 'input/description.md').write_text('changed task contract')
    assert verify(c, old).status_code == 409
    assert c.client.get(c.url).json()['status'] == 'needs_rebuild'
    new = prepare(c)
    assert new['delivery_id'] != old['delivery_id']
    result = c.client.post('/api/studio/packages', json={'project_id': c.project['id'], 'task_id': c.task.id,
        'name': 'stale', 'delivery_id': old['delivery_id']})
    assert result.status_code == 409


def test_invalid_input_failure_and_wrong_delivery_are_distinguished(legacy):
    c = legacy; prepared = prepare(c)
    assert verify(c, {**prepared, 'delivery_id': '0' * 32}).status_code == 409
    assert verify(c, prepared, 'NaN').status_code == 400
    failed = verify(c, prepared, '{}')
    assert failed.status_code == 200 and failed.json()['status'] == 'failed', failed.text
    assert 'trial' not in failed.json()
    assert c.client.get(c.url).json()['verification']['status'] == 'failed'
    passed = verify(c, prepared).json()
    assert passed['status'] == 'passed'


def test_explicit_dataframe_and_csv_trials(legacy):
    c = legacy
    code = "PREDICT_COLUMNS = ['value']\ndef predict(model, data):\n    return data[PREDICT_COLUMNS].sum().to_dict()\n"
    (c.root / 'solution.py').write_text(code)
    (c.logs / 'journal.json').write_text(json.dumps({'nodes': [{'id': 'selected-1', 'code': code}]}))
    prepared = prepare(c)
    frames = prepared['draft']['dataframes']
    assert frames == [{'pointer': '', 'columns': ['value']}]
    checked = verify(c, prepared, '[{"value":3},{"value":4}]', dataframes=frames)
    assert checked.json()['status'] == 'passed' and checked.json()['trial']['result'] == {'value': 7}, checked.text
    assert verify(c, prepared, '[{"wrong":3}]', dataframes=frames).status_code == 400
    assert verify(c, prepared, '[{"value":3}]', dataframes=frames * 2).status_code == 400
    assert verify(c, prepared, '[]', dataframes=[{'pointer': 'broken', 'columns': ['value']}]).status_code == 400
    csv = verify(c, prepared, input_mode='csv', csv_path=str(c.data / 'rows.csv'))
    assert csv.json()['status'] == 'passed' and csv.json()['trial']['result'] == {'value': 7}, csv.text
    assert verify(c, prepared, input_mode='csv', csv_path=str(c.data / 'rows.csv'), dataframes=frames).status_code == 400


def test_preparing_does_not_import_candidate_and_busy_operation_blocks_archive(legacy):
    c = legacy
    marker = c.ws / 'executed'
    code = f"from pathlib import Path\nPath({str(marker)!r}).write_text('imported')\n" + c.code
    (c.root / 'solution.py').write_text(code)
    (c.logs / 'journal.json').write_text(json.dumps({'nodes': [{'id': 'selected-1', 'code': code}]}))
    prepare(c)
    assert not marker.exists()
    with delivery.operation(c.task.id):
        assert c.client.post(c.url, json={'confirm': True}).status_code == 409
        assert c.client.post(f"/api/studio/projects/{c.project['id']}/archive").status_code == 409
    assert c.client.post(f"/api/studio/projects/{c.project['id']}/archive").status_code == 200
    assert c.client.post(c.url, json={'confirm': True}).status_code == 410


def test_source_change_during_trial_never_records_pass(legacy, monkeypatch):
    c = legacy; prepared = prepare(c)
    def racing_trial(*args, **kwargs):
        (c.ws / 'input/description.md').write_text('changed while running')
        return {'result': {'answer': 14}}
    monkeypatch.setattr(delivery, 'execute_trial', racing_trial)
    assert verify(c, prepared).status_code == 409
    assert delivery.current(app, c.task.id)['verification']['status'] == 'not_run'


def test_completed_final_identity_uses_executed_source_and_normalizes_old_crlf(legacy):
    c = legacy; final = c.ws / 'final_evaluation'; final.mkdir()
    (final / 'selected_solution.py').write_bytes(c.code.replace('\n', '\r\n').encode())
    state = {'status': 'completed', 'selection': {'node_id': 'selected-1'},
        'executed_code_sha256': hashlib.sha256(c.code.encode()).hexdigest(), 'serialization_module': 'frozen_final_module'}
    (final / 'status.json').write_text(json.dumps(state))
    import shutil
    shutil.copytree(final, c.root / 'final_evaluation')
    prepared = prepare(c)
    assert prepared['draft']['implementation_path'] == 'frozen_final_module.py'
    assert verify(c, prepared).json()['status'] == 'passed'
    (final / 'selected_solution.py').write_text('changed')
    (c.ws / 'input/description.md').write_text('force new revision')
    assert c.client.post(c.url, json={'confirm': True}).status_code == 409


def test_recorded_run_contract_links_are_materialized_with_provenance(legacy):
    c = legacy
    c.task.run_dir = str(c.ws.parent / 'recorded-run')
    original = Path(c.task.run_dir) / 'autorealize/description.md'
    original.parent.mkdir(parents=True); original.write_text('linked historical contract')
    link = c.ws / 'input/description.md'; link.unlink(); link.symlink_to(original)
    prepared = prepare(c)
    assert any('AutoRealize' in item for item in prepared['draft']['unresolved'])
    copy = delivery.prepared_root(app, c.task.id, delivery.current(app, c.task.id))
    assert (copy / 'contract/description.md').read_text() == original.read_text()
    assert not (copy / 'contract/description.md').is_symlink()
    provenance = json.loads((copy / 'contract_provenance.json').read_text(encoding='utf-8'))
    assert provenance['files'][0]['mode'] == 'recorded_run_autorealize_link_snapshot'
    assert link.is_symlink()
    original.write_text('subsequently changed')
    assert verify(c, prepared).status_code == 409


def test_contract_link_cannot_point_to_an_unrelated_file(legacy):
    c = legacy
    c.task.run_dir = str(c.ws.parent / 'recorded-run')
    allowed = Path(c.task.run_dir) / 'autorealize/description.md'
    allowed.parent.mkdir(parents=True); allowed.write_text('allowed')
    unrelated = c.ws.parent / 'private.txt'; unrelated.write_text('not a task contract')
    link = c.ws / 'input/description.md'; link.unlink(); link.symlink_to(unrelated)
    assert c.client.post(c.url, json={'confirm': True}).status_code == 409


def test_large_historical_contract_is_copied_whole_with_bounded_size(legacy, monkeypatch):
    c = legacy
    text = 'x' * (5 * 1024**2)
    (c.ws / 'input/description.md').write_text(text)
    prepare(c)
    copy = delivery.prepared_root(app, c.task.id, delivery.current(app, c.task.id))
    assert (copy / 'contract/description.md').read_text() == text
    monkeypatch.setattr(local_product, 'CONTRACT_MAX_BYTES', 1024)
    assert c.client.post(c.url, json={'confirm': True}).status_code == 413


def test_final_loading_recovery_endpoint_keeps_failure_and_frozen_identity(legacy):
    c = legacy
    source = '''from pathlib import Path
def predict(model_path,data): return {'answer':data['value']*2}
def final_evaluate(data,artifact_dir):
    model = artifact_dir/'frozen.bin'
    model.write_bytes(b'unchanged')
    return {'status':'completed','metrics':{'mae':1},'model_path':model.name,'inference_checks':{}}
'''
    c.root.joinpath('solution.py').write_text(source, encoding='utf-8')
    protocol = {'evaluation_phase':'search'}
    node = {'id':'selected-1','code':source,'metric':{'value':1.0},'evaluation_protocol':protocol}
    c.logs.joinpath('journal.json').write_text(json.dumps({'nodes':[node]}), encoding='utf-8')
    final = c.ws/'final_evaluation'; final.mkdir()
    final.joinpath('selected_solution.py').write_text(source, encoding='utf-8', newline='\n')
    checksum = hashlib.sha256(source.encode()).hexdigest()
    state = {'status':'failed','holdout_access_possible':True,'executed_code_sha256':checksum,
        'selection':{'node_id':node['id'],'code_sha256':checksum,'selection_score':1.0,'selection_protocol':protocol}}
    final.joinpath('status.json').write_text(json.dumps(state), encoding='utf-8')
    final.joinpath('execution.log').write_text("pickle.py\nAttributeError: Can't get attribute 'Model' on <module '__main__' from 'runfile.py'>")
    url = f'/api/studio/tasks/{c.task.id}/final-evaluation'
    before = c.client.get(url).json()
    assert before['can_repair_loading']
    endpoint = url+'/repair-loading'
    payload = {'confirm':True,'expected_status_sha256':before['status_sha256']}
    assert c.client.post(endpoint,json={**payload,'confirm':False}).status_code == 400
    assert c.client.post(endpoint,json={**payload,'expected_status_sha256':'0'*64}).status_code == 409
    with delivery.operation(c.task.id):
        assert c.client.post(endpoint,json=payload).status_code == 409
    response = c.client.post(endpoint,json=payload)
    assert response.status_code == 200, response.text
    after = response.json()
    assert after['status']=='completed' and after['result']['metrics']=={'mae':1}
    assert not after['can_repair_loading']
    assert json.loads((Path(after['prior_attempt_review']['previous_attempt'])/'status.json').read_text())==state
    assert c.client.post(endpoint,json=payload).status_code == 409
    assert json.loads((c.logs/'journal.json').read_text())['nodes']==[node]


def report_fixture(c, monkeypatch):
    import sys
    sys.path.insert(0, str(app.AUTOREPORT_DIR))
    from autoreport.collector import collect_evidence
    from autoreport.config import AutoReportConfig, EvidencePath
    from autoreport.delivery import build_delivery_contract, persist_delivery
    from autoreport.events import ReportEventWriter
    c.task.status, c.task.phase = 'running', 'report'
    c.task.run_started_at = app.now_ts()
    report_dir = c.ws.parent / 'report'
    report_dir.mkdir(exist_ok=True)
    receipt = delivery.begin_report(app, c.task, report_dir)
    assert receipt['status'] == 'prepared', receipt
    cfg = AutoReportConfig(task_name='legacy', output_dir=str(report_dir), evidence_paths=[EvidencePath('delivery_source', str(report_dir / 'delivery_source.json'))])
    bundle = collect_evidence(cfg, ReportEventWriter(report_dir, print_events_to_console=False))
    semantic = dict(name='历史双倍算法', description='既有算法直接推理。', input_description='输入 value 数值', output_description='answer 数值',
        input_schema={'type': 'object', 'required': ['value'], 'properties': {'value': {'type': 'number'}}},
        dependencies=[], limitations=['本次只核对接口。'], unresolved=[], dataframes=[])
    article = '# 历史任务报告\n\n复用冻结实现，不重新训练。\n'
    contract = build_delivery_contract('legacy', bundle, article, {'status': 'pass'}, semantic)
    persist_delivery(report_dir, contract)
    (report_dir / 'report.md').write_bytes(article.encode())
    (report_dir / 'report.json').write_text(json.dumps({'delivery': contract}), encoding='utf-8')
    return receipt, report_dir, contract


def test_autoreport_prepares_legacy_revision_then_publish_and_real_inference(legacy, monkeypatch):
    c = legacy
    original = digest_tree(c.ws)
    receipt, report_dir, contract = report_fixture(c, monkeypatch)
    old = delivery.current(app, c.task.id)
    frozen = digest_tree(delivery.prepared_root(app, c.task.id, old))
    delivery.import_report(app, c.task, report_dir, receipt)
    c.task.status, c.task.phase = 'completed', 'report_completed'
    result = c.client.get(c.url).json()
    assert result['report_ready'] and result['draft']['generator'] == 'AutoReport'
    assert result['delivery_id'] != old['id']
    assert digest_tree(delivery.prepared_root(app, c.task.id, old)) == frozen
    published = c.client.post('/api/studio/packages', json={'project_id': c.project['id'], 'task_id': c.task.id,
        'delivery_id': result['delivery_id'], 'name': contract['name'], 'description': contract['description'],
        'input_schema': contract['input_schema'], 'output_description': contract['output_description']})
    assert published.status_code == 200, published.text
    package = published.json()
    assert {'REPORT.md', 'DELIVERY.md', 'report_provenance.json'} <= {p['path'] for p in package['files']}
    invocation = c.client.post('/api/studio/invocations', json={'project_id': c.project['id'], 'request_id': 'report-only',
        'steps': [{'package_id': package['id'], 'data_json': '{"value":11}'}], 'confirm': True})
    assert invocation.status_code == 200, invocation.text
    assert invocation.json()['result'] == {'answer': 22}
    assert digest_tree(c.ws) == original


@pytest.mark.parametrize('mismatch', ['receipt', 'report_hash', 'contract_identity', 'source_changed', 'newer_attempt'])
def test_autoreport_rejects_stale_or_mismatched_documents(legacy, monkeypatch, mismatch):
    c = legacy
    receipt, report_dir, contract = report_fixture(c, monkeypatch)
    old = delivery.current(app, c.task.id)
    if mismatch == 'receipt':
        receipt['delivery_id'] = '0' * 32
    elif mismatch == 'report_hash':
        (report_dir / 'report.md').write_text('changed')
    elif mismatch == 'contract_identity':
        contract['node_id'] = 'another'
        (report_dir / 'delivery_contract.json').write_text(json.dumps(contract), encoding='utf-8')
        (report_dir / 'report.json').write_text(json.dumps({'delivery': contract}), encoding='utf-8')
    elif mismatch == 'source_changed':
        (c.root / 'solution.py').write_text(c.code + '# changed')
    else:
        app.write_json(delivery.area(app, c.task.id) / 'report_attempt.json', {'report_run_id': 'newer'})
    with pytest.raises(app.HTTPException):
        delivery.import_report(app, c.task, report_dir, receipt)
    assert delivery.current(app, c.task.id)['id'] == old['id']


def test_report_only_rerun_claims_before_return_and_allows_disabled_automatic_report(legacy, monkeypatch):
    c = legacy
    c.task.config.auto_report.enabled = False
    monkeypatch.setattr(app, '_validate_autoreport_rerun', lambda task: (_ for _ in ()).throw(app.HTTPException(409, 'running')) if task.status == 'running' else None)
    launched = []
    class DelayedThread:
        def __init__(self, **kw): launched.append(kw)
        def start(self): pass
    monkeypatch.setattr(app.threading, 'Thread', DelayedThread)
    response = c.client.post('/api/tasks/rerun-autoreport', json={'task_id': c.task.id, 'confirm': True})
    assert response.status_code == 200, response.text
    assert c.task.status == 'running' and c.task.phase == 'report'
    checkpoint = launched[0]['args'][1]
    assert checkpoint.status == 'completed' and not checkpoint.config.auto_report.enabled
    assert c.client.post('/api/tasks/rerun-autoreport', json={'task_id': c.task.id, 'confirm': True}).status_code == 409


def test_historical_rerun_drives_autoreport_and_delivery_in_same_pipeline(legacy, monkeypatch):
    import sys
    sys.path.insert(0, str(app.AUTOREPORT_DIR))
    from autoreport.collector import collect_evidence
    from autoreport.config import config_from_dict
    from autoreport.events import ReportEventWriter
    from autoreport.generator import generate_report, _report_section_titles
    c = legacy
    before = digest_tree(c.ws)
    report_dir = c.ws.parent / 'new-report'
    c.task.config.auto_report.enabled = False
    original_config = c.task.config.model_dump()
    c.task.run_dir = str(c.ws.parent / 'run')
    ar = c.ws.parent / 'ar'; ar.mkdir()
    (ar / 'description.md').write_text('Use value and return answer; never train during inference.')
    monkeypatch.setattr(app, '_validate_autoreport_rerun', lambda _: (Path(c.task.run_dir), ar, c.ws.parent, c.logs, c.ws, report_dir))
    monkeypatch.setattr(app, '_selected_model', lambda *a, **kw: {'model': 'test', 'apiKey': 'unused', 'baseUrl': 'https://example.invalid'})
    requests = []
    def transport(url, payload, **kw):
        requests.append(payload)
        if len(requests) == 1:
            result = {'problem': {}, 'method_cards': [], 'best_method': {}, 'comparison': [], 'reuse': {}, 'retrieve_requests': [], 'analysis_complete': True,
                'delivery_contract': dict(name='自动交付', description='双倍计算', input_description='输入 value 数值', output_description='输出 answer 数值',
                input_schema={'type': 'object', 'properties': {'value': {'type': 'number'}}, 'required': ['value']}, dependencies=[], limitations=['需核对业务边界'], unresolved=[], dataframes=[])}
            content = json.dumps(result)
        elif len(requests) == 2:
            content = '# 双倍结果\n\n' + '\n\n'.join('## '+title+'\n\n实际输入输出与边界。' for title in _report_section_titles(SimpleNamespace(language='zh')))
        elif 'Review the delivery contract' in json.dumps(payload, ensure_ascii=False):
            content = json.dumps(dict(name='自动交付', description='双倍计算', input_description='输入 value 数值',
                output_description='输出 answer 数值', input_schema={'type': 'object', 'properties': {'value': {'type': 'number'}},
                'required': ['value']}, dependencies=[], limitations=['需核对业务边界'], unresolved=[], dataframes=[]))
        else:
            content = json.dumps({'status': 'pass', 'issues': [], 'edits': []})
        return {'choices': [{'message': {'content': content}}]}
    monkeypatch.setattr('autoreport.generator._post_json_with_retry', transport)
    def service(base, endpoint, payload, **kwargs):
        assert endpoint == '/jobs/start'
        cfg = config_from_dict({**payload['config'], 'task_name': payload['task_name'], 'output_dir': payload['output_dir'],
            'evidence_paths': payload['evidence_paths'], 'llm': {**payload['config']['llm'], 'api_key': 'unused'}})
        events = ReportEventWriter(report_dir, print_events_to_console=False)
        generate_report(cfg, collect_evidence(cfg, events), events)
        # Simulate a long report; its runtime handle must survive through import.
        c.task.run_started_at = app.now_ts() - 100
        return {'job_id': 'real-report-pipeline'}
    monkeypatch.setattr(app, '_json_post', service)
    monkeypatch.setattr(app, '_poll_remote_job', lambda *a, **kw: {'status': 'completed', 'exit_code': 0})
    app._rerun_autoreport_thread(c.task.id, c.task.model_copy(deep=True))
    assert c.task.status == 'completed' and c.task.phase == 'report_completed', c.task.last_error
    assert c.task.config.model_dump() == original_config
    result = c.client.get(c.url).json()
    assert result['report_ready'] and result['draft']['input_schema']['required'] == ['value']
    assert len(requests) == 4, 'the audited report must also reconcile its delivery contract'
    assert digest_tree(c.ws) == before
