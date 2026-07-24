export type ReportStageStatus = 'pending' | 'running' | 'completed' | 'failed'

export interface ReportStageProgress {
  key: 'collect' | 'analyze' | 'write' | 'review' | 'finalize'
  label: string
  detail: string
  status: ReportStageStatus
}

export interface ReportProgressState {
  status: ReportStageStatus | 'idle'
  statusLabel: string
  activityLabel: string
  percent: number
  stages: ReportStageProgress[]
  error: string
}

const STAGE_DEFINITIONS: Array<Omit<ReportStageProgress, 'status'> & { components: string[] }> = [
  { key: 'collect', label: '整理材料', detail: '问题与搜索结果', components: ['autoreport.collector'] },
  { key: 'analyze', label: '分析方法', detail: '代码补读与候选比较', components: ['autoreport.analyzer'] },
  { key: 'write', label: '撰写报告', detail: '方法与使用说明', components: ['autoreport.writer'] },
  { key: 'review', label: '检查报告', detail: '完整性与准确性', components: ['autoreport.auditor'] },
  { key: 'finalize', label: '生成文件', detail: '章节与最终文档', components: ['autoreport.generator'] },
]

function text(value: unknown) {
  return typeof value === 'string' ? value : ''
}

function eventStatus(row: Record<string, unknown>): ReportStageStatus | null {
  const event = text(row.event).toUpperCase()
  if (event.endsWith('FAILED') || event === 'FAILED' || event === 'ERROR') return 'failed'
  if (['COMPLETED', 'SKIPPED', 'BYPASSED'].includes(event) || event.endsWith('COMPLETED')) return 'completed'
  if (event || text(row.component)) return 'running'
  return null
}

function stageForEvent(row: Record<string, unknown>) {
  const component = text(row.component)
  if (component === 'autoreport.generator' && text(row.event).toUpperCase() === 'ACTIVATED') return null
  return STAGE_DEFINITIONS.find((stage) => stage.components.includes(component))?.key ?? null
}

function eventActivity(row: Record<string, unknown>) {
  const component = text(row.component)
  const event = text(row.event).toUpperCase()
  const labels: Record<string, string> = {
    'autoreport.collector:ACTIVATED': '正在扫描任务与搜索结果',
    'autoreport.collector:COMPLETED': '材料整理完成',
    'autoreport.analyzer:ACTIVATED': '正在分析问题与候选方法',
    'autoreport.analyzer:LLM_REQUEST': '正在阅读代码并整理方法',
    'autoreport.analyzer:SOURCE_RETRIEVED': '正在补读关键代码',
    'autoreport.analyzer:CONTEXT_COMPACTED': '正在整理累计方法上下文',
    'autoreport.analyzer:COMPLETED': '方法分析完成',
    'autoreport.writer:ACTIVATED': '正在组织最终报告',
    'autoreport.writer:LLM_REQUEST': '正在撰写报告正文',
    'autoreport.writer:COMPLETED': '报告初稿完成',
    'autoreport.auditor:ACTIVATED': '正在检查报告完整性',
    'autoreport.auditor:LLM_REQUEST': '正在检查方法、对比与使用说明',
    'autoreport.auditor:COMPLETED': '报告检查完成',
    'autoreport.auditor:SKIPPED': '已按配置跳过最终检查',
    'autoreport.auditor:BYPASSED': '报告检查不可用，保留已生成正文',
    'autoreport.generator:GENERATED_FILE': '正在写入报告文件',
    'autoreport.generator:COMPLETED': '报告文件生成完成',
  }
  return labels[`${component}:${event}`] ?? '正在生成报告'
}

export function deriveReportProgress(
  currentState: Record<string, unknown> | undefined,
  events: Record<string, unknown>[],
): ReportProgressState {
  const stageStatuses = new Map<ReportStageProgress['key'], ReportStageStatus>()
  let lastStageIndex = -1
  for (const row of events) {
    const key = stageForEvent(row)
    if (!key) continue
    const status = eventStatus(row)
    if (!status) continue
    stageStatuses.set(key, status)
    lastStageIndex = Math.max(lastStageIndex, STAGE_DEFINITIONS.findIndex((stage) => stage.key === key))
  }

  const pipelineStatus = text(currentState?.status).toLowerCase()
  const pipelineCompleted = pipelineStatus === 'completed'
  const pipelineFailed = pipelineStatus === 'failed'
  const stages = STAGE_DEFINITIONS.map((definition, index): ReportStageProgress => {
    let status = stageStatuses.get(definition.key) ?? 'pending'
    if (pipelineCompleted) status = 'completed'
    else if (status === 'pending' && index < lastStageIndex) status = 'completed'
    return { key: definition.key, label: definition.label, detail: definition.detail, status }
  })

  if (pipelineFailed && !stages.some((stage) => stage.status === 'failed')) {
    const index = Math.max(0, lastStageIndex)
    stages[index] = { ...stages[index], status: 'failed' }
  }

  const completed = stages.filter((stage) => stage.status === 'completed').length
  const running = stages.some((stage) => stage.status === 'running')
  const percent = pipelineCompleted ? 100 : Math.min(95, completed * 20 + (running ? 10 : 0))
  const lastEvent = events.at(-1)
  const failureEvent = [...events].reverse().find((row) => eventStatus(row) === 'failed')
  const failureFields = failureEvent?.fields
  const error = failureFields && typeof failureFields === 'object'
    ? text((failureFields as Record<string, unknown>).error)
    : ''

  const status: ReportProgressState['status'] = pipelineCompleted
    ? 'completed'
    : pipelineFailed
      ? 'failed'
      : events.length > 0
        ? 'running'
        : 'idle'
  const labels: Record<ReportProgressState['status'], string> = {
    idle: '等待开始',
    pending: '等待开始',
    running: '生成中',
    completed: '已完成',
    failed: '生成失败',
  }

  return {
    status,
    statusLabel: labels[status],
    activityLabel: pipelineCompleted ? '最终报告已生成' : pipelineFailed ? '报告生成未完成' : lastEvent ? eventActivity(lastEvent) : '等待 AutoReport 启动',
    percent,
    stages,
    error,
  }
}
