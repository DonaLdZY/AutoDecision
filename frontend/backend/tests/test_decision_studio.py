import hashlib, json
from pathlib import Path
from types import SimpleNamespace
import pytest
from fastapi.testclient import TestClient
import app, decision_studio

@pytest.fixture(autouse=True)
def studio_usage_state(tmp_path, monkeypatch):
    monkeypatch.setattr(app, 'STATE_DIR', tmp_path / 'state')

@pytest.fixture
def live(tmp_path,monkeypatch):
    monkeypatch.setattr(app,'STATE_DIR',tmp_path/'state')
    monkeypatch.setattr(app,'TASKS_FILE',tmp_path/'state/tasks.json')
    monkeypatch.setattr(app,'store',app.TaskStore())
    monkeypatch.setattr(app.replay_recorder,'observe_task',lambda *a:None)
    monkeypatch.delenv('AUTODECISION_API_TOKEN',raising=False)
    monkeypatch.setattr(app,'get_global_settings',lambda:app.GlobalSettingsModel(python={'executable':app.sys.executable},llm={}))
    root=tmp_path/'data';root.mkdir();(root/'train.csv').write_text('value\n2\n')
    return TestClient(app.app),root,tmp_path

def project(client,root):
    result=client.post('/api/studio/projects',json={'name':'Factory','input_root':str(root)})
    assert result.status_code==200,result.text
    return result.json()


def test_export_sanitizes_legacy_package_inventory(tmp_path):
    inventory = tmp_path / "package_inventory.json"
    inventory.write_text(json.dumps({
        "schema_version": "autodecision.solution_export.v1",
        "task_id": "task",
        "source_config": {
            "input_root": "C:/Users/private/customer-data",
            "auto_realize": {"task_hint": "customer process requirements"},
        },
    }))

    exported = json.loads(decision_studio._package_inventory_for_export(inventory))

    assert "source_config" not in exported
    assert "customer process requirements" not in exported
    assert "C:/Users/private" not in exported


def test_project_and_chat_catalog(live):
    client,root,_=live;p=project(client,root)
    assert client.get(f"/api/studio/projects/{p['id']}/catalog").json()['files'][0]['columns']==['value']
    assert client.post('/api/studio/projects',json={'name':'bad','input_root':str(root/'missing')}).status_code==400
    c=client.post('/api/studio/conversations',json={'project_id':p['id']}).json()
    path=f"/api/studio/conversations/{c['id']}/messages"
    assert client.post(path,json={'text':'predict','request_id':'one'}).status_code==409
    response=client.post(path,json={'text':'predict','request_id':'two','mode':'catalog'})
    assert response.status_code==200,response.text
    assert response.json()['plan']['action']=='clarify'
    assert client.post(path,json={'text':'predict','request_id':'two','mode':'catalog'}).json()['id']==response.json()['id']

def test_chat_honors_explicit_package_selection_without_replanning(live, monkeypatch):
    client, _, _ = live
    p, _, pkg, _ = make_package(live)
    monkeypatch.setattr(decision_studio, 'request_plan', lambda *args: pytest.fail('explicit selection must not be replanned'))
    c = client.post('/api/studio/conversations', json={'project_id': p['id']}).json()
    response = client.post(f"/api/studio/conversations/{c['id']}/messages", json={
        'text': "Run this model for tomorrow's forecast", 'request_id': 'fixed-package', 'package_id': pkg['id'],
    })
    assert response.status_code == 200, response.text
    result = response.json()
    assert result['plan']['action'] == 'reuse'
    assert result['plan']['steps'] == [{'package_id': pkg['id'], 'reason': '用户明确指定模型包'}]
    assert 'calculator' in result['text']

def test_adapter_rejects_incompatible_units_and_overwrite():
    m=decision_studio.Mapping(source='x',target='load',source_unit='kW',target_unit='MW')
    assert decision_studio.adapt_input({'x':2000},[m])=={'load':2}
    with pytest.raises(Exception):decision_studio.adapt_input({'x':1},[decision_studio.Mapping(source='x',target='load',source_unit='kWh',target_unit='MW')])
    with pytest.raises(Exception):decision_studio.adapt_input({'x':1,'load':3},[m])

def test_invocation_summary_keeps_user_summary_and_hides_raw_provenance():
    record = {
        'id': 'call-1', 'status': 'failed', 'error': 'ModuleNotFoundError: No module named secret_pkg',
        'steps': [{
            'index': 0, 'package_id': 'pkg-1', 'version': '12', 'input_mode': 'project',
            'mappings': [{'source': 'private_column', 'target': 'model_column'}],
            'output_pointer': '/private/output',
            'input_provenance': {
                'cutoff': '2026-10-22T10:00:00', 'timezone': 'Asia/Shanghai',
                'cutoff_mode': 'exclusive', 'input_sha256': 'private-fingerprint',
                'sources': [{
                    'path': 'D:/confidential/plant.csv', 'field': 'private', 'rows': 12,
                    'columns': ['private_column'], 'first_observation': '2026-10-01T10:00:00',
                    'last_observation': '2026-10-22T09:00:00',
                }],
            },
        }],
    }

    summary = decision_studio.invocation_summary(record)
    step = summary['steps'][0]
    assert summary['error_summary'] == '运行环境缺少依赖'
    assert 'error' not in summary
    assert step['input_summary'] == {
        'source_count': 1, 'row_count': 12,
        'first_observation': '2026-10-01T10:00:00', 'last_observation': '2026-10-22T09:00:00',
        'cutoff': '2026-10-22T10:00:00', 'timezone': 'Asia/Shanghai',
    }
    assert set(step) == {'index', 'package_id', 'input_mode', 'input_summary'}

def test_real_publish_and_inference(live, monkeypatch):
    client,root,tmp=live;p=project(client,root)
    task=app.store.create(app.TaskConfigPayload(task_name='source',input_root=str(root),output_root=str(tmp/'runs')))
    logs=tmp/'logs';logs.mkdir();task.auto_ml_log_dir=str(logs)
    ws=tmp/'workspace';package=ws/'best_solution';package.mkdir(parents=True)
    (ws/'input').mkdir();(ws/'input/description.md').write_text('frozen contract')
    (package/'model.bin').write_bytes(b'model')
    (package/'solution.py').write_text("def predict(model_path, data): return {'answer': data['value'] * 2}")
    implementation=package/'selected.py';implementation.write_text('frozen')
    manifest={'node_id':'n1','entrypoint':'predict','artifact_required':True,'artifact_path':str(package/'model.bin'),
        'implementation_path':'selected.py','implementation_file_sha256':hashlib.sha256(implementation.read_bytes()).hexdigest()}
    (package/'solution_manifest.json').write_text(json.dumps(manifest));(package/'model_path.txt').write_text(str(package/'model.bin'))
    task.auto_ml_workspace_dir=str(ws);task.status='completed'
    response=client.post('/api/studio/import-tasks',json={'task_ids':[task.id]})
    assert response.status_code==200 and response.json()['imported']==1
    assert client.get('/api/studio/state').json()['projects'][0]['description'] == ''
    pub=client.post('/api/studio/packages',json={'project_id':p['id'],'task_id':task.id,'name':'doubler','description':'twice',
      'input_schema':{'type':'object','required':['value'],'properties':{'value':{'type':'number'}}},'output_description':'answer object'})
    assert pub.status_code==200,pub.text
    pkg=pub.json()
    c=client.post('/api/studio/conversations',json={'project_id':p['id']}).json()
    payload={'project_id':p['id'],'conversation_id':c['id'],'title':'test','request_id':'invoke-1','steps':[{'package_id':pkg['id'],'data_json':'{"value":7}'}],'confirm':True}
    result=client.post('/api/studio/invocations',json=payload)
    assert result.status_code==200,result.text
    assert result.json()['status']=='completed',result.text
    assert result.json()['result']=={'answer':14}
    assert client.post('/api/studio/invocations',json=payload).json()['id']==result.json()['id']
    assert client.get(f"/api/studio/packages/{pkg['id']}/bundle").status_code==200
    code = '''def decide(data):
    result = run_model(data)
    return {"answer": f"计算结果为 {result['answer']}。", "facts": result}
'''
    monkeypatch.setattr(decision_studio, 'request_decision_program', lambda *args: {
        'code': code, 'usage': {'prompt_tokens': 100, 'completion_tokens': 30}})
    decision = client.post('/api/studio/invocations', json={
        **payload, 'request_id': 'decision-1', 'decision_mode': True, 'question': '输入7的结果是多少？',
    })
    assert decision.status_code == 200, decision.text
    assert decision.json()['status'] == 'completed', decision.text
    assert decision.json()['answer'] == '计算结果为 14。'
    assert decision.json()['result'] == {'answer': 14}
    summary = client.get(f"/api/studio/invocations/{decision.json()['id']}?view=summary").json()
    assert summary['answer'] == '计算结果为 14。' and 'decision_program' not in summary
    assert 'decision_facts' not in summary
    workspace = client.get('/api/studio/state').json()
    invocation = next(item for item in workspace['invocations'] if item['id'] == decision.json()['id'])
    assert 'decision_program' not in invocation and 'decision_facts' not in invocation
    assert 'result' not in invocation and 'steps' not in invocation
    assert 'decision_program' in workspace['capabilities']
    conversation = next(item for item in workspace['conversations'] if item['id'] == c['id'])
    assert conversation['messages'][-1]['text'] == '计算结果为 14。'
    frozen=app.STATE_DIR/'studio'/'packages'/pkg['id']/'solution.py'
    frozen.write_text('tampered')
    payload['request_id']='invoke-2'
    assert client.post('/api/studio/invocations',json=payload).json()['status']=='failed'
    assert '校验失败' in client.post('/api/studio/invocations',json=payload).json()['error']

