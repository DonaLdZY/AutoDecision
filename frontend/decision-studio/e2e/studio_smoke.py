"""Browser acceptance tests for the isolated Decision Studio demo.

Run against a local server: python e2e/studio_smoke.py --url http://127.0.0.1:5178
Uses fresh browser contexts, synthetic data, and no AutoDecision / provider API.
"""
import argparse
import json
from pathlib import Path
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright, expect

parser = argparse.ArgumentParser()
parser.add_argument('--url', default='http://127.0.0.1:5178')
args = parser.parse_args()
ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'review'
OUT.mkdir(exist_ok=True)
checks = []
errors = []
external_requests = []


def passed(name):
    checks.append(name)
    print(f'PASS {name}', flush=True)


def stored(page):
    return page.evaluate("JSON.parse(localStorage.getItem('autodecision.studio.demo.v1'))")


def send(page, text):
    page.get_by_label('决策需求', exact=True).fill(text)
    page.get_by_role('button', name='发送需求', exact=True).click()
    expect(page.locator('.typing-message')).to_have_count(0, timeout=10000)


def nav(page, name):
    page.locator('.main-nav').get_by_role('button', name=name, exact=False).click()


def close(page):
    page.get_by_role('button', name='关闭详情', exact=True).click()
    expect(page.get_by_role('dialog')).to_have_count(0)


def attach(page):
    page.on('pageerror', lambda e: errors.append(str(e)))
    page.on('console', lambda msg: errors.append(msg.text) if msg.type == 'error' else None)
    page.on('request', lambda req: external_requests.append(req.url) if urlparse(req.url).hostname not in {'127.0.0.1', 'localhost', None} else None)


