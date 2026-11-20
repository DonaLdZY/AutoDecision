"""Live Gateway + browser acceptance, isolated state; never starts a training job.
Historical inference uses a chemical package, migrated sales model and bounded solver input.
The local planning provider is a protocol fixture, not a real language model.
"""
import hashlib, json, os, shutil, socket, subprocess, sys, tempfile, threading, time, urllib.request
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT=Path(__file__).resolve().parents[3]
STUDIO=ROOT/'frontend/decision-studio'
OUT=STUDIO/'review-v0.2.3';OUT.mkdir(exist_ok=True)
WORK=ROOT/'.codex-work/studio-v023-acceptance';WORK.mkdir(parents=True,exist_ok=True)
STATE=Path(tempfile.mkdtemp(prefix='state-',dir=WORK))
BACKEND=ROOT/'frontend/backend'
checks=[];errors=[];processes=[];logs=[]
def passed(name):checks.append(name);print('PASS',name,flush=True)
def free_port():
    s=socket.socket();s.bind(('127.0.0.1',0));port=s.getsockname()[1];s.close();return port
api_port=free_port();provider_port=free_port();ui_port=free_port()
class Provider(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def do_POST(self):
        body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        context=json.loads(body['messages'][-1]['content'])
        plans=[{'package_id':p['id'],'reason':'本地协议夹具：用户选择的测试计算包','mappings':[],'output_pointer':''} for p in context['packages'][:1]]
        answer={'action':'reuse' if plans else 'clarify','reply':'本地协议测试提供方已返回计划；这不是实际 LLM 质量评估。','steps':plans,'goal':'test','missing_inputs':['value']}
        response=json.dumps({'choices':[{'finish_reason':'stop','message':{'content':json.dumps(answer,ensure_ascii=False)}}],'usage':{'prompt_tokens':42,'completion_tokens':25}}).encode()
        self.send_response(200);self.send_header('Content-Type','application/json');self.end_headers();self.wfile.write(response)
provider=ThreadingHTTPServer(('127.0.0.1',provider_port),Provider)
threading.Thread(target=provider.serve_forever,daemon=True).start()
# Copy task metadata only; historical files are read from their original paths.
original_tasks=(BACKEND/'.state/tasks.json').read_bytes()
(STATE/'tasks.json').write_bytes(original_tasks)
settings=STATE/'global_settings.yaml'
settings.write_text(json.dumps({'python':{'executable':sys.executable},'llm':{'modelLibrary':[{'id':'fixture','name':'Protocol fixture (not LLM)','model':'fixture','baseUrl':f'http://127.0.0.1:{provider_port}/v1','apiKey':''}], 'roleModels':{'autoRealize':'fixture','autoMlCode':'fixture','autoMlFeedback':'fixture'}}}),encoding='utf8')
os.environ['AUTODECISION_STATE_DIR']=str(STATE);os.environ['AUTODECISION_GLOBAL_SETTINGS_PATH']=str(settings)
os.environ.pop('AUTODECISION_API_TOKEN',None)
sys.path.insert(0,str(BACKEND))
import app
from fastapi.testclient import TestClient
client=TestClient(app.app)
input_dir=STATE/'fixture-input';input_dir.mkdir();(input_dir/'observations.csv').write_text('value\n2\n3\n')
selected_dir=input_dir/'chosen-package';selected_dir.mkdir();(selected_dir/'visible.csv').write_text('value\n7\n')
excluded_dir=input_dir/'excluded-package';excluded_dir.mkdir();(excluded_dir/'excluded.csv').write_text('other\n9\n')
task=app.store.create(app.TaskConfigPayload(task_name='联调测试 · 数值翻倍',input_root=str(input_dir),output_root=str(STATE/'runs')))
ws=STATE/'fixture-workspace';pkg_root=ws/'best_solution';pkg_root.mkdir(parents=True)
(ws/'input').mkdir();(ws/'input/description.md').write_text('测试夹具，只验证产品链路，无业务指标。',encoding='utf8')
code="def predict(model_path, data):\n    return {'value': data['value'] * 2}\ndef train(*args):\n    raise RuntimeError('must not train')\n"
(pkg_root/'solution.py').write_text(code)
manifest={'node_id':'fixture-candidate','entrypoint':'predict','artifact_required':False}
(pkg_root/'solution_manifest.json').write_text(json.dumps(manifest))
fixture_log=STATE/'fixture-log';fixture_log.mkdir()
(fixture_log/'journal.json').write_text(json.dumps({'nodes':[{'id':'fixture-candidate','stage':'draft','code':code,'plan':'测试翻倍计算函数','metric':{'value':1,'maximize':True},'is_valid':True,'is_buggy':False}],'node2parent':{}}))
app.store.set_status(task.id,status='completed',phase='automl_completed',auto_ml_workspace_dir=str(ws),auto_ml_log_dir=str(fixture_log))
app.store._persist()

def api(path,data=None):
    raw=json.dumps(data,ensure_ascii=False).encode() if data is not None else None
    req=urllib.request.Request(f'http://127.0.0.1:{api_port}/api'+path,raw,{'Content-Type':'application/json'})
    with urllib.request.urlopen(req,timeout=180) as r:return json.load(r)
def start(args,cwd,env,tag):
    log=(WORK/(tag+'.log')).open('w',encoding='utf8');logs.append(log)
    p=subprocess.Popen(args,cwd=cwd,env=env,stdout=log,stderr=subprocess.STDOUT,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0));processes.append(p);return p
