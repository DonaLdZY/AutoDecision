"""Verify frozen-demo evidence and prepare its reviewed publication contract.

No training, search, holdout reselection, or candidate edits. Runtime inference
uses a moved copy of the exact exported implementation and model.
"""
from pathlib import Path
import ast
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT/'runs/chemical-studio-demo-20261019'


def save(name, value):
    (RUN/name).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def main():
    import numpy as np
    import pandas as pd
    sys.path.insert(0, str(ROOT/'frontend/backend'))
    from project_inputs import ProjectBinding, prepare_window
    receipt = json.loads((RUN/'receipt.json').read_text(encoding='utf-8'))
    workspace = next(RUN.glob('tasks/*/automl/workspaces/*'))
    selected = workspace/'best_solution'
    manifest = json.loads((selected/'solution_manifest.json').read_text(encoding='utf-8'))
    source = selected/manifest['implementation_path']
    assert hashlib.sha256(source.read_bytes()).hexdigest() == manifest['implementation_file_sha256']
    constants = {}
    for statement in ast.parse(source.read_text(encoding='utf-8')).body:
        if isinstance(statement, ast.Assign):
            for target in statement.targets:
                if isinstance(target, ast.Name):
                    try: constants[target.id] = ast.literal_eval(statement.value)
                    except (ValueError, TypeError): pass
    assert constants['WINDOW_HOURS'] == {'1h':1,'6h':6,'24h':24,'168h':168}
    assert manifest['node_id'] == 'fbfaa9467aad4cb69a4c2c82a25aacfb'
    device_columns = ['SampleTime', *constants['DEVICE_CORE_CHANNELS']]
    weather_columns = ['时间', *constants['WEATHER_CHANNELS']]
    input_binding = {'kind':'time_window','cutoff_field':'prediction_cutoff','timezone':'Asia/Shanghai','sources':[
        {'path':constants['DEVICE_FILE'],'field':'history','time_column':'SampleTime','columns':device_columns,
         'window_seconds':168*3600,'lower_bound':'inclusive','max_rows':20000},
        {'path':constants['WEATHER_FILE'],'field':'weather_history','time_column':'时间','columns':weather_columns,
         'window_seconds':168*3600,'lower_bound':'inclusive','max_rows':20000},
    ]}
    def records(columns, time_column):
        return {'type':'array','description':'完整已声明历史窗口；不得包含预测截止后的记录。数值允许源数据缺失，由冻结实现处理。',
                'items':{'type':'object','required':columns,
                         'properties':{c:({'type':'string'} if c==time_column else {'description':'原始数值或缺失 null，单位沿用项目数据'}) for c in columns}}}
    spec = {'name':'压滤液 Al(N) 下一小时预测与蒸汽参考',
        'description':'本次3601秒算法研发的冻结模型，按项目设备与天气历史预测 t+1小时压滤液 Al(N)，并提供训练期相近工况的蒸汽进气流量参考。留出305条 MAE 0.08625，弱于训练中位数基线0.08052，尚未达到业务验收。蒸汽参考是观察关联，缺少质量合格关联与真空泵流量证据，须人工复核，不是控制指令。latest 表示项目最新观测时刻。',
        'input_schema':{'type':'object','required':['prediction_cutoff','history','weather_history'],
            'properties':{'prediction_cutoff':{'type':'string','description':'Asia/Shanghai 本地观测截止时间；输出预测时间恒为该时刻+1小时。'},
                'history':records(device_columns,'SampleTime'),'weather_history':records(weather_columns,'时间')}},
        'input_binding':input_binding,
        'output_description':'JSON对象：prediction_cutoff、prediction_time、predicted_al_n（当量）、unit、steam_advice、limitations、model、contract、diagnostics。steam_advice 含 status、recommended_flow_kg_h、interval_kg_h、support_sample_count、current_flow_kg_h、basis、reason、caveats。status=unavailable/review_required时不得编造推荐值；即使ok也仅为历史相近工况参考，不能宣称因果最优、保证节能或自动控制。上限/下限/设定值0.5与原始质量标记存在冲突。'}
    save('publication-spec.json', spec)
    evidence = pd.read_csv(workspace/'final_evaluation/artifacts/holdout_evidence.csv')
    final = json.loads((workspace/'final_evaluation/result.json').read_text(encoding='utf-8'))
    mae = float(np.abs(evidence.y_true-evidence.y_pred).mean())
    rmse = float(np.sqrt(np.mean((evidence.y_true-evidence.y_pred)**2)))
    assert len(evidence)==305 and abs(mae-final['metrics']['holdout_mae'])<1e-12
    assert abs(rmse-final['metrics']['holdout_rmse'])<1e-12
    assert ((pd.to_datetime(evidence.prediction_time)-pd.to_datetime(evidence.prediction_cutoff)) == pd.Timedelta(hours=1)).all()
    baseline = float(np.abs(evidence.y_true-0.43).mean())
    assert abs(baseline-final['metrics']['train_median_baseline_mae_on_holdout'])<1e-12
    labels = pd.read_excel(Path(receipt['config']['input_root'])/'浓度.xls', sheet_name='Sheet1')
    labels = labels[(labels['参数']=='Al(N）') & (labels['部位']=='压滤液')].copy()
    labels['采样时间'] = pd.to_datetime(labels['采样时间'])
    labels['结果\n[单位为当量]'] = pd.to_numeric(labels['结果\n[单位为当量]'])
    targets = labels.groupby('采样时间')['结果\n[单位为当量]'].mean().sort_index()
    assert len(labels)==1525 and len(targets)==1519
    assert np.allclose(evidence.y_true.to_numpy(),targets.iloc[1214:].to_numpy(),rtol=0,atol=1e-12)
    assert list(pd.to_datetime(evidence.prediction_time))==list(targets.index[1214:])
    train_median = float(targets.iloc[:911].median())
    assert train_median == 0.43
    dev_cutoffs = targets.index[911:1214]-pd.Timedelta(hours=1)
    overlapping_dev = int((dev_cutoffs < targets.index[910]).sum())
    original = next(workspace.glob('final_evaluation_attempts/*/artifacts/'+final['model_path']))
    frozen = selected/manifest['artifact_path']
    assert original.read_bytes()==frozen.read_bytes()
    prepared = prepare_window(receipt['config']['input_root'], ProjectBinding.model_validate(input_binding), 'latest')
    save('reviewed-input-provenance.json',{k:v for k,v in prepared.items() if k!='data_json'})
    with tempfile.TemporaryDirectory(prefix='chemical-frozen-audit-') as tmp:
        target = Path(tmp)/'solution'; shutil.copytree(selected,target,ignore=shutil.ignore_patterns('runtime','__pycache__'))
        Path(tmp,'trial_input.json').write_text(prepared['data_json'],encoding='utf-8')
        Path(tmp,'trial_request.json').write_text(json.dumps({'entrypoint':'predict','model_path':manifest['artifact_path'],'input_mode':'json'}),encoding='utf-8')
        process = subprocess.run([sys.executable,'-I',str(ROOT/'frontend/backend/solution_trial_runner.py'),tmp],
            cwd=tmp,capture_output=True,text=True,encoding='utf-8',timeout=120)
        (RUN/'frozen-portability-audit.log').write_text(process.stdout+process.stderr,encoding='utf-8')
        if process.returncode: raise RuntimeError('Frozen inference failed; inspect frozen-portability-audit.log')
        prediction = json.loads(Path(tmp,'trial_result.json').read_text(encoding='utf-8'))
    audit = {'passed':True,'scope':'Independent arithmetic check of saved holdout rows, unchanged model hash, moved-package actual inference; not a new evaluation or business acceptance.',
        'node_id':manifest['node_id'],'holdout_n':len(evidence),'holdout_mae':mae,'holdout_rmse':rmse,
        'baseline_mae':baseline,'beats_baseline':mae<baseline,'frozen_model_sha256':hashlib.sha256(frozen.read_bytes()).hexdigest(),
        'implementation_sha256':manifest['implementation_file_sha256'],'original_frozen_model_unchanged':True,
        'source_label_rows':1525,'unique_target_times':1519,'holdout_truth_and_population_match_source':True,
        'dev_cutoffs_before_last_training_target_time':overlapping_dev,
        'time_split_limitation':'Source split sorts target times but does not embargo training targets until the first dev cutoff; early development points can precede the last training target. Holdout starts after all training targets. No score or frozen split was edited.',
        'input_bytes':len(prepared['data_json'].encode()),'prediction':prediction}
    save('independent-frozen-audit.json',audit)
    for directory in [workspace/'final_evaluation',selected/'final_evaluation']:
        (directory/'independent-verification.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(audit,ensure_ascii=False))


if __name__=='__main__': main()
