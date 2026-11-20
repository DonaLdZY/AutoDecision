"""Lifecycle tests only create/delete private pytest temporary directories."""
import hashlib
import json
import os
import stat
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app
import decision_studio as studio
import storage_management as storage


@pytest.fixture
def local(tmp_path, monkeypatch):
    root = tmp_path/'application'
    root.mkdir()
    state = root/'frontend/backend/.state'
    monkeypatch.setattr(app, 'APP_ROOT', root)
    monkeypatch.setattr(app, 'STATE_DIR', state)
    monkeypatch.setattr(app, 'TASKS_FILE', state/'tasks.json')
    for name, path in [('PROJECT_RUNS_DIR', root/'runs'), ('DEFAULT_RUNS_DIR', root/'runs'),
                       ('LEGACY_BACKEND_RUNS_DIR', root/'frontend/backend/runs'),
                       ('LEGACY_AUTOREALIZE_RUNS_DIR', root/'core/AutoRealize/runs')]:
        monkeypatch.setattr(app, name, path)
    monkeypatch.setattr(app, 'store', app.TaskStore())
    monkeypatch.setattr(app.replay_recorder, 'observe_task', lambda *_: None)
    monkeypatch.delenv('AUTODECISION_API_TOKEN', raising=False)
    monkeypatch.setattr(app, 'get_global_settings', lambda: app.GlobalSettingsModel())
    storage.SCAN_CACHE.clear()
    client = TestClient(app.app)
    data = tmp_path/'dataset'
    data.mkdir()
    (data/'train.csv').write_bytes(b'x,y\n1,2\n')
    project = client.post('/api/studio/projects', json={'name': 'Dataset', 'input_root': str(data)}).json()
    task = app.store.create(app.TaskConfigPayload(task_name='training', input_root=str(data), output_root=str(root/'runs')))
    run = root/'runs/training'
    run.mkdir(parents=True)
    (run/'model.bin').write_bytes(b'model' * 128)
    (run/'solution.py').write_text('def predict(): return 1', encoding='utf-8')
    task.run_dir = str(run)
    task.status = 'completed'
    task.phase = 'completed'
    app.store._persist()
    package_id = 'package-1'
    package_root = state/'studio/packages'/package_id
    package_root.mkdir(parents=True)
    (package_root/'solution.py').write_text('def predict(): return 1', encoding='utf-8')
    (package_root/'model.bin').write_bytes(b'weights')
    package = dict(id=package_id, project_id=project['id'], task_id=task.id, name='Predictor', version='1.0.0',
                   files=[], input_schema={}, input_binding=None, manifest={}, sha256={}, verification={}, created_at=1)
    with studio.database(app) as db:
        db.put('links', {'id': task.id, 'project_id': project['id']})
        db.put('packages', package)
        db.put('conversations', {'id': 'chat', 'project_id': project['id'], 'messages': []})
        db.put('invocations', {'id': 'call', 'project_id': project['id'], 'package_ids': [package_id], 'status': 'completed'})
        db.put('prepared_inputs', {'id': 'prepared', 'project_id': project['id'], 'package_id': package_id})
    return dict(client=client, root=root, data=data, project=project, task=task, run=run, package=package,
                package_root=package_root, state=state)


def choose(local, kind='projects', action='delete', ids=None):
    identities = ids or [local['project']['id'] if kind == 'projects' else local['task'].id if kind == 'tasks' else local['package']['id']]
    selection = {'resources': [{'kind': kind, 'id': identity} for identity in identities], 'action': action}
    result = local['client'].post('/api/studio/storage/preview', json=selection)
    assert result.status_code == 200, result.text
    return selection, result.json()


def apply(local, selection, preview):
    return local['client'].post('/api/studio/storage/apply', json={**selection, 'confirm': True,
                                                                'confirmation_token': preview['confirmation_token']})


def test_inventory_paths_and_actual_space(local):
    client = local['client']
    inventory = client.get('/api/studio/storage').json()['resources']
    assert {r['kind'] for r in inventory} >= {'projects', 'tasks', 'packages'}
    info = client.get('/api/studio/storage/packages/package-1').json()
    expected = sum(p.stat().st_size for p in local['package_root'].iterdir())
    assert info['bytes'] == expected and info['files'] == 2 and info['complete']
    assert info['paths'][0]['path'] == str(local['package_root'])


