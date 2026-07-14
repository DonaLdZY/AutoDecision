<script setup lang="ts">
import { computed } from 'vue'

type FileCognitionPayload = {
  json?: Record<string, unknown>
  markdown?: string
}

type ProbeActionView = {
  key: string
  action: string
  reason: string
  status: string
  columns: string[]
  conditions: unknown[]
  resultLines: string[]
  raw: unknown
}

type PlannerActionSpecView = {
  key: string
  action: string
  reason: string
  columns: string[]
  conditions: unknown[]
  groupBy: string[]
  aggregations: unknown[]
  dependentColumn: string
  limit: string
  raw: unknown
}

const props = defineProps<{
  path: string
  payload?: FileCognitionPayload | null
  isRoot?: boolean
}>()

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value) ? (value as Record<string, unknown>) : {}
}

function asArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : []
}

function asStringList(value: unknown): string[] {
  return asArray(value)
    .map((x) => String(x ?? '').trim())
    .filter(Boolean)
}

function compactJson(value: unknown) {
  try {
    return JSON.stringify(value ?? {}, null, 2)
  } catch {
    return String(value ?? '')
  }
}

function statusLabel(status: string) {
  if (status === 'completed') return '完成'
  if (status === 'failed') return '失败'
  if (status === 'pending') return '等待'
  if (status === 'running') return '运行中'
  return status || '-'
}

function actionLabel(action: string) {
  const labels: Record<string, string> = {
    preview_head: '预览表头切片',
    profile_numeric: '数值列画像',
    profile_categorical: '类别列画像',
    check_nulls: '缺失值检查',
    check_inf: '无穷或异常值检查',
    value_counts_topk: 'Top-K 取值分布',
    numeric_summary: '数值统计摘要',
    condition_ratio: '条件占比',
    filter_preview: '条件筛选预览',
    groupby_agg: '分组聚合',
    time_granularity: '时间粒度识别',
    uniqueness: '唯一性检查',
    functional_dependency: '函数依赖检查',
  }
  return labels[action] ?? action
}

function formatUnknown(value: unknown) {
  if (typeof value === 'string') return value
  if (typeof value === 'number' || typeof value === 'boolean') return String(value)
  if (value === null || value === undefined) return ''
  return compactJson(value)
}

const jsonPayload = computed(() => asRecord(props.payload?.json))
const metadata = computed(() => asRecord(jsonPayload.value.source_metadata))
const trace = computed(() => asRecord(metadata.value.cognition_trace))
const probePlan = computed(() => asRecord(metadata.value.probe_plan))
const hasPlannerPlan = computed(() => Object.keys(probePlan.value).length > 0)
const markdown = computed(() => String(props.payload?.markdown ?? ''))
const summary = computed(() => String(jsonPayload.value.summary ?? ''))
const role = computed(() => String(jsonPayload.value.role ?? trace.value.summary_role ?? '-'))
const keyColumns = computed(() => {
  const fromTrace = asStringList(trace.value.summary_key_columns)
  if (fromTrace.length > 0) return fromTrace
  return asStringList(jsonPayload.value.columns)
})
const fieldDescriptionCount = computed(() => {
  const semantics = asRecord(jsonPayload.value.column_semantics)
  const count = Object.keys(semantics).length
  if (count > 0) return count
  return Number(trace.value.summary_field_description_count ?? 0)
})
const focusColumns = computed(() => {
  const fromTrace = asStringList(trace.value.focus_columns)
  if (fromTrace.length > 0) return fromTrace
  return asStringList(probePlan.value.focus_columns)
})
const questionsToCheck = computed(() => {
  const fromTrace = asStringList(trace.value.questions_to_check)
  if (fromTrace.length > 0) return fromTrace
  return asStringList(probePlan.value.hypotheses)
})
const planningReason = computed(() => String(trace.value.planning_reason ?? probePlan.value.reason ?? ''))
const probeNeeded = computed(() => {
  if ('probe_needed' in trace.value) return Boolean(trace.value.probe_needed)
  if ('need_more_probe' in probePlan.value) return Boolean(probePlan.value.need_more_probe)
  return false
})
const plannedProbeActions = computed(() => asStringList(probePlan.value.probe_actions))
const plannerActionSpecs = computed<PlannerActionSpecView[]>(() => {
  const specs = asArray(probePlan.value.action_specs)
    .map((item, index) => {
      const row = asRecord(item)
      return {
        key: `${String(row.action ?? 'action')}-${index}`,
        action: String(row.action ?? 'unknown'),
        reason: String(row.reason ?? ''),
        columns: asStringList(row.columns),
        conditions: asArray(row.conditions),
        groupBy: asStringList(row.group_by),
        aggregations: asArray(row.aggregations),
        dependentColumn: String(row.dependent_column ?? ''),
        limit: row.limit === undefined ? '' : String(row.limit),
        raw: row,
      }
    })

  if (specs.length > 0) return specs

  return plannedProbeActions.value.map((action, index) => ({
    key: `${action}-${index}`,
    action,
    reason: '',
    columns: focusColumns.value,
    conditions: [],
    groupBy: [],
    aggregations: [],
    dependentColumn: '',
    limit: '',
    raw: { action },
  }))
})

