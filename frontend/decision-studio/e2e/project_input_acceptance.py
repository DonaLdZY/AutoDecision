"""Isolated real-API/browser checks of project-window inference (test fixture only)."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[3]
STUDIO = ROOT/'frontend/decision-studio'
OUT = STUDIO/'review-v0.2.4'
OUT.mkdir(exist_ok=True)
WORK = Path(tempfile.mkdtemp(prefix='studio-input-acceptance-'))
STATE = WORK/'state'
STATE.mkdir()
os.environ['AUTODECISION_STATE_DIR'] = str(STATE)
os.environ['AUTODECISION_GLOBAL_SETTINGS_PATH'] = str(WORK/'settings.json')
os.environ.pop('AUTODECISION_API_TOKEN',None)
(WORK/'settings.json').write_text(json.dumps({'python':{'executable':sys.executable}}))
sys.path.insert(0,str(ROOT/'frontend/backend'))
import app
from fastapi.testclient import TestClient

client = TestClient(app.app)
source = WORK/'input'
source.mkdir()
datafile = source/'observations.csv'
datafile.write_text('time,value\n2026-05-25 09:00:00,1\n2026-05-25 09:30:00,2\n2026-05-25 10:00:00,3\n')
project = client.post('/api/studio/projects',json={'name':'时间窗接口验收夹具','input_root':str(source)}).json()
task = app.store.create(app.TaskConfigPayload(task_name='仅接口验收，不是研发成果',input_root=str(source),output_root=str(WORK/'runs')))
ws = WORK/'workspace'
pkg = ws/'best_solution'
pkg.mkdir(parents=True)
(ws/'input').mkdir()
(ws/'input/description.md').write_text('Isolated product regression fixture, no business quality claims.')
code = "def predict(model_path,data):\n    return {'prediction_cutoff':data['prediction_cutoff'],'test_sum':sum(r['value'] for r in data['history'])}\ndef train(*args):\n    raise RuntimeError('Training is forbidden in inference')\n"
for name in ['solution.py','implementation.py']:
    (pkg/name).write_text(code)
manifest={'node_id':'fixture','entrypoint':'predict','artifact_required':False,'implementation_path':'implementation.py','implementation_file_sha256':hashlib.sha256((pkg/'implementation.py').read_bytes()).hexdigest()}
(pkg/'solution_manifest.json').write_text(json.dumps(manifest))
app.store.set_status(task.id,status='completed',phase='automl_completed',auto_ml_workspace_dir=str(ws))
app.store._persist()
with __import__('decision_studio').database(app) as db:
    db.put('links',{'id':task.id,'project_id':project['id']})
binding={'sources':[{'path':'observations.csv','field':'history','time_column':'time','columns':['time','value'],'window_seconds':3600}]}
response=client.post('/api/studio/packages',json={'project_id':project['id'],'task_id':task.id,'name':'时间窗求和验收夹具','input_binding':binding,
    'input_schema':{'type':'object','required':['history','prediction_cutoff']},'description':'仅产品接口验收，求和不是业务模型'})
assert response.status_code==200,response.text
package=response.json()
conversation=client.post('/api/studio/conversations',json={'project_id':project['id']}).json()
client.post(f"/api/studio/conversations/{conversation['id']}/messages",json={'text':'读取最新观测窗口求和','request_id':'fixture-plan','package_id':package['id'],'mode':'catalog'})


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0))
        return sock.getsockname()[1]


api_port,ui_port=free_port(),free_port()
processes=[]
logs=[]
checks=[]
errors=[]


def start(args,cwd,env,name):
    log=(WORK/(name+'.log')).open('w',encoding='utf-8');logs.append(log)
    p=subprocess.Popen(args,cwd=cwd,env=env,stdout=log,stderr=log,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    processes.append(p)
    return p


def ready(url,process):
    for _ in range(100):
        assert process.poll() is None,'server exited'
        try:
            with urllib.request.urlopen(url,timeout=1):return
        except Exception:time.sleep(.2)
    raise RuntimeError('server not ready')


try:
    env=os.environ.copy()
    gateway=start([sys.executable,'-m','uvicorn','app:app','--host','127.0.0.1','--port',str(api_port)],ROOT/'frontend/backend',env,'gateway')
    ready(f'http://127.0.0.1:{api_port}/api/health',gateway)
    env['AUTODECISION_GATEWAY_TARGET']=f'http://127.0.0.1:{api_port}'
    vite=start([shutil.which('node'),str(STUDIO/'node_modules/vite/bin/vite.js'),'preview','--host','127.0.0.1','--port',str(ui_port),'--strictPort'],STUDIO,env,'vite')
    ready(f'http://127.0.0.1:{ui_port}/',vite)
    from playwright.sync_api import sync_playwright,expect
    with sync_playwright() as pw:
        browser=pw.chromium.launch(channel='msedge' if sys.platform=='win32' else None,headless=True)
        page=browser.new_page(viewport={'width':1440,'height':1000})
        page.on('pageerror',lambda e:errors.append(str(e)))
        page.goto(f'http://127.0.0.1:{ui_port}/#chat',wait_until='networkidle')
        page.get_by_role('button',name='核对输入并调用',exact=False).click()
        expect(page.get_by_label('输入方式',exact=True)).to_have_value('project')
        expect(page.get_by_role('button',name='确认调用',exact=True)).to_be_disabled()
        page.get_by_role('button',name='准备项目输入',exact=True).click()
        expect(page.get_by_role('heading',name='输入已准备',exact=False)).to_contain_text('2026-05-25 10:00:00',timeout=15000)
        expect(page.get_by_text('observations.csv → history',exact=False)).to_contain_text('2 行')
        page.screenshot(path=str(OUT/'01-project-window-prepared.png'))
        checks.append('prepare actual CSV time window through product UI and API')
        checkbox=page.get_by_label('我已核对输入语义、单位、版本和组合接口，确认执行本地推理',exact=True)
        checkbox.check()
        page.get_by_label('数据截止时间',exact=True).fill('2026-05-25 09:30:00')
        expect(checkbox).not_to_be_checked()
        expect(page.get_by_role('button',name='确认调用',exact=True)).to_be_disabled()
        expect(page.get_by_text('包或截止时间已变化，请重新准备输入。',exact=True)).to_be_visible()
        page.get_by_role('button',name='准备项目输入',exact=True).click()
        expect(page.get_by_role('heading',name='输入已准备',exact=False)).to_contain_text('09:30:00',timeout=15000)
        checks.append('cutoff change invalidates prepared input and resets confirmation')
        datafile.write_text('time,value\n2026-05-25 09:30:00,999\n')
        checkbox.check()
        page.get_by_role('button',name='确认调用',exact=True).click()
        expect(page.get_by_role('heading',name='实际输出',exact=True)).to_be_visible(timeout=15000)
        expect(page.get_by_role('dialog').locator('.result-field').filter(has_text='test_sum')).to_contain_text('3')
        expect(page.locator('.live-detail')).to_contain_text('input_provenance')
        page.screenshot(path=str(OUT/'02-frozen-input-result.png'))
        checks.append('frozen snapshot is used despite subsequent source changes; provenance persisted')
        page.get_by_role('button',name='关闭详情',exact=True).click()
        expect(page.locator('.message-scroll .result-field').filter(has_text='test_sum')).to_contain_text('3',timeout=10000)
        for width,height in [(1440,1000),(390,844)]:
            page.set_viewport_size({'width':width,'height':height})
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
            page.screenshot(path=str(OUT/f'03-chat-result-{width}.png'))
        checks.append('actual result appears inside chat on desktop and mobile')
        assert not errors,errors
        browser.close()
    (OUT/'project-input-acceptance.json').write_text(json.dumps({'passed':True,'checks':checks,'errors':errors,
        'scope':'isolated real HTTP and local Python inference; fixture model, not chemical business validation',
        'real_provider_calls':0,'workdir':str(WORK)},ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'passed':True,'checks':checks},ensure_ascii=False))
finally:
    for p in reversed(processes):
        p.terminate()
        try:p.wait(timeout=5)
        except subprocess.TimeoutExpired:p.kill()
    for log in logs:log.close()
