"""Exercise the real paid planning + project-input + frozen-package UI flow.

Requires finish-chemical-studio-demo.py to have published this run's package.
Uses the running Studio and configured provider; no mocks, injected answers,
or candidate edits. Receipts and screenshots remain beside the real run.
"""
from pathlib import Path
import json
import urllib.request

from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT/'runs/chemical-studio-demo-20261019'
OUT = ROOT/'frontend/decision-studio/review-v0.2.4/real-chemical'
QUESTION = '基于项目最新设备数据，预测下个小时压滤液 Al(N) 结果，还有推荐的蒸汽进气流量。请列明预测时间、参考依据和适用限制。'


def state():
    with urllib.request.urlopen('http://127.0.0.1:18080/api/studio/state') as response:
        return json.load(response)


def main():
    receipt = json.loads((RUN/'receipt.json').read_text(encoding='utf-8'))
    package = json.loads((RUN/'published-package.json').read_text(encoding='utf-8'))
    assert package['task_id'] == receipt['task_id']
    assert any(p['id']==package['id'] for p in state()['packages'])
    OUT.mkdir(parents=True,exist_ok=True)
    errors=[]
    with sync_playwright() as pw:
        browser=pw.chromium.launch(channel='msedge',headless=True)
        page=browser.new_page(viewport={'width':1440,'height':1000})
        page.on('pageerror',lambda error:errors.append(str(error)))
        page.add_init_script('localStorage.setItem("studio.project",'+json.dumps(receipt['project_id'])+');')
        page.goto('http://127.0.0.1:5178/#chat',wait_until='networkidle')
        conversations=[c for c in state()['conversations'] if c['project_id']==receipt['project_id']
                       and any(m.get('role')=='user' and m.get('text')==QUESTION for m in c['messages'])]
        if not conversations:
            page.get_by_role('button',name='新建对话',exact=True).click()
            page.get_by_label('决策需求',exact=True).fill(QUESTION)
            with page.expect_response(lambda r:'/messages' in r.url and r.request.method=='POST',timeout=90000) as response:
                page.get_by_role('button',name='发送需求',exact=True).click()
            answer=response.value.json()
            (RUN/'real-planning-response.json').write_text(json.dumps(answer,ensure_ascii=False,indent=2),encoding='utf-8')
            assert response.value.ok,answer
            conversations=[c for c in state()['conversations'] if c['project_id']==receipt['project_id']
                           and any(m.get('text')==QUESTION for m in c['messages'])]
        conversation=conversations[0]
        # Reopening a previous run must select its actual persisted conversation.
        page.locator('.sidebar').get_by_role('button',name=conversation['title'],exact=False).click()
        plan_message=next(m for m in conversation['messages'] if m.get('plan'))
        assert plan_message['model']=='deepseek-flash',plan_message
        assert plan_message['plan']['action']=='reuse',plan_message
        assert [s['package_id'] for s in plan_message['plan']['steps']]==[package['id']],plan_message
        expect(page.get_by_role('button',name='核对输入并调用',exact=False)).to_be_visible()
        page.screenshot(path=str(OUT/'05-real-llm-plan.png'))
        existing=[i for i in state()['invocations'] if i['conversation_id']==conversation['id'] and i['status']=='completed']
        if not existing:
            page.get_by_role('button',name='核对输入并调用',exact=False).click()
            expect(page.get_by_label('输入方式',exact=True)).to_have_value('project')
            page.get_by_role('button',name='准备项目输入',exact=True).click()
            expect(page.get_by_role('heading',name='输入已准备',exact=False)).to_be_visible(timeout=30000)
            page.screenshot(path=str(OUT/'06-real-project-input.png'))
            page.get_by_label('每步超时（秒，1–120）',exact=True).fill('120')
            page.get_by_label('我已核对输入语义、单位、版本和组合接口，确认执行本地推理',exact=True).check()
            with page.expect_response(lambda r:r.url.endswith('/studio/invocations') and r.request.method=='POST',timeout=150000) as response:
                page.get_by_role('button',name='确认调用',exact=True).click()
            invocation=response.value.json()
            (RUN/'real-ui-invocation.json').write_text(json.dumps(invocation,ensure_ascii=False,indent=2),encoding='utf-8')
            assert invocation['status']=='completed',invocation
            expect(page.get_by_role('heading',name='实际输出',exact=True)).to_be_visible(timeout=10000)
            page.screenshot(path=str(OUT/'07-real-invocation-chain.png'))
            page.get_by_role('button',name='关闭详情',exact=True).click()
        else:
            with urllib.request.urlopen('http://127.0.0.1:18080/api/studio/invocations/'+existing[0]['id']) as response:
                invocation=json.load(response)
        expect(page.locator('.message-scroll .decision-result')).to_be_visible(timeout=10000)
        page.locator('.message-scroll').evaluate('''(el) => {
          const result = el.querySelector('.decision-result')
          if (result) el.scrollTop += result.getBoundingClientRect().top - el.getBoundingClientRect().top - 12
        }''')
        page.wait_for_timeout(300)
        page.screenshot(path=str(OUT/'08-real-chat-result.png'))
        page.set_viewport_size({'width':390,'height':844})
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
        page.screenshot(path=str(OUT/'09-real-chat-mobile.png'))
        assert not errors,errors
        browser.close()
    updated=next(c for c in state()['conversations'] if c['id']==conversation['id'])
    (RUN/'real-conversation.json').write_text(json.dumps(updated,ensure_ascii=False,indent=2),encoding='utf-8')
    result={'passed':True,'task_id':receipt['task_id'],'package_id':package['id'],
        'conversation_id':conversation['id'],'invocation_id':invocation['id'],
        'question':QUESTION,'model':plan_message['model'],'result':invocation['result'],'page_errors':errors,
        'scope':'Real running Studio, real DeepSeek plan, actual project CSV preparation, new frozen package subprocess inference.'}
    (RUN/'frontend-acceptance.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':
    main()
