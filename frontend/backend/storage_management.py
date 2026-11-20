"""User-confirmed lifecycle of registered resources and local run artifacts.

Directory scans never follow links. A deletion confirmation is bound to the
resource graph and the file inventory; no client-supplied path is a delete target.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import shutil
import stat
import threading
import time
from typing import Literal
from contextlib import contextmanager

from fastapi import HTTPException
from pydantic import BaseModel, Field
from local_product import TRIAL_LOCK

Kind = Literal['projects', 'datasets', 'tasks', 'packages', 'runs']
Action = Literal['archive', 'restore', 'delete']
SECRET = secrets.token_bytes(32)
LOCK = threading.RLock()
CACHE_LOCK = threading.Lock()
SCAN_CACHE: dict[str, tuple[float, dict]] = {}


class ResourceRef(BaseModel):
    kind: Kind
    id: str = Field(min_length=1, max_length=4096)


class Selection(BaseModel):
    resources: list[ResourceRef] = Field(min_length=1, max_length=1000)
    action: Action


class ApplySelection(Selection):
    confirm: bool = False
    confirmation_token: str = Field(default='', max_length=2048)


class OpenResource(ResourceRef):
    path: str = Field(max_length=4096)


def key(kind, identity):
    return f'{kind}:{identity}'


def absolute(path):
    # Do not resolve a link into its target when constructing a deletion path.
    return Path(os.path.abspath(os.path.expanduser(str(path))))


def linked(path):
    try:
        value = path.lstat()
        return stat.S_ISLNK(value.st_mode) or bool(getattr(value, 'st_file_attributes', 0) & 0x400)
    except FileNotFoundError:
        return False


def nested(path, parent):
    return absolute(path).is_relative_to(absolute(parent))


def overlaps(first, second):
    return nested(first, second) or nested(second, first)


def exists(path):
    return os.path.lexists(path)


def unique_roots(paths):
    original = list(dict.fromkeys(absolute(p) for p in paths))
    result = []
    for path in sorted(original, key=lambda p: (len(p.parts), str(p))):
        if not any(nested(path, parent) for parent in result):
            result.append(path)
    return sorted(result, key=original.index)


def scan(path, *, fresh=False):
    """Logical bytes of regular files, without double-counting hard links."""
    path = absolute(path)
    cache_key = str(path)
    with CACHE_LOCK:
        cached = SCAN_CACHE.get(cache_key)
        if not fresh and cached and time.monotonic() - cached[0] < 15:
            return dict(cached[1])
    result = dict(path=str(path), exists=exists(path), bytes=0, files=0, directories=0, links=0, errors=[])
    digest = hashlib.sha256()
    inodes = set()
    stack = [path] if result['exists'] else []
    while stack:
        current = stack.pop()
        try:
            info = current.lstat()
            digest.update(json.dumps([str(current), info.st_mode, info.st_size, info.st_mtime_ns,
                                      info.st_dev, info.st_ino], ensure_ascii=False).encode())
            if linked(current):
                result['links'] += 1
                digest.update(os.readlink(current).encode('utf-8', errors='replace'))
            elif stat.S_ISDIR(info.st_mode):
                result['directories'] += 1
                with os.scandir(current) as entries:
                    stack.extend(sorted((Path(e.path) for e in entries), key=str, reverse=True))
            elif stat.S_ISREG(info.st_mode):
                result['files'] += 1
                inode = (info.st_dev, info.st_ino) if info.st_ino else str(current)
                if inode not in inodes:
                    result['bytes'] += info.st_size
                    inodes.add(inode)
        except OSError as error:
            result['errors'].append(f'{current}: {error.strerror or type(error).__name__}')
    result['fingerprint'] = digest.hexdigest()
    with CACHE_LOCK:
        if len(SCAN_CACHE) > 2048:
            SCAN_CACHE.clear()
        SCAN_CACHE[cache_key] = (time.monotonic(), dict(result))
    return result


def runtime_roots(g):
    root = g.APP_ROOT
    return [root/'runs', root/'.codex-work', root/'test-runs', root/'test_run/output',
            root/'core/AutoRealize/runs', root/'core/AlgoEvolve/runs', root/'core/AutoReport/runs',
            root/'core/AutoReport/.codex-work', root/'frontend/backend/runs']


def path_error(g, path):
    path = absolute(path)
    protected = [absolute(g.APP_ROOT), absolute(g.STATE_DIR), absolute(Path.home()), Path(path.anchor),
                 absolute(g.STATE_DIR/'studio/studio.sqlite3'), absolute(g.TASKS_FILE), absolute(g.GLOBAL_SETTINGS_FILE)]
    if any(nested(p, path) for p in protected):
        return '不能删除应用、用户目录或磁盘根目录'
    system_paths = [absolute(os.environ[name]) for name in ['WINDIR', 'ProgramFiles', 'ProgramFiles(x86)', 'ProgramData'] if os.environ.get(name)]
    system_paths += [Path.home()/name for name in ['.ssh', '.codex', '.conda', '.config']]
    if os.name != 'nt':
        system_paths += [Path(name) for name in ['/etc', '/usr', '/bin', '/sbin', '/System', '/Library']]
    if any(overlaps(path, directory) for directory in system_paths):
        return '该位置属于系统、安装环境或用户配置目录'
    # A registered path may never turn a source/configuration folder into output.
    if nested(path, g.APP_ROOT):
        permitted = runtime_roots(g) + [g.STATE_DIR, g.APP_ROOT/'test_data', g.APP_ROOT/'test_data_simple',
                                       g.APP_ROOT/'test_run', g.APP_ROOT/'test_tasks']
        if not any(nested(path, parent) for parent in permitted):
            return '该位置属于应用源码或配置目录'
    for parent in [path, *path.parents]:
        if linked(parent):
            return '目录路径经过符号链接或目录联接'
    if path.is_dir() and any((path/name).exists() for name in ('.git', 'node_modules')):
        return '该目录包含源码仓库或安装依赖'
    return ''


def data_id(path):
    return hashlib.sha256(os.path.normcase(str(absolute(path))).encode()).hexdigest()[:32]


def input_roots(docs, tasks):
    # Preserve nested registrations: a nested input may be an alias to a target
    # outside its lexical parent, and that target must remain protected too.
    return list(dict.fromkeys(absolute(row['input_root']) for row in [*docs['projects'], *docs['packages'],
                              *docs['storage_inputs'], *(t.model_dump() for t in tasks)] if row.get('input_root')))


def input_error(path, protected_inputs, resolved_inputs=None):
    # Check both ancestors and descendants, even for archived or selected data.
    # Resolve aliases as well as lexical paths, without ever traversing them for deletion.
    resolved_path = absolute(path).resolve()
    resolved_inputs = resolved_inputs if resolved_inputs is not None else [absolute(root).resolve() for root in protected_inputs]
    if any(overlaps(path, root) for root in protected_inputs) or any(overlaps(resolved_path, root) for root in resolved_inputs):
        return '输入数据文件夹只允许归档，不能删除其内容或上级目录'
    return ''


def task_paths(g, task, *, include_metadata=False):
    paths = []
    if task.run_dir:
        paths.append(absolute(task.run_dir))
    paths.extend(g._candidate_task_run_dirs(task))
    # Explicit stored paths also cover older layouts with separate workspaces.
    paths.extend(absolute(p) for p in [task.auto_ml_workspace_dir, task.auto_ml_log_dir, task.report_dir] if p)
    for folder in ['deliveries', 'trials']:
        paths.append(g.STATE_DIR/folder/task.id)
    if include_metadata:
        paths.append(g.replay_recorder.path(g.STATE_DIR, task.id))
        paths.extend(g.STATE_DIR.glob(task.id + '.*.config.yaml'))
    else:
        paths = [p for p in paths if not exists(p) or p.is_dir()]
    roots = unique_roots(p for p in paths if exists(p))
    if not roots:
        if task.run_dir:
            return [absolute(task.run_dir)]
        candidate = absolute(g.resolve_output_root(task.output_root)) / task.task_name
        if candidate.parent == absolute(g.resolve_output_root(task.output_root)):
            roots.append(candidate)
    return roots


def snapshot(g, studio, db):
    docs = {kind: db.rows(kind, include_archived=True) for kind in
            ['projects', 'packages', 'conversations', 'invocations', 'links', 'prepared_inputs', 'storage_archives', 'storage_inputs']}
    tasks = g.store.list_tasks(include_archived=True)
    archived = {r['id']: r for r in docs['storage_archives']}
    projects = {p['id']: p for p in docs['projects']}
    links = {r['id']: r['project_id'] for r in docs['links']}
    tasks_by_id = {t.id: t for t in tasks}
    folders = {}
    # Unregistered inputs may retain a path-only deletion guard without becoming
    # a visible dataset registration again.
    visible_inputs = [row for row in docs['storage_inputs'] if not row.get('protection_only')]
    for row in [*docs['projects'], *(t.model_dump() for t in tasks), *docs['packages'], *visible_inputs]:
        if row.get('input_root'):
            path = absolute(row['input_root'])
            folders.setdefault(data_id(path), dict(path=str(path), name=path.name))
    for project in docs['projects']:
        folders[data_id(project['input_root'])]['name'] = project['name']
    protected_inputs = input_roots(docs, tasks)
    resolved_inputs = [absolute(root).resolve() for root in protected_inputs]
    resources = {}

    def add(kind, identity, name, paths, project_id='', archived_at=None, status='', input_root='', task_id=''):
        folder_id = data_id(input_root) if input_root else ''
        folder = folders.get(folder_id, {})
        inherited = bool(projects.get(project_id, {}).get('archived_at') or
                         (kind != 'datasets' and archived.get(key('datasets', folder_id), {}).get('archived_at')))
        direct = archived_at or archived.get(key(kind, identity), {}).get('archived_at')
        item = dict(kind=kind, id=identity, name=name, project_id=project_id, status=status,
                    archived=bool(direct or inherited), archived_direct=bool(direct), inherited_archive=inherited,
                    paths=[str(p) for p in unique_roots(paths)], data_id=folder_id,
                    data_name=folder.get('name', ''), data_path=folder.get('path', ''),
                    task_id=task_id, task_name=tasks_by_id[task_id].task_name if task_id in tasks_by_id else task_id,
                    can_delete=kind in ('tasks', 'packages', 'runs'))
        if item['can_delete'] and any(input_error(p, protected_inputs, resolved_inputs) or
                                      (exists(p) and path_error(g, p)) for p in item['paths']):
            item['can_delete'] = False
        resources[key(kind, identity)] = item

    for project in docs['projects']:
        add('projects', project['id'], project['name'], [absolute(project['input_root'])],
            archived_at=project.get('archived_at'), input_root=project['input_root'])
    project_folders = {data_id(p['input_root']) for p in docs['projects']}
    for identity, folder in folders.items():
        if identity not in project_folders:
            add('datasets', identity, folder['name'], [folder['path']], input_root=folder['path'])
    for task in tasks:
        project_id = links.get(task.id, '') or next((p['id'] for p in docs['projects']
                                                   if data_id(p['input_root']) == data_id(task.input_root)), '')
        add('tasks', task.id, task.task_name, task_paths(g, task), project_id, task.archived_at, task.status,
            input_root=task.input_root, task_id=task.id)
    for package in docs['packages']:
        task = tasks_by_id.get(package.get('task_id'))
        project = projects.get(package.get('project_id'), {})
        add('packages', package['id'], package['name'], [studio.package_root(g, package)],
            package.get('project_id', ''), package.get('archived_at'),
            input_root=task.input_root if task else package.get('input_root') or project.get('input_root', ''),
            task_id=package.get('task_id', ''))
    known = [absolute(p) for r in resources.values() for p in r['paths']]
    roots = runtime_roots(g) + [g.STATE_DIR/'deliveries', g.STATE_DIR/'trials', g.STATE_DIR/'replays',
                               g.STATE_DIR/'studio/packages', g.STATE_DIR/'autorealize-cognition', g.STATE_DIR/'studio/llm_contracts']
    associations = []
    for resource in list(resources.values()):
        if resource['kind'] == 'packages':
            continue
        for path in resource['paths']:
            parent = absolute(path).parent
            if parent not in roots and any(nested(parent, root) for root in roots):
                associations.append((parent, resource))

    def discover(child):
        # Only independent directory units. Split ancestors of known resources so
        # neither task folders nor imported inputs acquire a second delete handle.
        if not child.is_dir() or linked(child) or any(nested(child, p) for p in known + protected_inputs):
            return
        if any(nested(p, child) for p in known + protected_inputs):
            for descendant in sorted(child.iterdir()):
                discover(descendant)
            return
        identity = data_id(child)
        matches = [(len(parent.parts), resource) for parent, resource in associations if nested(child, parent)]
        closest = [resource for depth, resource in matches if depth == max((d for d, _ in matches), default=0)]
        folder_ids = {r['data_id'] for r in closest if r['data_id']}
        task_ids = {r['task_id'] for r in closest if r['task_id']}
        owner = next((r for r in closest if r['data_id']), {}) if len(folder_ids) == 1 else {}
        add('runs', identity, child.name, [child], owner['id'] if owner.get('kind') == 'projects' else owner.get('project_id', ''),
            input_root=owner.get('data_path', ''), task_id=next(iter(task_ids)) if len(task_ids) == 1 and owner else '')
        known.append(absolute(child))

    for root in roots:
        if not root.is_dir() or linked(root):
            continue
        for child in sorted(root.iterdir()):
            discover(child)
    return docs, tasks, resources


def resolve_ref(ref, docs, resources):
    resource = resources.get(key(ref.kind, ref.id))
    if resource is None:
        raise HTTPException(404, '资源不存在，请刷新列表')
    return resource


def details(resource, fresh=False):
    paths = [scan(p, fresh=fresh) for p in resource['paths']]
    return {**resource, 'paths': paths, 'bytes': sum(p['bytes'] for p in paths),
            'files': sum(p['files'] for p in paths), 'complete': not any(p['errors'] for p in paths)}


def build_plan(g, studio, db, selection):
    docs, tasks, resources = snapshot(g, studio, db)
    protected_inputs = input_roots(docs, tasks)
    resolved_inputs = [absolute(root).resolve() for root in protected_inputs]
    selected = {key(r.kind, r.id): resolve_ref(r, docs, resources) for r in selection.resources}
    project_ids = {r['id'] for r in selected.values() if r['kind'] == 'projects'}
    task_ids = {r['id'] for r in selected.values() if r['kind'] == 'tasks'}
    package_ids = {r['id'] for r in selected.values() if r['kind'] == 'packages'}
    dataset_ids = {r['id'] for r in selected.values() if r['kind'] == 'datasets'}
    linked_tasks = {r['id'] for r in resources.values() if r['kind'] == 'tasks' and
                    (r['project_id'] in project_ids or r['data_id'] in dataset_ids)}
    if selection.action == 'delete':
        package_ids |= {r['id'] for r in docs['packages'] if r.get('task_id') in task_ids}
        for kind, ids in [('tasks', task_ids), ('packages', package_ids)]:
            for identity in ids:
                resource = resources.get(key(kind, identity))
                if resource:
                    selected[key(kind, identity)] = resource
    affected_task_ids = task_ids | linked_tasks
    affected_projects = project_ids
    affected_task_ids |= {r['id'] for r in docs['links'] if r['project_id'] in affected_projects}
    affected_packages = package_ids | {r['id'] for r in docs['packages'] if r.get('project_id') in project_ids or r.get('task_id') in affected_task_ids}
    invocation_ids = {r['id'] for r in docs['invocations'] if r.get('project_id') in project_ids or
                      set(r.get('package_ids', [])) & package_ids}
    busy_invocation_ids = {r['id'] for r in docs['invocations'] if r.get('project_id') in affected_projects or
                           set(r.get('package_ids', [])) & affected_packages}
    blockers = []
    if selection.action == 'delete' and any(r['kind'] in ('projects', 'datasets') for r in selected.values()):
        blockers.append('数据文件夹只允许归档或还原；删除仅适用于开发目录和代码包，请取消选择数据文件夹')
    if selection.action != 'restore':
        if TRIAL_LOCK.locked():
            blockers.append('本地推理正在运行，请等待完成')
        if any(t.id in affected_task_ids and t.status == 'running' for t in tasks):
            blockers.append('仍有执行中的研发任务，请先停止任务')
        if affected_task_ids & studio.delivery.BUSY_TASKS:
            blockers.append('正在生成、验证或发布交付，请等待完成')
        if any(r['id'] in busy_invocation_ids and r.get('status') == 'running' for r in docs['invocations']):
            blockers.append('仍有执行中的模型调用，请等待完成')
        conversation_projects = affected_projects | {r['project_id'] for r in selected.values() if r['project_id']}
        if any(r.get('project_id') in conversation_projects and r['id'] in studio.BUSY_CONVERSATIONS for r in docs['conversations']):
            blockers.append('仍有执行中的对话，请等待完成')
    if selection.action == 'restore':
        for r in selected.values():
            if r['inherited_archive'] and r['project_id'] not in project_ids and r['data_id'] not in dataset_ids:
                blockers.append('请先还原所属数据文件夹')
    paths = unique_roots(p for r in selected.values() for p in r['paths']
                         if selection.action != 'delete' or r['kind'] in ('tasks', 'packages', 'runs'))
    if selection.action == 'delete':
        # Registry/replay files belong to a task; they are never standalone UI resources.
        paths = unique_roots([*paths, *(p for t in tasks if t.id in task_ids
                                      for p in task_paths(g, t, include_metadata=True))])
        if any(r['kind'] == 'runs' for r in selected.values()) and (
            any(t.status == 'running' for t in tasks) or studio.delivery.BUSY_TASKS or studio.BUSY_CONVERSATIONS or
            any(i.get('status') == 'running' for i in docs['invocations'])
        ):
            blockers.append('历史目录可能被当前运行使用，请等待任务和调用结束后再删除')
        for path in paths:
            error = input_error(path, protected_inputs, resolved_inputs) or (path_error(g, path) if exists(path) else '')
            if error:
                blockers.append(f'{error}：{path}')
        # References from surviving resources must never silently lose files.
        for r in resources.values():
            if key(r['kind'], r['id']) in selected or r['kind'] == 'runs':
                continue
            if any(overlaps(path, other) and exists(path) for path in paths for other in r['paths']):
                if r['kind'] not in ('projects', 'datasets'):
                    blockers.append(f'目录仍被「{r["name"]}」使用，请同时选择该资源')
    scanned = [scan(p, fresh=True) for p in paths]
    if selection.action == 'delete' and any(p['errors'] for p in scanned):
        blockers.append('部分目录无法完整读取，请检查权限后重试')
    counts = {kind: sum(r['kind'] == kind for r in selected.values()) for kind in ['projects', 'datasets', 'tasks', 'packages', 'runs']}
    counts['invocations'] = len(invocation_ids) if selection.action == 'delete' else 0
    # Bind confirmation to relationships/record revisions and to the disk inventory.
    signature = hashlib.sha256(json.dumps({'selection': selection.model_dump(), 'docs': docs,
        'tasks': [t.model_dump() for t in tasks], 'paths': scanned}, sort_keys=True, ensure_ascii=False,
        default=str).encode()).hexdigest()
    return dict(action=selection.action, resources=list(selected.values()), paths=scanned, counts=counts,
                bytes=sum(p['bytes'] for p in scanned), files=sum(p['files'] for p in scanned),
                blockers=list(dict.fromkeys(blockers)), fingerprint=signature,
                _project_ids=project_ids, _task_ids=task_ids, _package_ids=package_ids,
                _invocation_ids=invocation_ids, _docs=docs, _inputs=protected_inputs,
                _task_inputs=[t.input_root for t in tasks if t.id in task_ids and t.input_root])


def issue_token(fingerprint):
    body = f'{int(time.time()) + 600}:{fingerprint}:{secrets.token_hex(8)}'
    return body + ':' + hmac.new(SECRET, body.encode(), hashlib.sha256).hexdigest()


def validate_token(token, fingerprint):
    try:
        expires, expected, nonce, signature = token.split(':')
        body = ':'.join([expires, expected, nonce])
        return int(expires) >= time.time() and expected == fingerprint and hmac.compare_digest(
            signature, hmac.new(SECRET, body.encode(), hashlib.sha256).hexdigest())
    except (ValueError, TypeError):
        return False


def _retry_readonly_file(function, path, error):
    """Clear only a Windows regular file's read-only bit, never ACLs or links."""
    path = Path(path)
    if os.name != 'nt' or not isinstance(error, PermissionError):
        raise error
    info = path.lstat()
    if linked(path) or not stat.S_ISREG(info.st_mode) or info.st_mode & stat.S_IWRITE:
        raise error
    original_mode = stat.S_IMODE(info.st_mode)
    path.chmod(original_mode | stat.S_IWRITE)
    try:
        function(path)
    except OSError:
        # A real sharing/ACL error must remain visible, with the file unchanged.
        try:
            path.chmod(original_mode)
        except OSError:
            pass
        raise