def test_token_protection(live,monkeypatch):
    client,_,_=live;monkeypatch.setenv('AUTODECISION_API_TOKEN','token')
    assert client.get('/api/studio/state').status_code==401
    assert client.get('/api/health').status_code==200

def make_package(live, code="def predict(model_path, data): return {'value': data['value'] * 2}", schema=None, input_binding=None):
    client, source, tmp = live
    p = project(client, source)
    task = app.store.create(app.TaskConfigPayload(task_name='package-source', input_root=str(source), output_root=str(tmp/'runs')))
    ws = tmp / task.id
    root = ws / 'best_solution'; root.mkdir(parents=True)
    (ws/'input').mkdir(); (ws/'input/description.md').write_text('Frozen original contract')
    (root/'implementation.py').write_text(code)
    (root/'solution.py').write_text(code + "\ndef train(*a): raise RuntimeError('forbidden training')\n")
    manifest = {'node_id':'node', 'entrypoint':'predict','artifact_required':False,'implementation_path':'implementation.py',
        'implementation_file_sha256':hashlib.sha256((root/'implementation.py').read_bytes()).hexdigest()}
    (root/'solution_manifest.json').write_text(json.dumps(manifest))
    task.auto_ml_workspace_dir=str(ws); task.status='completed'
    assert client.post('/api/studio/import-tasks',json={'task_ids':[task.id]}).json()['imported']==1
    response=client.post('/api/studio/packages',json={'project_id':p['id'],'task_id':task.id,'name':'calculator','input_schema':schema or {},'input_binding':input_binding})
    assert response.status_code==200,response.text
    return p, task, response.json(), root


@pytest.mark.parametrize('lower_bound,expected', [('exclusive', 3), ('inclusive', 7)])
def test_project_snapshot_call_is_frozen_and_bound_to_package(live, lower_bound, expected):
    client, source, tmp = live
    file = source/'observations.csv'
    file.write_text('time,value\n2026-05-25 08:30:00,4\n2026-05-25 09:20:00,1\n2026-05-25 09:30:00,2\n')
    binding = {'sources':[{'path':'observations.csv','field':'history','time_column':'time',
        'columns':['time','value'],'window_seconds':3600,'lower_bound':lower_bound}]}
    p, task, pkg, root = make_package(live, code="def predict(model_path, data): return {'answer': sum(r['value'] for r in data['history']), 'cutoff': data['prediction_cutoff']}", input_binding=binding)
    response = client.post(f"/api/studio/packages/{pkg['id']}/prepare-input",json={})
    assert response.status_code == 200, response.text
    prepared = response.json()
    assert 'data_json' not in prepared
    assert pkg['input_binding']['sources'][0]['field'] == 'history'
    assert pkg['input_binding']['sources'][0]['lower_bound'] == lower_bound
    file.write_text('time,value\n2026-05-25 09:30:00,999\n')
    step = {'package_id':pkg['id'],'input_mode':'project','prepared_input_id':prepared['id']}
    result = call(client,p,[step])
    assert result['status'] == 'completed', result
    assert result['result']['answer'] == expected
    assert result['steps'][0]['input_provenance']['input_sha256'] == prepared['input_sha256']
    assert result['steps'][0]['input_provenance']['sources'][0]['rows'] == (3 if lower_bound == 'inclusive' else 2)
    step['mappings'] = [{'source':'history','target':'other'}]
    assert call(client,p,[step],request_id='mapping')['status'] == 'failed'
    with decision_studio.database(app) as db:
        row = db.get('prepared_inputs',prepared['id'])
        row['package_id'] = 'different-package'
        db.put('prepared_inputs',row)
    step.pop('mappings')
    assert call(client,p,[step],request_id='wrong-version')['status'] == 'failed'

def call(client,p,steps,request_id='unique'):
    response=client.post('/api/studio/invocations',json={'project_id':p['id'],'request_id':request_id,'steps':steps,'confirm':True})
    assert response.status_code==200,response.text
    return response.json()


def test_large_project_snapshot_survives_prepare_and_real_inference(live):
    client, source, tmp = live
    from datetime import datetime, timedelta
    start = datetime(2026, 5, 23)
    # Two days of 63-column minute observations exceed the old 1 MiB cap.
    columns = ['time', *(f'sensor_{i}' for i in range(62))]
    rows = [','.join([(start + timedelta(minutes=i)).isoformat(sep=' '), *(['1.25']*62)]) for i in range(2881)]
    (source/'observations.csv').write_text(','.join(columns)+'\n'+'\n'.join(rows), encoding='utf-8')
    binding = {'sources':[{'path':'observations.csv','field':'history','time_column':'time',
        'columns':columns,'window_seconds':172800}]}
    code = "def predict(model_path, data): return {'rows': len(data['history']), 'total': sum(sum(v for k,v in row.items() if k != 'time') for row in data['history']), 'first':data['history'][0]['time'], 'last':data['history'][-1]['time']}"
    p, task, pkg, root = make_package(live, code=code, input_binding=binding)
    response = client.post(f"/api/studio/packages/{pkg['id']}/prepare-input",json={})
    assert response.status_code == 200, response.text
    prepared = response.json()
    with decision_studio.database(app) as db:
        raw = db.get('prepared_inputs',prepared['id'])['data_json']
    assert 1024**2 < len(raw.encode()) < 16*1024**2
    result = call(client,p,[{'package_id':pkg['id'],'input_mode':'project','prepared_input_id':prepared['id']}])
    assert result['status'] == 'completed', result
    assert result['result'] == {'rows':2880,'total':2880*62*1.25,'first':'2026-05-23 00:01:00','last':'2026-05-25 00:00:00'}
    # The explicit JSON route must accept the same complete snapshot.
    again = call(client,p,[{'package_id':pkg['id'],'data_json':raw}],request_id='large-json')
    assert again['status'] == 'completed', again
    assert again['result'] == result['result']
    # Character validation alone cannot enforce a UTF-8 byte limit.
    too_large = json.dumps({'note':'铝'*(6*1024**2)}, ensure_ascii=False)
    rejected = call(client,p,[{'package_id':pkg['id'],'data_json':too_large}],request_id='too-large')
    assert rejected['status'] == 'failed' and '16 MiB' in rejected['error']

