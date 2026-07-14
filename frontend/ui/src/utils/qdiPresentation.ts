export type QdiQuestionView = {
  id: string
  question: string
  status: string
  category: string
  priority: string
  confidence: string
  whyBlocking: string
  answer: string
  unresolvedReason: string
  remainingUncertainty: string
  evidence: string[]
  downstreamNotes: string[]
  usedFiles: string[]
  depth: number
}

export type QdiLiveProgress = {
  started: boolean
  completed: boolean
  active: boolean
  activityLabel: string
  currentQuestionId: string
  currentAction: string
  actionRound: number
  queuedQuestions: number
  actionDecisions: number
  scriptSuccesses: number
  scriptFailures: number
  repairCalls: number
  lastUpdate: string
  eventQuestions: QdiQuestionView[]
}

export function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {}
}

export function asArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : []
}

export function textValue(value: unknown): string {
  if (typeof value === 'string') return value.trim()
  if (typeof value === 'number' || typeof value === 'boolean') return String(value)
  const record = asRecord(value)
  for (const key of ['text', 'summary', 'fact', 'message', 'evidence', 'note']) {
    const candidate = String(record[key] ?? '').trim()
    if (candidate) return candidate
  }
  if (Object.keys(record).length > 0) {
    try {
      return JSON.stringify(record)
    } catch {
      return String(value ?? '')
    }
  }
  return ''
}

export function textList(value: unknown): string[] {
  return asArray(value).map(textValue).filter(Boolean)
}

function mergeNonEmpty(target: Record<string, unknown>, source: Record<string, unknown>) {
  for (const [key, value] of Object.entries(source)) {
    if (value === undefined || value === null || value === '') continue
    if (Array.isArray(value) && value.length === 0) continue
    target[key] = value
  }
}

export function normalizeQdiQuestions(reportValue: unknown): QdiQuestionView[] {
  const report = asRecord(reportValue)
  const merged = new Map<string, Record<string, unknown>>()
  const order: string[] = []

  const addRows = (value: unknown, prefix: string) => {
    asArray(value).forEach((raw, index) => {
      const row = asRecord(raw)
      if (Object.keys(row).length === 0) return
      const id = String(row.question_id ?? row.id ?? `${prefix}-${index + 1}`).trim()
      if (!merged.has(id)) {
        merged.set(id, {})
        order.push(id)
      }
      mergeNonEmpty(merged.get(id)!, row)
    })
  }

  addRows(report.questions, 'question')
  addRows(report.question_records, 'record')
  addRows(report.answers, 'answer')

  const unresolvedRows = asArray(report.unresolved_questions)
  unresolvedRows.forEach((raw, index) => {
    const row = asRecord(raw)
    const rawText = textValue(raw)
    const id = String(row.question_id ?? row.id ?? '').trim()
    const matchedId = id || order.find((candidate) => {
      const existing = merged.get(candidate) ?? {}
      return rawText && rawText === String(existing.question ?? '').trim()
    })
    const targetId = matchedId || `unresolved-${index + 1}`
    if (!merged.has(targetId)) {
      merged.set(targetId, {})
      order.push(targetId)
    }
    mergeNonEmpty(merged.get(targetId)!, row)
    const target = merged.get(targetId)!
    if (!target.question && rawText) target.question = rawText
    if (!target.status) target.status = 'unresolved'
    if (!target.unresolved_reason && rawText !== target.question) target.unresolved_reason = rawText
  })

  return order.map((id) => {
    const row = merged.get(id) ?? {}
    const answer = String(row.answer ?? row.short_answer ?? '').trim()
    const status = String(row.status ?? (answer ? 'resolved' : 'pending')).trim().toLowerCase()
    const depth = Number(row.depth ?? 0)
    return {
      id,
      question: String(row.question ?? id).trim(),
      status,
      category: String(row.category ?? 'other').trim(),
      priority: String(row.priority ?? 'medium').trim(),
      confidence: String(row.confidence ?? '').trim(),
      whyBlocking: String(row.why_blocking ?? '').trim(),
      answer,
      unresolvedReason: String(row.unresolved_reason ?? '').trim(),
      remainingUncertainty: String(row.remaining_uncertainty ?? '').trim(),
      evidence: textList(row.evidence),
      downstreamNotes: textList(row.downstream_notes),
      usedFiles: textList(row.used_files ?? row.candidate_files),
      depth: Number.isFinite(depth) ? depth : 0,
    }
  })
}

export function isResolvedQdiStatus(status: string) {
  return ['resolved', 'answered', 'completed', 'complete', 'done'].includes(status.toLowerCase())
}

function eventLocalTime(value: unknown) {
  const date = new Date(String(value ?? ''))
  if (Number.isNaN(date.getTime())) return ''
  return date.toLocaleTimeString('zh-CN', { hour12: false })
}

