export function summarizeGoal(value: unknown, maxLength = 180): string {
  const text = String(value ?? '').replace(/\s+/g, ' ').trim()
  if (!text) return '未填写研发目标'
  if (text.length <= maxLength) return text
  const sentence = text.slice(0, maxLength).match(/^.*?[。！？!?；;]/)?.[0]?.trim()
  if (sentence && sentence.length >= Math.min(24, maxLength * 0.45)) return sentence
  return `${text.slice(0, maxLength).trimEnd()}…`
}

export function formatDate(value: unknown): string {
  if (value == null || value === '') return '时间未知'
  const numeric = typeof value === 'number' ? value : Number(value)
  const timestamp = Number.isFinite(numeric)
    ? Math.abs(numeric) < 100_000_000_000 ? numeric * 1000 : numeric
    : typeof value === 'string' ? Date.parse(value) : Number.NaN
  if (!Number.isFinite(timestamp)) return '时间未知'
  const parsed = new Date(timestamp)
  if (!Number.isFinite(parsed.getTime())) return '时间未知'
  return parsed.toLocaleString('zh-CN', { hour12: false })
}

export function projectDescription(value: unknown): string {
  const description = String(value ?? '').trim()
  if (!description || description === '从已有任务登记的数据项目；运行证据取自任务实际产物。') {
    return '本地数据项目'
  }
  return description
}

