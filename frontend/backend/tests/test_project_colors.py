"""Project accents survive refreshes, archive/restore, imports and legacy migration."""
import re
import app
import decision_studio as studio
from test_storage_management import local


def test_creation_colors_are_unique_and_persisted(local):
    client = local['client']
    first = local['project']
    second = client.post('/api/studio/projects', json={'name': 'Second', 'input_root': str(local['data'])}).json()
    assert re.fullmatch(r'#[0-9A-F]{6}', first['color'])
    assert first['color'] != second['color']
    for _ in range(2):
        rows = client.get('/api/studio/state').json()['projects']
        assert next(p['color'] for p in rows if p['id'] == first['id']) == first['color']
        assert next(p['color'] for p in rows if p['id'] == second['id']) == second['color']
    assert client.post(f"/api/studio/projects/{first['id']}/archive").status_code == 200
    assert client.get('/api/studio/state').json()['archived_projects'][0]['color'] == first['color']
    assert client.post(f"/api/studio/projects/{first['id']}/restore").json()['color'] == first['color']


def test_legacy_migration_includes_archives_and_changes_only_color(local):
    with studio.database(app) as db:
        original = db.get('projects', local['project']['id'])
        original.pop('color')
        db.put('projects', original)
        archived = {**original, 'id': 'old-archived', 'archived_at': 100}
        db.put('projects', archived)
    result = local['client'].get('/api/studio/state').json()
    active = next(p for p in result['projects'] if p['id'] == original['id'])
    hidden = result['archived_projects'][0]
    assert active['color'] != hidden['color']
    assert {k: v for k, v in active.items() if k != 'color'} == original
    assert {k: v for k, v in hidden.items() if k != 'color'} == archived
    with studio.database(app) as db:
        assert db.get('projects', original['id']) == active
        assert db.get('projects', archived['id'], include_archived=True) == hidden
    assert local['client'].get('/api/studio/state').json()['archived_projects'][0] == hidden


def test_imported_projects_get_an_unused_color(local):
    task = app.store.create(app.TaskConfigPayload(task_name='Other', input_root=str(local['root']),
                                                output_root=str(local['root']/'output')))
    assert local['client'].post('/api/studio/import-tasks', json={'task_ids': [task.id]}).status_code == 200
    with studio.database(app) as db:
        rows = db.rows('projects', include_archived=True)
    assert len(rows) == 2 and len({p['color'] for p in rows}) == 2


def test_color_allocator_exceeds_the_named_palette_without_repeating():
    rows = []
    for _ in range(64):
        rows.append({'color': studio.next_project_color(rows)})
    assert len({p['color'] for p in rows}) == 64