def test_compose_actual_output_and_frozen_source(live):
    client,_,_=live
    p,task,pkg,root=make_package(live)
    # Source gets rewritten after release; frozen copy still executes the original function.
    (root/'solution.py').write_text("def predict(*a): raise Exception('source changed')")
    record=call(client,p,[{'package_id':pkg['id'],'data_json':'{"value":7}'},
                         {'package_id':pkg['id'],'input_mode':'previous'}])
    assert record['status']=='completed' and record['result']=={'value':28}
    assert len(record['steps'])==2
    assert record['steps'][0]['trial']['result']=={'value':14}
    assert record['steps'][1]['trial']['input_sha256'] != record['steps'][0]['trial']['input_sha256']
    assert not (app.STATE_DIR/'trials'/task.id).exists()
    import io,zipfile
    with zipfile.ZipFile(io.BytesIO(client.get(f"/api/studio/packages/{pkg['id']}/bundle").content)) as archive:
        assert 'capability.json' in archive.namelist() and 'CAPABILITY.md' in archive.namelist()
        assert json.loads(archive.read('capability.json'))['source_task_id']==task.id

def test_real_mapping_array_and_dataframe(live):
    client,_,_=live
    p,_,pkg,_=make_package(live,"def predict(model_path, data): return {'total': float(data['history']['load_mw'].sum())}")
    record=call(client,p,[{'package_id':pkg['id'], 'data_json':'{"history":[{"load_mw":2},{"load_mw":3}]}',
                         'dataframes':[{'pointer':'/history','columns':['load_mw']}]}])
    assert record['status']=='completed',record
    assert record['result']=={'total':5}
    assert record['steps'][0]['dataframes'][0]['pointer']=='/history'
    result=decision_studio.adapt_input([{'load_kw':2000},{'load_kw':3000}],[decision_studio.Mapping(source='load_kw',target='load_mw',source_unit='kW',target_unit='MW')])
    assert result==[{'load_mw':2},{'load_mw':3}]


@pytest.mark.parametrize("schema,frames", [
    ({"type": "object", "properties": {"Id": {"type": "integer"}}},
     [{"pointer": "/properties", "columns": ["Id"]}]),
    ({"type": "object", "properties": {"Id": {"type": "integer"}}},
     [{"pointer": "", "columns": ["Id"]}]),
    ({"type": "array", "items": {"type": "object", "properties": {"Id": {}}}},
     [{"pointer": "/data", "columns": ["Id"]}]),
    ({}, [{"pointer": "", "columns": ["Id", "Id"]}]),
])
def test_publish_contract_rejects_schema_metadata_as_input_data(live, schema, frames):
    client, _, _ = live
    p, task, _, _ = make_package(live)
    response = client.post('/api/studio/packages', json={
        'project_id': p['id'], 'task_id': task.id, 'name': 'invalid table contract',
        'input_schema': schema, 'dataframes': frames,
    })
    assert response.status_code == 400


def test_root_and_nested_table_contracts_address_runtime_rows():
    for schema, pointer in [
        ({"type": "array", "items": {"type": "object", "properties": {"Id": {}}}}, ""),
        ({"type": "object", "properties": {"history": {
            "type": "array", "items": {"type": "object", "properties": {"Id": {}}}}}}, "/history"),
    ]:
        decision_studio.validate_dataframe_contract(
            schema, [decision_studio.DataFrameInput(pointer=pointer, columns=['Id'])])


def test_provider_retries_transient_failure_and_records_unknown_usage(live, monkeypatch):
    import io
    import urllib.error
    _, _, _ = live
    attempts = []

    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self, size):
            return json.dumps({'id': 'response-2', 'choices': [{'finish_reason': 'stop'}],
                               'usage': {'prompt_tokens': 20, 'completion_tokens': 10,
                                         'prompt_tokens_details': {'cached_tokens': 12}}}).encode()

    def open_request(request, timeout):
        # Exercise providers that reject the default Python-urllib identity.
        assert request.get_header("User-agent") == "AutoDecision"
        assert request.get_header("Authorization") == "Bearer secret"
        attempts.append(1)
        if len(attempts) == 1:
            raise urllib.error.HTTPError(request.full_url, 502, 'bad gateway', {}, io.BytesIO(b'secret provider details'))
        return Response()

    monkeypatch.setattr(decision_studio.urllib.request, 'urlopen', open_request)
    monkeypatch.setattr(decision_studio.time, 'sleep', lambda seconds: None)
    result = decision_studio._provider_json(app, 'https://provider/v1/chat/completions',
                                           {'model': 'test', 'thinking': {'type': 'enabled'}},
                                           {'Authorization': 'Bearer secret'}, stage='studio.planning', timeout=60)
    assert result['id'] == 'response-2' and len(attempts) == 2
    rows = [json.loads(line) for line in (app.STATE_DIR / 'studio/llm_usage.jsonl').read_text().splitlines()]
    assert len(rows) == 2
    assert rows[0]['usage_available'] is False and rows[0]['prompt_tokens'] is None
    assert rows[0]['provider_cache_tokens_known'] is False
    assert rows[1]['prompt_cache_hit_tokens'] == 12 and rows[1]['usage_available'] is True
    assert 'secret' not in json.dumps(rows)


def test_provider_does_not_retry_authentication_errors(live, monkeypatch):
    import io
    import urllib.error
    def fail(request, timeout):
        raise urllib.error.HTTPError(request.full_url, 401, 'unauthorized', {}, io.BytesIO(b'private'))
    monkeypatch.setattr(decision_studio.urllib.request, 'urlopen', fail)
    with pytest.raises(Exception) as error:
        decision_studio._provider_json(app, 'https://provider/v1/chat/completions', {'model': 'test'}, {},
                                       stage='studio.planning', timeout=60)
    assert error.value.status_code == 502
    assert 'private' not in str(error.value)
    assert len((app.STATE_DIR / 'studio/llm_usage.jsonl').read_text().splitlines()) == 1


def test_suggested_plan_repairs_duplicate_prediction_call_with_bounded_usage(monkeypatch):
    """Regression: statistics over predictions must not re-enter the predictor."""
    plans = [
        {'action': 'reuse', 'reply': '先预测再统计', 'steps': [
            {'package_id': 'house', 'reason': '预测'},
            {'package_id': 'house', 'reason': '汇总预测均值'},
        ]},
        {'action': 'reuse', 'reply': '使用房价模型预测，再计算均值。', 'steps': [
            {'package_id': 'house', 'reason': '预测房价'},
        ]},
    ]
    calls = []

    def respond(g, endpoint, body, headers, *, stage, timeout):
        calls.append({'stage': stage, 'body': json.loads(json.dumps(body))})
        index = len(calls) - 1
        return {'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps(plans[index])}}],
                'usage': {'prompt_tokens': 20 + index, 'completion_tokens': 10,
                          **({'prompt_tokens_details': {'cached_tokens': 12}} if index else {})}}

    monkeypatch.setattr(decision_studio, '_provider_json', respond)
    model = {'model': 'test', 'baseUrl': 'http://127.0.0.1/v1', 'thinkingMode': 'enabled'}
    plan, usage, _ = decision_studio.request_plan(app, {'packages': [{'id': 'house'}]}, model)
    assert len(plan['steps']) == 1 and plan['steps'][0]['package_id'] == 'house'
    assert [call['stage'] for call in calls] == ['studio.planning', 'studio.planning.repair']
    assert all(call['body']['thinking'] == {'type': 'enabled'} for call in calls)
    assert '汇总' in calls[1]['body']['messages'][-1]['content']
    assert usage['prompt_tokens'] == 41 and usage['completion_tokens'] == 20 and usage['request_count'] == 2
    assert 'prompt_tokens_details' not in usage  # One response did not report cache usage.


