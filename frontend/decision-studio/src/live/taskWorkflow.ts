export interface DeliveryOverview {
  state: 'not_started' | 'running' | 'needs_attention' | 'awaiting_delivery' | 'awaiting_report' | 'awaiting_publish' | 'published'
  published_ids: string[]
  package_id: string
  delivery_id: string
  verification_status: string
  report_status?: string
  detail?: string
}
interface TaskState { id: string; status: string; phase: string }
export function taskWorkflow(task: TaskState, overview?: DeliveryOverview) {
  const stage = task.status === 'running' ? 'running' : overview?.state ||
    (task.status === 'completed' ? 'awaiting_delivery' : task.status === 'idle' ? 'not_started' : 'needs_attention')
  const views = {
    not_started: { label: '待启动', detail: '保存的是研究草稿，检查启动条件后开始执行。', action: '查看任务', tone: 'neutral' },
    running: { label: '研究中', detail: '任务仍在执行，完成后继续检查交付与发布。', action: '查看进度', tone: 'info' },
    needs_attention: { label: '需要处理', detail: overview?.detail || '本次运行尚未完成，请检查失败原因和可恢复的成果。', action: '查看并处理', tone: 'warning' },
    awaiting_delivery: { label: '研究完成 · 待交付', detail: '研究已结束，尚未发布为对话可调用的能力。请检查成果、生成交付包并核对发布。', action: '检查并交付成果', tone: 'warning' },
    awaiting_report: { label: '待生成报告与交付包', detail: '已有研究记录，报告与交付材料尚未就绪。请在交付页检查原因并生成材料。', action: '处理报告与交付', tone: 'warning' },
    awaiting_publish: { label: '交付包已生成 · 待发布', detail: overview?.verification_status === 'passed'
      ? '交付试算已通过，核对用途与输入要求后发布，供对话复用。'
      : '交付包已生成。请检查使用说明和试算状态，再核对发布，供对话复用。', action: '核对并发布', tone: 'warning' },
    published: { label: '已发布 · 可复用', detail: '成果已登记到能力目录，可以查看算法包并在对话中使用。', action: '查看已发布算法包', tone: 'success' },
  } as const
  return { ...views[stage], stage, packageId: overview?.package_id || '',
    pendingDelivery: task.status === 'completed' && stage !== 'published',
    kind: stage === 'published' ? 'package' : ['awaiting_delivery', 'awaiting_report', 'awaiting_publish'].includes(stage) ||
      (stage === 'needs_attention' && task.status === 'completed') ? 'delivery' : 'task' }
}
export function invocationBlockers(steps: { package_id: string; input_mode: string; csv_path: string; data_json: string; cutoff: string; prepared: any }[], availableIds: string[]) {
  const problems: string[] = []
  if (!steps.length) return ['请先选择一个算法包。']
  steps.forEach((step, i) => {
    const prefix = `第 ${i + 1} 步：`
    if (!availableIds.includes(step.package_id)) problems.push(prefix + '算法包已不可用，请重新选择。')
    if (step.input_mode === 'previous' && i === 0) problems.push(prefix + '首步需要输入数据，请选择项目数据、填写字段或 CSV。')
    if (step.input_mode === 'project' && (step.prepared?.package_id !== step.package_id || step.prepared?.requestedCutoff !== step.cutoff))
      problems.push(prefix + '请点击“准备项目输入”；修改算法包或截止时间后需要重新准备。')
    if (step.input_mode === 'csv' && !step.csv_path.trim()) problems.push(prefix + '请选择项目中的 CSV 文件或填写文件路径。')
    if (step.input_mode === 'json') {
      try { JSON.parse(step.data_json) } catch { problems.push(prefix + '输入文件或字段还不是有效 JSON，请检查输入。') }
    }
  })
  return problems
}
