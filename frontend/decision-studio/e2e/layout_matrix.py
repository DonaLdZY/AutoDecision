"""Check layout containment across desktop, tablet and small mobile viewports."""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

root = Path(__file__).resolve().parents[1]
results = []
with sync_playwright() as pw:
    browser = pw.chromium.launch()
    for width, height in [(1600,1000),(1440,900),(1280,800),(1024,768),(768,1024),(390,844),(360,800)]:
        context = browser.new_context(viewport={'width':width,'height':height}, reduced_motion='reduce')
        page = context.new_page()
        for route in ['chat','projects','packages','tasks','invocations','settings']:
            page.goto(f'http://127.0.0.1:5178/#{route}',wait_until='networkidle')
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), (width,route,'document overflow')
            assert page.locator('.main-content').evaluate('(el)=>el.scrollWidth <= el.clientWidth'), (width,route,'main overflow')
            if route == 'chat':
                box=page.locator('.composer-area').bounding_box()
                assert box['y'] >= 0 and box['y']+box['height'] <= height+1, (width,route,'composer clipped')
                expect(page.get_by_role('button',name='发送需求',exact=True)).to_be_in_viewport()
                if width==1440: page.screenshot(path=str(root/'review/08-chat-laptop.png'))
            if route == 'packages':
                page.get_by_role('button',name='查看生产负荷预测详情',exact=True).click()
                expect(page.get_by_role('dialog')).to_be_visible()
                assert page.locator('.dialog-body').evaluate('(el)=>el.scrollWidth <= el.clientWidth'), (width,route,'dialog overflow')
                page.get_by_role('button',name='输入 / 输出合同',exact=True).click()
                assert page.locator('.dialog-body').evaluate('(el)=>el.scrollWidth <= el.clientWidth'), (width,route,'contract overflow')
                page.keyboard.press('Escape')
            results.append({'width':width,'height':height,'page':route,'passed':True})
        context.close()
    browser.close()
(root/'review/layout-validation.json').write_text(json.dumps({'passed':len(results),'cases':results,'scope':'Viewport containment; tables and algorithm graph may scroll within their containers.'},ensure_ascii=False,indent=2),encoding='utf-8')
print(f'PASS {len(results)} viewport/page combinations')