def test_suggested_plan_repair_stops_after_second_invalid_plan(monkeypatch):
    calls = []

    def respond(*args, **kwargs):
        calls.append(kwargs['stage'])
        return {'choices': [{'message': {'content': json.dumps({
            'action': 'reuse', 'reply': '使用不存在的包', 'steps': [{'package_id': 'unknown'}],
        })}}]}

    monkeypatch.setattr(decision_studio, '_provider_json', respond)
    with pytest.raises(Exception) as error:
        decision_studio.request_plan(app, {'packages': []},
                                     {'model': 'test', 'baseUrl': 'http://127.0.0.1/v1'})
    assert error.value.status_code == 502
    assert len(calls) == 2


def test_thinking_tool_program_repairs_once_and_preserves_tool_pairing(monkeypatch):
    settings = app.GlobalSettingsModel(llm={
        'modelLibrary': [{'id': 'test', 'model': 'glm-test', 'baseUrl': 'http://localhost/v1',
                          'thinkingMode': 'enabled'}], 'roleModels': {'autoRealize': 'test'},
    })
    monkeypatch.setattr(app, 'get_global_settings', lambda: settings)
    code = 'def decide(data):\n    result = run_model(data)\n    return {"answer": f"共有{len(result)}项结果。"}'
    calls = []

    def respond(g, endpoint, body, headers, *, stage, timeout):
        calls.append({'stage': stage, 'body': json.loads(json.dumps(body))})
        submitted = code if len(calls) == 2 else 'def decide(data):\n    return {"answer": "没有真实调用"}'
        return {'choices': [{'finish_reason': 'tool_calls', 'message': {
            'content': None, 'reasoning_content': 'provider thinking',
            'tool_calls': [{'id': 'call-1', 'type': 'function', 'function': {
                'name': 'submit_decision_program', 'arguments': json.dumps({'code': submitted}),
            }}],
        }}], 'usage': {'prompt_tokens': 20, 'completion_tokens': 10}}

    monkeypatch.setattr(decision_studio, '_provider_json', respond)
    program = decision_studio.request_decision_program(app, '结果有多少项？', {})
    assert program['code'] == code and program['thinking_requested'] == 'true'
    assert program['request_count'] == 2 and program['usage']['prompt_tokens'] == 40
    assert all(call['body']['tool_choice'] == 'auto' for call in calls)
    messages = calls[1]['body']['messages']
    assert messages[-2]['reasoning_content'] == 'provider thinking'
    assert messages[-1]['role'] == 'tool' and messages[-1]['tool_call_id'] == 'call-1'


def test_catalog_preserves_full_normal_csv_header_for_plan_matching(live):
    client, root, _ = live
    columns = ['Id', *[f'feature_{i}' for i in range(79)]]
    (root / 'test.csv').write_text(','.join(columns) + '\n', encoding='utf-8')
    p = project(client, root)
    files = client.get(f"/api/studio/projects/{p['id']}/catalog").json()['files']
    table = next(row for row in files if row['name'] == 'test.csv')
    assert table['columns'] == columns and table['column_count'] == 80
    assert table['columns_limited'] is False


def test_suggested_mappings_require_actual_fields_and_remove_identity():
    context = {
        'packages': [{'id': 'house', 'table_inputs': [{'pointer': '', 'columns': ['Id', 'Area']}]}],
        'data_catalog': {'files': [{'name': 'test.csv', 'columns': ['Id', 'Area']}]},
    }
    value = {'action': 'reuse', 'reply': '预测', 'steps': [{
        'package_id': 'house', 'mappings': [{'source': 'Id', 'target': 'Id'}],
    }]}
    assert decision_studio._validate_suggested_plan(value, context).steps[0].mappings == []
    value['steps'][0]['mappings'] = [{'source': 'test.csv全部80个特征列', 'target': '模型输入特征'}]
    with pytest.raises(ValueError, match='精确'):
        decision_studio._validate_suggested_plan(value, context)


def test_first_failure_stops_chain_and_schema_rejects(live):
    client,_,_=live
    p,_,pkg,_=make_package(live,schema={'type':'object','required':['value'],'properties':{'value':{'type':'number'}}})
    result=call(client,p,[{'package_id':pkg['id'],'data_json':'{}'},{'package_id':pkg['id'],'input_mode':'previous'}])
    assert result['status']=='failed' and result['steps']==[] and '必填' in result['error']
    response=client.post('/api/studio/invocations',json={'project_id':p['id'],'request_id':'unique','steps':[{'package_id':pkg['id'],'data_json':'{"value":9}'}],'confirm':True})
    assert response.status_code==409
    with pytest.raises(Exception): decision_studio.validate_schema_document({'type':'object','additionalProperties':False})

def test_cross_project_call_and_plan_references_rejected(live,monkeypatch):
    client,root,_=live
    p,_,pkg,_=make_package(live)
    other=project(client,root)
    response=client.post('/api/studio/invocations',json={'project_id':other['id'],'request_id':'cross','steps':[{'package_id':pkg['id']}],'confirm':True})
    assert response.status_code==400
    c=client.post('/api/studio/conversations',json={'project_id':other['id']}).json()
    assert client.post(f"/api/studio/conversations/{c['id']}/messages",json={'text':'reuse','request_id':'wrong','mode':'catalog','package_id':pkg['id']}).status_code==400
    settings=app.GlobalSettingsModel(llm={'modelLibrary':[{'id':'local','baseUrl':'http://127.0.0.1:9000/v1','model':'local'}],'roleModels':{'autoRealize':'local'}})
    monkeypatch.setattr(app,'get_global_settings',lambda:settings)
    class Response:
        def __enter__(self): return self
        def __exit__(self,*a): pass
        def read(self,n): return json.dumps({'choices':[{'message':{'content':json.dumps({'action':'reuse','reply':'reuse','steps':[{'package_id':'wrong'}]})}}]}).encode()
    monkeypatch.setattr(decision_studio.urllib.request,'urlopen',lambda *a,**k:Response())
    with pytest.raises(Exception) as error: decision_studio.request_plan(app,{'packages':[{'id':pkg['id']} ]})
    assert error.value.status_code==502


def test_deepseek_plan_keeps_thinking_and_accepts_context_over_legacy_limit(monkeypatch):
    settings = app.GlobalSettingsModel(llm={
        "modelLibrary": [{
            "id": "deepseek",
            "model": "deepseek-flash",
            "baseUrl": "https://api.deepseek.com",
            "apiKey": "test-key",
            "thinkingMode": "default",
            "contextWindowTokens": 1_000_000,
        }],
        "roleModels": {"autoRealize": "deepseek"},
    })
    monkeypatch.setattr(app, "get_global_settings", lambda: settings)
    captured = {}

    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self, _size):
            return json.dumps({
                "choices": [{
                    "finish_reason": "stop",
                    "message": {"content": json.dumps({
                        "action": "clarify",
                        "reply": "Need one more detail.",
                        "steps": [],
                        "goal": "",
                        "missing_inputs": ["evaluation metric"],
                    })},
                }],
                "usage": {"prompt_tokens": 9000, "completion_tokens": 500},
            }).encode()

    def open_request(request, timeout):
        captured["body"] = json.loads(request.data)
        captured["timeout"] = timeout
        return Response()

    monkeypatch.setattr(decision_studio.urllib.request, "urlopen", open_request)
    context = {"packages": [], "project_context": "x" * 30_000}

    plan, usage, model = decision_studio.request_plan(app, context)

    assert plan["action"] == "clarify"
    assert usage["prompt_tokens"] == 9000
    assert model == "deepseek-flash"
    assert captured["body"]["thinking"] == {"type": "enabled"}
    assert captured["body"]["max_tokens"] == 8192
    assert captured["timeout"] == 60