function resultLines(summary: Record<string, unknown>) {
  const lines: string[] = []
  if (summary.rows_matched !== undefined && summary.rows_total !== undefined) {
    lines.push(`匹配行数: ${summary.rows_matched} / ${summary.rows_total}`)
  }
  if (summary.ratio !== undefined) lines.push(`占比: ${summary.ratio}`)
  if (summary.valid_datetime_count !== undefined) lines.push(`有效时间值: ${summary.valid_datetime_count}`)
  if (summary.groups_checked !== undefined) lines.push(`检查分组: ${summary.groups_checked}`)
  if (summary.violation_groups !== undefined) lines.push(`依赖违例分组: ${summary.violation_groups}`)
  if (summary.error) lines.push(`错误: ${summary.error}`)

  const warnings = asStringList(summary.warnings)
  if (warnings.length > 0) lines.push(`警告: ${warnings.slice(0, 3).join('; ')}`)

  const columns = asStringList(summary.columns)
  if (columns.length > 0) lines.push(`字段: ${columns.slice(0, 8).join(', ')}`)

  const valueCounts = asRecord(summary.value_counts)
  for (const [column, rows] of Object.entries(valueCounts).slice(0, 4)) {
    const top = asArray(rows)
      .map((row) => {
        const r = asRecord(row)
        return `${String(r.value ?? '')}(${String(r.count ?? '')})`
      })
      .filter(Boolean)
      .slice(0, 5)
      .join(', ')
    if (top) lines.push(`${column}: ${top}`)
  }

  const numericRows = asArray(summary.numeric_summary)
  for (const row of numericRows.slice(0, 4)) {
    const r = asRecord(row)
    const column = String(r.column ?? '')
    if (!column) continue
    lines.push(`${column}: mean=${r.mean ?? '-'}, std=${r.std ?? '-'}, min=${r.min ?? '-'}, max=${r.max ?? '-'}`)
  }

  if (summary.preview_rows !== undefined) lines.push(`预览行数: ${summary.preview_rows}`)
  if (summary.result_rows !== undefined) lines.push(`结果行数: ${summary.result_rows}`)
  return lines.length > 0 ? lines : ['已执行。']
}

const actions = computed<ProbeActionView[]>(() => {
  const traceActions = asArray(trace.value.actions)
  if (traceActions.length > 0) {
    return traceActions.map((item, index) => {
      const row = asRecord(item)
      const summaryRecord = asRecord(row.result_summary)
      return {
        key: String(row.result_key ?? `${row.action ?? 'action'}-${index}`),
        action: String(row.action ?? 'unknown'),
        reason: String(row.reason ?? ''),
        status: String(row.status ?? 'completed'),
        columns: asStringList(row.columns),
        conditions: asArray(row.conditions),
        resultLines: resultLines(summaryRecord),
        raw: row,
      }
    })
  }

  const resultKeys = asStringList(metadata.value.probe_result_keys)
  return [...plannedProbeActions.value, ...resultKeys].filter((x, index, arr) => arr.indexOf(x) === index).map((name, index) => ({
    key: `${name}-${index}`,
    action: name,
    reason: '',
    status: 'completed',
    columns: focusColumns.value,
    conditions: [],
    resultLines: ['旧任务未保存结构化 trace。'],
    raw: asRecord(metadata.value.probe_results)[name],
  }))
})

const rawTraceText = computed(() => {
  if (Object.keys(trace.value).length > 0) return compactJson(trace.value)
  const raw = {
    probe_plan: probePlan.value,
    probe_results: metadata.value.probe_results,
  }
  return compactJson(raw)
})
const rawPlannerText = computed(() => compactJson(probePlan.value))
</script>