def delete_path(path):
    """Use the stdlib's non-following symlink/junction deletion implementation."""
    path = absolute(path)
    if not exists(path):
        return
    if linked(path):
        raise HTTPException(409, f'目录已被替换为链接，请重新检查：{path}')
    if not path.is_dir():
        try:
            path.unlink()
        except PermissionError as error:
            _retry_readonly_file(os.unlink, path, error)
        return
    # onerror also works on the supported Python environments before 3.12.
    shutil.rmtree(path, onerror=lambda function, target, exc: _retry_readonly_file(function, target, exc[1]))


def apply_records(g, db, selection, plan):
    if selection.action != 'delete':
        tasks_changed = False
        for ref in selection.resources:
            archived_at = time.time() if selection.action == 'archive' else None
            if ref.kind == 'tasks':
                task = g.store.get(ref.id, include_archived=True)
                task.archived_at = archived_at
                task.updated_at = time.time()
                tasks_changed = True
            elif ref.kind in ('projects', 'packages'):
                record = db.get(ref.kind, ref.id, include_archived=True)
                if archived_at:
                    record['archived_at'] = archived_at
                else:
                    record.pop('archived_at', None)
                db.put(ref.kind, record)
            elif archived_at:
                db.put('storage_archives', {'id': key(ref.kind, ref.id), 'kind': ref.kind,
                       'resource_id': ref.id, 'archived_at': archived_at})
            else:
                db.connection.execute('DELETE FROM documents WHERE kind=? AND id=?', ('storage_archives', key(ref.kind, ref.id)))
        if tasks_changed:
            g.store._persist()
        return
    projects, tasks, packages, invocations = (plan['_project_ids'], plan['_task_ids'], plan['_package_ids'], plan['_invocation_ids'])
    # Keep imported input locations registered after their last development task
    # is deleted, so the data remains visible and protected on subsequent requests.
    for path in plan['_task_inputs']:
        db.put('storage_inputs', {'id': data_id(path), 'input_root': str(absolute(path))})
    for kind, ids in [('projects', projects), ('packages', packages), ('links', tasks), ('invocations', invocations)]:
        db.connection.executemany('DELETE FROM documents WHERE kind=? AND id=?', [(kind, identity) for identity in ids])
    for kind in ['conversations', 'prepared_inputs']:
        for record in plan['_docs'][kind]:
            if record.get('project_id') in projects or record.get('package_id') in packages:
                db.connection.execute('DELETE FROM documents WHERE kind=? AND id=?', (kind, record['id']))
            elif kind == 'conversations':
                messages = record.get('messages', [])
                retained = [m for m in messages if m.get('invocation_id') not in invocations and not
                            any(s.get('package_id') in packages for s in (m.get('plan') or {}).get('steps', []))]
                if retained != messages:
                    db.put(kind, {**record, 'messages': retained})
    for task_id in tasks:
        g.store._tasks.pop(task_id, None)
        g.store._handles.pop(task_id, None)
    if tasks:
        g.store._persist()
    for resource in plan['resources']:
        db.connection.execute('DELETE FROM documents WHERE kind=? AND id=?',
                              ('storage_archives', key(resource['kind'], resource['id'])))