def test_request_plan_normalizes_question_style_clarification(monkeypatch):
    settings = app.GlobalSettingsModel(llm={
        "modelLibrary": [{
            "id": "deepseek",
            "model": "deepseek-flash",
            "baseUrl": "https://api.deepseek.com",
            "apiKey": "test-key",
            "contextWindowTokens": 1_000_000,
        }],
        "roleModels": {"autoRealize": "deepseek"},
    })
    monkeypatch.setattr(app, "get_global_settings", lambda: settings)

    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self, _size):
            return json.dumps({"choices": [{
                "finish_reason": "stop",
                "message": {"content": json.dumps({
                    "type": "clarify",
                    "question": "Which evaluation metric should be optimized?",
                    "options": [{"label": "MAE"}, {"label": "RMSE"}],
                    "missing": ["evaluation metric"],
                    "allow_custom": True,
                })},
            }]}).encode()

    monkeypatch.setattr(
        decision_studio.urllib.request,
        "urlopen",
        lambda *args, **kwargs: Response(),
    )

    plan, _, _ = decision_studio.request_plan(app, {"packages": []})

    assert plan["action"] == "clarify"
    assert plan["steps"] == []
    assert plan["missing_inputs"] == ["evaluation metric"]
    assert "MAE、RMSE" in plan["reply"]
    assert "直接填写其他答案" in plan["reply"]


def test_planning_context_budget_uses_configured_model_window():
    large_context = {
        "history": [{"role": "user", "content": "current request"}],
        "data_catalog": {"files": [{"name": f"file-{i}"} for i in range(32)]},
        "project_cognition": {"historical_research": [{"task_id": f"task-{i}"} for i in range(12)]},
        "project_notes": "x" * 30_000,
    }
    original = json.loads(json.dumps(large_context))

    fitted = decision_studio._fit_planning_context(
        large_context,
        {"contextWindowTokens": 1_000_000, "maxTokens": 32_768},
    )

    assert fitted == original
    assert decision_studio._planning_limits(
        {"contextWindowTokens": 1_000_000, "maxTokens": 32_768}
    )[0] == 8192


def test_planning_context_budget_compacts_old_material_to_fit_smaller_window():
    context = {
        "history": [
            {"role": "user", "content": f"old request {i} " + "x" * 5000}
            for i in range(8)
        ],
        "data_catalog": {
            "files": [{"name": f"file-{i}", "summary": "x" * 4000} for i in range(32)]
        },
        "project_cognition": {
            "historical_research": [{"task_id": f"task-{i}", "summary": "x" * 1000} for i in range(12)]
        },
    }
    context["history"][-1]["content"] = "current request"

    fitted = decision_studio._fit_planning_context(
        context,
        {"contextWindowTokens": 32_768, "maxTokens": 32_768},
    )

    assert len(fitted["data_catalog"]["files"]) == 8
    assert len(fitted["history"]) == 2
    assert fitted["history"][-1]["content"] == "current request"
    assert 2 <= len(fitted["project_cognition"]["historical_research"]) < 12


def test_deepseek_research_draft_keeps_thinking(monkeypatch):
    settings = app.GlobalSettingsModel(llm={
        "modelLibrary": [{
            "id": "deepseek",
            "model": "deepseek-flash",
            "baseUrl": "https://api.deepseek.com",
            "apiKey": "test-key",
            "thinkingMode": "default",
        }],
        "roleModels": {"autoRealize": "deepseek"},
    })
    monkeypatch.setattr(app, "get_global_settings", lambda: settings)
    captured = {}

    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self, _size):
            return json.dumps({"choices": [{
                "message": {"content": json.dumps({
                    "title": "Demand forecast",
                    "goal": "Forecast next-hour demand.",
                    "evaluation": "Compare MAE with a seasonal naive baseline.",
                    "constraints": ["Use the selected project data only."],
                    "input_scope": "selected project folder",
                    "basis": "user request",
                })},
            }]}).encode()

    def open_request(request, timeout):
        captured["body"] = json.loads(request.data)
        return Response()

    monkeypatch.setattr(decision_studio.urllib.request, "urlopen", open_request)

    draft = decision_studio.request_research_draft(
        app,
        {"project": {"name": "Synthetic project"}, "research_data": {"files": []}},
        "Forecast next-hour demand.",
    )

    assert draft.source == "llm"
    assert captured["body"]["thinking"] == {"type": "enabled"}
    assert captured["body"]["max_tokens"] == 8192


def test_draft_config_project_link_and_new_experiment(live):
    client,root,tmp=live;p=project(client,root)
    task=client.post(f"/api/studio/projects/{p['id']}/tasks",json={'task_name':'draft','output_root':str(tmp/'runs'),'auto_ml':{'steps':4}}).json()
    assert task['input_root']==str(root) and task['status']=='idle'
    assert any(l['id']==task['id'] for l in client.get('/api/studio/state').json()['links'])
    child=client.post(f"/api/studio/tasks/{task['id']}/experiment").json()
    assert child['parent_task_id']==task['id'] and child['run_dir'] is None
    assert client.post('/api/studio/import-tasks',json={'task_ids':[task['id'],task['id']]}).json()['imported']==0

def test_dataframe_rejects_schema_loss(live):
    client,_,_=live;p,_,pkg,_=make_package(live)
    result=call(client,p,[{'package_id':pkg['id'],'data_json':'{"history":[{"a":1,"b":2}]}','dataframes':[{'pointer':'/history','columns':['a']}]}])
    assert result['status']=='failed' and '一一对应' in result['error']


def test_research_uses_exactly_one_selected_directory(live):
    client, root, tmp = live
    p = project(client, root)
    selected = root / 'chosen'; selected.mkdir()
    (selected / 'only.csv').write_text('x\n1\n')
    sibling = root / 'excluded'; sibling.mkdir()
    (sibling / 'private.csv').write_text('private\n2\n')
    url = f"/api/studio/projects/{p['id']}"
    preview = client.get(url + '/research-data', params={'input_root': str(selected)})
    assert preview.status_code == 200, preview.text
    assert [f['name'] for f in preview.json()['files']] == ['only.csv']
    result = client.post(url + '/tasks', json={'task_name': 'single', 'input_root': str(selected)})
    assert result.status_code == 200, result.text
    task = result.json()
    assert task['input_root'] == task['config']['input_root'] == str(selected)
    assert not task['run_dir'] and task['status'] == 'idle'
    child = client.post(f"/api/studio/tasks/{task['id']}/experiment").json()
    assert child['input_root'] == str(selected)
    for value in [str(tmp), str(root / '..' / 'data'), str(root / 'absent'), '', ['one', 'two']]:
        assert client.post(url + '/tasks', json={'task_name': 'bad', 'input_root': value}).status_code in (400, 422)
    assert client.get(url + '/research-data', params={'input_root': str(tmp)}).status_code == 400
    config = task['config']; config['input_root'] = str(sibling)
    updated = client.put(f"/api/studio/tasks/{task['id']}", json=config)
    assert updated.status_code == 200 and updated.json()['input_root'] == str(sibling)
    config['input_root'] = str(tmp)
    assert client.put(f"/api/studio/tasks/{task['id']}", json=config).status_code == 400
    assert app.store.get(task['id']).input_root == str(sibling)


