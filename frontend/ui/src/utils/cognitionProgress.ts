export type CognitionStageStatus = 'pending' | 'running' | 'completed' | 'failed'

export type CognitionStageView = {
  key: string
  label: string
  detail: string
  status: CognitionStageStatus
}

export type CognitionProgressView = {
  status: CognitionStageStatus
  statusLabel: string
  activityLabel: string
  percent: number
  selectedFiles: number
  completedFiles: number
  activeLlmCalls: number
  lastUpdate: string
  stages: CognitionStageView[]
}

type EventRow = Record<string, unknown>

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {}
}

function eventName(row: EventRow) {
  return String(row.event ?? '').toUpperCase()
}

function componentName(row: EventRow) {
  return String(row.component ?? '')
}

function promptName(row: EventRow) {
  return String(asRecord(row.fields).prompt ?? '')
}

function hasEvent(events: EventRow[], component: string, event: string) {
  return events.some((row) => componentName(row) === component && eventName(row) === event)
}

function latestEvent(events: EventRow[], predicate: (row: EventRow) => boolean) {
  return [...events].reverse().find(predicate)
}

function activePromptCounts(events: EventRow[]) {
  const counts = new Map<string, number>()
  for (const row of events) {
    if (componentName(row) !== 'llm.client') continue
    const prompt = promptName(row)
    if (!prompt) continue
    const event = eventName(row)
    if (event === 'REQUEST_STARTED') counts.set(prompt, (counts.get(prompt) ?? 0) + 1)
    if (['REQUEST_COMPLETED', 'REQUEST_FAILED', 'PARSE_RETRYING'].includes(event)) {
      counts.set(prompt, Math.max(0, (counts.get(prompt) ?? 0) - 1))
    }
  }
  return counts
}

function localTime(value: unknown) {
  const raw = String(value ?? '')
  if (!raw) return ''
  const date = new Date(raw)
  if (Number.isNaN(date.getTime())) return raw
  return date.toLocaleTimeString('zh-CN', { hour12: false })
}

function stageStatus(options: { completed: boolean; running: boolean; failed?: boolean }): CognitionStageStatus {
  if (options.failed) return 'failed'
  if (options.completed) return 'completed'
  if (options.running) return 'running'
  return 'pending'
}

function activityFromPrompt(prompt: string, activeCount: number) {
  if (prompt === 'cognition_summary') return `正在生成单文件认知摘要${activeCount > 1 ? `，${activeCount} 个并发调用` : ''}`
  if (prompt === 'question_investigator_initial_questions') return 'QDI 正在规划需要进一步核实的问题'
  if (prompt === 'question_investigator_action') return 'QDI 正在分析证据并决定下一步动作'
  if (prompt === 'question_investigator_script_repair') return 'QDI 正在修复只读探查脚本'
  if (prompt) return `模型正在处理 ${prompt}`
  return ''
}

