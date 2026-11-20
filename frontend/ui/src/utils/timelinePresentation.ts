type TimelineEvent = Record<string, unknown>

const COMPONENT_LABELS: [string, string][] = [
  ['module.data_cognition.file_artifact', '生成文件说明'],
  ['module.data_cognition.investigator', '检查业务问题'],
  ['module.data_cognition.relations', '分析数据表关联'],
  ['module.data_cognition.parallel', '读取数据文件'],
  ['module.data_cognition.image_dir', '识别图像数据'],
  ['module.data_cognition.authority', '核对来源依据'],
  ['module.data_cognition.constraints', '整理业务约束'],
  ['module.data_cognition', '理解数据'],
  ['module.task_definition.evaluation_contract', '整理评价标准'],
  ['module.task_definition.problem_paradigm', '识别问题类型'],
  ['module.task_definition.description_sections', '检查任务说明'],
  ['module.task_definition.intent', '整理任务目标'],
  ['module.task_definition', '整理任务合同'],
  ['autoreport.collector', '整理研发证据'],
  ['autoreport.analyzer', '核对报告材料'],
  ['autoreport.generator', '生成报告'],
  ['stage.p1.image', '识别图像内容'],
  ['stage.p1', '读取输入文件'],
  ['agent.file_cognition', '分析输入文件'],
  ['agent.predict_split_generator', '生成数据切分方案'],
  ['llm.client', 'AI 分析'],
  ['pipeline', '任务流程'],
  ['workflow', '任务流程'],
  ['checker', '检查结果'],
  ['automl', '搜索方案'],
  ['algoevolve', '搜索方案'],
]

const EVENT_LABELS: Record<string, string> = {
  READING_FILE: '开始读取数据文件',
  READ_COMPLETED: '数据文件已读取',
  READ_FAILED: '读取数据文件失败',
  GENERATED_FILE: '分析材料已生成',
  RUN_COMPLETED: '任务已完成',
  REQUEST_STARTED: 'AI 分析已开始',
  REQUEST_COMPLETED: 'AI 分析已完成',
  SCRIPT_COMPLETED: '检查脚本已完成',
  SCRIPT_FAILED: '检查脚本失败',
  QUESTION_COMPLETED: '问题调查已完成',
  SOURCE_RETRIEVED: '已找到参考资料',
  SKIPPED: '此步骤已跳过',
  ACTION_FAILED: '操作失败',
  ACTION_COMPLETED: '操作已完成',
}

const STATUS_LABELS: Record<string, string> = {
  running: '进行中',
  started: '已启动',
  activated: '进行中',
  completed: '已完成',
  success: '已完成',
  failed: '失败',
  error: '失败',
  warning: '需留意',
  retrying: '正在重试',
  skipped: '已跳过',
  created: '已创建',
}

function asRecord(value: unknown): TimelineEvent {
  return value && typeof value === 'object' && !Array.isArray(value) ? (value as TimelineEvent) : {}
}

function text(value: unknown): string {
  return typeof value === 'string' ? value.trim() : ''
}

export function phaseLabel(value: unknown): string {
  const phase = text(value).toLowerCase().replaceAll('-', '_')
  if (['autorealize', 'auto_realize', 'data_cognition'].includes(phase)) return '数据理解'
  if (['task_definition', 'definition', 'review_repair'].includes(phase)) return '任务定义'
  if (['automl', 'auto_ml', 'search'].includes(phase)) return '方案搜索'
  if (['report', 'auto_report', 'delivery'].includes(phase)) return '报告与交付'
  if (['starting', 'resuming'].includes(phase)) return '准备运行'
  if (phase === 'completed') return '已完成'
  if (phase === 'running') return '运行中'
  return '等待更新'
}

export function activeProcessStep(phaseValue: unknown, componentValue: unknown) {
  const phase = text(phaseValue).toLowerCase().replaceAll('-', '_')
  const component = text(componentValue).toLowerCase()

  if (['automl', 'auto_ml', 'search'].includes(phase)) return 'automl'
  if (['report', 'auto_report', 'delivery'].includes(phase)) return 'report'
  if (
    component.includes('task_definition')
    || component.includes('stage.p2')
    || ['task_definition', 'definition', 'review_repair'].includes(phase)
  ) return 'task_definition'
  if (
    component.includes('data_cognition')
    || component.includes('file_cognition')
    || component.includes('stage.p1')
    || ['autorealize', 'auto_realize', 'data_cognition'].includes(phase)
  ) return 'data_cognition'
  return null
}

