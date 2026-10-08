import type { MctsNode, ReplayEvent, ReplayRecording, SnapshotPayload, Task } from '../types'
import { defaultTaskConfig } from '../composables/useTasks'
import { projectReplay } from './replay'

const start = Date.UTC(2026, 7, 18, 9) / 1000
const config = defaultTaskConfig(1)
config.task_name = '华东门店 · 月度销售预测'
config.auto_realize.task_hint = '预测各门店下个月销售额，识别节假日和促销的影响。'
config.auto_ml.steps = 20
const task: Task = { id: 'local-demonstration', task_name: config.task_name, input_root: '', output_root: '',
  created_at: start, updated_at: start + 3280, status: 'completed', phase: 'completed', config }
const events: ReplayEvent[] = []
function add(offset: number, stage: ReplayEvent['stage'], kind: ReplayEvent['kind'], label: string, payload: ReplayEvent['payload']) {
  events.push({ sequence: events.length + 1, timestamp: start + offset, offset_ms: offset * 1000, stage, kind, label, payload })
}
add(0, 'data_cognition', 'stage', '开始分析输入数据', { task: { status: 'running', phase: 'autorealize' } })
add(1, 'data_cognition', 'artifact', '完成输入目录清点', { snapshot: { auto_realize: { directory_tree_text: 'sales_forecast/\n- sales_history.csv\n- stores.xlsx\n- promotion_calendar.csv\n- 业务需求.md' } } })
const cognitionIndex: NonNullable<SnapshotPayload['auto_realize']['file_cognition_index']> = {}
const fileSummaries = ['门店月度销售历史。字段：store_id、month、sales、units。销售额单位为人民币元；只使用预测窗口前的数据。', '门店维表。字段：store_id、region、store_type、opening_date。以 store_id 与销售表关联，需检查唯一键与未匹配门店。', '促销与节假日日历。字段：date、campaign、region。只纳入预测时刻已公布的计划。', '业务目标：预测下一自然月各门店销售额。硬约束：全门店覆盖、金额非负、禁止未来数据。评估：三窗口滚动 MAE。']
for (const [i, name] of ['sales_history.csv', 'stores.xlsx', 'promotion_calendar.csv', '业务需求.md'].entries()) {
  cognitionIndex[name] = { markdown: `# ${name}\n\n示例文件认知。\n\n${fileSummaries[i]}` }
  add(15 + i * 25, 'data_cognition', 'event', `完成文件认知 · ${name}`, { event: { timestamp: start + 15 + i * 25, component: 'module.data_cognition.file_artifact', event: 'GENERATED_FILE', fields: { file: name }, status: 'completed', message: `完成 ${name} 的结构与字段分析` }, snapshot: { auto_realize: { file_cognition_index: { ...cognitionIndex } } } })
}
add(120, 'data_cognition', 'artifact', '数据关联与业务约束提取完成', { snapshot: { auto_realize: { data_cognition_report: { status: 'completed' }, data_description_text: '# 销售预测数据认知\n\n界面演示，以下为示例数据说明。\n\n销售历史通过 store_id 关联门店维表，通过日期和区域关联促销日历。\n\n已确认约束：未来月份不能参与训练或特征计算；输出覆盖有效门店且为非负金额。\n\n待评估：滚动窗口表现、节假日影响与不同模型残差的互补性。' } } })
const description = '# 华东门店月度销售预测\n\n> 界面演示数据，以下指标与结果用于展示交互。\n\n## Overview\n预测各门店下一个自然月的销售额，支持备货与经营决策。\n\n## Data\n- sales_history.csv：门店、月份、销售额、销量。\n- stores.xlsx：门店属性、区域、开业日期。\n- promotion_calendar.csv：预先发布的促销与节假日日历。\n\n## Evaluation\n统一使用三个历史滚动窗口验证，指标为 MAE，越低越好。预测窗口内真实销售额不得参与特征工程。\n\n## Constraints\n1. 预测结果覆盖每一个有效门店。\n2. 销售额非负，输出人民币元。\n3. 不得使用预测时刻后才能获得的数据。\n\n## Submission\n输出 store_id,month,sales，保留输入门店与月份的唯一映射。\n\n## Reproducibility\n固定验证窗口与随机种子；保存预处理器、模型、train.py、predict.py 与依赖文件。'
add(130, 'task_definition', 'stage', '建立统一任务与评估合同', { event: { component: 'task_definition', status: 'running', message: '核对预测窗口、评价指标与业务约束' } })
add(240, 'task_definition', 'artifact', '任务定义完成 · MAE / 滚动验证', { snapshot: { auto_realize: { description_text: description, automl_context_text: '任务类型：时序预测\n评估方向：minimize\n验证：3 个时间滚动窗口\n硬约束：非负、全门店覆盖、禁止未来信息\n交付：train.py、predict.py、预处理器、模型与依赖清单。', current_state: { status: 'completed' } } } })
add(270, 'automl', 'stage', '启动蒙特卡洛树搜索', { task: { status: 'running', phase: 'automl' } })
const definitions: [string, string | null, string, string, number | null, string[]?][] = [
  ['01', null, 'draft', '季节性基线', 8420], ['02', null, 'draft', 'LightGBM', 6840], ['03', null, 'draft', 'CatBoost', 7110],
  ['04', '01', 'improve', '门店分组均值', 7990], ['05', '02', 'improve', '时间滞后特征', 5930], ['06', '03', 'improve', '促销交互特征', 6480],
  ['07', '02', 'improve', '多窗口训练', null], ['08', '04', 'evolution', '趋势残差修正', 7250], ['09', '05', 'improve', '滚动统计特征', 5280],
  ['10', '07', 'debug', '修复窗口边界', 6190], ['11', '06', 'improve', '门店类别编码', 5920], ['12', '09', 'improve', '稳健损失函数', 5060],
  ['13', '11', 'evolution', '分层残差模型', 5510], ['14', '09', 'fusion', 'LightGBM + CatBoost', 4780, ['09', '11']],
  ['15', '10', 'improve', '节假日编码', 5780], ['16', '12', 'improve', '时序参数搜索', 4910], ['17', '13', 'improve', '类别平滑', 5390],
  ['18', '14', 'improve', '窗口权重校准', 4560], ['19', '16', 'fusion', '三模型加权融合', 4390, ['16', '17', '18']],
  ['20', '19', 'improve', '门店分层校准', 4210],
]
definitions.forEach(([id, parent, stage, label, metric, sources], i) => {
  const node: MctsNode = { id: `candidate-${id}`, parent_id: parent ? `candidate-${parent}` : null, stage, label,
    fusion_sources: sources?.map(s => `candidate-${s}`), metric, maximize: false, is_buggy: metric === null, is_valid: metric !== null,
    search_eligible: metric !== null, delivery_ready: metric !== null, delivery_certified: metric !== null, pending_execution: false,
    visits: Math.max(1, 12 - Math.floor(i / 2)), uct: 0.82 + i / 100, exec_time: 48 + i * 3,
    created_time: new Date((start + 300 + i * 130) * 1000).toISOString(), status: metric === null ? 'failed' : 'completed',
    plan: `${label}\n\n使用统一的三个滚动验证窗口。构造仅依赖预测时点前历史数据的特征，按门店聚合误差，保留完整覆盖与非负输出约束。${sources ? '\n\n融合来源：' + sources.join('、') + '。权重仅在训练侧的验证结果上确定。' : ''}`,
    code: '# Interface demonstration only; this candidate was not executed.\nfrom pathlib import Path\nimport joblib\n\ndef predict(model_path, data):\n    bundle = joblib.load(Path(model_path))\n    features = bundle["preprocessor"].transform(data)\n    return bundle["model"].predict(features).clip(min=0)\n',
    result: metric === null ? '示例诊断：验证窗口越界，等待 Debug。' : `示例 MAE: ${metric}\n约束检查：非负 / 门店完整性 / 时间边界通过。`,
    llm_insight: sources ? '不同模型的验证残差呈互补趋势，加权融合降低了不同门店间的误差波动。此结果为界面演示。' : '该候选沿用统一评估口径；可在右侧检查方案、代码、运行结果及交付状态。此结果为界面演示。',
  }
  add(300 + i * 130, 'automl', 'node', `生成 ${id} · ${label}`, { node: { id: node.id, parent_id: node.parent_id, stage, label, fusion_sources: node.fusion_sources, pending_execution: true, status: 'generating' } })
  add(380 + i * 130, 'automl', 'node', `${id} · ${metric === null ? '评估失败' : `MAE ${metric.toLocaleString()}`}`, { node })
})
add(3000, 'report', 'stage', '生成候选对比与交付报告', { task: { status: 'running', phase: 'report' } })
add(3280, 'report', 'artifact', '交付报告完成', { task: { status: 'completed', phase: 'completed' }, snapshot: { auto_report: { current_state: { status: 'completed' }, report_markdown: '# 月度销售预测 · 决策报告\n\n> 示例数据，非实际训练结果。\n\n## 问题与约束\n预测华东各门店下一自然月销售额。统一采用滚动时间验证，所有候选保持数据边界、完整覆盖和非负约束。\n\n## 最终方案\n三模型加权融合与门店分层校准。演示 MAE 为 4,210，季节性基线为 8,420。\n\n## 候选对比\n| 算法 | MAE（演示） | 状态 |\n|---|---:|---|\n| 季节性基线 | 8,420 | 已评估 |\n| LightGBM | 6,840 | 已评估 |\n| CatBoost | 7,110 | 已评估 |\n| 双模型融合 | 4,780 | 已评估 |\n| 最终融合校准 | 4,210 | 已评估 |\n\n## 复用与交付\n实际任务需检查模型文件、训练入口、推理入口、依赖与一致性验证记录。该演示不提供已训练模型。' } } })
const recording: ReplayRecording = { schema_version: 1, task_id: task.id, task_name: task.task_name, fidelity: 'reconstructed',
  fidelity_notes: ['内置界面演示，所有节点、指标与事件均为示例，未执行模型训练。'], started_at: start, ended_at: start + 3280, duration_ms: 3280000, events }
export const demoRecording = recording
export const demoTask = task
export const demoSnapshot: SnapshotPayload = projectReplay(recording, events.length - 1, task)