def test_research_draft_uses_selected_project_context_and_validates_package(live, monkeypatch):
    client, root, _ = live
    conversation_project = project(client, root)
    target_root = root / 'target'; target_root.mkdir()
    selected = target_root / 'selected'; selected.mkdir()
    (selected / 'fresh.csv').write_text('target\n1\n')
    target_project = project(client, target_root)
    conversation = client.post('/api/studio/conversations', json={'project_id': conversation_project['id']}).json()
    with decision_studio.database(app) as db:
        row = db.get('conversations', conversation['id'])
        row['messages'] = [{'role': 'user', 'text': 'Use the new project for a fresh forecast.'}]
        db.put('conversations', row)
        db.put('links', {'id': 'target-task', 'project_id': target_project['id']})
        db.put('packages', {'id': 'target-package', 'project_id': target_project['id'], 'name': 'target model'})
        db.put('packages', {'id': 'source-package', 'project_id': conversation_project['id'], 'name': 'source model'})

    captured = {}
    def cognition_context(_g, selected_project, linked_ids):
        captured['project'] = selected_project
        captured['linked_ids'] = linked_ids
        return {'project': {'name': selected_project['name']}, 'historical_research': []}

    def draft(_g, context, source_text):
        captured['context'] = context
        captured['source_text'] = source_text
        return decision_studio.ResearchDraft(title='draft', goal=source_text)

    monkeypatch.setattr(decision_studio, '_project_cognition_context', cognition_context)
    monkeypatch.setattr(decision_studio, 'request_research_draft', draft)
    endpoint = f"/api/studio/conversations/{conversation['id']}/research-draft"

    response = client.post(endpoint, json={
        'text': 'forecast the target project',
        'project_id': target_project['id'],
        'package_id': 'target-package',
        'input_root': str(selected),
    })
    assert response.status_code == 200, response.text
    assert captured['project']['id'] == target_project['id']
    assert captured['linked_ids'] == {'target-task'}
    assert captured['context']['packages'][0]['id'] == 'target-package'
    assert captured['context']['research_data']['relative_root'] == 'selected'
    assert captured['context']['research_data']['files'][0]['name'] == 'fresh.csv'
    assert captured['context']['conversation_project']['name'] == conversation_project['name']
    assert captured['context']['conversation'][0]['text'] == 'Use the new project for a fresh forecast.'

    wrong_package = client.post(endpoint, json={
        'text': 'forecast the target project',
        'project_id': target_project['id'],
        'package_id': 'source-package',
    })
    assert wrong_package.status_code == 400
    assert client.post(endpoint, json={'text': 'missing project', 'project_id': 'missing'}).status_code == 404

    fallback = client.post(endpoint, json={'text': 'stay with conversation project'})
    assert fallback.status_code == 200, fallback.text
    assert captured['project']['id'] == conversation_project['id']
    outside = client.post(endpoint, json={
        'text': 'outside', 'project_id': target_project['id'], 'input_root': str(root),
    })
    assert outside.status_code == 400


def test_research_rejects_intermediate_directory_link(live, monkeypatch):
    client, root, _ = live
    p = project(client, root)
    linked = root / 'linked'; nested = linked / 'nested'; nested.mkdir(parents=True)
    original = Path.is_symlink
    monkeypatch.setattr(Path, 'is_symlink', lambda path: path == linked or original(path))
    url = f"/api/studio/projects/{p['id']}/tasks"
    assert client.post(url, json={'task_name': 'linked', 'input_root': str(nested)}).status_code == 400


def test_project_archive_restore_preserves_all_evidence(live):
    client, root, _ = live
    p, task, pkg, source = make_package(live)
    conversation = client.post('/api/studio/conversations', json={'project_id': p['id']}).json()
    invocation = call(client, p, [{'package_id': pkg['id'], 'data_json': '{"value":3}'}])
    frozen = app.STATE_DIR/'studio/packages'/pkg['id']/'solution.py'
    digest = hashlib.sha256(frozen.read_bytes()).hexdigest()
    url = f"/api/studio/projects/{p['id']}"
    assert client.post(url + '/archive').json()['status'] == 'archived'
    state = client.get('/api/studio/state').json()
    assert not state['projects'] and not state['packages'] and not state['conversations'] and not state['invocations']
    assert state['archived_projects'][0]['id'] == p['id']
    assert any(link['id'] == task.id for link in state['links'])
    assert client.post('/api/studio/import-tasks', json={'task_ids': [task.id]}).json()['imported'] == 0
    assert client.get(url + '/catalog').status_code == 410
    assert client.post(url + '/tasks', json={'task_name': 'bad'}).status_code == 410
    assert client.post(f"/api/studio/tasks/{task.id}/experiment").status_code == 410
    assert client.post('/api/studio/conversations', json={'project_id': p['id']}).status_code == 410
    assert client.post('/api/studio/invocations', json={'project_id': p['id'], 'request_id': 'deleted', 'confirm': True,
        'steps': [{'package_id': pkg['id']}]}).status_code == 410
    assert client.post(url + '/restore', json={}).status_code == 200
    state = client.get('/api/studio/state').json()
    assert not state['archived_projects']
    assert state['packages'][0]['id'] == pkg['id']
    assert state['conversations'][0]['id'] == conversation['id']
    assert state['invocations'][0]['id'] == invocation['id']
    assert app.store.get(task.id).status == 'completed'
    assert (root/'train.csv').exists() and (source/'solution.py').exists()
    assert hashlib.sha256(frozen.read_bytes()).hexdigest() == digest


def test_project_archive_blocks_active_work(live):
    client, root, _ = live
    p = project(client, root)
    task = client.post(f"/api/studio/projects/{p['id']}/tasks", json={'task_name': 'busy'}).json()
    url = f"/api/studio/projects/{p['id']}"
    app.store.set_status(task['id'], status='running', run_started_at=app.now_ts())
    assert client.post(url + '/archive').status_code == 409
    app.store.set_status(task['id'], status='idle')
    with decision_studio.database(app) as db:
        db.put('invocations', {'id': 'busy', 'project_id': p['id'], 'status': 'running'})
    assert client.post(url + '/archive').status_code == 409
    with decision_studio.database(app) as db:
        db.put('invocations', {'id': 'busy', 'project_id': p['id'], 'status': 'completed'})
    conv = client.post('/api/studio/conversations', json={'project_id': p['id']}).json()
    decision_studio.BUSY_CONVERSATIONS.add(conv['id'])
    try:
        assert client.post(url + '/archive').status_code == 409
    finally:
        decision_studio.BUSY_CONVERSATIONS.discard(conv['id'])
    assert client.post(url + '/archive').status_code == 200


def test_historical_candidates_are_lightweight_and_versioned_format(live, monkeypatch):
    client, root, _ = live
    p, task, pkg, source = make_package(live)
    url = f"/api/studio/projects/{p['id']}/package-candidates"

    def deep_inspection_must_not_run(*_args, **_kwargs):
        raise AssertionError('the task index must not inspect artifact files')

    monkeypatch.setattr(decision_studio, 'inspect_solution', deep_inspection_must_not_run)
    monkeypatch.setattr(decision_studio.delivery, 'current', deep_inspection_must_not_run)
    row = client.get(url).json()[0]
    assert row['inspection'] == 'not_checked'
    assert row['published_ids'] == [pkg['id']]
    assert row['task_id'] == task.id
    assert row['phase'] == task.phase
    assert row['created_at'] == task.created_at
    assert row['updated_at'] == task.updated_at
    assert 'trial_ready' not in row and 'report_ready' not in row and 'issues' not in row
    import io, zipfile
    with zipfile.ZipFile(io.BytesIO(client.get(f"/api/studio/packages/{pkg['id']}/bundle").content)) as bundle:
        metadata = json.loads(bundle.read('capability.json'))
        assert metadata['format'] == 'autodecision.capability' and metadata['format_version'] == 1
        assert metadata['model_path'] is None
    manifest_path = source/'solution_manifest.json'
    manifest = json.loads(manifest_path.read_text())
    manifest.pop('implementation_file_sha256')
    manifest_path.write_text(json.dumps(manifest))
    row = client.get(url).json()[0]
    # The index intentionally does not inspect the artifact, even when it is
    # malformed. Deep validation belongs to the task detail/action endpoint.
    assert row['inspection'] == 'not_checked'
    assert row['published_ids'] == [pkg['id']]
    other = project(client, root)
    assert client.get(f"/api/studio/projects/{other['id']}/package-candidates").json() == []