export function componentLabel(value: unknown, phase?: unknown): string {
  const component = text(value).toLowerCase()
  for (const [prefix, label] of COMPONENT_LABELS) {
    if (component === prefix || component.startsWith(`${prefix}.`)) return label
  }
  if (component.startsWith('module.')) return phaseLabel(phase)
  if (component.startsWith('agent.')) return '算法分析'
  if (component.startsWith('autoreport.')) return '报告与交付'
  return phaseLabel(phase)
}

function safeMessage(value: unknown): string {
  const message = text(value)
  if (!message || message.length > 240) return ''
  if (/^[\[{]/.test(message) || /traceback|stack trace/i.test(message)) return ''
  if (/[A-Za-z]:[\\/]|\/(?:home|workspace|tmp)\//i.test(message)) return ''
  return message
}

export function timelineEventTitle(event: TimelineEvent, phase?: unknown): string {
  const message = safeMessage(event.message)
  if (message) return message

  const name = text(event.event).toUpperCase()
  if (EVENT_LABELS[name]) return EVENT_LABELS[name]
  const component = componentLabel(event.component, phase)
  if (name === 'ACTIVATED' || name === 'STARTED' || name === 'RUNNING') return `${component}中`
  if (name === 'COMPLETED' || name.endsWith('_COMPLETED') || name.endsWith('_GENERATED')) {
    return `${component}已完成`
  }
  if (name === 'FAILED' || name.endsWith('_FAILED') || name.includes('ERROR')) return `${component}失败`
  return '运行状态已更新'
}

function fileName(value: unknown): string {
  const path = text(value).replaceAll('\\', '/').replace(/\/+$/, '')
  return path ? path.split('/').at(-1) || '' : ''
}

export function timelineEventSummary(event: TimelineEvent): string {
  const fields = asRecord(event.fields)
  const parts: string[] = []
  const file = fileName(fields.file ?? fields.source)
  if (file) parts.push(file)

  const counts: [string, string][] = [
    ['rows', '行'],
    ['files', '个文件'],
    ['tables', '张表'],
    ['relations', '条关联'],
    ['questions', '个问题'],
    ['workers', '个并行任务'],
  ]
  for (const [key, unit] of counts) {
    const count = fields[key]
    if (typeof count === 'number' && Number.isFinite(count)) parts.push(`${count.toLocaleString('zh-CN')}${unit}`)
  }

  const seconds = fields.seconds
  if (typeof seconds === 'number' && Number.isFinite(seconds)) parts.push(`耗时 ${seconds.toFixed(1)} 秒`)
  if (parts.length) return parts.join(' · ')
  if (eventTone(event) === 'failed') return '展开技术详情查看错误信息。'
  return ''
}

export function eventStatusLabel(event: TimelineEvent): string {
  const status = text(event.status).toLowerCase()
  if (text(event.severity).toLowerCase() === 'error') return '失败'
  if (text(event.severity).toLowerCase() === 'warning') return '需留意'
  return STATUS_LABELS[status] ?? '已记录'
}

export function eventTone(event: TimelineEvent): 'running' | 'success' | 'warning' | 'failed' | 'info' {
  const status = text(event.status).toLowerCase()
  const severity = text(event.severity).toLowerCase()
  if (['failed', 'error'].includes(status) || severity === 'error') return 'failed'
  if (status === 'running' || status === 'started') return 'running'
  if (severity === 'warning' || status === 'warning') return 'warning'
  if (status === 'completed' || status === 'success') return 'success'
  return 'info'
}

export function timelineEventTime(value: unknown): string {
  if (value == null || value === '') return '时间未知'
  const numeric = typeof value === 'number' ? value : Number(value)
  const timestamp = Number.isFinite(numeric)
    ? Math.abs(numeric) < 100_000_000_000
      ? numeric * 1000
      : numeric
    : typeof value === 'string'
      ? Date.parse(value)
      : Number.NaN
  if (!Number.isFinite(timestamp)) return '时间未知'
  const date = new Date(timestamp)
  if (!Number.isFinite(date.getTime())) return '时间未知'
  return date.toLocaleString('zh-CN', { hour12: false })
}
