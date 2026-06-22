import json
from pathlib import Path
p=Path('runs/城市配送/autorealize/realize_report/automl_context_pack.json')
if p.exists():
    data=json.loads(p.read_text(encoding='utf-8-sig'))
    print('keys=', list(data.keys()))
    for k in ['problem_paradigm','task_goal','priority_rules','data_orchestration','modeling_boundary','constraints','leakage_guards','pitfalls']:
        v=data.get(k)
        print('\n['+k+']', type(v).__name__)
        if isinstance(v, str): print(v[:500])
        elif isinstance(v, list):
            print('len=', len(v))
            for item in v[:3]: print('-', str(item)[:500])
    print('\n[evaluation_contract]', data.get('evaluation_contract', {}).keys())
    print(json.dumps(data.get('evaluation_contract', {}), ensure_ascii=False, indent=2)[:1500])
    print('\n[output_contract]', data.get('output_contract', {}).keys())
    print(json.dumps(data.get('output_contract', {}), ensure_ascii=False, indent=2)[:1000])
    print('\n[data_access] len=', len(data.get('data_access') or []))
    for x in (data.get('data_access') or [])[:8]:
        print('-', x.get('path') or x.get('pattern'), '|', x.get('read_method'), '|', str(x.get('read_example') or '')[:160].replace('\n',' / '))