def test_research_optimization_uses_dedicated_model_and_bounded_project_metadata(live, monkeypatch):
    client, root, tmp = live
    project_row = project(client, root)
    (root / 'private.csv').write_text('feature,target\nSECRET_DATA_ROW,42\n')
    model = {'id': 'optimizer', 'model': 'optimizer-model', 'baseUrl': 'https://provider/v1', 'apiKey': 'secret-key'}
    llm = {'modelLibrary': [model], 'roleModels': {'promptOptimizer': 'optimizer'}}
    monkeypatch.setattr(app, 'get_global_settings', lambda: app.GlobalSettingsModel(llm=llm))
    calls = []
    result = {'title': '需求预测', 'goal': '预测目标', 'evaluation': 'MAE',
              'constraints': ['不得泄漏未来数据'], 'changes': ['补充任务边界'], 'questions': ['如何切分数据？']}
    def provider(g, endpoint, body, headers, *, stage, timeout):
        calls.append((endpoint, body, headers, stage))
        return {'choices': [{'finish_reason': 'tool_calls', 'message': {'tool_calls': [{'function': {
            'name': 'submit_research_optimization', 'arguments': json.dumps(result, ensure_ascii=False)}}]}}]}
    monkeypatch.setattr(decision_studio, '_provider_json', provider)
    response = client.post(f"/api/studio/projects/{project_row['id']}/research-optimization", json={
        'input_root': str(root), 'title': '原题', 'goal': '预测需求', 'evaluation': 'MAE', 'constraints': '不得泄漏未来数据'})
    assert response.status_code == 200, response.text
    assert response.json()['model'] == 'optimizer-model' and response.json()['goal'] == '预测目标'
    endpoint, body, headers, stage = calls[0]
    assert endpoint == 'https://provider/v1/chat/completions' and stage == 'studio.research_optimization'
    assert headers['Authorization'] == 'Bearer secret-key'
    prompt = body['messages'][0]['content']
    assert '可选建议' in prompt and '最多三个具体问题' in prompt
    assert 'constraints 只整理用户已明确提出的硬约束' in prompt
    assert '不要主动添加与用户任务无关的免责声明' in prompt
    assert '用户明确提出的要求和约束仍应保留' in prompt
    assert '禁止编造' not in prompt and '未知内容写空' not in prompt
    data = json.loads(body['messages'][1]['content'])
    assert data['draft']['constraints'] == '不得泄漏未来数据'
    assert 'feature' in json.dumps(data) and 'SECRET_DATA_ROW' not in json.dumps(data)
    assert str(root) not in json.dumps(data)
    assert client.get('/api/tasks').json() == []
    invalid = client.post(f"/api/studio/projects/{project_row['id']}/research-optimization", json={
        'input_root': str(tmp), 'goal': '预测需求'})
    assert invalid.status_code == 400 and len(calls) == 1


def test_research_optimization_repairs_invalid_response_once(live, monkeypatch):
    client, root, _ = live
    project_row = project(client, root)
    model = {'id': 'optimizer', 'model': 'test', 'baseUrl': 'http://localhost:9000/v1'}
    monkeypatch.setattr(app, 'get_global_settings', lambda: app.GlobalSettingsModel(llm={
        'modelLibrary': [model], 'roleModels': {'promptOptimizer': 'optimizer'}}))
    calls = []
    def provider(g, endpoint, body, headers, *, stage, timeout):
        calls.append(stage)
        content = 'not-json' if len(calls) == 1 else json.dumps({'title': '', 'goal': '改写目标', 'evaluation': '',
            'constraints': [], 'changes': [], 'questions': ['评价指标是什么？']})
        return {'choices': [{'finish_reason': 'stop', 'message': {'content': content}}]}
    monkeypatch.setattr(decision_studio, '_provider_json', provider)
    response = client.post(f"/api/studio/projects/{project_row['id']}/research-optimization", json={'input_root': str(root), 'goal': '目标'})
    assert response.status_code == 200 and response.json()['goal'] == '改写目标'
    assert calls == ['studio.research_optimization', 'studio.research_optimization.repair']


def test_research_optimization_rejects_invalid_model(live):
    client, root, _ = live
    project_row = project(client, root)
    response = client.post(f"/api/studio/projects/{project_row['id']}/research-optimization", json={'input_root': str(root), 'goal': '目标'})
    assert response.status_code == 409
    assert client.get('/api/tasks').json() == []


def test_research_optimization_accepts_longer_lists_and_matches_tool_schema(live, monkeypatch):
    client, root, _ = live
    project_row = project(client, root)
    model = {'id': 'optimizer', 'model': 'test', 'baseUrl': 'http://localhost:9000/v1'}
    monkeypatch.setattr(app, 'get_global_settings', lambda: app.GlobalSettingsModel(llm={
        'modelLibrary': [model], 'roleModels': {'promptOptimizer': 'optimizer'}}))
    result = {'title': 'ok', 'goal': 'goal', 'evaluation': '',
              'constraints': [f'constraint {n}' for n in range(21)],
              'changes': [f'change {n}' for n in range(11)],
              'questions': [f'question {n}' for n in range(15)]}
    calls = []
    def provider(g, endpoint, body, headers, *, stage, timeout):
        calls.append(body)
        return {'choices': [{'finish_reason': 'tool_calls', 'message': {'tool_calls': [{'function': {
            'name': 'submit_research_optimization', 'arguments': json.dumps(result)}}]}}]}
    monkeypatch.setattr(decision_studio, '_provider_json', provider)
    response = client.post(f"/api/studio/projects/{project_row['id']}/research-optimization", json={
        'input_root': str(root), 'goal': 'goal'})
    assert response.status_code == 200, response.text
    assert response.json()['questions'] == result['questions']
    assert response.json()['constraints'] == result['constraints']
    props = calls[0]['tools'][0]['function']['parameters']['properties']
    assert all(props[key]['maxItems'] == 100 for key in ('constraints', 'changes', 'questions'))
    assert props['title']['maxLength'] == 80
    assert len(calls) == 1


