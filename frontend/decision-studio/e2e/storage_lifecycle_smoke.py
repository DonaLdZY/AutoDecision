"""Exercise the real Vue UI and FastAPI handlers against temporary resources only.

Browser API requests are bridged to TestClient; production data is never opened
by the backend. Vite serves the actual production build on a private free port.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    frontend = Path(__file__).resolve().parents[1]
    backend = frontend.parent/'backend'
    with tempfile.TemporaryDirectory(prefix='autodecision-storage-browser-') as temporary:
        fixture_root = Path(temporary)
        os.environ['AUTODECISION_STATE_DIR'] = str(fixture_root/'initial-state')
        os.environ['AUTODECISION_GLOBAL_SETTINGS_PATH'] = str(fixture_root/'settings.yaml')
        sys.path[:0] = [str(backend), str(backend/'tests')]
        import pytest
        import app
        from test_storage_management import local
        from playwright.sync_api import sync_playwright, expect

        with pytest.MonkeyPatch.context() as monkeypatch:
            test = local.__wrapped__(fixture_root, monkeypatch)
            client = test['client']
            opened = []
            monkeypatch.setattr(app, '_open_directory', lambda path: (opened.append(str(path)) or True, None))
            orphan = test['root']/'.codex-work/browser-history'
            orphan.mkdir(parents=True)
            (orphan/'old-model.bin').write_bytes(b'old weights' * 100)
            before = hashlib.sha256((test['data']/'train.csv').read_bytes()).hexdigest()
            with socket.socket() as probe:
                probe.bind(('127.0.0.1', 0))
                port = probe.getsockname()[1]
            url = f'http://127.0.0.1:{port}'
            command = [shutil.which('node'), str(frontend/'node_modules/vite/bin/vite.js'), 'preview',
                       '--host', '127.0.0.1', '--port', str(port), '--strictPort']
            with (args.output/'preview.log').open('w', encoding='utf-8') as log:
                server = subprocess.Popen(command, cwd=frontend, stdout=log, stderr=log,
                                          creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                try:
                    deadline = time.monotonic() + 30
                    while True:
                        try:
                            urllib.request.urlopen(url, timeout=1).close()
                            break
                        except OSError:
                            if time.monotonic() > deadline:
                                raise RuntimeError('Preview did not start')
                            time.sleep(.1)
                    with sync_playwright() as playwright:
                        browser = playwright.chromium.launch(headless=True)
                        context = browser.new_context(viewport={'width': 1440, 'height': 1000})
                        failures, errors = [], []

                        def bridge(route):
                            request = route.request
                            path = request.url.split('/api/', 1)[1]
                            response = client.request(request.method, '/api/' + path, content=request.post_data,
                                                      headers={'Content-Type': 'application/json'})
                            if response.status_code >= 400:
                                failures.append({'path': path, 'status': response.status_code, 'body': response.text})
                            route.fulfill(status=response.status_code, content_type='application/json', body=response.content)

                        context.route('**/api/**', bridge)
                        page = context.new_page()
                        page.on('pageerror', lambda error: errors.append(str(error)))
                        page.set_default_timeout(15000)

                        def navigate(name):
                            page.locator('.sidebar').get_by_role('button', name=name, exact=True).click()
                            page.wait_for_load_state('networkidle')

                        def confirm(action):
                            dialog = page.get_by_role('dialog', name=action+'确认')
                            button = dialog.get_by_role('button', name='确认'+action, exact=True)
                            if action == '删除':
                                expect(button).to_be_disabled()
                                dialog.get_by_role('checkbox').check()
                            expect(button).to_be_enabled()
                            button.click()
                            expect(dialog).not_to_be_visible()
                            page.wait_for_load_state('networkidle')

                        page.goto(url+'/#projects', wait_until='networkidle')
                        card = page.locator('.project-tile').filter(has=page.get_by_role('heading', name='Dataset', exact=True))
                        expect(card.get_by_text('8 B', exact=True)).to_be_visible()
                        expect(card.get_by_role('button', name='删除', exact=True)).to_have_count(0)
                        expect(page.locator('.file-catalog')).to_have_count(0)
                        card.get_by_role('button', name=re.compile('^打开目录 ')).click()
                        assert opened == [str(test['data'])]
                        card.get_by_role('button', name='归档', exact=True).click()
                        dialog = page.get_by_role('dialog', name='归档确认')
                        expect(dialog.get_by_text(re.compile('磁盘文件保持原位'))).to_be_visible()
                        page.screenshot(path=str(args.output/'01-archive-confirm.png'), full_page=True)
                        dialog.get_by_role('button', name='取消', exact=True).click()
                        assert test['data'].exists()
                        card.get_by_role('button', name='归档', exact=True).click()
                        confirm('归档')
                        assert test['data'].exists() and test['run'].exists() and test['package_root'].exists()
                        navigate('本地存储')
                        page.get_by_role('button', name=re.compile('^已归档')).click()
                        project_row = page.locator(f'[data-resource="projects:{test["project"]["id"]}"]')
                        project_row.get_by_role('button', name='还原', exact=True).click()
                        confirm('还原')
                        assert hashlib.sha256((test['data']/'train.csv').read_bytes()).hexdigest() == before

                        navigate('研发任务')
                        task_row = page.locator('.task-storage-row')
                        expect(task_row.get_by_role('button', name='归档', exact=True)).to_be_enabled()
                        task_row.get_by_role('button', name='归档', exact=True).click()
                        confirm('归档')
                        assert test['run'].exists()
                        expect(page.get_by_role('heading', name='这里还没有研发任务')).to_be_visible()
                        navigate('本地存储')
                        page.get_by_role('button', name=re.compile('^已归档')).click()
                        task_row = page.locator(f'[data-resource="tasks:{test["task"].id}"]')
                        task_row.get_by_role('button', name='还原', exact=True).click()
                        confirm('还原')

                        navigate('本地存储')
                        page.get_by_role('button', name=re.compile('^使用中')).click()
                        data_group = page.locator('.storage-data-group').filter(has=page.get_by_role('heading', name='Dataset', exact=True))
                        task_group = data_group.locator('[data-task="' + test['task'].id + '"]')
                        expect(task_group.locator('.storage-item')).to_have_count(2)
                        expect(data_group.locator('[data-resource^="projects:"]').get_by_role('button', name='删除', exact=True)).to_have_count(0)
                        page.get_by_label('全选', exact=True).check()
                        expect(page.locator('.storage-toolbar').get_by_role('button', name='删除', exact=True)).to_be_disabled()
                        page.get_by_role('button', name='清空选择', exact=True).click()
                        task_group.get_by_role('checkbox', name='选择任务分组 training', exact=True).check()
                        page.locator('.storage-toolbar').get_by_role('button', name='归档', exact=True).click()
                        confirm('归档')
                        assert test['run'].exists() and test['package_root'].exists()
                        page.get_by_role('button', name=re.compile('^已归档')).click()
                        task_group = page.locator('[data-task="' + test['task'].id + '"]')
                        expect(task_group.locator('.storage-item')).to_have_count(2)
                        page.locator('.storage-toolbar').get_by_role('button', name='还原', exact=True).click()
                        confirm('还原')

                        navigate('算法模型包')
                        package_card = page.locator('.package-tile')
                        package_card.get_by_role('button', name='删除', exact=True).click()
                        dialog = page.get_by_role('dialog', name='删除确认')
                        expect(dialog.get_by_text(re.compile('将永久删除'))).to_be_visible()
                        expect(dialog.get_by_role('button', name='确认删除', exact=True)).to_be_disabled()
                        dialog.get_by_role('button', name='取消', exact=True).click()
                        assert test['package_root'].exists()
                        package_card.get_by_role('button', name='删除', exact=True).click()
                        expect(page.get_by_role('dialog').get_by_role('checkbox')).to_be_visible()
                        page.screenshot(path=str(args.output/'02-delete-confirm.png'), full_page=True)
                        confirm('删除')
                        assert not test['package_root'].exists() and test['run'].exists() and test['data'].exists()

                        navigate('项目数据')
                        expect(page.locator('.file-catalog')).to_have_count(0)
                        assert hashlib.sha256((test['data']/'train.csv').read_bytes()).hexdigest() == before
                        navigate('本地存储')
                        expect(page.locator('.storage-loading')).to_have_count(0)
                        page.screenshot(path=str(args.output/'03-storage-desktop.png'), full_page=True)
                        page.set_viewport_size({'width': 390, 'height': 844})
                        page.wait_for_timeout(150)
                        assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth'), 'Mobile horizontal overflow'
                        page.screenshot(path=str(args.output/'04-storage-mobile.png'), full_page=True)
                        page.set_viewport_size({'width': 1440, 'height': 1000})
                        page.get_by_label('资源类型', exact=True).select_option('artifacts')
                        page.get_by_label('全选', exact=True).check()
                        page.locator('.storage-toolbar').get_by_role('button', name='删除', exact=True).click()
                        confirm('删除')
                        assert test['data'].exists() and not test['run'].exists() and not orphan.exists()
                        assert hashlib.sha256((test['data']/'train.csv').read_bytes()).hexdigest() == before
                        inventory = client.get('/api/studio/storage').json()['resources']
                        assert len(inventory) == 1 and inventory[0]['kind'] == 'projects'
                        page.reload(wait_until='networkidle')
                        project_row = page.locator('[data-resource="projects:' + test['project']['id'] + '"]')
                        expect(project_row.get_by_text('8 B', exact=True)).to_be_visible()
                        expect(project_row.get_by_role('button', name='删除', exact=True)).to_have_count(0)
                        project_row.get_by_role('button', name='归档', exact=True).click()
                        confirm('归档')
                        page.reload(wait_until='networkidle')
                        expect(page.get_by_role('heading', name='没有匹配的本地资源')).to_be_visible()
                        page.screenshot(path=str(args.output/'05-empty-active-storage.png'), full_page=True)
                        state = client.get('/api/studio/state').json()
                        counts = {kind: len(state[kind]) for kind in ['projects', 'archived_projects', 'tasks', 'packages', 'conversations', 'invocations']}
                        assert counts == {'projects': 0, 'archived_projects': 1, 'tasks': 0, 'packages': 0, 'conversations': 0, 'invocations': 0}, counts
                        assert not app.TaskStore().list_tasks(include_archived=True)
                        assert hashlib.sha256((test['data']/'train.csv').read_bytes()).hexdigest() == before
                        assert not failures, failures
                        assert not errors, errors
                        (args.output/'result.json').write_text(json.dumps({'passed': True, 'final_counts': counts,
                            'input_data_preserved': True, 'api_failures': failures, 'browser_errors': errors,
                            'checks': ['directory open', 'space size', 'cancel', 'data/task grouping',
                                       'no individual files', 'data folder archive-only', 'task group multiselect',
                                       'batch archive and restore', 'package deletion', 'development batch deletion',
                                       'data hash unchanged', 'reload', 'mobile']}, ensure_ascii=False, indent=2), encoding='utf-8')
                        print('PASS: grouped folder lifecycle, batch operations, permanent artifact deletion, preserved imported data, and mobile layout')
                        browser.close()
                finally:
                    server.terminate()
                    server.wait(timeout=15)


if __name__ == '__main__':
    main()