@pytest.mark.parametrize('kind', ['projects', 'tasks', 'packages'])
def test_archive_restore_preserves_every_file_and_is_persistent(local, kind):
    before = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for root in [local['data'], local['run'], local['package_root']] for p in root.rglob('*') if p.is_file()}
    selection, preview = choose(local, kind, 'archive')
    assert not preview['blockers']
    assert apply(local, selection, preview).json()['status'] == 'archived'
    identity = selection['resources'][0]['id']
    resource = next(r for r in local['client'].get('/api/studio/storage').json()['resources'] if r['kind'] == kind and r['id'] == identity)
    assert resource['archived']
    state = local['client'].get('/api/studio/state').json()
    if kind == 'projects':
        assert not state['projects'] and not state['packages']
    elif kind == 'tasks':
        assert not state['tasks']
        assert app.TaskStore().get(identity, include_archived=True).archived_at
        assert local['client'].post('/api/tasks/start', json={'task_id': identity}).status_code == 410
    else:
        assert not state['packages']
        assert local['client'].get(f'/api/studio/packages/{identity}').status_code == 410
    selection, preview = choose(local, kind, 'restore')
    assert apply(local, selection, preview).json()['status'] == 'restored'
    assert all(Path(path).exists() and hashlib.sha256(Path(path).read_bytes()).hexdigest() == digest for path, digest in before.items())


def test_data_folder_cannot_be_deleted_even_with_forged_confirmation(local):
    selection, preview = choose(local)
    assert preview['blockers'] and not preview['confirmation_token']
    assert preview['paths'] == []
    result = apply(local, selection, {**preview, 'confirmation_token': 'forged'})
    assert result.status_code == 409
    assert local['data'].exists() and local['run'].exists() and local['package_root'].exists()
    assert local['client'].delete('/api/studio/projects/' + local['project']['id']).status_code == 403


def test_delete_task_preserves_input_but_removes_published_package_and_auxiliary_data(local):
    for path in [local['state']/'trials'/local['task'].id/'trial.json',
                 local['state']/'deliveries'/local['task'].id/'model.bin',
                 app.replay_recorder.path(local['state'], local['task'].id)]:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('artifact', encoding='utf-8')
    selection, preview = choose(local, 'tasks')
    assert not preview['blockers'], preview['blockers']
    assert apply(local, selection, preview).status_code == 200
    assert (local['data']/'train.csv').exists()
    assert not local['run'].exists() and not local['package_root'].exists()
    assert not (local['state']/'trials'/local['task'].id).exists()
    assert not app.replay_recorder.path(local['state'], local['task'].id).exists()
    assert local['client'].get('/api/studio/state').json()['projects']


def test_delete_package_only_removes_frozen_copy(local):
    selection, preview = choose(local, 'packages')
    assert not preview['blockers']
    assert apply(local, selection, preview).status_code == 200
    assert not local['package_root'].exists()
    assert local['run'].exists() and local['data'].exists()
    assert app.store.get(local['task'].id)


def test_confirmation_is_required_and_not_reusable_for_another_action(local):
    selection, preview = choose(local, 'packages', 'archive')
    assert local['client'].post('/api/studio/storage/apply', json=selection).status_code == 400
    result = apply(local, {**selection, 'action': 'delete'}, preview)
    assert result.status_code == 409
    assert local['package_root'].exists()
    assert local['client'].delete('/api/studio/projects/'+local['project']['id']).status_code == 403


def test_changed_nested_file_invalidates_delete_confirmation(local):
    selection, preview = choose(local, 'tasks')
    (local['run']/'model.bin').write_bytes(b'new model')
    result = apply(local, selection, preview)
    assert result.status_code == 409
    assert local['run'].exists() and app.store.get(local['task'].id)


def test_shared_and_archived_data_are_protected_in_bulk(local):
    second = local['client'].post('/api/studio/projects', json={'name': 'Shared dataset', 'input_root': str(local['data'])}).json()
    selection, preview = choose(local, action='archive', ids=[local['project']['id'], second['id']])
    assert apply(local, selection, preview).status_code == 200
    selection['action'] = 'delete'
    selection['resources'] += [{'kind': 'tasks', 'id': local['task'].id}, {'kind': 'packages', 'id': 'package-1'}]
    preview = local['client'].post('/api/studio/storage/preview', json=selection).json()
    assert preview['blockers'] and not preview['confirmation_token']
    result = apply(local, selection, {**preview, 'confirmation_token': 'forged'})
    assert result.status_code == 409 and (local['data']/'train.csv').exists()
    assert local['run'].exists() and local['package_root'].exists()