<template>
  <article class="probe-panel">
    <header class="panel-header">
      <div>
        <p class="eyebrow">{{ isRoot ? '数据总认知' : '文件认知' }}</p>
        <h4>{{ path || '请选择左侧节点' }}</h4>
      </div>
      <span class="role-pill">{{ role }}</span>
    </header>

    <p v-if="summary" class="summary">{{ summary }}</p>

    <section v-if="payload" class="metric-grid">
      <div class="metric-card">
        <span>Planner 决策</span>
        <strong>{{ probeNeeded ? '需要追加探查' : '基础切片足够' }}</strong>
      </div>
      <div class="metric-card">
        <span>关键字段</span>
        <strong>{{ keyColumns.length }}</strong>
      </div>
      <div class="metric-card">
        <span>待验证假设</span>
        <strong>{{ questionsToCheck.length }}</strong>
      </div>
      <div class="metric-card">
        <span>字段说明</span>
        <strong>{{ fieldDescriptionCount }}</strong>
      </div>
    </section>

    <section v-if="payload && hasPlannerPlan" class="planner-section">
      <div class="planner-title-row">
        <div>
          <p class="eyebrow">Planner Agent</p>
          <h5>探查计划</h5>
        </div>
        <span class="decision-pill" :class="probeNeeded ? 'need' : 'enough'">
          {{ probeNeeded ? 'need_more_probe=true' : 'need_more_probe=false' }}
        </span>
      </div>

      <p v-if="planningReason" class="reason">{{ planningReason }}</p>

      <div v-if="focusColumns.length > 0" class="planner-block">
        <strong>关注字段</strong>
        <div class="chips">
          <span v-for="column in focusColumns" :key="column">{{ column }}</span>
        </div>
      </div>

      <div v-if="questionsToCheck.length > 0" class="planner-block">
        <strong>待验证假设 to verify</strong>
        <ul class="question-list">
          <li v-for="question in questionsToCheck" :key="question">{{ question }}</li>
        </ul>
      </div>

      <div v-if="plannedProbeActions.length > 0" class="planner-block">
        <strong>计划调用的工具</strong>
        <div class="chips action-chips">
          <span v-for="action in plannedProbeActions" :key="action">{{ actionLabel(action) }}</span>
        </div>
      </div>

      <div v-if="plannerActionSpecs.length > 0" class="planner-action-list">
        <article v-for="spec in plannerActionSpecs" :key="spec.key" class="planner-action-card">
          <div class="action-head">
            <strong>{{ actionLabel(spec.action) }}</strong>
            <span>{{ spec.action }}</span>
          </div>
          <p v-if="spec.reason" class="action-reason">{{ spec.reason }}</p>
          <div v-if="spec.columns.length > 0" class="mini-chips">
            <span v-for="column in spec.columns" :key="column">{{ column }}</span>
          </div>
          <dl class="spec-grid">
            <template v-if="spec.conditions.length > 0">
              <dt>conditions</dt>
              <dd>{{ formatUnknown(spec.conditions) }}</dd>
            </template>
            <template v-if="spec.groupBy.length > 0">
              <dt>group_by</dt>
              <dd>{{ spec.groupBy.join(', ') }}</dd>
            </template>
            <template v-if="spec.aggregations.length > 0">
              <dt>aggregations</dt>
              <dd>{{ formatUnknown(spec.aggregations) }}</dd>
            </template>
            <template v-if="spec.dependentColumn">
              <dt>dependent_column</dt>
              <dd>{{ spec.dependentColumn }}</dd>
            </template>
            <template v-if="spec.limit">
              <dt>limit</dt>
              <dd>{{ spec.limit }}</dd>
            </template>
          </dl>
        </article>
      </div>

      <details class="raw-details compact">
        <summary>查看 Planner 原始 JSON</summary>
        <pre>{{ rawPlannerText }}</pre>
      </details>
    </section>

    <section v-else-if="payload && !isRoot" class="planner-section muted">
      <h5>Planner Agent 计划</h5>
      <p>该文件暂未保存 Planner 计划。旧任务可能需要重新跑 AutoRealize 才会生成结构化计划。</p>
    </section>

    <section v-if="actions.length > 0" class="probe-section">
      <h5>工具执行结果</h5>
      <div class="action-list">
        <article v-for="action in actions" :key="action.key" class="action-card" :class="action.status">
          <div class="action-head">
            <strong>{{ actionLabel(action.action) }}</strong>
            <span>{{ statusLabel(action.status) }}</span>
          </div>
          <p v-if="action.reason" class="action-reason">{{ action.reason }}</p>
          <div v-if="action.columns.length > 0" class="mini-chips">
            <span v-for="column in action.columns" :key="column">{{ column }}</span>
          </div>
          <ul class="result-lines">
            <li v-for="line in action.resultLines" :key="line">{{ line }}</li>
          </ul>
        </article>
      </div>
      <details class="raw-details">
        <summary>查看原始探查 JSON</summary>
        <pre>{{ rawTraceText }}</pre>
      </details>
    </section>

    <section class="markdown-section">
      <h5>{{ isRoot ? 'data_description.md' : '最终认知 Markdown' }}</h5>
      <pre>{{ markdown || '暂无内容' }}</pre>
    </section>
  </article>
