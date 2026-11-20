"""Launch/inspect the real chemical Studio demo through public local APIs.

Credentials are read by the services from local settings, never from this file.
"""
from pathlib import Path
import argparse
import json
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RUN_DIR = ROOT / 'runs/chemical-studio-demo-20261019'
BASE = 'http://127.0.0.1:18080'


def request(path, payload=None, method=None, timeout=60):
    req = urllib.request.Request(BASE + path, data=None if payload is None else json.dumps(payload, ensure_ascii=False).encode(),
        headers={'Content-Type': 'application/json'}, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.load(response)


HINT = '''硫酸铝工艺真实研发：预测下一小时压滤液 Al(N)，并交付可复用预测与蒸汽流量参考算法包。
目标：以预测截止时刻 t 已可见的设备历史数据，预测 t+1小时的压滤液 Al(N)（单位为当量）。明确这是一小时提前预测，不能把采样时刻即时回归当成提前预测。标签仅来自浓度.xls 中参数 Al(N）（注意全角右括号）、部位 压滤液 的结果列；原液 Al 可作历史特征但不能混作标签。标签有稀疏采样，不能伪造每小时真值。若多个目标化验记录具有相同采样时间，按该时间组内有限结果的算术平均作为本次实验的确定性默认标签；这是公开披露的实现口径，不宣称为官方化验规则。必须报告原始目标行数、唯一采样时间数、重复时间组数、组内结果冲突数及过滤数。每条化验 s 对应预测截止 t=s-1h。只用 <=t 的设备/天气观测；不得使用截止后的设备和天气，不得把真实未来天气当预报。不使用无法证明发布时间的化验作在线历史特征；若使用需显式可见性规则，保守起见可不使用。设备 SampleTime 是时间列。
设备.csv 的统计不得把字段画像前 20,000 行或其日期范围当作全表范围。对完整 CSV 做只读分块扫描，至少统计总记录数、SampleTime 有效/无效数及全表最早/最晚时间，并将扫描范围与预览范围分别记录到本次 AutoRealize/QDI 证据中；关联字段的 directional_coverage 不代表时间覆盖。
weather_ruyuan_hourly_20250101_20260525.csv 也必须做完整只读扫描，以“时间”为时间列，记录总行数、有效/无效时间数和全表最早/最晚时间；把完整扫描范围与字段画像预览范围分开写入本次证据，不得将抽样画像当成全表结论。
读全任务需求和工艺说明。仅从提供的数据构建特征，窗口长度、缺失处理、模型类别可搜索，但所有候选使用同一固定时间划分和评估样本。最早60%可用标签训练，中间20%开发，最后20%作为一次性留出；该人口与历史r19评估重叠，只能作为已访问人口的探索性对照，不能宣称独立盲测或泛化验证。跨分割边界按预测时点清洗：训练标签时刻必须不晚于最早被评分样本的预测截止时刻，按一小时预测跨度 purge 边界重叠样本；时间顺序切分本身不够。特征只能向过去取，预处理只在训练拟合。融合权重、收缩系数、校准器、阈值和元模型只允许在训练段 OOF/嵌套验证或独立校准段拟合，不得在同一开发样本上拟合后再用该样本评分。主指标开发MAE越小越好，同时报RMSE和训练中位数基线。留出不参与搜索/选模型，只在候选冻结后由引擎评估一次；如进行全数据重训必须单独明确保存。唯一引擎评估入口为 final_evaluate(data, artifact_dir)，并须输出逐行评估证据；不得另设未定义返回合同的 evaluate_holdout 提交入口。
所有候选必须对冻结评估人口中的每个样本恰好输出一个有限预测，并保留稳定的样本 ID、截止时间与真值对应关系。缺失预测、异常、非有限数、错时预测或预测失败会使该候选整体无效；不得静默删行、取交集、跳过失败样本或缩小评估分母。必须保存 expected/scored/failed 行数，只有 expected=scored 且 failed=0 才能参与排序或最终结论。
可复用入口 predict(model_path,data)：支持 JSON 对象，包含 prediction_cutoff 字符串、history 原始设备记录数组（保持原字段名），可选 weather_history 数组。函数内部显式把记录转成DataFrame，推理不训练、不读取训练原表、不依赖机器绝对路径。必须对空历史、未来记录、缺列、覆盖不足给出清楚报错；预测时间恒为cutoff+1h。输出JSON对象包含 prediction_cutoff、prediction_time、predicted_al_n、unit、蒸汽建议 steam_advice 和适用限制，纯Python有限数值便于前端展示。训练/评估使用同一特征逻辑。保存模型、预处理、所需历史参考表、输入列顺序、依赖、命令和真实可重放调用样例。
final_evaluate(data, artifact_dir) 必须只从传入的 artifact_dir 加载 selected_config.json、冻结模型和所有必需配方文件；不得基于 __file__、cwd、绝对机器路径或其它候选目录寻找配置，缺少文件时明确失败。完成结果必须返回非空、有限数值 metrics 对象，inference_checks 对象或对象数组，以及相对于 artifact_dir 的 model_path。留出只在候选选择冻结后执行一次；本次 r19 留出集与历史实验重叠，报告只能作为已访问评估人口上的探索性对照，不宣称独立盲测或泛化验证。
蒸汽建议是有数据支持的操作参考，不宣称因果优化、自动控制或保证节能。按工艺文档压力校正关系：标准值=(蒸汽进气压力-600)*2+蒸汽进气流量。优先从训练期相近进料流量/压力/工况且有可用质量证据的历史样本估计压力归一后的合理流量参考，再换算当前压力下kg/h；输出推荐值/区间、实际支持样本数、当前流量和依据。若数据不足/停机/超出训练支持，必须返回 unavailable/review_required 及原因，不能捏造。可使用稳健分位数或近邻支持方法，具体算法由搜索确定；建议与Al预测区别报告，不将相关性预测冒充干预效果。原数据上下限/设定值均0.5而合格标记与之不一致，不可凭此臆造质量合格阈值。记录这种冲突。
工艺约束：各效压力为反馈量非可控设定；每次蒸汽阀开度变化<=5个百分点不等于流量变化<=5%。日常液位与开机液位说明存在不同情境，不能混用。真空泵流量必须>0但设备表可能无该字段，缺失时明确人工核查条件，不得认定自动控制可用。不输出未经证据支持的阀开度指令。
资源与交付：CPU总计8核、内存10GiB、两个搜索worker。设备表327MB，采用分块读取/向量化预聚合，禁止把整表展开成巨大滑窗矩阵。单候选执行上限600秒；整体AlgoEvolve搜索预算3600秒，AutoRealize与报告另计。优先先形成可运行的稳健基线，再改进树模型/时间特征。predict需在120秒内完成且只加载冻结模型。最终交付必须可以独立试算、打包并在Studio对话复用。'''


def _resolve_run_dir(value):
    run_dir = Path(value).expanduser().resolve()
    allowed_roots = [(ROOT / "runs").resolve(), (ROOT / ".codex-work").resolve()]
    if not any(run_dir.is_relative_to(parent) for parent in allowed_roots):
        raise ValueError("Run output must stay under AutoDecision/runs or AutoDecision/.codex-work")
    return run_dir


def launch(run_dir):
    receipt_path = run_dir / 'receipt.json'
    if run_dir.exists() and any(run_dir.iterdir()):
        raise RuntimeError(f'Run output directory is not empty; refusing to reuse: {run_dir}')
    state = request('/api/studio/state')
    project = next(p for p in state['projects'] if Path(p['input_root']).name == '化学工厂')
    payload = {'task_name': f'硫酸铝下一小时Al(N)预测与蒸汽参考-{run_dir.name}',
        'input_root': project['input_root'], 'output_root': str(run_dir / 'tasks'),
        'auto_realize': {'task_hint': HINT, 'llm_file_cognition_mode': 'documents_only',
            'llm_concurrency': 2, 'llm_timeout': 240, 'enable_vllm': True,
            'investigation_max_questions': 6, 'investigation_max_rounds_per_question': 3,
            'investigation_max_scripts_per_question': 3, 'investigation_script_timeout_secs': 180,
            'prompt_token_budget': 24000, 'review_gate_policy': 'strict'},
        'auto_ml': {'steps': 1000, 'time_limit_secs': 3600, 'parallel_search_num': 2,
            'initial_drafts': 3, 'search_num_drafts': 6, 'exec_timeout_secs': 600,
            'use_global_memory': False, 'use_coldstart': False, 'use_optimization_experience_library': False,
            'auto_install_missing_dependencies': False, 'code_request_timeout_secs': 600,
            'feedback_request_timeout_secs': 300, 'code_generation_max_retries': 3,
            'feedback_generation_max_retries': 3, 'fast_first_draft_skip_pre_review': False},
        'auto_report': {'enabled': True},
        'resources': {'cpu_cores': 8, 'memory_limit_gb': 10, 'accelerator_mode': 'none'}}
    task = request(f"/api/studio/projects/{project['id']}/tasks", payload)
    run_dir.mkdir(parents=True, exist_ok=True)
    receipt = {'project_id': project['id'], 'task_id': task['id'], 'config': payload}
    receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(request('/api/tasks/start', {'task_id': task['id']}), ensure_ascii=False))