def test_running_work_blocks_archive_and_delete(local):
    local['task'].status = 'running'
    local['task'].run_started_at = app.now_ts()
    for action in ['archive', 'delete']:
        _, preview = choose(local, action=action)
        assert preview['blockers'] and not preview['confirmation_token']
    local['task'].status = 'completed'
    studio.delivery.BUSY_TASKS.add(local['task'].id)
    try:
        _, preview = choose(local)
        assert preview['blockers']
    finally:
        studio.delivery.BUSY_TASKS.discard(local['task'].id)


def test_delete_failure_keeps_registry_and_reports_failure(local, monkeypatch):
    selection, preview = choose(local, 'tasks')
    def fail(_path):
        raise PermissionError('busy')
    monkeypatch.setattr(storage, 'delete_path', fail)
    result = apply(local, selection, preview)
    assert result.status_code == 500
    assert local['client'].get('/api/studio/state').json()['projects']
    assert app.store.get(local['task'].id) and local['data'].exists()


def test_dangerous_source_root_blocked(local):
    with studio.database(app) as db:
        record = db.get('projects', local['project']['id'])
        record['input_root'] = str(local['root'])
        db.put('projects', record)
    _, preview = choose(local)
    assert preview['blockers'] and not preview['confirmation_token']
    assert local['root'].exists()


def test_open_uses_registered_path_not_arbitrary_client_path(local, monkeypatch):
    opened = []
    monkeypatch.setattr(app, '_open_directory', lambda path: (opened.append(path) or True, None))
    payload = {'kind': 'packages', 'id': 'package-1', 'path': str(local['data'])}
    assert local['client'].post('/api/studio/storage/open', json=payload).status_code == 404
    payload['path'] = str(local['package_root'])
    assert local['client'].post('/api/studio/storage/open', json=payload).status_code == 200
    assert opened == [local['package_root']]


def test_individual_file_management_is_not_supported(local):
    for action in ['archive', 'restore', 'delete']:
        payload = {'resources': [{'kind': 'files', 'id': 'train.csv'}], 'action': action}
        assert local['client'].post('/api/studio/storage/preview', json=payload).status_code == 422
    assert local['client'].get('/api/studio/storage/files/train.csv').status_code == 422
    catalog = local['client'].get(f'/api/studio/projects/{local["project"]["id"]}/catalog').json()
    assert 'storage_id' not in catalog['files'][0] and 'archived_files' not in catalog
    assert (local['data']/'train.csv').exists()


def test_inventory_only_contains_directory_units_and_data_task_relationships(local):
    history = local['root']/'.codex-work/history'
    history.mkdir(parents=True)
    (history.parent/'standalone.log').write_text('log')
    (history/'model.bin').write_bytes(b'model')
    inventory = local['client'].get('/api/studio/storage').json()['resources']
    assert all(Path(path).is_dir() for row in inventory for path in row['paths'])
    assert not any(row['name'] in ['standalone.log', 'model.bin', 'train.csv'] for row in inventory)
    task = next(row for row in inventory if row['kind'] == 'tasks')
    package = next(row for row in inventory if row['kind'] == 'packages')
    project = next(row for row in inventory if row['kind'] == 'projects')
    assert task['data_id'] == package['data_id'] == project['data_id']
    assert task['task_id'] == package['task_id'] == local['task'].id
    assert task['task_name'] == package['task_name'] == 'training'
    assert task['can_delete'] and package['can_delete'] and not project['can_delete']


@pytest.mark.parametrize('archived', [False, True])
def test_input_nested_in_runtime_root_cannot_be_deleted_through_task_or_ancestor(local, archived):
    container = local['root']/'.codex-work/experiment'
    data = container/'input'
    data.mkdir(parents=True)
    (data/'keep.csv').write_text('keep')
    output = container/'development'
    output.mkdir()
    (output/'model.bin').write_text('weights')
    with studio.database(app) as db:
        project = db.get('projects', local['project']['id'])
        project['input_root'] = str(data)
        if archived:
            project['archived_at'] = 1
        db.put('projects', project)
    local['task'].input_root = str(data)
    inventory = local['client'].get('/api/studio/storage').json()['resources']
    raw = [r for r in inventory if r['kind'] == 'runs']
    assert any(str(output) in r['paths'] for r in raw)
    assert not any(storage.overlaps(p, data) for r in raw for p in r['paths'])
    # A stale or manipulated task output cannot turn its imported input into output.
    local['task'].run_dir = str(container)
    selection, preview = choose(local, 'tasks')
    assert preview['blockers'] and not preview['confirmation_token']
    assert apply(local, selection, {**preview, 'confirmation_token': 'forged'}).status_code == 409
    assert (data/'keep.csv').read_text() == 'keep'