export function deriveCognitionProgress(
  eventsValue: unknown,
  options: { totalFiles: number; completedFiles: number; failedFiles: number; reportAvailable?: boolean },
): CognitionProgressView {
  const events = Array.isArray(eventsValue) ? eventsValue.filter((row): row is EventRow => !!row && typeof row === 'object') : []
  const selectedEvent = latestEvent(events, (row) => componentName(row) === 'module.data_cognition' && eventName(row) === 'FILES_SELECTED')
  const selectedFields = asRecord(selectedEvent?.fields)
  const selectedFiles = Number(selectedFields.selected ?? selectedFields.total_files ?? options.totalFiles) || options.totalFiles
  const completedFiles = Math.min(selectedFiles || options.completedFiles, options.completedFiles)
  const moduleCompleted = hasEvent(events, 'module.data_cognition', 'COMPLETED') || options.reportAvailable === true
  const moduleFailed = hasEvent(events, 'module.data_cognition', 'FAILED')
  const qdiStarted = hasEvent(events, 'module.data_cognition.investigator', 'ACTIVATED')
  const qdiCompleted = hasEvent(events, 'module.data_cognition.investigator', 'COMPLETED')
  const synthesisStarted = events.some((row) => [
    'module.data_cognition.relations',
    'module.data_cognition.constraints',
    'module.data_cognition.authority',
  ].includes(componentName(row)))
  const synthesisCompleted = qdiStarted || moduleCompleted
  const filesStarted = events.some((row) => componentName(row).startsWith('stage.P1') || promptName(row) === 'cognition_summary')
  const filesCompleted = hasEvent(events, 'module.data_cognition.parallel', 'COMPLETED') || synthesisStarted || qdiStarted || moduleCompleted
  const publishStarted = events.some((row) => componentName(row) === 'module.data_cognition' && ['GENERATING_FILE', 'GENERATED_FILE'].includes(eventName(row)))

  const stages: CognitionStageView[] = [
    {
      key: 'discover',
      label: '发现与分组',
      detail: selectedFiles > 0 ? `已选择 ${selectedFiles} 个文件` : '扫描目录与文件名模式',
      status: stageStatus({ completed: moduleCompleted || Boolean(selectedEvent) || filesStarted, running: events.length > 0 }),
    },
    {
      key: 'files',
      label: '文件读取与认知',
      detail: selectedFiles > 0 ? `${completedFiles}/${selectedFiles} 个文件已形成认知` : '等待文件清单',
      status: stageStatus({ completed: filesCompleted, running: filesStarted, failed: options.failedFiles > 0 && !filesStarted }),
    },
    {
      key: 'synthesis',
      label: '关系、约束与总体认知',
      detail: '汇总跨文件关系、权威事实和约束',
      status: stageStatus({ completed: synthesisCompleted, running: synthesisStarted }),
    },
    {
      key: 'qdi',
      label: 'QDI 深入调查',
      detail: '逐项核实阻塞建模的问题',
      status: stageStatus({ completed: qdiCompleted || moduleCompleted, running: qdiStarted }),
    },
    {
      key: 'publish',
      label: '认知产物写入',
      detail: '生成数据认知报告与数据说明',
      status: stageStatus({ completed: moduleCompleted, running: publishStarted }),
    },
  ]

  const weights = [10, 42, 16, 27, 5]
  let percent = 0
  stages.forEach((stage, index) => {
    if (stage.status === 'completed') percent += weights[index]
    else if (stage.status === 'running') {
      if (stage.key === 'files' && selectedFiles > 0) percent += weights[index] * Math.min(1, completedFiles / selectedFiles)
      else percent += weights[index] * 0.35
    }
  })

  const activePrompts = activePromptCounts(events)
  const activePromptEntry = [...activePrompts.entries()].reverse().find(([, count]) => count > 0)
  const latest = events.at(-1)
  let activityLabel = activePromptEntry ? activityFromPrompt(activePromptEntry[0], activePromptEntry[1]) : ''
  if (!activityLabel && qdiStarted && !qdiCompleted) {
    const latestQdi = latestEvent(events, (row) => componentName(row) === 'module.data_cognition.investigator')
    const event = eventName(latestQdi ?? {})
    if (event === 'SCRIPT_COMPLETED') activityLabel = 'QDI 脚本已执行，正在分析输出并形成下一步判断'
    else if (event === 'SCRIPT_FAILED') activityLabel = 'QDI 脚本执行失败，正在修复或切换调查动作'
    else if (event === 'QUESTION_STARTED') activityLabel = 'QDI 正在调查当前问题'
    else activityLabel = 'QDI 正在逐项核实数据与任务定义中的关键问题'
  }
  if (!activityLabel && synthesisStarted && !synthesisCompleted) activityLabel = '正在推断跨文件关系并提取权威事实与约束'
  if (!activityLabel && filesStarted && !filesCompleted) activityLabel = '正在读取文件并生成结构化认知卡片'
  if (!activityLabel && moduleCompleted) activityLabel = '数据总体认知已完成'
  if (!activityLabel) activityLabel = '等待数据认知开始'

  const status: CognitionStageStatus = moduleFailed ? 'failed' : moduleCompleted ? 'completed' : events.length > 0 ? 'running' : 'pending'
  return {
    status,
    statusLabel: status === 'completed' ? '已完成' : status === 'failed' ? '存在异常' : status === 'running' ? '进行中' : '等待开始',
    activityLabel,
    percent: Math.max(0, Math.min(100, Math.round(percent))),
    selectedFiles,
    completedFiles,
    activeLlmCalls: [...activePrompts.values()].reduce((sum, count) => sum + count, 0),
    lastUpdate: localTime(latest?.ts),
    stages,
  }
}