def status(run_dir):
    receipt = json.loads((run_dir / 'receipt.json').read_text(encoding='utf-8'))
    task = next(t for t in request('/api/tasks') if t['id'] == receipt['task_id'])
    print(json.dumps({k: task.get(k) for k in ['id','task_name','status','phase','run_dir','auto_ml_log_dir','auto_ml_workspace_dir','last_error']}, ensure_ascii=False, indent=2))
    if task.get('run_dir'):
        root = Path(task['run_dir'])
        events = list(root.rglob('event_stream.jsonl'))
        if events:
            latest = max(events,key=lambda p:p.stat().st_mtime)
            rows = latest.read_text(encoding='utf-8').splitlines()
            print(json.dumps({'latest_events':[{'ts':e.get('ts'),'event':e.get('event'),'prompt':e.get('fields',{}).get('prompt')}
                for e in [json.loads(row) for row in rows[-3:]]]},ensure_ascii=False))
        audits = list(latest.parent.glob('artifact_consistency_batches_round_*.json')) if events else []
        if audits and task.get('phase') == 'review_repair':
            latest = max(audits, key=lambda p: p.stat().st_mtime)
            audit = json.loads(latest.read_text(encoding='utf-8'))
            print(json.dumps({'audit':str(latest.relative_to(root)),
                'completed_batches':audit.get('completed_batches'), 'batch_count':audit.get('batch_count'),
                'blocking_issues':[{'batch':b['batch'], 'artifact':i.get('artifact'),
                    'section':i.get('section'), 'message':i.get('message')}
                    for b in audit.get('batches',[]) for i in b.get('review',{}).get('issues',[])
                    if i.get('severity') == 'blocking']}, ensure_ascii=False))
    if task.get('auto_ml_log_dir'):
        logs = Path(task['auto_ml_log_dir'])
        for name in ['run_status.json','search_state.json']:
            if (logs/name).exists():
                data = json.loads((logs/name).read_text(encoding='utf-8'))
                print(json.dumps({name:{k:v for k,v in data.items() if k in ['status','phase','reason','elapsed_seconds','cumulative_search_elapsed_seconds','completed_steps','active_searches','stop_reason','updated_at']}},ensure_ascii=False))
        if (logs/'journal.json').exists():
            j = json.loads((logs/'journal.json').read_text(encoding='utf-8'))
            nodes = j.get('nodes',[]) if isinstance(j,dict) else j
            print(json.dumps({'nodes':len(nodes),'candidates':[{'id':n.get('id'),'stage':n.get('stage'),'valid':n.get('is_valid'),'buggy':n.get('is_buggy'),'metric':n.get('metric')} for n in nodes[-6:]]},ensure_ascii=False))
        if (logs/'AlgoEvolve.log').exists():
            print('\n'.join((logs/'AlgoEvolve.log').read_text(encoding='utf-8',errors='replace').splitlines()[-8:]))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['launch','status'])
    parser.add_argument('--run-dir', type=Path, default=DEFAULT_RUN_DIR,
        help='Isolated output directory. Must be under AutoDecision/runs or AutoDecision/.codex-work.')
    args = parser.parse_args()
    selected_run_dir = _resolve_run_dir(args.run_dir)
    launch(selected_run_dir) if args.action == 'launch' else status(selected_run_dir)
