"""Confirmed conversation lifecycle, independent of data and model artifacts."""
from __future__ import annotations

import hashlib
import json
import time
from typing import Literal

from fastapi import HTTPException
from pydantic import BaseModel, Field

from storage_management import issue_token, validate_token


class ConversationSelection(BaseModel):
    ids: list[str] = Field(min_length=1, max_length=500)
    action: Literal['archive', 'restore', 'delete']


class ApplyConversations(ConversationSelection):
    confirm: bool = False
    confirmation_token: str = Field(default='', max_length=2048)


class RenameConversation(BaseModel):
    title: str = Field(min_length=1, max_length=120)


def summary(record, projects, busy_ids=()):
    project = projects.get(record['project_id'], {})
    messages = record.get('messages', [])
    return dict(id=record['id'], project_id=record['project_id'], title=record.get('title') or '新的决策对话',
                project_name=project.get('name', '未关联项目'), message_count=len(messages),
                created_at=record.get('created_at', 0),
                updated_at=record.get('updated_at') or max([record.get('created_at', 0),
                                                           *(m.get('created_at', 0) for m in messages)]),
                archived=bool(record.get('archived_at') or project.get('archived_at')),
                archived_at=record.get('archived_at'), inherited_archive=bool(project.get('archived_at')),
                busy=record['id'] in busy_ids)


def build_plan(studio, db, selection):
    records = [db.get('conversations', identity, include_archived=True) for identity in dict.fromkeys(selection.ids)]
    projects = {p['id']: p for p in db.rows('projects', include_archived=True)}
    calls = [r for r in db.rows('invocations', include_archived=True) if r.get('conversation_id') in selection.ids]
    busy = studio.BUSY_CONVERSATIONS | {r.get('conversation_id') for r in calls if r.get('status') == 'running'}
    blockers = []
    for record in records:
        if record['id'] in busy:
            blockers.append(f'「{record.get("title") or "对话"}」正在生成回复或执行调用，请等待完成')
        if selection.action == 'restore' and projects.get(record['project_id'], {}).get('archived_at'):
            blockers.append('所属数据项目已归档，请先在数据项目中还原')
    signature = hashlib.sha256(json.dumps({'selection': selection.model_dump(), 'records': records, 'calls': calls,
                                         'projects': [projects.get(r['project_id']) for r in records]},
                                        sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return dict(conversations=[summary(r, projects, busy) for r in records],
                message_count=sum(len(r.get('messages', [])) for r in records),
                invocation_count=len(calls), blockers=list(dict.fromkeys(blockers)), fingerprint=signature,
                _records=records, _calls=calls)


def install(g, studio):
    app = g.app

    @app.get('/api/studio/conversations')
    def conversation_index():
        with studio.database(g) as db:
            projects = {p['id']: p for p in db.rows('projects', include_archived=True)}
            busy = studio.BUSY_CONVERSATIONS | {r.get('conversation_id') for r in db.rows('invocations') if r.get('status') == 'running'}
            rows = [summary(r, projects, busy) for r in db.rows('conversations', include_archived=True)]
        return sorted(rows, key=lambda r: r['updated_at'], reverse=True)

    @app.post('/api/studio/conversations/preview')
    def preview(payload: ConversationSelection):
        with studio.database(g) as db:
            plan = build_plan(studio, db, payload)
        return {**{k: v for k, v in plan.items() if not k.startswith('_') and k != 'fingerprint'},
                'confirmation_token': issue_token(plan['fingerprint']) if not plan['blockers'] else ''}

    @app.post('/api/studio/conversations/manage')
    def manage(payload: ApplyConversations):
        if not payload.confirm or not payload.confirmation_token:
            raise HTTPException(400, '请先查看影响范围并确认操作')
        selection = ConversationSelection(ids=payload.ids, action=payload.action)
        with studio.database(g) as db:
            plan = build_plan(studio, db, selection)
            if plan['blockers']:
                raise HTTPException(409, '；'.join(plan['blockers']))
            if not validate_token(payload.confirmation_token, plan['fingerprint']):
                raise HTTPException(409, '对话内容已变化，请重新确认')
            for record in plan['_records']:
                if payload.action == 'delete':
                    db.connection.execute('DELETE FROM documents WHERE kind=? AND id=?', ('conversations', record['id']))
                else:
                    if payload.action == 'archive':
                        record['archived_at'] = time.time()
                    else:
                        record.pop('archived_at', None)
                    db.put('conversations', record)
            if payload.action == 'delete':
                # Calls are independently managed evidence, not conversation messages.
                for call in plan['_calls']:
                    call['conversation_id'] = ''
                    db.put('invocations', call)
        return {'status': payload.action, 'ids': [r['id'] for r in plan['_records']]}

    @app.patch('/api/studio/conversations/{conversation_id}')
    def rename(conversation_id: str, payload: RenameConversation):
        title = payload.title.strip()
        if not title:
            raise HTTPException(422, '对话名称不能为空')
        with studio.database(g) as db:
            record = db.get('conversations', conversation_id, include_archived=True)
            if conversation_id in studio.BUSY_CONVERSATIONS:
                raise HTTPException(409, '正在生成回复，请等待完成后重命名')
            record.update(title=title, title_custom=True, updated_at=time.time())
            db.put('conversations', record)
        return record