def test_unlinked_input_folder_stays_visible_and_protected_after_development_deleted(local):
    other = local['root']/'.codex-work/experiment/input'
    other.mkdir(parents=True)
    (other/'keep.csv').write_text('keep')
    local['task'].input_root = str(other)
    with studio.database(app) as db:
        db.connection.execute("DELETE FROM documents WHERE kind='links'")
    inventory = local['client'].get('/api/studio/storage').json()['resources']
    dataset = next(r for r in inventory if r['kind'] == 'datasets')
    task = next(r for r in inventory if r['kind'] == 'tasks')
    assert dataset['data_id'] == task['data_id'] and not dataset['can_delete']
    selection, preview = choose(local, 'datasets', 'archive', [dataset['id']])
    assert apply(local, selection, preview).status_code == 200
    assert not local['client'].get('/api/studio/state').json()['tasks']
    selection, preview = choose(local, 'datasets', 'restore', [dataset['id']])
    assert apply(local, selection, preview).status_code == 200
    selection, preview = choose(local, 'tasks')
    assert not preview['blockers'], preview['blockers']
    assert apply(local, selection, preview).status_code == 200
    inventory = local['client'].get('/api/studio/storage').json()['resources']
    assert any(r['kind'] == 'datasets' and r['id'] == dataset['id'] for r in inventory)
    assert (other/'keep.csv').exists()
    assert not any(storage.overlaps(p, other) for r in inventory if r['kind'] == 'runs' for p in r['paths'])


def test_database_itself_cannot_be_a_delete_target(local):
    assert storage.path_error(app, app.STATE_DIR/'studio')
    assert storage.path_error(app, app.STATE_DIR/'studio/studio.sqlite3')
    assert storage.path_error(app, app.TASKS_FILE)


def test_legacy_delete_cannot_remove_another_projects_input(local):
    imported = local['run']/'external-import'
    imported.mkdir()
    (imported/'keep.csv').write_text('keep')
    local['client'].post('/api/studio/projects', json={'name': 'Other input', 'input_root': str(imported)})
    result = local['client'].delete(f'/api/tasks/{local["task"].id}?delete_files=true')
    assert result.status_code == 403
    assert (imported/'keep.csv').exists() and app.store.get(local['task'].id)


def test_missing_development_uses_recorded_path_and_can_remove_stale_task(local):
    storage.delete_path(local['run'])
    local['task'].output_root = str(local['root']/'Files/old/malformed/root')
    inventory = local['client'].get('/api/studio/storage').json()['resources']
    task = next(r for r in inventory if r['kind'] == 'tasks')
    assert task['paths'] == [str(local['run'])] and task['can_delete']
    selection, preview = choose(local, 'tasks')
    assert not preview['blockers'], preview['blockers']
    assert apply(local, selection, preview).status_code == 200
    assert not app.store.list_tasks(include_archived=True) and (local['data']/'train.csv').exists()


def test_sibling_development_is_grouped_with_its_registered_data(local):
    container = local['root']/'.codex-work/experiment'
    source, output = container/'imported', container/'development'
    source.mkdir(parents=True)
    output.mkdir()
    with studio.database(app) as db:
        project = db.get('projects', local['project']['id'])
        project['input_root'] = str(source)
        db.put('projects', project)
    inventory = local['client'].get('/api/studio/storage').json()['resources']
    raw = next(r for r in inventory if r['paths'] == [str(output)])
    project = next(r for r in inventory if r['kind'] == 'projects')
    assert raw['data_id'] == project['data_id'] and raw['project_id'] == project['id']
    assert raw['can_delete']


def test_task_archive_failure_restores_in_memory_state(local, monkeypatch):
    selection, preview = choose(local, 'tasks', 'archive')
    def fail():
        raise OSError('Disk write failed')
    monkeypatch.setattr(app.store, '_persist', fail)
    with pytest.raises(OSError):
        apply(local, selection, preview)
    assert not app.store.get(local['task'].id).archived_at


