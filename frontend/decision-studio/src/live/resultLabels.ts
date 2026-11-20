export const resultLabels: Record<string, string> = {
  prediction: '预测结果',
  predictions: '预测结果',
  id: '记录编号',
  saleprice: '预测房价',
  dev_log_rmse: '开发集对数 RMSE',
  holdout_log_rmse: '留出集对数 RMSE',
  holdout_rmse_ln: '留出集对数 RMSE',
  ln_rmse: '对数 RMSE',
  result: '结果',
  results: '结果',
  prediction_cutoff: '观测截止时间',
  prediction_time: '预测时间',
  predicted_al_n: '预测压滤液 Al(N)',
  unit: '单位',
  value: '数值',
  confidence: '置信度',
  interval: '预测区间',
  mae: '平均绝对误差（MAE）',
  rmse: '均方根误差（RMSE）',
  mse: '均方误差（MSE）',
  r2: '拟合优度（R²）',
  accuracy: '准确率',
  f1: 'F1 分数',
  auc: 'AUC',
  n: '评估样本数',
  count: '数量',
  sample_count: '样本数',
  baseline: '基线',
  baseline_mae: '基线 MAE',
  baseline_rmse: '基线 RMSE',
  median_baseline_mae: '训练中位数基线 MAE',
  holdout_mae: '独立验证 MAE',
  holdout_rmse: '独立验证 RMSE',
  status: '状态',
  reason: '依据',
  limitations: '适用限制',
  caveats: '需复核事项',
  name: '名称',
  label: '项目',
  timestamp: '时间',
  time: '时间',
  date: '日期',
  target: '预测目标',
  actual: '实际值',
  predicted: '预测值',
  error: '误差',
  steam_advice: '蒸汽进气流量参考',
  recommended_flow_kg_h: '参考流量（kg/h）',
  recommended_steam_flow: '参考蒸汽流量',
  current_flow_kg_h: '当前流量（kg/h）',
  support_count: '支持样本数',
  support_sample_count: '支持样本数',
  interval_kg_h: '参考区间（kg/h）',
  basis: '参考依据',
  metrics: '评估指标',
  model: '模型信息',
  contract: '调用约定',
  diagnostics: '诊断信息',
  execution_evidence: '执行详情',
  version: '版本',
}
export function resultLabel(key: string) {
  return resultLabels[key.toLowerCase()] || key.replace(/_/g, ' ')
}
export function resultText(value: unknown): string {
  if (value == null) return '未提供'
  if (typeof value === 'boolean') return value ? '是' : '否'
  if (typeof value === 'number')
    return Number.isFinite(value) ? String(Number(value.toPrecision(8))) : '无有效数值'
  return (
    (
      {
        ok: '正常',
        completed: '已完成',
        failed: '失败',
        unavailable: '暂不可用',
        not_applicable: '不适用',
        review_required: '需要复核',
        passed: '已通过',
        running: '进行中',
      } as Record<string, string>
    )[String(value)] || String(value)
  )
}