export function humanApiError(detail: unknown, status: number): string {
  const fallback = status === 422 ? '输入信息不完整或格式不正确，请检查后重试。'
    : status === 404 ? '内容当前不可用，请刷新后重试。'
    : status === 401 || status === 403 ? '当前连接没有访问权限，请检查连接设置。'
    : `请求未完成（${status}），请稍后重试。`
  if (typeof detail === 'string') {
    const text = detail.trim()
    if (/^[{[]/.test(text)) {
      try { return humanApiError(JSON.parse(text), status) } catch { return fallback }
    }
    return text || fallback
  }
  if (Array.isArray(detail)) {
    const names: Record<string, string> = {
      name: '名称', title: '标题', task_name: '任务名称', description: '用途说明',
      input_root: '数据目录', output_root: '结果目录', text: '需求', question: '问题',
      goal: '研发目标', time_limit_secs: '搜索时间', timeout_seconds: '执行时间',
      cpu_cores: '处理器数量', memory_limit_gb: '内存', csv_path: '数据文件',
      data_json: '输入数据', input_schema: '输入要求', steps: '调用顺序',
      confirm: '确认选项', apiKey: '访问密钥', baseUrl: '服务地址',
    }
    const lines = detail.slice(0, 3).map(value => {
      const item = record(value), location = Array.isArray(item.loc) ? item.loc : []
      const key = [...location].reverse().find(part => typeof part === 'string' && names[part])
      const name = key ? names[String(key)] : '输入'
      const type = String(item.type || '')
      return name + (type === 'missing' ? '尚未填写。'
        : /too_short|string_type|list_type|dict_type|parsing/.test(type) ? '为空或格式不正确。'
        : /too_long/.test(type) ? '内容过长，请精简后重试。'
        : /greater_than|less_than/.test(type) ? '超出允许范围，请调整后重试。'
        : '格式不符合要求，请检查后重试。')
    })
    return [...new Set(lines)].join('') || fallback
  }
  const object = record(detail)
  if (typeof object.message === 'string') return humanApiError(object.message, status)
  if (object.detail && object.detail !== detail) return humanApiError(object.detail, status)
  return fallback
}

const taskStatusLabels: Record<string, string> = {
  idle: '待启动',
  starting: '准备启动',
  running: '运行中',
  completed: '已完成',
  failed: '需要处理',
  stopped: '已停止',
  interrupted: '已中断',
  interrupted_resumable: '已中断，可恢复',
  interrupted_incomplete: '已中断，检查点不完整',
  report_completed: '报告已完成',
  automl_completed: '方案搜索已完成',
  autorealize_completed: '数据分析已完成',
}

const phaseLabels: Record<string, string> = {
  config: '待配置',
  starting: '准备启动',
  autorealize: '数据理解',
  autorealize_completed: '数据理解已完成',
  automl: '方案搜索',
  automl_completed: '方案搜索已完成',
  final_evaluation_running: '独立评估',
  final_evaluation_completed: '独立评估已完成',
  report: '报告与交付',
  report_generating: '生成报告',
  report_completed: '报告与交付',
  completed: '流程完成',
  review_repair: '合同审查',
  review_repair_failed: '合同审查需处理',
}

export function humanTaskStatus(value: unknown): string {
  const key = String(value ?? '').trim().toLowerCase()
  return taskStatusLabels[key] || (key ? '状态更新中' : '状态未知')
}

export function humanPhase(value: unknown): string {
  const key = String(value ?? '').trim().toLowerCase()
  if (phaseLabels[key]) return phaseLabels[key]
  if (key.includes('report')) return '报告与交付'
  if (key.includes('automl') || key.includes('search')) return '方案搜索'
  if (key.includes('autorealize') || key.includes('cognition')) return '数据理解'
  return key ? '处理中' : '等待开始'
}

export function humanFinalEvaluationStatus(value: unknown): string {
  const key = String(value ?? '').trim().toLowerCase()
  return ({
    not_started: '尚未进行独立评估',
    running: '正在进行独立评估',
    completed: '独立评估已完成',
    failed: '独立评估失败',
    unavailable: '独立评估暂不可读',
    no_eligible_candidate: '目前没有符合交付条件的方案',
    invalid_result_fields: '评估结果需要修正',
    pending: '等待独立复核',
  } as Record<string, string>)[key] || (key ? '独立评估状态已记录' : '尚未进行独立评估')
}

export function humanReportStatus(value: unknown): string {
  const key = String(value ?? '').trim().toLowerCase()
  return ({
    not_ready: '报告尚未生成',
    not_started: '报告尚未生成',
    ready: '报告已生成，等待审核',
    generating: '正在生成报告',
    failed: '报告生成失败',
    blocked: '报告交付需要处理',
  } as Record<string, string>)[key] || (key ? '报告状态已记录' : '报告尚未生成')
}

export function candidateReadiness(node: Record<string, any>): {
  label: string
  tone: 'success' | 'warning' | 'neutral'
} {
  // Historical runtime_ok also incorporates review rejection, not only exceptions.
  if (node.is_buggy === true || node.runtime_ok === false) return { label: '需要修正', tone: 'warning' }
  if (node.delivery_certified === true) return { label: '已通过交付检查', tone: 'success' }
  if (node.delivery_ready === true || node.artifact_ready === true) return { label: '可继续整理交付', tone: 'success' }
  if (node.is_valid === true || node.search_eligible === true) return { label: '已完成评估', tone: 'neutral' }
  return { label: '等待检查', tone: 'neutral' }
}

export function inputSummary(step: {
  input_mode?: string
  input_summary?: {
    source_count?: number
    row_count?: number | null
    first_observation?: string | null
    last_observation?: string | null
    cutoff?: string | null
  }
}): string[] {
  const details = step.input_summary
  if (!details?.source_count) {
    return [step.input_mode === 'previous' ? '接收上一环节结果' : step.input_mode === 'project' ? '使用本地项目数据' : '使用本次提交的输入']
  }
  const parts = [`本地项目数据 · ${details.source_count} 个数据源`]
  if (typeof details.row_count === 'number') parts[0] += ` · ${details.row_count.toLocaleString('zh-CN')} 条记录`
  const range = details.first_observation || details.last_observation
    ? `观测范围：${details.first_observation || '未知'} 至 ${details.last_observation || '未知'}`
    : ''
  const cutoff = details.cutoff ? `数据截止：${details.cutoff}` : ''
  const provenance = [range, cutoff].filter(Boolean).join(' · ')
  if (provenance) parts.push(provenance)
  return parts
}

export const fieldNames: Record<string, string> = {
  prediction_cutoff: '观测截止时间', prediction_time: '预测时间', predicted_al_n: '预测压滤液 Al(N)',
  prediction: '预测值', predictions: '预测结果', actual: '实际值', answer: '结果', value: '数值',
  unit: '单位', steam_advice: '蒸汽流量参考', recommended_flow_kg_h: '参考流量（kg/h）',
  recommended_steam_flow: '参考蒸汽流量', current_flow_kg_h: '当前流量（kg/h）',
  support_count: '参考样本数', support_sample_count: '参考样本数', interval_kg_h: '参考区间（kg/h）',
  basis: '参考依据', caveats: '需复核事项', status: '状态', reason: '依据', limitations: '适用限制',
  history: '历史观测', weather: '天气观测', time: '时间', timestamp: '时间', rows: '记录数',
  mae: '平均绝对误差（MAE）', rmse: '均方根误差（RMSE）', r2: '拟合优度（R²）',
  accuracy: '准确率', f1: 'F1 分数', baseline_mae: '基线 MAE', model_mae: '模型 MAE',
  passed: '通过', failed: '失败', ok: '可用', unavailable: '暂不可用', review_required: '需人工复核',
}
export function fieldName(key: string): string {
  return fieldNames[key] || fieldNames[key.toLowerCase()] || key.replaceAll('_', ' ')
}
export function scalar(value: unknown): string {
  if (value == null || value === '') return '未提供'
  if (typeof value === 'boolean') return value ? '是' : '否'
  if (typeof value === 'number') return Number.isFinite(value) ? Number(value.toPrecision(7)).toLocaleString('zh-CN', { maximumFractionDigits: 7 }) : '无有效数值'
  const text = String(value)
  return fieldNames[text] || text
}
export function record(value: unknown): Record<string, any> {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, any> : {}
}

/** Decode protocol wrappers; never turn arbitrary JSON or source code into UI prose. */
export function humanNarrative(value: unknown, depth = 0): string {
    if (depth > 3 || value == null) return ''
    if (typeof value === 'string') {
      const text = value.trim()
      if (!text) return ''
      if (/^[\[{]/.test(text)) {
        try { return humanNarrative(JSON.parse(text), depth + 1) } catch { return '' }
      }
      if (/^(?:def |import |from \w+ import|@@ |diff --git|```(?:python|json))/m.test(text)) return ''
      return text.replace(/^Plan:\s*/i, '')
    }
    if (typeof value === 'object' && !Array.isArray(value)) {
      const result = record(value)
      for (const key of ['human_insight', 'summary', 'analysis', 'reason', 'plan', 'error', 'message']) {
        const text = humanNarrative(result[key], depth + 1)
        if (text) return text
      }
    }
    return ''
}
export function candidatePlan(node: Record<string, any>): string {
  return humanNarrative(node.plan) || '该候选没有可读的方案说明，可在技术详情中查看源码。'
}
/** Candidate output is a machine protocol; prefer the review intended for readers. */
export function candidateSummary(node: Record<string, any>): string {
  const text = humanNarrative(node.insight) || humanNarrative(node.llm_insight) || humanNarrative(node.result)
  if (text) return text
  return node.is_buggy ? '方案检查未通过，可查看详情。' : node.metric != null ? '已完成开发集评估。' : '正在等待评估结果。'
}

export interface SummaryItem { label: string; value: string }

export function taskResourceSummary(value: unknown): string {
  const resources = record(value)
  const parts: string[] = []
  if (typeof resources.cpu_cores === 'number') parts.push(`${resources.cpu_cores} 核处理器`)
  if (typeof resources.memory_limit_gb === 'number') parts.push(resources.memory_limit_gb > 0 ? `${resources.memory_limit_gb} GB 内存上限` : '内存不限额')
  const accelerator = resources.accelerator_mode
  parts.push(accelerator === 'all' ? '使用全部加速设备' : accelerator === 'selected' ? '使用指定加速设备' : accelerator === 'none' ? '仅使用 CPU' : '加速设备未配置')
  return parts.join(' · ')
}

export function webResearchSummary(enabled: boolean, value: unknown): SummaryItem[] | null {
  if (!enabled) return null
  const metrics = record(value)
  const status = String(metrics.status || 'not_started').trim().toLowerCase()
  const search = record(metrics.search)
  const attempts = Array.isArray(metrics.fetch_attempts) ? metrics.fetch_attempts : []
  const accepted = finiteNumber(search.accepted_count)
  const elapsed = finiteNumber(metrics.elapsed_ms)
  const labels: Record<string, string> = {
    started: '正在检索公开资料',
    success: accepted ? `找到 ${accepted} 条公开参考资料` : '已检索公开资料',
    cache_hit: '复用了已缓存的公开资料',
    no_relevant_results: '没有找到可用的公开资料，方案搜索继续',
    error: '网页检索暂不可用，方案搜索继续',
    skipped: '未执行网页检索，方案搜索继续',
    cache_join_miss: '同一检索正在由其他任务处理，方案搜索继续',
    not_started: '网页检索尚未开始',
  }
  const rows: SummaryItem[] = [
    { label: '状态', value: labels[status] || '网页检索状态已记录' },
  ]
  if (elapsed !== undefined && elapsed > 0) rows.push({ label: '耗时', value: `${(elapsed / 1000).toFixed(1)} 秒` })
  const fetched = attempts.filter((row) => record(row).status === 'success').length
  if (fetched > 0) rows.push({ label: '已读取网页', value: String(fetched) })
  const hosts = Array.isArray(search.source_hosts)
    ? search.source_hosts.filter((host): host is string => typeof host === 'string' && host.length > 0).slice(0, 5)
    : []
  if (hosts.length > 0) rows.push({ label: '来源网站', value: hosts.join(' · ') })
  return rows
}

function finiteNumber(value: unknown): number | undefined {
  return typeof value === 'number' && Number.isFinite(value) && value >= 0 ? value : undefined
}

const artifactLabels: Record<string, string> = {
  data_cognition_report: '数据理解记录',
  question_investigation_report: '问题调查记录',
  task_definition_report: '任务定义记录',
  main_task_protocol: '任务执行约定',
  evaluation_contract_report: '评价约定',
  artifact_consistency_report: '产物一致性检查',
  automl_context_pack: '方案搜索上下文',
}

export function humanArtifactLabel(value: unknown): string {
  const key = String(value ?? '').trim()
  return artifactLabels[key] || (key ? key.replaceAll('_', ' ') : '系统记录')
}

export function humanSnapshotError(value: unknown): string {
  const errors = record(value)
  const entries = Object.entries(errors).filter(([, item]) => item != null && String(item).trim())
  if (!entries.length) return '部分任务信息暂时无法读取。'
  const labels: Record<string, string> = {
    auto_realize: '数据理解结果',
    auto_ml: '方案搜索结果',
    auto_report: '报告与交付结果',
    final_evaluation: '独立评估结果',
    delivery: '交付检查结果',
  }
  const names = entries.slice(0, 3).map(([key]) => labels[key] || '部分任务信息')
  return `${names.join('、')}暂时无法读取，请稍后重试。`
}

export function formatDuration(value: unknown): string {
  const seconds = finiteNumber(value)
  if (seconds === undefined) return '未记录'
  if (seconds < 60) return `${seconds.toFixed(1)} 秒`
  const minutes = Math.floor(seconds / 60)
  const remainder = Math.round(seconds % 60)
  return `${minutes} 分钟${remainder ? ` ${remainder} 秒` : ''}`
}

export function formatMetric(value: unknown): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) return '尚无指标'
  return Number(value.toPrecision(6)).toLocaleString('zh-CN', { maximumFractionDigits: 6 })
}

export function usageSummary(value: unknown): SummaryItem[] {
  const usage = record(value)
  const input = finiteNumber(usage.prompt_tokens ?? usage.input_tokens)
  const output = finiteNumber(usage.completion_tokens ?? usage.output_tokens)
  const cached = finiteNumber(usage.prompt_cache_hit_tokens ?? record(usage.prompt_tokens_details).cached_tokens ?? usage.cache_read_input_tokens)
  const items: SummaryItem[] = []
  if (input !== undefined) items.push({ label: '输入', value: `${input.toLocaleString('zh-CN')} tokens` })
  if (output !== undefined) items.push({ label: '输出', value: `${output.toLocaleString('zh-CN')} tokens` })
  if (cached !== undefined) items.push({ label: '模型输入缓存', value: input && cached <= input ? `${(cached / input * 100).toFixed(1)}%` : `${cached.toLocaleString('zh-CN')} tokens` })
  return items
}

export function resourceSummary(value: unknown): SummaryItem[] {
  const inventory = record(value), cpu = record(inventory.cpu), memory = record(inventory.memory)
  const logical = finiteNumber(cpu.logical_count), physical = finiteNumber(cpu.physical_count)
  const total = finiteNumber(memory.total_gb)
  const items: SummaryItem[] = [
    { label: '处理器', value: logical ? `${logical} 个逻辑核心${physical ? ` · ${physical} 个物理核心` : ''}` : '未检测到核心信息' },
    { label: '内存', value: total !== undefined ? `${total.toLocaleString('zh-CN', { maximumFractionDigits: 1 })} GB` : '未检测到内存信息' },
  ]
  const devices = Array.isArray(inventory.devices) ? inventory.devices : []
  for (const device of devices) {
    const gpu = record(device), mb = finiteNumber(gpu.memory_mb)
    items.push({ label: '加速设备', value: `${typeof gpu.name === 'string' ? gpu.name : '未命名设备'}${mb !== undefined ? ` · ${(mb / 1024).toFixed(1)} GB 显存` : ''}${gpu.runtime_available === false ? ' · 运行环境不可用' : ''}` })
  }
  if (!devices.length) items.push({ label: '加速设备', value: '未检测到，将使用 CPU' })
  return items
}