with sync_playwright() as pw:
    browser = pw.chromium.launch()
    context = browser.new_context(viewport={'width':1600, 'height':1000}, reduced_motion='reduce')
    page = context.new_page()
    attach(page)
    page.goto(args.url, wait_until='networkidle')
    expect(page.get_by_role('heading', name='明日用能与错峰排产')).to_be_visible()
    expect(page.locator('.invocation-card')).to_have_count(1)
    expect(page.get_by_role('button', name='查看执行详情', exact=True)).to_be_in_viewport()
    box = page.locator('.composer-area').bounding_box()
    assert box['y'] + box['height'] <= 1001, box
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    page.screenshot(path=str(OUT / '01-chat-desktop.png'))
    passed('Default conversation, result receipt and composer are visible without page overflow')

    page.get_by_role('button', name='查看执行详情', exact=True).click()
    expect(page.get_by_role('dialog')).to_be_visible()
    expect(page.get_by_text('新增训练', exact=True)).to_be_visible()
    page.get_by_role('button', name='输入对齐', exact=True).click()
    expect(page.get_by_text('forecast.predicted_load_mw', exact=True)).to_be_visible()
    page.screenshot(path=str(OUT / '04-invocation-mapping.png'))
    page.get_by_role('button', name='调用代码', exact=True).click()
    expect(page.locator('.dark-code')).to_contain_text('"allow_training": False')
    page.get_by_role('button', name='结果与输出', exact=True).click()
    expect(page.locator('.detail-result')).to_contain_text('2,840')
    with page.expect_download() as info:
        page.get_by_role('button', name='导出执行记录', exact=True).click()
    data = json.loads(Path(info.value.path()).read_text(encoding='utf-8'))
    assert data['demo'] is True and data['packages'][0]['version'] == '1.2.0'
    page.keyboard.press('Escape')
    expect(page.get_by_role('dialog')).to_have_count(0)
    passed('Invocation tabs, frozen version export, and Escape dismissal work')

    nav(page, '算法模型包')
    page.screenshot(path=str(OUT / '02-packages-desktop.png'))
    page.get_by_label('搜索模型包', exact=True).fill('异常')
    expect(page.locator('.package-card')).to_have_count(1)
    page.get_by_label('搜索模型包', exact=True).fill('不存在的能力')
    expect(page.get_by_role('heading', name='没有匹配的模型包')).to_be_visible()
    page.get_by_role('button', name='清除筛选', exact=True).click()
    expect(page.locator('.package-card')).to_have_count(3)
    page.get_by_role('button', name='查看生产负荷预测详情', exact=True).click()
    page.get_by_role('button', name='输入 / 输出合同', exact=True).click()
    expect(page.get_by_role('dialog').get_by_text('production_plan', exact=True)).to_be_visible()
    page.get_by_role('button', name='文件与调用', exact=True).click()
    expect(page.get_by_role('dialog').get_by_text('packages/load-forecast/1.2.0/model/model.pkl', exact=True)).to_be_visible()
    with page.expect_download() as info:
        page.get_by_role('button', name='导出包说明', exact=True).click()
    package_manifest = json.loads(Path(info.value.path()).read_text(encoding='utf-8'))
    assert package_manifest['demo'] and 'weights' in package_manifest['immutable']
    page.get_by_role('button', name='版本与来源', exact=True).click()
    page.get_by_role('button', name='查看来源任务 AD-021', exact=True).click()
    expect(page.get_by_role('heading', name='生产负荷预测模型研发', exact=True)).to_be_visible()
    close(page)
    passed('Package search, empty state, contract, artifacts, manifest and source task navigation work')

    nav(page, '数据项目')
    page.get_by_role('button', name='字段与语义', exact=True).click()
    expect(page.locator('.data-table-panel').get_by_text('实测平均有功功率', exact=True)).to_be_visible()
    page.get_by_role('button', name='数据预览', exact=True).click()
    page.screenshot(path=str(OUT / '05-project-data.png'))
    passed('Project data preview and schema switch work')

    nav(page, '研发任务')
    page.locator('.task-row').first.click()
    page.get_by_role('button', name='暂停', exact=True).click()
    expect(page.get_by_role('button', name='推进演示', exact=True)).to_be_disabled()
    page.get_by_role('button', name='继续', exact=True).click()
    expect(page.get_by_role('button', name='推进演示', exact=True)).to_be_enabled()
    page.get_by_role('button', name='候选 4 序列网络', exact=True).click()
    expect(page.locator('.candidate-details')).to_contain_text('shape mismatch')
    page.get_by_role('button', name='候选 12 跨分支融合', exact=True).click()
    expect(page.locator('.candidate-details')).to_contain_text('额外参考 #07')
    page.set_viewport_size({'width':1600,'height':1100})
    page.locator('.dialog-body').evaluate('(el)=>el.scrollTop=110')
    page.screenshot(path=str(OUT / '03-task-search-desktop.png'))
    close(page)
    page.set_viewport_size({'width':1600,'height':1000})
    passed('Task pause/resume, failure node and cross-branch fusion details work')

    page.get_by_role('button', name='新建对话', exact=False).click()
    send(page, '预测设备剩余寿命')
    expect(page.get_by_role('button', name='创建研发任务', exact=False)).to_be_visible()
    page.get_by_role('button', name='创建研发任务', exact=False).click()
    new_task_id = stored(page)['tasks'][0]['id']
    expect(page.get_by_role('dialog').get_by_text('业务需求', exact=True)).to_be_visible()
    page.get_by_role('button', name='推进演示', exact=True).click()
    expect(page.get_by_text('项目数据证据', exact=True)).to_be_visible()
    page.get_by_role('button', name='推进演示', exact=True).click()
    expect(page.get_by_role('group', name='模拟候选算法搜索树', exact=True)).to_be_visible()
    page.get_by_role('button', name='推进演示', exact=True).click()
    expect(page.get_by_text('生产验收', exact=True)).to_be_visible()
    expect(page.get_by_text('未执行', exact=True)).to_be_visible()
    page.get_by_role('button', name='推进演示', exact=True).click()
    expect(page.get_by_role('button', name='发布演示模型包', exact=True)).to_be_disabled()
    page.get_by_role('checkbox').check()
    page.screenshot(path=str(OUT / '06-publish-capability.png'))
    page.get_by_role('button', name='发布演示模型包', exact=True).click()
    expect(page.get_by_role('dialog').get_by_role('heading', name='设备剩余寿命预测 v1.0.0', exact=True)).to_be_visible()
    current = stored(page)
    new_package = next(pkg for pkg in current['packages'] if pkg['taskId'] == new_task_id)
    assert new_package['projectId'] == 'steel'
    page.get_by_role('button', name='在对话中使用', exact=True).click()
    expect(page.locator('.pinned-package')).to_contain_text('设备剩余寿命预测')
    send(page, '使用这个包预测设备剩余寿命')
    expect(page.locator('.invocation-card')).to_contain_text('182')
    assert stored(page)['invocations'][0]['packageIds'] == [new_package['id']]
    count_before = len(stored(page)['tasks'])
    page.get_by_role('button', name='新建对话', exact=False).click()
    send(page, '预测设备剩余寿命')
    expect(page.locator('.invocation-card')).to_have_count(1)
    assert len(stored(page)['tasks']) == count_before
    passed('Full lifecycle: capability gap → research → validation → reviewed publication → pinned and natural-language reuse')

    page.get_by_role('button', name='新建对话', exact=False).click()
    send(page, '这张新表的功率字段是 power_kw，请检查单位对齐')
    page.locator('.mapping-control select').select_option('kWh')
    page.get_by_role('button', name='确认对齐并调用', exact=True).click()
    expect(page.locator('.toast-message')).to_contain_text('不能直接映射为功率')
    expect(page.locator('.invocation-card')).to_have_count(0)
    page.locator('.mapping-control select').select_option('kW')
    page.get_by_role('button', name='确认对齐并调用', exact=True).click()
    expect(page.locator('.invocation-card')).to_have_count(1)
    expect(page.get_by_role('button', name='已确认并调用', exact=True)).to_be_disabled()
    current = stored(page)
    assert current['invocations'][0]['aligned'] is True
    assert any('÷ 1000' in m['rule'] for m in current['invocations'][0]['mapping'])
    assert next(pkg for pkg in current['packages'] if pkg['id'] == 'pkg-load')['version'] == '1.2.0'
    saved_conversation = current['conversationId']
    page.reload(wait_until='networkidle')
    expect(page.locator('.invocation-card')).to_have_count(1)
    assert stored(page)['conversationId'] == saved_conversation
    passed('Incompatible energy/power mapping is blocked; confirmed conversion preserves model version and survives reload')

    page.get_by_label('当前数据项目', exact=True).select_option('water')
    expect(page.locator('.context-rail')).to_contain_text('分区用水需求预测')
    expect(page.locator('.context-rail')).not_to_contain_text('生产负荷预测')
    send(page, '预测明天的分区用水需求')
    expect(page.locator('.invocation-card')).to_contain_text('12,640')
    assert stored(page)['invocations'][0]['packageIds'] == ['pkg-water']
    nav(page, '算法模型包')
    expect(page.locator('.package-card')).to_have_count(1)
    nav(page, '研发任务')
    expect(page.locator('.task-row')).to_have_count(1)
    page.get_by_label('当前数据项目', exact=True).select_option('steel')
    nav(page, '决策对话')
    expect(page.locator('.context-rail')).to_contain_text('设备剩余寿命预测')
    passed('Project-scoped conversations, packages, invocations and tasks remain isolated')

    page.get_by_role('button', name='新建对话', exact=False).click()
    send(page, '请分析一个没有预设的自定义需求')
    expect(page.locator('.message-text').last).to_contain_text('预设场景')
    expect(page.locator('.invocation-card')).to_have_count(0)
    passed('Unsupported free text receives an explicit demo limitation instead of a fabricated execution')

    nav(page, '数据项目')
    page.get_by_role('button', name='新建项目', exact=True).click()
    page.get_by_label('项目名称', exact=True).fill('测试厂 · 设备管理')
    page.get_by_role('button', name='创建演示项目', exact=False).click()
    expect(page.get_by_role('heading', name='给这个项目添加第一份数据', exact=True)).to_be_visible()
    page.get_by_role('button', name='添加演示数据', exact=True).first.click()
    expect(page.locator('.table-list>button')).to_have_count(3)
    nav(page, '算法模型包')
    expect(page.locator('.package-card')).to_have_count(0)
    page.locator('.settings-nav').click()
    page.get_by_label('可用 CPU 核心', exact=True).fill('12')
    page.get_by_role('button', name='保存演示配置', exact=True).click()
    expect(page.locator('.resource-mini')).to_contain_text('12')
    page.reload(wait_until='networkidle')
    expect(page.get_by_label('可用 CPU 核心', exact=True)).to_have_value('12')
    page.get_by_role('button', name='重置演示数据', exact=True).click()
    page.get_by_role('button', name='取消', exact=True).click()
    assert len(stored(page)['projects']) == 3
    page.get_by_role('button', name='重置演示数据', exact=True).click()
    page.get_by_role('button', name='确认重置演示', exact=True).click()
    expect(page.get_by_role('heading', name='明日用能与错峰排产', exact=True)).to_be_visible()
    assert len(stored(page)['projects']) == 2
    passed('Project creation, synthetic data import, settings persistence and cancel/confirm reset work')

    page.evaluate("localStorage.setItem('autodecision.studio.demo.v1', '{broken')")
    page.reload(wait_until='networkidle')
    expect(page.get_by_role('heading', name='明日用能与错峰排产', exact=True)).to_be_visible()
    page.get_by_role('button', name='使用说明', exact=True).click()
    for _ in range(8):
        page.keyboard.press('Tab')
        assert page.evaluate("document.querySelector('dialog').contains(document.activeElement)")
    page.keyboard.press('Escape')
    passed('Corrupt saved state recovers; native dialog traps keyboard focus and supports Escape')

    context.close()
    mobile_context = browser.new_context(viewport={'width':390,'height':844}, is_mobile=True, has_touch=True, device_scale_factor=1, reduced_motion='reduce')
    mobile = mobile_context.new_page()
    attach(mobile)
    mobile.goto(args.url, wait_until='networkidle')
    expect(mobile.get_by_role('button', name='打开导航', exact=True)).to_be_visible()
    assert mobile.evaluate('document.documentElement.scrollWidth <= innerWidth')
    box = mobile.locator('.composer-area').bounding_box()
    assert box['y'] + box['height'] <= 845, box
    mobile.screenshot(path=str(OUT / '07-chat-mobile.png'))
    mobile.get_by_role('button', name='打开导航', exact=True).click()
    nav(mobile, '算法模型包')
    expect(mobile.get_by_role('heading', name='算法模型包 3', exact=True)).to_be_visible()
    mobile.get_by_role('button', name='查看生产负荷预测详情', exact=True).click()
    dialog_box=mobile.get_by_role('dialog').bounding_box()
    assert dialog_box['x'] >= 0 and dialog_box['x'] + dialog_box['width'] <= 390
    close(mobile)
    mobile.get_by_role('button', name='打开导航', exact=True).click()
    mobile.get_by_label('当前数据项目', exact=True).select_option('water')
    mobile.get_by_role('button', name='打开导航', exact=True).click()
    nav(mobile, '决策对话')
    send(mobile, '预测明天的用水需求')
    expect(mobile.locator('.invocation-card')).to_contain_text('12,640')
    passed('390 px mobile navigation, project switch, dialogs and conversation submission work')
    mobile_context.close()
    browser.close()

assert not errors, errors
assert not external_requests, external_requests
passed('No browser runtime/console errors or external API/data requests observed')
report={'demo_version':'0.1.0','checks':checks,'passed':len(checks),'console_errors':errors,'external_requests':external_requests,'scope':'Chromium browser UI acceptance with synthetic state; no backend or model execution','screenshots':sorted(p.name for p in OUT.glob('*.png'))}
(OUT/'browser-validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(report,ensure_ascii=False,indent=2),flush=True)