export function deriveQdiLiveProgress(eventsValue: unknown, reportValue: unknown): QdiLiveProgress {
  const events = asArray(eventsValue).map(asRecord).filter((row) => Object.keys(row).length > 0)
  const report = asRecord(reportValue)
  const progress = asRecord(report.progress)
  const questionMap = new Map<string, QdiQuestionView>()
  let started = false
  let completed = false
  let currentQuestionId = String(progress.current_question_id ?? '')
  let currentAction = String(progress.current_action ?? '')
  let actionRound = Number(progress.action_round ?? 0) || 0
  let actionSelectedEvents = 0
  let actionCallCompletions = 0
  let scriptSuccesses = 0
  let scriptFailures = 0
  let repairCalls = 0
  let activeQdiCalls = 0
  let lastQdiEvent: Record<string, unknown> = {}

  for (const row of events) {
    const component = String(row.component ?? '')
    const event = String(row.event ?? '').toUpperCase()
    const fields = asRecord(row.fields)
    const prompt = String(fields.prompt ?? '')
    const isQdiPrompt = prompt.startsWith('question_investigator_')
    if (component === 'module.data_cognition.investigator') {
      started = true
      lastQdiEvent = row
      if (event === 'COMPLETED') completed = true
      if (event === 'SCRIPT_COMPLETED') scriptSuccesses += 1
      if (event === 'SCRIPT_FAILED') scriptFailures += 1
      if (event === 'ACTION_SELECTED') {
        actionSelectedEvents += 1
        currentQuestionId = String(fields.question_id ?? currentQuestionId)
        currentAction = String(fields.action ?? currentAction)
        actionRound = Number(fields.action_round ?? actionRound) || actionRound
      }
      if (event === 'QUESTION_STARTED') currentQuestionId = String(fields.question_id ?? currentQuestionId)
      const qid = String(fields.question_id ?? '').trim()
      if (qid && ['QUESTION_QUEUED', 'AUTO_ENTITY_ALIAS_QUESTION_QUEUED', 'QUESTION_STARTED', 'QUESTION_COMPLETED'].includes(event)) {
        const existing = questionMap.get(qid)
        const questionStatus = event === 'QUESTION_COMPLETED'
          ? String(fields.question_status ?? 'completed')
          : event === 'QUESTION_STARTED' ? 'investigating' : existing?.status ?? 'pending'
        questionMap.set(qid, {
          id: qid,
          question: String(fields.question ?? existing?.question ?? `调查问题 ${qid}`),
          status: questionStatus,
          category: String(fields.category ?? existing?.category ?? 'other'),
          priority: String(fields.priority ?? existing?.priority ?? 'medium'),
          confidence: '',
          whyBlocking: '',
          answer: String(fields.short_answer ?? existing?.answer ?? ''),
          unresolvedReason: String(fields.unresolved_reason ?? existing?.unresolvedReason ?? ''),
          remainingUncertainty: '',
          evidence: [],
          downstreamNotes: [],
          usedFiles: [],
          depth: Number(fields.depth ?? existing?.depth ?? 0) || 0,
        })
      }
    }
    if (component === 'llm.client' && isQdiPrompt) {
      started = true
      lastQdiEvent = row
      if (event === 'REQUEST_STARTED') activeQdiCalls += 1
      if (['REQUEST_COMPLETED', 'REQUEST_FAILED', 'PARSE_RETRYING'].includes(event)) {
        activeQdiCalls = Math.max(0, activeQdiCalls - 1)
      }
      if (event === 'REQUEST_COMPLETED' && prompt === 'question_investigator_action') actionCallCompletions += 1
      if (event === 'REQUEST_COMPLETED' && prompt === 'question_investigator_script_repair') repairCalls += 1
    }
  }

  const normalizedQuestions = normalizeQdiQuestions(report)
  for (const question of normalizedQuestions) questionMap.set(question.id, question)
  if (normalizedQuestions.length > 0) started = true
  if (!progress.phase && normalizedQuestions.length > 0 && normalizedQuestions.every((question) => {
    return !['pending', 'investigating', 'in_progress', 'refined'].includes(question.status)
  })) completed = true
  const stepResults = asArray(report.step_results).map(asRecord)
  if (stepResults.length > 0) {
    scriptSuccesses = stepResults.filter((row) => String(row.status ?? '').toLowerCase() === 'completed').length
    scriptFailures = stepResults.filter((row) => String(row.status ?? '').toLowerCase() === 'failed').length
  }
  const actionHistory = asArray(report.action_history)
  const actionDecisions = actionHistory.length > 0
    ? actionHistory.length
    : Math.max(actionSelectedEvents, actionCallCompletions)

  const phase = String(progress.phase ?? '')
  if (phase) started = true
  if (phase === 'completed') completed = true
  const active = started && !completed && (activeQdiCalls > 0 || phase !== 'completed')
  let activityLabel = String(report.summary ?? '').trim()
  if (active) {
    if (phase === 'planning') activityLabel = '正在根据总体数据认知规划调查问题'
    else if (phase === 'deciding_action') activityLabel = `正在决定问题 ${currentQuestionId || '-'} 的下一步调查动作`
    else if (phase === 'executing_action') activityLabel = `正在执行 ${currentAction || '调查动作'}`
    else if (phase === 'script_failed') activityLabel = '只读脚本失败，正在修复或调整调查方式'
    else if (phase === 'script_completed') activityLabel = '只读脚本已完成，正在分析输出'
    else {
      const latestPrompt = String(asRecord(lastQdiEvent.fields).prompt ?? '')
      if (latestPrompt === 'question_investigator_initial_questions') activityLabel = '正在规划调查问题'
      else if (latestPrompt === 'question_investigator_script_repair') activityLabel = '正在修复只读探查脚本'
      else if (latestPrompt === 'question_investigator_action') activityLabel = '正在分析当前证据并选择下一步动作'
      else activityLabel = currentQuestionId ? `正在调查问题 ${currentQuestionId}` : 'QDI 调查正在进行'
    }
  }
  if (!activityLabel) activityLabel = completed ? 'QDI 调查已完成' : '等待 QDI 开始'

  return {
    started,
    completed,
    active,
    activityLabel,
    currentQuestionId,
    currentAction,
    actionRound,
    queuedQuestions: Number(progress.total_questions ?? questionMap.size) || questionMap.size,
    actionDecisions,
    scriptSuccesses,
    scriptFailures,
    repairCalls,
    lastUpdate: eventLocalTime(lastQdiEvent.ts),
    eventQuestions: [...questionMap.values()],
  }
}
