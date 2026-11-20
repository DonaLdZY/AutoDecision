"""Exercise conversation management using private backend state and the real Vue build."""
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
    with tempfile.TemporaryDirectory(prefix='autodecision-conversation-browser-') as temporary:
        fixture_root = Path(temporary)
        os.environ['AUTODECISION_STATE_DIR'] = str(fixture_root/'initial-state')
        os.environ['AUTODECISION_GLOBAL_SETTINGS_PATH'] = str(fixture_root/'settings.yaml')
        sys.path[:0] = [str(backend), str(backend/'tests')]
        import pytest
        import app
        import decision_studio as studio
        from test_storage_management import local
        from playwright.sync_api import sync_playwright, expect

        with pytest.MonkeyPatch.context() as monkeypatch:
            test = local.__wrapped__(fixture_root, monkeypatch)
            client = test['client']
            other_data = fixture_root/'other-dataset'
            other_data.mkdir()
            (other_data/'data.csv').write_text('value\n3\n')
            other_project = client.post('/api/studio/projects', json={
                'name': '第二个数据项目', 'input_root': str(other_data)}).json()
            with studio.database(app) as db:
                db.put('conversations', dict(id='other-chat', project_id=other_project['id'],
                    title='其他项目的决策', messages=[dict(id='other-message', role='assistant', text='其他项目的历史回复')],
                    created_at=1, updated_at=2))
            titles = {'chat': '测试决策对话', 'second': '批量对话 A', 'third': '批量对话 B'}
            titles.update({f'extra-{i}': f'历史决策 {i}' for i in range(8)})
            titles['long'] = '特别长的决策对话名称及多级项目业务场景' * 5
            original_messages = [dict(id='user-message', role='user', text='测试历史需求'),
                                 dict(id='assistant-message', role='assistant', text='已保存的完整历史回复')]
            with studio.database(app) as db:
                for index, (identity, title) in enumerate(titles.items()):
                    db.put('conversations', dict(id=identity, project_id=test['project']['id'], title=title,
                        created_at=1, updated_at=100+index, messages=original_messages))
                call = db.get('invocations', 'call')
                call['conversation_id'] = 'chat'
                db.put('invocations', call)
            before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest()
                      for root in [test['data'], test['run'], test['package_root']]
                      for path in root.rglob('*') if path.is_file()}
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
                    deadline = time.monotonic()+30
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
                            response = client.request(request.method, '/api/'+path, content=request.post_data,
                                                      headers={'Content-Type': 'application/json'})
                            if response.status_code >= 400:
                                failures.append(dict(path=path, status=response.status_code, body=response.text))
                            route.fulfill(status=response.status_code, content_type='application/json', body=response.content)

                        context.route('**/api/**', bridge)
                        page = context.new_page()
                        page.on('pageerror', lambda error: errors.append(str(error)))
                        page.set_default_timeout(15000)

                        def tab(identity):
                            return page.locator(f'.conversation-tab[data-conversation="{identity}"]')

                        def menu_for(row):
                            row.hover()
                            row.locator('.conversation-menu-trigger').click()
                            return page.get_by_role('menu')

                        def confirm(action):
                            dialog = page.get_by_role('dialog', name=action+'对话', exact=True)
                            button = dialog.get_by_role('button', name='确认'+action, exact=True)
                            expect(button).to_be_enabled()
                            button.click()
                            expect(dialog).not_to_be_visible()
                            page.wait_for_load_state('networkidle')

                        def history(tab='active'):
                            if not page.get_by_role('dialog', name='对话历史', exact=True).is_visible():
                                page.get_by_role('button', name='对话历史', exact=True).click()
                            modal = page.get_by_role('dialog', name='对话历史', exact=True)
                            modal.get_by_role('button', name=re.compile('^已归档' if tab == 'archived' else '^全部对话')).click()
                            return modal

                        def history_row(identity):
                            return page.locator(f'.conversation-history-row[data-conversation="{identity}"]')

                        def assert_layout():
                            assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth'), 'Page overflow'
                            for dialog in page.locator('dialog[open]').all():
                                assert dialog.evaluate('(e) => e.scrollWidth <= e.clientWidth+1'), 'Dialog overflow'

                        page.goto(url+'/', wait_until='networkidle')
                        expect(page.get_by_role('heading', name='项目数据', exact=True)).to_be_visible()
                        expect(page.locator('.main-nav button > span:first-of-type')).to_have_text(
                            ['项目数据', '研发任务', '算法模型包', '决策对话'])
                        expect(page.locator('.sidebar .conversation-sidebar-row')).to_have_count(0)
                        expect(page.locator('.sidebar select')).to_have_count(0)
                        original_project_id = test['project']['id']

                        def choose_project(identity):
                            page.locator('.sidebar-project-context').click()
                            card = page.locator(f'.project-tile[data-project="{identity}"]')
                            card.locator('.project-select').click()
                            expect(card).to_have_class(re.compile('chosen'))
                            expect(card.locator('.project-select')).to_have_attribute('aria-pressed', 'true')
                            assert page.locator('.project-tile.chosen').count() == 1
                            page.wait_for_function('''(identity) => {
                                const card = document.querySelector(`.project-tile[data-project="${identity}"]`)
                                return getComputedStyle(card).borderTopColor === getComputedStyle(document.querySelector('.sidebar')).borderLeftColor
                            }''', arg=identity)
                            border = card.evaluate('(e) => getComputedStyle(e).borderTopColor')
                            accent = page.locator('.sidebar').evaluate('(e) => getComputedStyle(e).borderLeftColor')
                            assert border == accent, (border, accent)
                            return accent

                        def nav(label):
                            page.locator('.main-nav').get_by_role('button', name=re.compile('^'+label)).click()

                        first_accent = choose_project(original_project_id)
                        page.screenshot(path=str(args.output/'00-project-selection.png'), full_page=True)
                        nav('决策对话')
                        expect(page.locator('.conversation-tab')).to_have_count(12)
                        tab('chat').get_by_role('tab').click()
                        page.get_by_role('textbox', name='决策需求', exact=True).fill('第一个对话草稿')
                        tab('second').get_by_role('tab').click()
                        expect(page.get_by_role('textbox', name='决策需求', exact=True)).to_have_value('')
                        page.get_by_role('textbox', name='决策需求', exact=True).fill('第二个对话草稿')
                        tab('chat').get_by_role('tab').click()
                        expect(page.get_by_role('textbox', name='决策需求', exact=True)).to_have_value('第一个对话草稿')
                        tab('chat').get_by_role('tab').press('ArrowRight')
                        expect(page.get_by_role('tab', selected=True)).to_be_focused()
                        tab('chat').get_by_role('tab').click()
                        second_accent = choose_project(other_project['id'])
                        assert second_accent != first_accent
                        nav('研发任务')
                        expect(page.get_by_role('heading', name='这里还没有研发任务')).to_be_visible()
                        nav('算法模型包')
                        expect(page.locator('.package-tile')).to_have_count(0)
                        nav('决策对话')
                        expect(page.locator('.conversation-tab')).to_have_count(1)
                        expect(page.get_by_text('其他项目的历史回复', exact=True)).to_be_visible()
                        choose_project(original_project_id)
                        nav('研发任务')
                        expect(page.locator('.task-storage-row')).to_have_count(1)
                        nav('算法模型包')
                        expect(page.locator('.package-tile')).to_have_count(1)
                        nav('决策对话')
                        expect(tab('chat').get_by_role('tab')).to_have_attribute('aria-selected', 'true')
                        expect(page.get_by_role('textbox', name='决策需求', exact=True)).to_have_value('第一个对话草稿')
                        page.get_by_role('textbox', name='决策需求', exact=True).fill('')
                        page.screenshot(path=str(args.output/'00-conversation-tabs.png'), full_page=True)
                        page.reload(wait_until='networkidle')
                        expect(tab('chat').get_by_role('tab')).to_have_attribute('aria-selected', 'true')
                        tab('chat').get_by_role('tab', name='测试决策对话', exact=True).click()
                        trigger = tab('chat').locator('.conversation-menu-trigger')
                        trigger.focus()
                        trigger.press('ArrowDown')
                        expect(page.get_by_role('menuitem', name='重命名', exact=True)).to_be_focused()
                        page.get_by_role('menuitem', name='重命名', exact=True).press('ArrowDown')
                        expect(page.get_by_role('menuitem', name='归档', exact=True)).to_be_focused()
                        page.get_by_role('menuitem', name='归档', exact=True).press('Escape')
                        expect(trigger).to_be_focused()
                        expect(page.get_by_role('menu')).not_to_be_visible()
                        menu = menu_for(tab('chat'))
                        page.screenshot(path=str(args.output/'01-tab-menu.png'), full_page=True)
                        menu.get_by_role('menuitem', name='重命名', exact=True).click()
                        dialog = page.get_by_role('dialog', name='重命名对话', exact=True)
                        dialog.get_by_role('textbox', name='对话名称', exact=True).fill('我的测试决策')
                        dialog.get_by_role('button', name='保存', exact=True).click()
                        expect(dialog).not_to_be_visible()
                        expect(page.get_by_role('heading', name='我的测试决策', exact=True)).to_be_visible()
                        page.get_by_role('button', name='当前对话操作', exact=True).click()
                        page.get_by_role('menuitem', name='归档', exact=True).click()
                        dialog = page.get_by_role('dialog', name='归档对话', exact=True)
                        expect(dialog.get_by_text(re.compile('全部消息保留'))).to_be_visible()
                        dialog.get_by_role('button', name='取消', exact=True).click()
                        expect(tab('chat')).to_be_visible()
                        page.get_by_role('button', name='当前对话操作', exact=True).click()
                        page.get_by_role('menuitem', name='归档', exact=True).click()
                        confirm('归档')
                        expect(tab('chat')).to_have_count(0)
                        with studio.database(app) as db:
                            assert db.get('conversations', 'chat', include_archived=True)['messages'] == original_messages
                        modal = history('archived')
                        modal.get_by_role('searchbox', name='搜索对话', exact=True).fill('我的测试')
                        expect(history_row('chat')).to_be_visible()
                        menu_for(history_row('chat')).get_by_role('menuitem', name='还原', exact=True).click()
                        confirm('还原')
                        expect(history_row('chat')).to_have_count(0)
                        modal = history()
                        expect(history_row('chat')).to_be_visible()
                        history_row('chat').locator('.conversation-history-copy').click()
                        expect(modal).not_to_be_visible()
                        expect(page.get_by_text('已保存的完整历史回复', exact=True)).to_be_visible()
                        expect(tab('chat')).to_be_visible()

                        modal = history()
                        modal.get_by_role('searchbox', name='搜索对话', exact=True).fill('批量对话')
                        expect(page.locator('.conversation-history-row')).to_have_count(2)
                        modal.get_by_role('checkbox', name='全选', exact=True).check()
                        modal.locator('.conversation-bulk-bar').get_by_role('button', name='归档', exact=True).click()
                        confirm('归档')
                        expect(page.locator('.conversation-history-row')).to_have_count(0)
                        modal = history('archived')
                        expect(page.locator('.conversation-history-row')).to_have_count(2)
                        modal.get_by_role('checkbox', name='全选', exact=True).check()
                        modal.locator('.conversation-bulk-bar').get_by_role('button', name='还原', exact=True).click()
                        confirm('还原')
                        modal = history()
                        expect(page.locator('.conversation-history-row')).to_have_count(2)
                        modal.get_by_role('checkbox', name='全选', exact=True).check()
                        modal.locator('.conversation-bulk-bar').get_by_role('button', name='删除', exact=True).click()
                        dialog = page.get_by_role('dialog', name='删除对话', exact=True)
                        expect(dialog.get_by_text(re.compile('将永久删除所选对话及全部消息'))).to_be_visible()
                        page.screenshot(path=str(args.output/'02-batch-delete-confirm.png'), full_page=True)
                        dialog.get_by_role('button', name='取消', exact=True).click()
                        with studio.database(app) as db:
                            assert db.get('conversations', 'second') and db.get('conversations', 'third')
                        modal.locator('.conversation-bulk-bar').get_by_role('button', name='删除', exact=True).click()
                        confirm('删除')
                        expect(page.locator('.conversation-history-row')).to_have_count(0)
                        with studio.database(app) as db:
                            assert not db.connection.execute("SELECT id FROM documents WHERE kind='conversations' AND id IN ('second', 'third')").fetchall()
                        modal.get_by_role('searchbox', name='搜索对话', exact=True).fill('')
                        expect(page.locator('.conversation-history-row')).to_have_count(10)
                        page.screenshot(path=str(args.output/'03-history-desktop.png'), full_page=True)
                        modal.get_by_role('button', name='关闭详情', exact=True).click()
                        # Native popovers must stay on screen even at the bottom of a scrolled tab strip.
                        tab('chat').scroll_into_view_if_needed()
                        menu_for(tab('chat'))
                        box = page.get_by_role('menu').bounding_box()
                        assert box and box['x'] >= 0 and box['y'] >= 0 and box['y']+box['height'] <= 1000
                        page.get_by_role('menuitem', name='重命名', exact=True).press('Escape')
                        page.locator('.conversation-tabs-scroll').evaluate('(e) => e.scrollLeft = 0')
                        tab('long').get_by_role('tab', name=titles['long'], exact=True).click()
                        for width in [1440, 1024, 768, 390, 320]:
                            page.set_viewport_size({'width': width, 'height': 900})
                            page.wait_for_function('''() => {
                                const tab = document.querySelector('.conversation-tab.active').getBoundingClientRect()
                                const strip = document.querySelector('.conversation-tabs-scroll').getBoundingClientRect()
                                return tab.left >= strip.left - 1 && tab.right <= strip.right + 1
                            }''')
                            assert_layout()
                            modal = history()
                            assert_layout()
                            menu_for(history_row('long'))
                            box = page.get_by_role('menu').bounding_box()
                            assert box and box['x'] >= 0 and box['x']+box['width'] <= width
                            page.get_by_role('menuitem', name='重命名', exact=True).press('Escape')
                            if width == 390:
                                page.screenshot(path=str(args.output/'04-history-mobile.png'), full_page=True)
                            modal.get_by_role('button', name='关闭详情', exact=True).click()
                            page.screenshot(path=str(args.output/f'tabs-{width}.png'), full_page=True)
                            if width > 760:
                                choose_project(original_project_id)
                            else:
                                page.get_by_role('button', name='打开导航', exact=True).click()
                                nav('项目数据')
                            assert_layout()
                            page.screenshot(path=str(args.output/f'projects-{width}.png'), full_page=True)
                            if width <= 760:
                                page.get_by_role('button', name='打开导航', exact=True).click()
                            nav('决策对话')
                        # The dialog remains reachable from a conversation tab on mobile.
                        active_tab = tab('chat')
                        menu_for(active_tab).get_by_role('menuitem', name='重命名', exact=True).click()
                        dialog = page.get_by_role('dialog', name='重命名对话', exact=True)
                        expect(dialog.get_by_role('textbox')).to_be_focused()
                        dialog.get_by_role('textbox').press('Tab')
                        assert dialog.evaluate('(e) => e.contains(document.activeElement)')
                        dialog.get_by_role('button', name='取消', exact=True).click()
                        page.set_viewport_size({'width': 1440, 'height': 1000})
                        tab('chat').get_by_role('tab', name='我的测试决策', exact=True).click()
                        page.get_by_role('button', name='当前对话操作', exact=True).click()
                        page.get_by_role('menuitem', name='删除', exact=True).click()
                        confirm('删除')
                        expect(tab('chat')).to_have_count(0)
                        page.reload(wait_until='networkidle')
                        expect(tab('chat')).to_have_count(0)
                        expect(tab('second')).to_have_count(0)
                        expect(tab('third')).to_have_count(0)
                        expect(page.locator('.conversation-tab')).to_have_count(9)
                        with studio.database(app) as db:
                            assert db.get('invocations', 'call')['conversation_id'] == ''
                            assert db.get('packages', 'package-1')
                        assert app.TaskStore().get(test['task'].id)
                        page.locator('.sidebar-project-context').click()
                        page.get_by_role('button', name='创建数据项目', exact=True).click()
                        dialog = page.get_by_role('dialog', name='创建数据项目', exact=True)
                        dialog.get_by_role('textbox', name='项目名称', exact=True).fill('前端新建项目')
                        dialog.get_by_role('textbox', name='数据目录（本机绝对路径）', exact=True).fill(str(other_data))
                        dialog.get_by_role('button', name='创建项目', exact=True).click()
                        expect(dialog).not_to_be_visible()
                        created = next(p for p in client.get('/api/studio/state').json()['projects'] if p['name'] == '前端新建项目')
                        assert created['color'] not in [test['project']['color'], other_project['color']]
                        expect(page.locator(f'.project-tile[data-project="{created["id"]}"]')).to_have_class(re.compile('chosen'))
                        nav('决策对话')
                        expect(page.locator('.conversation-tab')).to_have_count(0)
                        page.get_by_role('button', name='新建对话', exact=True).click()
                        expect(page.locator('.conversation-tab')).to_have_count(1)
                        page.get_by_role('textbox', name='决策需求', exact=True).fill('目录验证')
                        page.get_by_label('对话设置', exact=True).click()
                        page.get_by_label('模型使用', exact=True).select_option('catalog')
                        page.get_by_role('button', name='发送需求', exact=True).click()
                        expect(page.locator('.conversation-tab-button')).to_contain_text('目录验证')
                        expect(page.get_by_role('textbox', name='决策需求', exact=True)).to_have_value('')
                        page.reload(wait_until='networkidle')
                        expect(page.locator('.conversation-tab')).to_have_count(1)
                        assert all(Path(path).exists() and hashlib.sha256(Path(path).read_bytes()).hexdigest() == digest
                                   for path, digest in before.items())
                        assert not failures, failures
                        assert not errors, errors
                        (args.output/'result.json').write_text(json.dumps(dict(passed=True, api_failures=failures,
                            browser_errors=errors, preserved_resource_files=len(before), checks=[
                            'project navigation order', 'project card selection and sidebar color', 'scoped tasks/packages/conversations',
                            'project and tab persistence', 'per-conversation drafts', 'new project color', 'new conversation and send',
                            'all conversation tabs', 'keyboard menu', 'rename', 'cancel', 'header actions',
                            'archive preserves messages', 'restore from archived history', 'search',
                            'batch archive restore delete', 'real database deletion', 'reload persistence',
                            'responsive widths 1440/1024/768/390/320', 'mobile focus', 'resource preservation']),
                            ensure_ascii=False, indent=2), encoding='utf-8')
                        print('PASS: conversation tabs, history, rename, archive/restore, batch deletion, responsive layout')
                        browser.close()
                finally:
                    server.terminate()
                    server.wait(timeout=15)


if __name__ == '__main__':
    main()