</template>

<style scoped>
.probe-panel {
  display: grid;
  gap: 12px;
}

.panel-header {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: start;
}

.eyebrow {
  margin: 0 0 4px;
  color: #6c84a8;
  font-size: 12px;
  letter-spacing: 0.03em;
  text-transform: uppercase;
}

.panel-header h4 {
  margin: 0;
  color: #1f436d;
  word-break: break-all;
}

.role-pill,
.decision-pill {
  border: 1px solid #b7c9e6;
  border-radius: 999px;
  padding: 4px 9px;
  background: #eef5ff;
  color: #315b8a;
  font-size: 12px;
  white-space: nowrap;
}

.decision-pill.need {
  border-color: #9bbdf2;
  background: #eaf2ff;
  color: #255fa8;
}

.decision-pill.enough {
  border-color: #afd7bd;
  background: #ebf8ef;
  color: #287142;
}

.summary {
  margin: 0;
  color: #2f4d73;
  line-height: 1.55;
}

.metric-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 8px;
}

.metric-card {
  border: 1px solid #d6e2f2;
  border-radius: 12px;
  background: linear-gradient(180deg, #f9fcff, #edf5ff);
  padding: 9px;
}

.metric-card span {
  display: block;
  color: #6a82a3;
  font-size: 12px;
}

.metric-card strong {
  display: block;
  margin-top: 4px;
  color: #214a78;
}

.planner-section,
.probe-section,
.markdown-section {
  border: 1px solid #d6e2f2;
  border-radius: 12px;
  background: #fbfdff;
  padding: 10px;
}

.planner-section {
  background: linear-gradient(135deg, #f7fbff 0%, #eef7f4 100%);
  border-color: #c7deea;
}

.planner-section.muted {
  background: #f7f9fc;
  color: #667f9f;
}

.planner-title-row {
  display: flex;
  align-items: start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 8px;
}

.planner-section h5,
.probe-section h5,
.markdown-section h5 {
  margin: 0 0 8px;
  color: #244b78;
}

.reason {
  margin: 0 0 10px;
  color: #415f84;
  line-height: 1.5;
}

.planner-block {
  display: grid;
  gap: 6px;
  margin-top: 10px;
}

.planner-block > strong {
  color: #294f78;
  font-size: 13px;
}

.chips,
.mini-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.chips span,
.mini-chips span {
  border-radius: 999px;
  background: #e7f1ff;
  color: #2d5f97;
  padding: 2px 7px;
  font-size: 12px;
}

.action-chips span {
  background: #e9f7ef;
  color: #2e7650;
}

.question-list,
.result-lines {
  margin: 8px 0 0;
  padding-left: 18px;
  color: #425f82;
}

.planner-action-list,
.action-list {
  display: grid;
  gap: 8px;
  margin-top: 10px;
}

.planner-action-card,
.action-card {
  border: 1px solid #d7e3f2;
  border-left: 4px solid #6ea3da;
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.92);
  padding: 9px;
}

.planner-action-card {
  border-left-color: #48a873;
}

.action-card.failed {
  border-left-color: #d05252;
}

.action-head {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  color: #244b78;
}

.action-head span {
  color: #5d779b;
  font-size: 12px;
}

.action-reason {
  margin: 6px 0;
  color: #526f92;
}

.spec-grid {
  display: grid;
  grid-template-columns: max-content minmax(0, 1fr);
  gap: 4px 10px;
  margin: 8px 0 0;
  color: #445f82;
  font-size: 12px;
}

.spec-grid dt {
  color: #6f87a8;
}

.spec-grid dd {
  margin: 0;
  overflow-wrap: anywhere;
}

.raw-details {
  margin-top: 8px;
  color: #31577f;
}

.raw-details.compact pre {
  max-height: 300px;
}

.raw-details pre,
.markdown-section pre {
  margin: 8px 0 0;
  border: 1px solid #d5e2f2;
  border-radius: 10px;
  background: #f7fbff;
  padding: 10px;
  max-height: 520px;
  overflow: auto;
  white-space: pre-wrap;
  font-size: 12px;
  color: #233f60;
}

@media (max-width: 900px) {
  .metric-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
</style>