def test_task_registry_write_failure_preserves_previous_file(local, monkeypatch):
    original = app.TASKS_FILE.read_bytes()
    def fail(path, *_args, **_kwargs):
        path.write_text('partial write', encoding='utf-8')
        raise OSError('Disk full')
    monkeypatch.setattr(app, 'write_json', fail)
    with pytest.raises(OSError):
        app.store._persist()
    assert app.TASKS_FILE.read_bytes() == original
    assert not list(app.TASKS_FILE.parent.glob('.tasks.json.*.tmp'))


def test_symlink_replacement_after_preview_does_not_delete_external_data(local):
    selection, preview = choose(local, 'tasks')
    moved = local['run'].with_name('original-run')
    local['run'].rename(moved)
    try:
        local['run'].symlink_to(local['data'], target_is_directory=True)
    except OSError:
        moved.rename(local['run'])
        pytest.skip('Symlinks unavailable')
    result = apply(local, selection, preview)
    assert result.status_code == 409
    assert (local['data']/'train.csv').exists()
    assert app.store.get(local['task'].id)


def test_orphan_history_archive_restore_delete(local):
    directory = local['root']/'.codex-work/old-run'
    directory.mkdir(parents=True)
    (directory/'weights.bin').write_bytes(b'weights')
    resource = next(r for r in local['client'].get('/api/studio/storage').json()['resources'] if r['name'] == 'old-run')
    for action in ['archive', 'restore', 'delete']:
        selection, preview = choose(local, 'runs', action, [resource['id']])
        assert not preview['blockers'], preview['blockers']
        assert apply(local, selection, preview).status_code == 200
        assert directory.exists() == (action != 'delete')


def test_scan_and_delete_do_not_follow_symlink(tmp_path):
    root = tmp_path/'artifacts'; root.mkdir()
    outside = tmp_path/'outside'; outside.mkdir()
    (outside/'keep.bin').write_bytes(b'keep'*512)
    (root/'model.bin').write_bytes(b'model')
    try:
        (root/'input').symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip('Symlinks unavailable in this test environment')
    info = storage.scan(root, fresh=True)
    assert info['bytes'] == 5 and info['links'] == 1
    storage.delete_path(root)
    assert not root.exists() and (outside/'keep.bin').exists()


def test_scan_counts_hardlinked_file_bytes_once(tmp_path):
    (tmp_path/'one.bin').write_bytes(b'x'*512)
    try:
        os.link(tmp_path/'one.bin', tmp_path/'two.bin')
    except OSError:
        pytest.skip('Hard links unavailable')
    info = storage.scan(tmp_path, fresh=True)
    assert info['files'] == 2 and info['bytes'] == 512


def test_nested_input_alias_protects_its_external_target(local, tmp_path):
    outside = tmp_path/'imported-external'
    outside.mkdir()
    (outside/'keep.csv').write_text('keep')
    alias = local['data']/'nested-input'
    try:
        alias.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip('Symlinks unavailable')
    local['task'].input_root = str(alias)
    local['task'].run_dir = str(outside)
    selection, preview = choose(local, 'tasks')
    assert preview['blockers'] and not preview['confirmation_token']
    assert apply(local, selection, {**preview, 'confirmation_token': 'forged'}).status_code == 409
    assert (outside/'keep.csv').exists()


def test_unregistered_input_guards_are_not_listed_but_still_prevent_data_deletion(local):
    original = local['run']/'unregistered-source'
    original.mkdir()
    (original/'keep.csv').write_text('original input')
    identity = storage.data_id(original)
    with studio.database(app) as db:
        db.put('storage_inputs', {'id': identity, 'input_root': str(original), 'protection_only': True})
    resources = local['client'].get('/api/studio/storage').json()['resources']
    assert not any(row['kind'] == 'datasets' and row['id'] == identity for row in resources)
    assert not any(row['kind'] == 'runs' and any(storage.overlaps(path, original) for path in row['paths']) for row in resources)
    selection, preview = choose(local, 'tasks', 'delete')
    assert preview['blockers'] and not preview['confirmation_token']
    assert apply(local, selection, {**preview, 'confirmation_token': 'forged'}).status_code == 409
    assert local['client'].delete(f'/api/tasks/{local["task"].id}?delete_files=true').status_code == 403
    assert (original/'keep.csv').read_text() == 'original input'