@contextmanager
def trial_exclusion():
    if not TRIAL_LOCK.acquire(blocking=False):
        raise HTTPException(409, '本地推理正在运行，请等待完成')
    try:
        yield
    finally:
        TRIAL_LOCK.release()


def install(g, studio):
    app = g.app

    @app.get('/api/studio/storage')
    def inventory():
        with studio.database(g) as db:
            _docs, _tasks, resources = snapshot(g, studio, db)
        return {'resources': list(resources.values())}

    @app.get('/api/studio/storage/{kind}/{identity}')
    def resource_storage(kind: Kind, identity: str, refresh: bool = False):
        with studio.database(g) as db:
            docs, _tasks, resources = snapshot(g, studio, db)
            resource = resolve_ref(ResourceRef(kind=kind, id=identity), docs, resources)
        return details(resource, fresh=refresh)

    @app.post('/api/studio/storage/open')
    def open_storage(payload: OpenResource):
        with studio.database(g) as db:
            docs, _tasks, resources = snapshot(g, studio, db)
            resource = resolve_ref(payload, docs, resources)
        path = absolute(payload.path)
        if str(path) not in resource['paths'] or not exists(path):
            raise HTTPException(404, '资源目录不存在，请刷新列表')
        if any(linked(parent) for parent in [path, *path.parents]):
            raise HTTPException(409, '资源路径经过链接，请在文件管理器核实位置')
        directory = path if path.is_dir() else path.parent
        ok, error = g._open_directory(directory)
        if not ok:
            raise HTTPException(400, f'打开目录失败：{error}')
        return {'ok': True, 'path': str(directory)}

    @app.post('/api/studio/storage/preview')
    def preview(payload: Selection):
        with LOCK, studio.database(g) as db, g.store._lock:
            plan = build_plan(g, studio, db, payload)
        result = {k: v for k, v in plan.items() if not k.startswith('_') and k != 'fingerprint'}
        result['confirmation_token'] = issue_token(plan['fingerprint']) if not plan['blockers'] else ''
        return result

    @app.post('/api/studio/storage/apply')
    def apply(payload: ApplySelection):
        if not payload.confirm or not payload.confirmation_token:
            raise HTTPException(400, '请先查看影响范围并确认操作')
        selection = Selection(resources=payload.resources, action=payload.action)
        with LOCK, studio.delivery.LOCK, studio.database(g) as db, g.store._lock:
            plan = build_plan(g, studio, db, selection)
            if plan['blockers']:
                raise HTTPException(409, '；'.join(plan['blockers']))
            if not validate_token(payload.confirmation_token, plan['fingerprint']):
                raise HTTPException(409, '资源或目录内容已变化，请重新打开确认窗口')
            deleted = []
            with trial_exclusion():
                if payload.action == 'delete':
                    for row in plan['paths']:
                        path = absolute(row['path'])
                        error = input_error(path, plan['_inputs']) or (path_error(g, path) if exists(path) else '')
                        if error:
                            raise HTTPException(409, f'{error}：{path}')
                        try:
                            delete_path(path)
                            if exists(path):
                                raise OSError('路径仍然存在')
                            deleted.append(str(path))
                        except (OSError, HTTPException) as error:
                            with CACHE_LOCK:
                                SCAN_CACHE.clear()
                            raise HTTPException(500, f'删除未完成，记录仍保留。请检查目录权限或文件占用后重试：{path}；{error}') from error
                tasks_before = {identity: task.model_copy(deep=True) for identity, task in g.store._tasks.items()}
                handles_before = dict(g.store._handles)
                try:
                    apply_records(g, db, selection, plan)
                except Exception:
                    g.store._tasks = tasks_before
                    g.store._handles = handles_before
                    raise
            with CACHE_LOCK:
                SCAN_CACHE.clear()
        return {'status': {'archive': 'archived', 'restore': 'restored', 'delete': 'deleted'}[payload.action],
                'deleted_paths': deleted, 'counts': plan['counts'], 'bytes': plan['bytes'] if payload.action == 'delete' else 0}

    # DELETE must never silently mean archive, including for older API clients.
    @app.delete('/api/studio/projects/{project_id}')
    def delete_project(project_id: str):
        raise HTTPException(403, '数据文件夹只允许归档或还原，不允许删除')

    return {'inventory': inventory, 'preview': preview, 'apply': apply}
