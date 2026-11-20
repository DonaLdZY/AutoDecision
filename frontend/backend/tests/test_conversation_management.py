"""Conversation lifecycle against private SQLite state and resource fixtures."""
import pytest

import app
import decision_studio as studio
from test_storage_management import local


@pytest.fixture
def chats(local):
    with studio.database(app) as db:
        for identity, updated in [('chat', 10), ('second', 20)]:
            db.put('conversations', dict(id=identity, project_id=local['project']['id'], title=identity,
                messages=[dict(id=identity + '-message', role='user', text='private message ' + identity)],
                created_at=1, updated_at=updated))
        call = db.get('invocations', 'call')
        call['conversation_id'] = 'chat'
        db.put('invocations', call)
    return local


def preview(chats, action='archive', ids=None):
    payload = dict(ids=ids or ['chat'], action=action)
    response = chats['client'].post('/api/studio/conversations/preview', json=payload)
    assert response.status_code == 200, response.text
    return payload, response.json()


def apply(chats, payload, plan):
    return chats['client'].post('/api/studio/conversations/manage', json={**payload, 'confirm': True,
        'confirmation_token': plan['confirmation_token']})


def test_archive_restore_preserves_messages_and_survives_reopening(chats):
    client = chats['client']
    with studio.database(app) as db:
        original = db.get('conversations', 'chat')
    payload, plan = preview(chats)
    assert plan['message_count'] == plan['invocation_count'] == 1
    assert not plan['blockers']
    assert apply(chats, payload, plan).status_code == 200
    assert [r['id'] for r in client.get('/api/studio/state').json()['conversations']] == ['second']
    row = next(r for r in client.get('/api/studio/conversations').json() if r['id'] == 'chat')
    assert row['archived'] and row['message_count'] == 1 and 'messages' not in row
    assert client.post('/api/studio/conversations/chat/messages', json={'text': 'hello', 'mode': 'catalog',
        'request_id': 'new'}).status_code == 410
    with studio.database(app) as db:
        assert db.get('conversations', 'chat', include_archived=True)['messages'] == original['messages']
    payload, plan = preview(chats, 'restore')
    assert apply(chats, payload, plan).status_code == 200
    with studio.database(app) as db:
        assert db.get('conversations', 'chat') == original


def test_delete_removes_conversation_messages_but_preserves_independent_resources(chats):
    payload, plan = preview(chats, 'delete', ['chat', 'second', 'chat'])
    assert len(plan['conversations']) == 2 and plan['message_count'] == 2
    assert apply(chats, payload, plan).json()['ids'] == ['chat', 'second']
    assert not chats['client'].get('/api/studio/conversations').json()
    with studio.database(app) as db:
        assert not db.connection.execute("SELECT body FROM documents WHERE kind='conversations'").fetchall()
        assert db.get('invocations', 'call')['conversation_id'] == ''
        assert db.get('packages', 'package-1') and db.get('projects', chats['project']['id'])
    assert app.TaskStore().get(chats['task'].id)
    assert (chats['data']/'train.csv').exists() and (chats['run']/'model.bin').exists()
    assert (chats['package_root']/'model.bin').exists()


def test_rename_is_trimmed_and_survives_next_message(chats):
    client = chats['client']
    response = client.patch('/api/studio/conversations/chat', json={'title': '  新名称  '})
    assert response.status_code == 200 and response.json()['title'] == '新名称'
    response = client.post('/api/studio/conversations/chat/messages', json={'text': '下一条消息',
        'mode': 'catalog', 'request_id': 'follow-up'})
    assert response.status_code == 200, response.text
    rows = client.get('/api/studio/conversations').json()
    assert rows[0]['id'] == 'chat' and rows[0]['title'] == '新名称' and rows[0]['message_count'] == 3
    for title in ['', '   ', 'x'*121]:
        assert client.patch('/api/studio/conversations/chat', json={'title': title}).status_code == 422


@pytest.mark.parametrize('action', ['archive', 'delete', 'restore'])
@pytest.mark.parametrize('busy_kind', ['planning', 'invocation'])
def test_busy_conversations_block_entire_batch(chats, monkeypatch, action, busy_kind):
    payload, plan = preview(chats, action, ['second', 'chat'])
    if busy_kind == 'planning':
        monkeypatch.setattr(studio, 'BUSY_CONVERSATIONS', {'chat'})
    else:
        with studio.database(app) as db:
            call = db.get('invocations', 'call')
            call['status'] = 'running'
            db.put('invocations', call)
    assert apply(chats, payload, plan).status_code == 409
    _, blocked = preview(chats, action, ['second', 'chat'])
    assert blocked['blockers'] and not blocked['confirmation_token']
    with studio.database(app) as db:
        assert len(db.rows('conversations')) == 2
    rows = chats['client'].get('/api/studio/conversations').json()
    assert next(r for r in rows if r['id'] == 'chat')['busy']


def test_confirmation_cannot_be_forged_or_reused_after_changes(chats):
    client = chats['client']
    payload, plan = preview(chats, 'delete')
    assert client.post('/api/studio/conversations/manage', json=payload).status_code == 400
    assert apply(chats, payload, {**plan, 'confirmation_token': 'forged'}).status_code == 409
    assert apply(chats, {**payload, 'action': 'archive'}, plan).status_code == 409
    assert apply(chats, {**payload, 'ids': ['second']}, plan).status_code == 409
    assert client.patch('/api/studio/conversations/chat', json={'title': 'changed'}).status_code == 200
    assert apply(chats, payload, plan).status_code == 409
    with studio.database(app) as db:
        assert len(db.rows('conversations')) == 2


def test_inherited_archive_is_visible_but_restore_requires_active_project(chats):
    with studio.database(app) as db:
        project = db.get('projects', chats['project']['id'])
        project['archived_at'] = 100
        db.put('projects', project)
    rows = chats['client'].get('/api/studio/conversations').json()
    assert len(rows) == 2 and all(r['archived'] and r['inherited_archive'] for r in rows)
    assert not chats['client'].get('/api/studio/state').json()['conversations']
    payload, plan = preview(chats, 'restore')
    assert plan['blockers'] and not plan['confirmation_token']
    assert apply(chats, payload, {**plan, 'confirmation_token': 'forged'}).status_code == 409
    payload, plan = preview(chats, 'delete')
    assert not plan['blockers'] and apply(chats, payload, plan).status_code == 200
    assert (chats['data']/'train.csv').exists()


def test_missing_id_prevents_partial_batch_changes(chats):
    payload, plan = preview(chats, 'delete', ['chat', 'second'])
    with studio.database(app) as db:
        db.connection.execute("DELETE FROM documents WHERE kind='conversations' AND id='second'")
    assert apply(chats, payload, plan).status_code == 404
    with studio.database(app) as db:
        assert db.get('conversations', 'chat')['messages']


def test_rename_blocked_during_planning(chats, monkeypatch):
    monkeypatch.setattr(studio, 'BUSY_CONVERSATIONS', {'chat'})
    assert chats['client'].patch('/api/studio/conversations/chat', json={'title': 'new'}).status_code == 409


def test_archived_conversation_can_be_renamed_then_deleted(chats):
    payload, plan = preview(chats)
    assert apply(chats, payload, plan).status_code == 200
    assert chats['client'].patch('/api/studio/conversations/chat', json={'title': 'archived name'}).status_code == 200
    payload, plan = preview(chats, 'delete')
    assert plan['conversations'][0]['title'] == 'archived name'
    assert apply(chats, payload, plan).status_code == 200
    assert all(r['id'] != 'chat' for r in chats['client'].get('/api/studio/conversations').json())