@pytest.mark.skipif(os.name != 'nt', reason='Windows read-only file deletion')
def test_delete_task_removes_readonly_artifacts_and_preserves_readonly_inputs(local):
    readonly_input = local['data']/'reference.pdf'
    readonly_input.write_bytes(b'imported reference')
    readonly_input.chmod(stat.S_IREAD)
    artifact = local['run']/'autorealize'/'initial-validation.pdf'
    artifact.parent.mkdir()
    artifact.write_bytes(b'generated report')
    artifact.chmod(stat.S_IREAD)
    try:
        selection, preview = choose(local, 'tasks')
        assert not preview['blockers'], preview['blockers']
        result = apply(local, selection, preview)
        assert result.status_code == 200, result.text
        assert result.json()['status'] == 'deleted'
        assert not local['run'].exists() and not local['package_root'].exists()
        assert all(task.id != local['task'].id for task in app.store.list_tasks(include_archived=True))
        assert readonly_input.read_bytes() == b'imported reference'
        assert not readonly_input.stat().st_mode & stat.S_IWRITE
    finally:
        readonly_input.chmod(stat.S_IREAD | stat.S_IWRITE)
        if artifact.exists():
            artifact.chmod(stat.S_IREAD | stat.S_IWRITE)


@pytest.mark.skipif(os.name != 'nt', reason='Windows read-only file deletion')
def test_delete_standalone_readonly_artifact(tmp_path):
    artifact = tmp_path/'report.pdf'
    artifact.write_bytes(b'report')
    artifact.chmod(stat.S_IREAD)
    try:
        storage.delete_path(artifact)
        assert not artifact.exists()
    finally:
        if artifact.exists():
            artifact.chmod(stat.S_IREAD | stat.S_IWRITE)


@pytest.mark.skipif(os.name != 'nt', reason='Windows read-only file deletion')
@pytest.mark.parametrize('readonly', [False, True])
def test_readonly_retry_preserves_real_permission_failures(tmp_path, readonly):
    artifact = tmp_path/'locked.pdf'
    artifact.write_bytes(b'keep')
    if readonly:
        artifact.chmod(stat.S_IREAD)
    attempts = []
    error = PermissionError('file is held open')
    def fail(path):
        attempts.append(path)
        raise error
    try:
        with pytest.raises(PermissionError, match='file is held open'):
            storage._retry_readonly_file(fail, artifact, error)
        assert len(attempts) == int(readonly)
        assert artifact.read_bytes() == b'keep'
        assert bool(artifact.stat().st_mode & stat.S_IWRITE) != readonly
    finally:
        artifact.chmod(stat.S_IREAD | stat.S_IWRITE)


@pytest.mark.skipif(os.name != 'nt', reason='Windows read-only file deletion')
def test_readonly_retry_never_changes_link_target(tmp_path):
    outside = tmp_path/'outside.pdf'
    outside.write_bytes(b'keep outside')
    alias = tmp_path/'alias.pdf'
    try:
        alias.symlink_to(outside)
    except OSError:
        pytest.skip('Symlinks unavailable')
    outside.chmod(stat.S_IREAD)
    try:
        with pytest.raises(PermissionError):
            storage._retry_readonly_file(lambda path: pytest.fail('link must not be retried'), alias, PermissionError('denied'))
        assert outside.read_bytes() == b'keep outside'
        assert not outside.stat().st_mode & stat.S_IWRITE
    finally:
        outside.chmod(stat.S_IREAD | stat.S_IWRITE)


@pytest.mark.skipif(os.name != 'nt', reason='Windows file sharing and read-only attributes')
def test_locked_readonly_file_keeps_task_and_can_be_deleted_after_close(local):
    artifact = local['run']/'locked.pdf'
    artifact.write_bytes(b'locked report')
    artifact.chmod(stat.S_IREAD)
    try:
        selection, preview = choose(local, 'tasks')
        assert not preview['blockers'], preview['blockers']
        with artifact.open('rb') as held:
            result = apply(local, selection, preview)
            assert result.status_code == 500, result.text
            assert app.store.get(local['task'].id)
            assert held.read() == b'locked report'
            assert not artifact.stat().st_mode & stat.S_IWRITE
        selection, preview = choose(local, 'tasks')
        result = apply(local, selection, preview)
        assert result.status_code == 200, result.text
        assert not local['run'].exists()
        assert local['data'].exists()
    finally:
        if artifact.exists():
            artifact.chmod(stat.S_IREAD | stat.S_IWRITE)