def wait_url(url,p):
    for _ in range(100):
        if p.poll() is not None:raise RuntimeError('service exited: '+str(p.returncode))
        try:
            with urllib.request.urlopen(url,timeout=1) as response:
                if response.status==200:return
        except Exception:time.sleep(.2)
    raise RuntimeError('service timeout '+url)
try:
    env=os.environ.copy()
    gateway=start([sys.executable,'-m','uvicorn','app:app','--host','127.0.0.1','--port',str(api_port)],BACKEND,env,'gateway-test')
    wait_url(f'http://127.0.0.1:{api_port}/api/health',gateway)
    env['AUTODECISION_GATEWAY_TARGET']=f'http://127.0.0.1:{api_port}'
    vite=start([shutil.which('node'),str(STUDIO/'node_modules/vite/bin/vite.js'),'preview','--host','127.0.0.1','--port',str(ui_port),'--strictPort'],STUDIO,env,'vite-test')
    wait_url(f'http://127.0.0.1:{ui_port}/',vite)
    from playwright.sync_api import sync_playwright,expect
    with sync_playwright() as pw:
        browser=pw.chromium.launch(channel='msedge' if sys.platform=='win32' else None)
        page=browser.new_page(viewport={'width':1440,'height':1000},device_scale_factor=1)
        page.on('pageerror',lambda e:errors.append(str(e)))
        page.goto(f'http://127.0.0.1:{ui_port}/#chat')
        expect(page.get_by_text('已连接',exact=True)).to_be_visible(timeout=15000)
        expect(page.get_by_text('先为数据建立一个工作空间',exact=True)).to_be_visible()
        passed('empty real mode, no synthetic seed')
        page.get_by_role('button',name='导入已有任务',exact=True).click()
        expect(page.get_by_role('button',name='导入已有任务',exact=True)).to_have_count(0,timeout=15000)
        state=api('/studio/state')
        fixture_project=next(p for p in state['projects'] if p['input_root']==str(input_dir))
        page.get_by_label('当前数据项目',exact=True).select_option(fixture_project['id'])
        expect(page.get_by_text('observations.csv',exact=False)).to_be_visible(timeout=10000)
        passed('import actual TaskStore and read directory')
        page.locator('.main-nav').get_by_role('button',name='研发任务',exact=False).click()
        page.get_by_role('button',name='联调测试 · 数值翻倍',exact=False).click()
        expect(page.get_by_role('dialog').get_by_role('heading',name='联调测试 · 数值翻倍',exact=True)).to_be_visible(timeout=15000)
        page.get_by_role('button',name='03 算法搜索').click()
        expect(page.get_by_role('button',name='候选 1 draft')).to_be_visible()
        page.screenshot(path=str(OUT/'02-actual-search.png'))
        passed('real journal tree and candidate code')
        page.get_by_role('button',name='关闭详情',exact=True).click()
        page.locator('.main-nav').get_by_role('button',name='算法模型包',exact=False).click()
        candidate=page.locator('.candidate-row').filter(has_text='联调测试 · 数值翻倍')
        expect(candidate).to_contain_text('交付待整理')
        candidate.get_by_role('button',name='整理交付',exact=True).click()
        expect(page.get_by_role('heading',name='交付整理与调用验证',exact=True)).to_be_visible(timeout=15000)
        page.get_by_role('button',name='生成兼容交付包',exact=True).click()
        expect(page.get_by_role('heading',name='自动生成的调用说明草稿',exact=True)).to_be_visible(timeout=15000)
        expect(page.get_by_text('结构检查通过',exact=True)).to_be_visible()
        expect(page.get_by_label('适用范围与限制',exact=True)).to_have_value(__import__('re').compile('value'))
        expect(page.get_by_label('输出结构说明',exact=True)).to_have_value(__import__('re').compile('value'))
        passed('legacy result button prepares a separate copy and fills evidence-backed draft descriptions')
        page.get_by_label('交付试算输入 JSON',exact=True).fill('{}')
        page.get_by_label('已核对输入，执行本地推理，不重新训练',exact=True).check()
        page.get_by_role('button',name='运行交付试算',exact=True).click()
        expect(page.get_by_text('上次提交输入试算失败',exact=True)).to_be_visible(timeout=15000)
        page.get_by_label('交付试算输入 JSON',exact=True).fill('{"value":7}')
        expect(page.get_by_role('button',name='运行交付试算',exact=True)).to_be_disabled()
        page.get_by_label('已核对输入，执行本地推理，不重新训练',exact=True).check()
        page.get_by_role('button',name='运行交付试算',exact=True).click()
        expect(page.get_by_text('上次提交输入试算成功',exact=True)).to_be_visible(timeout=15000)
        expect(page.locator('.delivery-panel pre').last).to_contain_text('14')
        page.screenshot(path=str(OUT/'09-delivery-trial.png'))
        for width,height in [(390,844),(1024,800)]:
            page.set_viewport_size({'width':width,'height':height})
            sizes=page.evaluate('({w:innerWidth,scroll:document.documentElement.scrollWidth})')
            assert sizes['scroll']<=sizes['w']+1,sizes
            if width==390:page.screenshot(path=str(OUT/'10-mobile-delivery.png'))
        page.set_viewport_size({'width':1440,'height':1000})
        delivery_check=api(f'/studio/tasks/{task.id}/delivery')
        assert delivery_check['verification']['status']=='passed'
        assert (pkg_root/'solution.py').read_text()==code
        passed('real trial failure then success, input-change confirmation reset, persisted result and delivery layouts')
        page.get_by_label('能力名称',exact=True).fill('联调计算包')
        page.get_by_label('适用范围与限制',exact=True).fill('测试用的数值翻倍计算；输入对象 value，返回 value 两倍。无业务验收结论。')
        page.get_by_label('输入 JSON Schema（可选）',exact=True).fill(json.dumps({'type':'object','required':['value'],'properties':{'value':{'type':'number'}}}))
        page.get_by_label('输出结构说明',exact=True).fill('JSON 对象 value')
        page.get_by_label('已检查选定身份、输入合同、依赖和验证范围；发布不代表业务验收通过',exact=True).check()
        page.get_by_role('button',name='发布模型包',exact=True).click()
        expect(page.get_by_role('dialog').get_by_role('heading',name='联调计算包',exact=True)).to_be_visible(timeout=15000)
        page.screenshot(path=str(OUT/'03-published-package.png'))
        page.get_by_role('button',name='关闭详情',exact=True).click()
        passed('publish frozen package through real bundle service')
        page.locator('.main-nav').get_by_role('button',name='算法模型包',exact=False).click()
        expect(page.get_by_role('heading',name='已有研发成果',exact=True)).to_be_visible()
        expect(page.locator('.candidate-row').filter(has_text='联调测试 · 数值翻倍')).to_contain_text('已有 1 个发布版本')
        passed('historical results remain visible with actual publication readiness')
        page.get_by_role('button',name='在对话中使用',exact=True).click()
        page.get_by_label('决策需求',exact=True).fill('请用当前包计算 value=7')
        page.get_by_role('button',name='发送需求',exact=True).click()
        expect(page.get_by_role('button',name='核对输入并调用',exact=False)).to_be_visible(timeout=15000)
        page.screenshot(path=str(OUT/'01-chat-plan.png'))
        passed('HTTP planning contract using explicitly labeled local provider fixture')
        page.get_by_role('button',name='核对输入并调用',exact=False).click()
        page.get_by_label('实际输入 JSON',exact=True).fill('{"value":7}')
        page.get_by_role('button',name='添加下游模型包步骤',exact=True).click()
        page.get_by_label('我已核对输入语义、单位、版本和组合接口，确认执行本地推理',exact=True).check()
        page.get_by_role('button',name='确认调用',exact=True).click()
        expect(page.get_by_role('heading',name='实际输出',exact=True)).to_be_visible(timeout=30000)
        expect(page.get_by_role('dialog').locator('pre').first).to_contain_text('28')
        page.screenshot(path=str(OUT/'04-real-composition.png'))
        records=api('/studio/state')['invocations'];assert records[0]['status']=='completed'
        record=api('/studio/invocations/'+records[0]['id']);assert record['result']=={'value':28} and len(record['steps'])==2
        passed('two real subprocess predictions compose 7 -> 14 -> 28')
        page.get_by_role('button',name='关闭详情',exact=True).click()
        page.reload();expect(page.get_by_text('查看实际调用结果与执行链',exact=True)).to_be_visible(timeout=15000)
        passed('conversations and invocation survive page reload')
        page.locator('.main-nav').get_by_role('button',name='研发任务',exact=False).click()
        page.get_by_role('button',name='新建研发任务',exact=True).click()
        page.get_by_label('任务名称',exact=True).fill('联调草稿')
        page.get_by_label('业务目标与约束',exact=True).fill('只测试真实草稿保存，不启动训练')
        page.get_by_role('button',name='保存研发草稿',exact=True).click()
        expect(page.get_by_role('button',name='检查并启动',exact=True)).to_be_visible(timeout=10000)
        # Explicitly do not click start: no paid calls or training in acceptance.
        page.get_by_role('button',name='关闭详情',exact=True).click()
        passed('research draft created, no training started')
        page.get_by_role('button',name='新建研发任务',exact=True).click()
        expect(page.get_by_label('所属数据项目',exact=True)).to_have_value(fixture_project['id'])
        page.get_by_label('任务名称',exact=True).fill('单数据包研发草稿')
        page.get_by_label('业务目标与约束',exact=True).fill('仅选择 chosen-package，不读取兄弟包')
        page.get_by_label('数据包目录',exact=True).fill(str(STATE))
        expect(page.get_by_role('dialog').get_by_role('alert')).to_contain_text('必须位于所选项目目录内')
        expect(page.get_by_role('button',name='保存研发草稿',exact=True)).to_be_disabled()
        page.get_by_label('数据包目录',exact=True).fill(str(selected_dir))
        preview=page.get_by_label('研发数据包文件预览',exact=True)
        expect(preview).to_contain_text('visible.csv')
        expect(preview).not_to_contain_text('excluded.csv')
        page.screenshot(path=str(OUT/'07-single-data-package.png'))
        page.get_by_role('button',name='保存研发草稿',exact=True).click()
        expect(page.get_by_role('button',name='检查并启动',exact=True)).to_be_visible(timeout=10000)
        single=next(t for t in api('/tasks') if t['task_name'].startswith('单数据包研发草稿'))
        assert single['input_root']==str(selected_dir) and single['config']['input_root']==str(selected_dir)
        assert single['status']=='idle' and not single['run_dir']
        page.get_by_role('button',name='关闭详情',exact=True).click()
        passed('single directory preview, outside-project rejection, exact scope saved without training')
        page.get_by_role('button',name='设置 v0.2.3',exact=False).click()
        expect(page.get_by_label('Python 解释器绝对路径')).to_have_value(sys.executable,timeout=10000)
        expect(page.get_by_role('heading',name='模型配置',exact=True)).to_be_visible()
        expect(page.get_by_role('heading',name='角色模型分配',exact=True)).to_be_visible()
        expect(page.locator('.model-editor')).to_have_count(1)
        # This acceptance run intentionally provisions its own local HTTP fixture;
        # the production DeepSeek default is covered by backend settings tests.
        expect(page.locator('.model-editor input').first).to_have_value('Protocol fixture (not LLM)')
        expect(page.get_by_label('数据分析（要求多模态模型）')).to_have_value('fixture')
        expect(page.get_by_label('算法编码')).to_have_value('fixture')
        expect(page.get_by_label('评审与报告')).to_have_value('fixture')
        assert 'Gateway' not in page.locator('main').inner_text()
        passed('one isolated fixture, shared roles, multimodal label, no Gateway settings copy')
        page.screenshot(path=str(OUT/'05-settings.png'))
        passed('real settings and redacted model configuration')
        page.locator('.main-nav').get_by_role('button',name='数据项目',exact=False).click()
        tile=page.locator('.project-tile').filter(has=page.get_by_role('heading',name='联调测试 · 数值翻倍',exact=True))
        tile.get_by_role('button',name='删除项目',exact=True).click()
        page.get_by_role('button',name='确认删除项目',exact=True).click()
        expect(page.get_by_role('dialog')).to_have_count(0,timeout=10000)
        expect(page.locator('.project-tile').filter(has=page.get_by_role('heading',name='联调测试 · 数值翻倍',exact=True))).to_have_count(0)
        hidden=api('/studio/state')
        assert any(p['id']==fixture_project['id'] for p in hidden['archived_projects'])
        assert not any(p['project_id']==fixture_project['id'] for p in hidden['packages'])
        assert (input_dir/'observations.csv').exists() and (pkg_root/'solution.py').exists()
        page.locator('.archived-projects summary').click()
        page.screenshot(path=str(OUT/'08-deleted-project-restore.png'))
        page.locator('.archived-projects .panel-heading').filter(has_text='联调测试 · 数值翻倍').get_by_role('button',name='恢复项目',exact=True).click()
        expect(page.get_by_label('当前数据项目',exact=True)).to_have_value(fixture_project['id'],timeout=10000)
        restored=api('/studio/state')
        assert any(p['project_id']==fixture_project['id'] for p in restored['packages'])
        assert any(i['project_id']==fixture_project['id'] for i in restored['invocations'])
        page.locator('.main-nav').get_by_role('button',name='决策对话',exact=False).click()
        expect(page.get_by_text('查看实际调用结果与执行链',exact=True)).to_be_visible(timeout=15000)
        passed('project deletion and restoration preserve files, packages, conversations and invocation records')
        for width,height in [(1440,1000),(1024,800),(390,844)]:
            page.set_viewport_size({'width':width,'height':height})
            for name in ['chat','projects','packages','tasks','invocations','settings']:
                page.goto(f'http://127.0.0.1:{ui_port}/#{name}')
                page.wait_for_timeout(450)
                sizes=page.evaluate('({w:innerWidth,scroll:document.documentElement.scrollWidth})')
                assert sizes['scroll']<=sizes['w']+1,(name,width,sizes)
            if width==390:page.screenshot(path=str(OUT/'06-mobile-settings.png'))
        passed('18 page/viewport layouts, no document horizontal overflow')
        page.set_viewport_size({'width':1440,'height':1000})
        page.goto(f'http://127.0.0.1:{ui_port}/?demo=1#chat')
        expect(page.get_by_text('交互演示 · 模拟数据',exact=True)).to_be_visible()
        passed('explicit demo entry still separate')
        browser.close()
    # Actual historical model through same HTTP service, using recorded probe input.
    chemical=next(t for t in api('/tasks') if '压滤液' in t['task_name'])
    chemical_project=next(l['project_id'] for l in api('/studio/state')['links'] if l['id']==chemical['id'])
    source=Path(chemical['auto_ml_workspace_dir'])/'best_solution'
    source_digest={str(p.relative_to(source)):hashlib.sha256(p.read_bytes()).hexdigest() for p in source.rglob('*') if p.is_file()}
    published=api('/studio/packages',{'project_id':chemical_project,'task_id':chemical['id'],'name':'压滤液历史冻结包 · 集成验收','description':'离线回顾性窗口；最终指标劣于中位数基线，不能宣称业务达标','input_schema':{'type':'object','required':['prediction_cutoff','history']}})
    historical=ROOT/'runs/industrial-examples-20260907/optimization-validation/chemical-final-inference-1788832511124409500/moved_export'
    import pandas as pd
    probe=json.loads((historical/'probe_config.json').read_text(encoding='utf8'))['requests'][0]
    history=pd.read_pickle(historical/probe['history'])
    payload={'prediction_cutoff':probe['prediction_cutoff'],'history':json.loads(history.to_json(orient='records',date_format='iso',force_ascii=False))}
    result=api('/studio/invocations',{'project_id':chemical_project,'request_id':'real-chemical-check','steps':[{'package_id':published['id'],'data_json':json.dumps(payload,ensure_ascii=False),'dataframes':[{'pointer':'/history','columns':list(history.columns)}]}],'confirm':True,'timeout_seconds':120})
    assert result['status']=='completed',result.get('error')
    assert abs(result['result'][0]-probe['expected'])<1e-9,(result['result'],probe['expected'])
    assert {str(p.relative_to(source)):hashlib.sha256(p.read_bytes()).hexdigest() for p in source.rglob('*') if p.is_file()}==source_digest
    actual={'source_task_id':chemical['id'],'source_node_id':published['manifest']['node_id'],'history_rows':len(history),'history_columns':len(history.columns),'prediction_cutoff':probe['prediction_cutoff'],'expected':probe['expected'],'observed':result['result'],'absolute_difference':abs(result['result'][0]-probe['expected']),'source_files_unchanged':True,'training_started':False,'scope':'one historical inference request; no new model quality evaluation'}
    (OUT/'historical-inference.json').write_text(json.dumps(actual,ensure_ascii=False,indent=2),encoding='utf8')
    passed('real chemical model, 63-column nested DataFrame, matches frozen output without training')
    # Migrate two real historical results only in the isolated state directory.
    migrations=[]
    for identity in ['feed6c8316a54982b3453df9fb84ee50','c4ea05c56bac42839ce2737ca483cad7']:
        historical_task=next(t for t in api('/tasks') if t['id']==identity)
        historical_ws=Path(historical_task['auto_ml_workspace_dir'])
        historical_source=historical_ws/'best_solution'
        original={p.relative_to(historical_source).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in historical_source.rglob('*') if p.is_file()}
        prepared=api(f'/studio/tasks/{identity}/delivery',{'confirm':True})
        assert prepared['structure_ready'] and prepared['verification']['status']=='not_run',prepared
        if identity.startswith('feed'):
            test_input={'input_mode':'csv','csv_path':str(Path(historical_task['input_root'])/'predict.csv')}
            expected=pd.read_csv(historical_ws/'best_submission/submission.csv')['sales'].tolist()
            scope='6 existing sales prediction rows, compare persisted selected submission; no refit'
        else:
            empty={'orders':[],'tw_map':{},'order_info':{},'cost_rules':{},'pool':{},'veh_map':{}}
            test_input={'input_mode':'json','data_json':json.dumps(empty),'dataframes':[{'pointer':'/orders','columns':['订单号','cust','consignee','vol','wt','shipper']}]}
            scope='empty-orders/no-vehicles interface smoke test only; not the full 2104-order optimization or business validation'
        verified=api(f'/studio/tasks/{identity}/delivery/verify',{'confirm':True,'delivery_id':prepared['delivery_id'],'timeout_seconds':60,**test_input})
        assert verified['status']=='passed',verified
        if identity.startswith('feed'):
            observed=verified['trial']['result']
            assert len(observed)==len(expected)==6
            difference=max(abs(a-b) for a,b in zip(observed,expected))
            assert difference<1e-8,(observed,expected)
        else:
            observed=verified['trial']['result']['packing_report']
            assert observed['chosen_completion']==0 and observed['slots_n']==0
            difference=None
        assert {p.relative_to(historical_source).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in historical_source.rglob('*') if p.is_file()}==original
        migrations.append({'task_id':identity,'source_node_id':prepared['source_node_id'],'delivery_id':prepared['delivery_id'],
            'entrypoint':prepared['draft']['entrypoint'],'verification':verified['status'],'observed':observed,
            'max_absolute_difference':difference,'source_files_unchanged':True,'training_started':False,'scope':scope})
    (OUT/'historical-delivery.json').write_text(json.dumps(migrations,ensure_ascii=False,indent=2),encoding='utf8')
    passed('real legacy sales and delivery solver migration, immutable originals, verified existing-model inference and bounded solver input')
    assert not errors,errors
    assert (BACKEND/'.state/tasks.json').read_bytes()==original_tasks
    (OUT/'acceptance.json').write_text(json.dumps({'passed':True,'checks':checks,'browser_errors':errors,'isolated_state':str(STATE),'real_provider_calls':0,'planning_provider':'local protocol fixture, not LLM','original_tasks_unchanged':True},ensure_ascii=False,indent=2),encoding='utf8')
finally:
    provider.shutdown()
    for p in reversed(processes):
        if p.poll() is None:
            p.terminate()
            try:p.wait(timeout=8)
            except subprocess.TimeoutExpired:p.kill()
    for log in logs:log.close()