def test_research_optimization_repair_receives_specific_safe_validation_feedback(live, monkeypatch):
    client, root, _ = live
    project_row = project(client, root)
    model = {'id': 'optimizer', 'model': 'test', 'baseUrl': 'http://localhost:9000/v1'}
    monkeypatch.setattr(app, 'get_global_settings', lambda: app.GlobalSettingsModel(llm={
        'modelLibrary': [model], 'roleModels': {'promptOptimizer': 'optimizer'}}))
    calls = []
    def provider(g, endpoint, body, headers, *, stage, timeout):
        calls.append(json.loads(json.dumps(body)))
        output = {'title': 'x' * 81, 'goal': 'private contents', 'evaluation': '',
                  'constraints': [], 'changes': [], 'questions': []}
        return {'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps(output)}}]}
    monkeypatch.setattr(decision_studio, '_provider_json', provider)
    response = client.post(f"/api/studio/projects/{project_row['id']}/research-optimization", json={
        'input_root': str(root), 'goal': 'goal'})
    assert response.status_code == 502
    assert '任务名称超过 80 个字符' in response.json()['detail']
    assert 'private contents' not in response.text
    assert '任务名称超过 80 个字符' in calls[1]['messages'][-1]['content']
    assert client.get('/api/tasks').json() == []


def test_chat_includes_unpublished_verified_delivery_and_publication_link(live, monkeypatch):
    client, root, tmp = live
    p = project(client, root)
    task = app.store.create(app.TaskConfigPayload(task_name='hourly flow', input_root=str(root), output_root=str(tmp/'runs')))
    task.status = 'completed'
    task.phase = 'report_completed'
    with decision_studio.database(app) as db:
        db.put('links', {'id': task.id, 'project_id': p['id']})
    delivery_id = 'a' * 32
    area = decision_studio.delivery.area(app, task.id)
    package = area / delivery_id / 'best_solution'
    package.mkdir(parents=True)
    (package/'delivery_contract.json').write_text(json.dumps({'entrypoint': 'predict', 'observed_input_fields': ['history', 'target_pairs']}))
    (area/'current.json').write_text(json.dumps({'id': delivery_id, 'source_fingerprint': 'source',
        'sha256': {}, 'contract_sha256': {}, 'fingerprint': 'copy', 'verification': {
        'status': 'passed', 'delivery_id': delivery_id, 'package_fingerprint': 'copy'}}))
    captured = {}
    def plan(_g, context, _model):
        captured.update(context)
        return {'action': 'clarify', 'reply': '已有模型交付，审核发布后即可复用。', 'steps': [], 'goal': '', 'missing_inputs': []}, {}, 'test'
    monkeypatch.setattr(decision_studio, 'request_plan', plan)
    monkeypatch.setattr(app, '_selected_model', lambda *a, **k: {})
    c = client.post('/api/studio/conversations', json={'project_id': p['id']}).json()
    result = client.post(f"/api/studio/conversations/{c['id']}/messages", json={'text': 'predict next hour', 'request_id': 'unpublished'})
    assert result.status_code == 200, result.text
    candidate = captured['unpublished_deliveries'][0]
    assert candidate['verification_status'] == 'passed'
    assert candidate['input_fields'] == ['history', 'target_pairs']
    assert captured['packages'] == []
    assert result.json()['publication_candidates'][0]['task_id'] == task.id
    assert decision_studio._unpublished_deliveries(app, {task.id}, {task.id}) == []
    assert decision_studio._unpublished_deliveries(app, set(), set()) == []
    metadata = json.loads((area/'current.json').read_text())
    metadata['verification']['package_fingerprint'] = 'stale'
    (area/'current.json').write_text(json.dumps(metadata))
    assert decision_studio._unpublished_deliveries(app, {task.id}, set())[0]['verification_status'] == 'not_run'


def test_planning_input_evidence_is_bound_to_current_package_and_omits_data(live):
    client, root, _ = live
    p = project(client, root)
    package = {'id': 'traffic', 'fingerprint': 'v2', 'input_binding': {'kind': 'time_window'}}
    with decision_studio.database(app) as db:
        for identity, project_id, version, cutoff, created in [
            ('correct', p['id'], 'v2', '2025-07-11 23:59:59', 1),
            ('old-version', p['id'], 'v1', '2025-02-11 23:59:59', 2),
            ('other-project', 'elsewhere', 'v2', '2026-11-17 10:00:00', 3)]:
            db.put('prepared_inputs', {'id': identity, 'project_id': project_id, 'package_id': 'traffic',
                'package_fingerprint': version, 'cutoff': cutoff, 'timezone': 'Asia/Shanghai',
                'cutoff_mode': 'latest_observation', 'created_at': created, 'data_json': 'private vehicle data'})
        result = decision_studio._input_snapshot_evidence(db, p['id'], [package])
    assert len(result) == 1
    assert result[0]['cutoff'] == '2025-07-11 23:59:59'
    assert result[0]['prepared_input_id'] == 'correct'
    assert 'private vehicle data' not in json.dumps(result)


@pytest.mark.parametrize(('status', 'phase', 'expected'), [
    ('idle', 'config', 'not_started'),
    ('running', 'report', 'running'),
    ('completed', 'completed', 'awaiting_delivery'),
    ('failed', 'automl_failed', 'needs_attention'),
    ('failed', 'report_failed', 'awaiting_report'),
])
def test_task_delivery_overview_keeps_research_and_publication_separate(live, status, phase, expected):
    task = {'id': 'a' * 32, 'status': status, 'phase': phase}
    result = decision_studio.task_delivery_overview(app, task, [])
    assert result['state'] == expected
    assert result['package_id'] == ''


def test_task_delivery_overview_matches_export_by_delivery_identity_and_rejects_old_runs(live, monkeypatch):
    _, _, _ = live
    task = {'id': 'b' * 32, 'status': 'completed', 'phase': 'completed', 'run_started_at': 100}
    metadata = {'id': 'c' * 32, 'created_at': 101, 'fingerprint': 'delivery-copy',
                'report_run_id': 'report', 'verification': {'status': 'passed',
                'delivery_id': 'c' * 32, 'package_fingerprint': 'delivery-copy'}}
    monkeypatch.setattr(decision_studio.delivery, 'current', lambda *a: metadata)
    package = {'id': 'export', 'task_id': task['id'], 'created_at': 102,
               'delivery_id': metadata['id'], 'fingerprint': 'sanitized-export'}
    # Export sanitizes its inventory, so export and delivery fingerprints can differ.
    result = decision_studio.task_delivery_overview(app, task, [package])
    assert result['state'] == 'published'
    assert result['package_id'] == 'export'
    assert result['verification_status'] == 'passed'
    task['run_started_at'] = 200
    result = decision_studio.task_delivery_overview(app, task, [package])
    assert result['state'] == 'awaiting_delivery'
    assert result['package_id'] == ''
    assert result['published_ids'] == ['export']


def test_task_delivery_overview_marks_new_revision_pending_and_never_reuses_stale_trial(live, monkeypatch):
    task = {'id': 'b' * 32, 'status': 'completed', 'phase': 'completed'}
    metadata = {'id': 'new', 'fingerprint': 'new-copy', 'report_run_id': 'report',
                'verification': {'status': 'passed', 'delivery_id': 'old', 'package_fingerprint': 'old-copy'}}
    monkeypatch.setattr(decision_studio.delivery, 'current', lambda *a: metadata)
    result = decision_studio.task_delivery_overview(app, task, [
        {'id': 'old-package', 'task_id': task['id'], 'delivery_id': 'old', 'fingerprint': 'old-copy'}])
    assert result['state'] == 'awaiting_publish'
    assert result['verification_status'] == 'not_run'
    assert result['package_id'] == ''


def test_workspace_delivery_guidance_survives_corrupt_metadata_without_scanning_models(live, monkeypatch):
    client, root, tmp = live
    p = project(client, root)
    task = app.store.create(app.TaskConfigPayload(task_name='completed', input_root=str(root), output_root=str(tmp/'runs')))
    app.store.set_status(task.id, status='completed', phase='completed')
    with decision_studio.database(app) as db:
        db.put('links', {'id': task.id, 'project_id': p['id']})
    area = decision_studio.delivery.area(app, task.id)
    area.mkdir(parents=True)
    (area/'current.json').write_text('{broken', encoding='utf-8')
    def forbidden(*args, **kwargs):
        raise AssertionError('state cards must not inspect or execute model artifacts')
    monkeypatch.setattr(decision_studio, 'inspect_solution', forbidden)
    monkeypatch.setattr(decision_studio, 'execute_trial', forbidden)
    response = client.get('/api/studio/state')
    assert response.status_code == 200, response.text
    overview = response.json()['task_deliveries'][task.id]
    assert overview['state'] == 'needs_attention'
    assert '重新生成' in overview['detail']
