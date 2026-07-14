<script setup lang="ts">
import { computed } from 'vue'
import type { SnapshotPayload } from '../types'

type ContractStatus = 'pending' | 'running' | 'completed' | 'warning'

type ContractPhase = {
  id: string
  index: string
  title: string
  subtitle: string
  status: ContractStatus
  detail: string
}

type DataFileView = {
  path: string
  role: string
  method: string
  summary: string
  sheets: string[]
  fieldCount: number
}

const props = defineProps<{
  snapshot?: SnapshotPayload
  activeStepRunning?: boolean
}>()

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {}
}

function asArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : []
}

function firstText(...values: unknown[]) {
  for (const value of values) {
    const text = String(value ?? '').trim()
    if (text) return text
  }
  return ''
}

function textList(value: unknown): string[] {
  return asArray(value)
    .map((item) => {
      if (typeof item === 'string' || typeof item === 'number') return String(item).trim()
      const row = asRecord(item)
      return firstText(row.text, row.name, row.title, row.summary, row.rule, row.description, row.path)
    })
    .filter(Boolean)
}

function unique(values: string[]) {
  return [...new Set(values.map((item) => item.trim()).filter(Boolean))]
}

function collectText(value: unknown, depth = 0): string[] {
  if (depth > 3 || value === null || value === undefined) return []
  if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') {
    const text = String(value).trim()
    return text ? [text] : []
  }
  if (Array.isArray(value)) return value.flatMap((item) => collectText(item, depth + 1))
  const row = asRecord(value)
  return Object.entries(row)
    .filter(([key]) => !['schema_version', 'confidence', 'passed', 'enabled'].includes(key))
    .flatMap(([, item]) => collectText(item, depth + 1))
}

function columnsFrom(value: unknown): string[] {
  return asArray(value)
    .map((item) => {
      if (typeof item === 'string') return item.trim()
      const row = asRecord(item)
      return firstText(row.name, row.column, row.field, row.id)
    })
    .filter(Boolean)
}

function statusLabel(status: ContractStatus) {
  return {
    pending: '等待',
    running: '编译中',
    completed: '已就绪',
    warning: '需确认',
  }[status]
}

const ar = computed(() => props.snapshot?.auto_realize ?? {})
const taskDefinitionReport = computed(() => asRecord(ar.value.task_definition_report))
const evaluationContractReport = computed(() => asRecord(ar.value.evaluation_contract_report))
const downstreamContext = computed(() => asRecord(taskDefinitionReport.value.downstream_context))

const mainTaskProtocol = computed(() => {
  const direct = asRecord(ar.value.main_task_protocol)
  if (Object.keys(direct).length > 0) return direct
  return asRecord(taskDefinitionReport.value.main_task_protocol)
})

const automlContextPack = computed(() => {
  const direct = asRecord(ar.value.automl_context_pack)
  if (Object.keys(direct).length > 0) return direct
  return asRecord(taskDefinitionReport.value.automl_context_pack)
})

const authoritativeMemory = computed(() => {
  const direct = asRecord(ar.value.authoritative_task_memory)
  if (Object.keys(direct).length > 0) return direct
  const protocolMemory = asRecord(mainTaskProtocol.value.authoritative_memory)
  if (Object.keys(protocolMemory).length > 0) return protocolMemory
  return asRecord(downstreamContext.value.authoritative_memory)
})

const agentContextPack = computed(() => {
  const direct = asRecord(ar.value.agent_context_pack)
  if (Object.keys(direct).length > 0) return direct
  return asRecord(downstreamContext.value.agent_context_pack)
})

const originalRequirementsText = computed(() => String(ar.value.original_requirements_text ?? '').trim())
const descriptionText = computed(() => String(ar.value.description_text ?? '').trim())
const automlContextText = computed(() => String(ar.value.automl_context_text ?? '').trim())
const taskHint = computed(() => firstText(
  taskDefinitionReport.value.task_hint,
  props.snapshot?.task?.config?.auto_realize?.task_hint,
))

const taskClassification = computed(() => asRecord(taskDefinitionReport.value.task_classification))
const paradigmReport = computed(() => asRecord(taskDefinitionReport.value.problem_paradigm))
const protocolParadigm = computed(() => asRecord(mainTaskProtocol.value.problem_paradigm))
const taskProtocol = computed(() => {
  const direct = asRecord(mainTaskProtocol.value.task_protocol)
  if (Object.keys(direct).length > 0) return direct
  return asRecord(taskDefinitionReport.value.description_protocol_bundle)
})

const paradigm = computed(() => firstText(
  protocolParadigm.value.problem_paradigm,
  paradigmReport.value.problem_paradigm,
  taskClassification.value.task_type,
  automlContextPack.value.problem_paradigm,
  '待分类',
))

const paradigmReason = computed(() => firstText(
  protocolParadigm.value.reasoning,
  paradigmReport.value.reasoning,
  taskClassification.value.reasoning,
))

const taskGoal = computed(() => firstText(
  taskProtocol.value.task_goal,
  automlContextPack.value.task_goal,
  asArray(asRecord(taskDefinitionReport.value.plan).objectives)[0],
  taskHint.value,
  '等待提炼任务目标。',
))

const taskOverview = computed(() => firstText(
  taskProtocol.value.overview,
  taskProtocol.value.summary,
  taskHint.value,
))

const dataAccessProtocol = computed(() => {
  const direct = asRecord(mainTaskProtocol.value.data_access_protocol)
  if (Object.keys(direct).length > 0) return direct
  const fromTask = asRecord(taskProtocol.value.data_access)
  if (Object.keys(fromTask).length > 0) return fromTask
  return asRecord(downstreamContext.value.data_access_protocol)
})

const dataFiles = computed<DataFileView[]>(() => {
  const sourceRows = asArray(dataAccessProtocol.value.files).length > 0
    ? asArray(dataAccessProtocol.value.files)
    : asArray(automlContextPack.value.data_access)
  const grouped = new Map<string, DataFileView>()

  for (const raw of sourceRows) {
    const row = asRecord(raw)
    const path = firstText(row.path, row.file, row.source, row.table_id)
    if (!path) continue
    const sheet = firstText(row.sheet_name, row.sheet)
    const fields = asArray(row.fields)
    const columns = textList(row.columns)
    const existing = grouped.get(path)
    if (existing) {
      if (sheet && !existing.sheets.includes(sheet)) existing.sheets.push(sheet)
      existing.fieldCount = Math.max(existing.fieldCount, fields.length, columns.length)
      if (!existing.summary) existing.summary = firstText(row.row_grain, row.summary)
      continue
    }
    grouped.set(path, {
      path,
      role: firstText(row.file_role, row.role, row.kind, '数据文件'),
      method: firstText(row.read_method, row.read_example, '按协议读取'),
      summary: firstText(row.row_grain, row.summary),
      sheets: sheet ? [sheet] : [],
      fieldCount: Math.max(fields.length, columns.length),
    })
  }
  return [...grouped.values()]
})

const evaluationFinal = computed(() => {
  const final = asRecord(evaluationContractReport.value.final)
  if (Object.keys(final).length > 0) return final
  const protocolEvaluation = asRecord(mainTaskProtocol.value.evaluation_contract)
  if (Object.keys(protocolEvaluation).length > 0) return protocolEvaluation
  return asRecord(taskDefinitionReport.value.evaluation_contract)
})

const revisionLog = computed(() => asArray(evaluationContractReport.value.revision_log).map(asRecord))
const reflectionLog = computed(() => asArray(evaluationContractReport.value.reflection_log).map(asRecord))
const latestReflection = computed(() => reflectionLog.value[reflectionLog.value.length - 1] ?? {})

const evaluationPassed = computed(() => Boolean(evaluationFinal.value.passed))
const primaryMetric = computed(() => firstText(
  evaluationFinal.value.primary_metric,
  evaluationFinal.value.metric_name,
  asRecord(taskProtocol.value.evaluation_summary).primary_metric,
  '待定义',
))
const metricDirection = computed(() => firstText(evaluationFinal.value.metric_direction, evaluationFinal.value.direction))
const metricFormula = computed(() => firstText(
  evaluationFinal.value.scalar_score_formula,
  evaluationFinal.value.metric_formula,
  evaluationFinal.value.score_formula,
  '尚未提供唯一评分公式。',
))
const evaluationScope = computed(() => firstText(
  evaluationFinal.value.computation_scope,
  evaluationFinal.value.validation_protocol,
  evaluationFinal.value.aggregation_rule,
))
const invalidSolutionRules = computed(() => unique([
  ...collectText(evaluationFinal.value.invalid_solution_rules),
  ...collectText(evaluationFinal.value.hard_constraints),
]).slice(0, 12))
const submissionChecks = computed(() => unique(collectText(evaluationFinal.value.submission_checks)).slice(0, 12))

const outputContract = computed(() => {
  const direct = asRecord(mainTaskProtocol.value.output_contract)
  if (Object.keys(direct).length > 0) return direct
  const taskOutput = asRecord(taskProtocol.value.output)
  if (Object.keys(taskOutput).length > 0) return taskOutput
  const agentOutput = asRecord(agentContextPack.value.submission_contract)
  if (Object.keys(agentOutput).length > 0) return agentOutput
  return asRecord(downstreamContext.value.authoritative_submission_contract)
})

const outputColumns = computed(() => unique([
  ...columnsFrom(outputContract.value.columns),
  ...columnsFrom(outputContract.value.required_columns),
  ...columnsFrom(outputContract.value.submission_columns),
  ...columnsFrom(downstreamContext.value.generated_submission_columns),
  ...columnsFrom(downstreamContext.value.submission_columns),
]))

const outputFiles = computed(() => unique([
  firstText(outputContract.value.output_filename),
  ...textList(outputContract.value.files),
  ...textList(outputContract.value.output_files),
  ...textList(outputContract.value.artifacts),
  ...textList(taskProtocol.value.output_files),
]))

const outputSummary = computed(() => firstText(
  outputContract.value.description,
  outputContract.value.format,
  outputContract.value.row_grain,
  outputContract.value.row_unit,
  outputContract.value.prediction_unit,
  outputContract.value.no_sample_submission_reason,
  outputContract.value.output_kind,
  '等待定义输出与交付格式。',
))

const constraints = computed(() => unique([
  ...collectText(taskProtocol.value.constraints),
  ...collectText(automlContextPack.value.constraints),
  ...collectText(evaluationFinal.value.hard_constraints),
  ...collectText(asRecord(authoritativeMemory.value.constraint_memory).hard_constraints),
]).slice(0, 18))

const modelingSections = computed(() => {
  const candidates = [
    { title: '监督学习 / 深度学习', value: taskProtocol.value.ml_dl },
    { title: '优化 / 决策', value: taskProtocol.value.optimization },
    { title: '强化学习', value: taskProtocol.value.rl },
    { title: '混合方案', value: taskProtocol.value.hybrid },
  ]
  return candidates
    .map((item) => ({ ...item, points: unique(collectText(item.value)).slice(0, 5) }))
    .filter((item) => item.points.length > 0)
})

const methodNotes = computed(() => unique([
  ...collectText(automlContextPack.value.method_strategy),
  ...collectText(automlContextPack.value.modeling_boundary),
  ...collectText(protocolParadigm.value.method_routing_notes),
]).slice(0, 8))

const authoritySources = computed(() => unique([
  ...textList(authoritativeMemory.value.source_files),
  ...textList(agentContextPack.value.priority_order),
]).slice(0, 12))

const authorityConflicts = computed(() => unique(collectText(mainTaskProtocol.value.authority_conflicts)).slice(0, 12))
const defectsAfterGate = computed(() => unique(collectText(taskDefinitionReport.value.defects_after_gate)))
const evaluationIssues = computed(() => unique(collectText(evaluationFinal.value.issues)))
const evaluationFixes = computed(() => unique(collectText(evaluationFinal.value.fixes)))
const reflectionIssues = computed(() => unique(collectText(latestReflection.value.ambiguity_points)))
const sampleIssues = computed(() => unique(collectText(asRecord(ar.value.submission_report).issues)))

const riskItems = computed(() => unique([
  ...defectsAfterGate.value,
  ...evaluationIssues.value,
  ...reflectionIssues.value,
  ...authorityConflicts.value,
  ...sampleIssues.value,
]).slice(0, 20))

const authorityStatus = computed<ContractStatus>(() => {
  if (originalRequirementsText.value || taskHint.value) return 'completed'
  return props.activeStepRunning ? 'running' : 'pending'
})

const modelingStatus = computed<ContractStatus>(() => {
  if (Object.keys(taskProtocol.value).length > 0 || Object.keys(taskClassification.value).length > 0) return 'completed'
  return props.activeStepRunning ? 'running' : 'pending'
})

const evaluationStatus = computed<ContractStatus>(() => {
  if (Object.keys(evaluationFinal.value).length === 0) return props.activeStepRunning ? 'running' : 'pending'
  return evaluationPassed.value ? 'completed' : 'warning'
})

const deliveryStatus = computed<ContractStatus>(() => {
  if (descriptionText.value && automlContextText.value) return 'completed'
  if (descriptionText.value || Object.keys(outputContract.value).length > 0) return 'warning'
  return props.activeStepRunning ? 'running' : 'pending'
})

const phases = computed<ContractPhase[]>(() => [
  {
    id: 'authority',
    index: '01',
    title: '权威输入',
    subtitle: '需求与事实优先级',
    status: authorityStatus.value,
    detail: originalRequirementsText.value
      ? `已保留 ${originalRequirementsText.value.length} 字原始需求，并登记 ${authoritySources.value.length} 条权威来源或优先级。`
      : '等待读取原始需求与权威说明。',
  },
  {
    id: 'modeling',
    index: '02',
    title: '任务建模',
    subtitle: '目标、范式与数据访问',
    status: modelingStatus.value,
    detail: `${paradigm.value}；已整理 ${dataFiles.value.length} 个数据文件的读取协议。`,
  },
  {
    id: 'evaluation',
    index: '03',
    title: '评估与约束',
    subtitle: '统一评分合同',
    status: evaluationStatus.value,
    detail: Object.keys(evaluationFinal.value).length > 0
      ? `${primaryMetric.value}${metricDirection.value ? ` · ${metricDirection.value}` : ''}；${constraints.value.length} 条约束证据。`
      : '等待生成可执行的评价公式和非法解处理规则。',
  },
  {
    id: 'delivery',
    index: '04',
    title: '输出交付',
    subtitle: 'description 与 AutoML 上下文',
    status: deliveryStatus.value,
    detail: descriptionText.value
      ? `description.md 已生成；AutoML Context ${automlContextText.value ? '已就绪' : '尚待生成'}。`
      : '等待固化任务书、输出格式与机器上下文。',
  },
])

const overallStatus = computed(() => {
  if (deliveryStatus.value === 'completed' && evaluationPassed.value && riskItems.value.length === 0) {
    return { label: '合同已就绪', tone: 'completed' as ContractStatus }
  }
  if (riskItems.value.length > 0 || evaluationStatus.value === 'warning' || deliveryStatus.value === 'warning') {
    return { label: '存在待确认项', tone: 'warning' as ContractStatus }
  }
  if (props.activeStepRunning) return { label: '合同编译中', tone: 'running' as ContractStatus }
  return { label: '等待任务定义', tone: 'pending' as ContractStatus }
})

const contractSummary = computed(() => firstText(
  taskOverview.value,
  taskGoal.value,
  '把原始需求、数据认知与 QDI 结论编译为可执行任务合同。',
))

const hasContent = computed(() => Boolean(
  Object.keys(taskDefinitionReport.value).length
  || Object.keys(mainTaskProtocol.value).length
  || originalRequirementsText.value
  || props.activeStepRunning,
))
</script>

<template>
  <section class="contract-workbench">
    <header class="contract-hero">
      <div class="hero-copy">
        <p class="hero-eyebrow">Task Contract Compiler</p>
        <div class="hero-title-row">
          <h2 class="hero-title">任务合同编译</h2>
          <span class="hero-state" :class="overallStatus.tone">{{ overallStatus.label }}</span>
        </div>
        <p class="hero-summary">{{ contractSummary }}</p>
        <div class="hero-tags">
          <span>{{ paradigm }}</span>
          <span v-if="primaryMetric !== '待定义'">指标 {{ primaryMetric }}</span>
          <span>{{ dataFiles.length }} 个数据文件</span>
          <span>{{ riskItems.length }} 个待确认项</span>
        </div>
      </div>

      <div class="readiness-board">
        <div>
          <span>任务书</span>
          <strong>{{ descriptionText ? 'READY' : 'WAIT' }}</strong>
        </div>
        <div>
          <span>评估合同</span>
          <strong>{{ evaluationPassed ? 'PASS' : Object.keys(evaluationFinal).length ? 'REVIEW' : 'WAIT' }}</strong>
        </div>
        <div>
          <span>AutoML Context</span>
          <strong>{{ automlContextText ? 'READY' : 'WAIT' }}</strong>
        </div>
      </div>
    </header>

    <template v-if="hasContent">
      <section class="phase-rail" aria-label="任务合同编译阶段">
        <article v-for="phase in phases" :key="phase.id" class="phase-card" :class="phase.status">
          <div class="phase-top">
            <span class="phase-index">{{ phase.index }}</span>
            <span class="phase-status" :class="phase.status">{{ statusLabel(phase.status) }}</span>
          </div>
          <h3>{{ phase.title }}</h3>
          <p class="phase-subtitle">{{ phase.subtitle }}</p>
          <p class="phase-detail">{{ phase.detail }}</p>
        </article>
      </section>

      <section class="contract-grid">
        <article class="contract-card modeling-card wide">
          <header class="card-header">
            <div>
              <p class="card-kicker">Problem Contract</p>
              <h3>任务目标与建模边界</h3>
            </div>
            <span class="card-badge">{{ paradigm }}</span>
          </header>
          <p class="goal-copy">{{ taskGoal }}</p>
          <p v-if="paradigmReason" class="reason-copy">{{ paradigmReason }}</p>

          <div v-if="modelingSections.length > 0" class="modeling-grid">
            <section v-for="section in modelingSections" :key="section.title">
              <strong>{{ section.title }}</strong>
              <ul>
                <li v-for="point in section.points" :key="point">{{ point }}</li>
              </ul>
            </section>
          </div>

          <div v-if="methodNotes.length > 0" class="method-notes">
            <strong>下游方法边界</strong>
            <span v-for="note in methodNotes" :key="note">{{ note }}</span>
          </div>
        </article>

        <article class="contract-card data-card">
          <header class="card-header">
            <div>
              <p class="card-kicker">Data Access</p>
              <h3>精确数据访问</h3>
            </div>
            <span class="card-count">{{ dataFiles.length }}</span>
          </header>
          <div v-if="dataFiles.length > 0" class="file-list">
            <article v-for="file in dataFiles.slice(0, 8)" :key="file.path" class="file-row">
              <div>
                <strong>{{ file.path }}</strong>
                <span>{{ file.role }} · {{ file.method }}</span>
              </div>
              <p v-if="file.summary">{{ file.summary }}</p>
              <div class="file-meta">
                <span v-if="file.sheets.length > 0">sheet {{ file.sheets.join(', ') }}</span>
                <span v-if="file.fieldCount > 0">{{ file.fieldCount }} fields</span>
              </div>
            </article>
            <p v-if="dataFiles.length > 8" class="more-copy">其余 {{ dataFiles.length - 8 }} 个文件已写入最终数据访问协议。</p>
          </div>
          <p v-else class="empty-copy">数据访问协议尚未生成。</p>
        </article>

        <article class="contract-card constraint-card">
          <header class="card-header">
            <div>
              <p class="card-kicker">Constraint Set</p>
              <h3>约束与不可编造边界</h3>
            </div>
            <span class="card-count">{{ constraints.length }}</span>
          </header>
          <ol v-if="constraints.length > 0" class="contract-list numbered">
            <li v-for="item in constraints" :key="item">{{ item }}</li>
          </ol>
          <p v-else class="empty-copy">尚未提取结构化约束。</p>
        </article>

        <article class="contract-card evaluation-card wide">
          <header class="card-header">
            <div>
              <p class="card-kicker">Evaluation Contract</p>
              <h3>统一评价合同</h3>
            </div>
            <span class="contract-pass" :class="evaluationPassed ? 'passed' : 'review'">
              {{ evaluationPassed ? 'PASSED' : Object.keys(evaluationFinal).length ? 'REVIEW' : 'WAITING' }}
            </span>
          </header>

          <div class="metric-layout">
            <div class="metric-main">
              <span>Primary Metric</span>
              <strong>{{ primaryMetric }}</strong>
              <small v-if="metricDirection">{{ metricDirection }}</small>
            </div>
            <div class="formula-box">
              <span>Deterministic Formula</span>
              <code>{{ metricFormula }}</code>
            </div>
          </div>

          <p v-if="evaluationScope" class="scope-copy">{{ evaluationScope }}</p>

          <div class="evaluation-columns">
            <section>
              <strong>非法解与约束处理</strong>
              <ul v-if="invalidSolutionRules.length > 0" class="contract-list">
                <li v-for="item in invalidSolutionRules" :key="item">{{ item }}</li>
              </ul>
              <p v-else class="empty-copy">未记录非法解处理规则。</p>
            </section>
            <section>
              <strong>提交与验证检查</strong>
              <ul v-if="submissionChecks.length > 0" class="contract-list">
                <li v-for="item in submissionChecks" :key="item">{{ item }}</li>
              </ul>
              <p v-else class="empty-copy">未记录提交检查规则。</p>
            </section>
          </div>
        </article>

        <article class="contract-card output-card wide">
          <header class="card-header">
            <div>
              <p class="card-kicker">Output Contract</p>
              <h3>输出与交付</h3>
            </div>
            <span class="card-badge">{{ outputColumns.length }} columns</span>
          </header>
          <p class="output-copy">{{ outputSummary }}</p>

          <div v-if="outputFiles.length > 0" class="output-files">
            <span v-for="file in outputFiles" :key="file">{{ file }}</span>
          </div>

          <div v-if="outputColumns.length > 0" class="column-cloud">
            <span v-for="column in outputColumns" :key="column">{{ column }}</span>
          </div>
          <p v-else class="empty-copy">未定义固定提交列，以下游输出合同与 description.md 为准。</p>
        </article>
      </section>

      <section class="risk-panel" :class="{ clear: riskItems.length === 0 }">
        <header class="risk-header">
          <div>
            <p class="card-kicker">Residual Risk</p>
            <h3>{{ riskItems.length > 0 ? '仍需确认' : '合同检查通过' }}</h3>
          </div>
          <span>{{ riskItems.length }}</span>
        </header>

        <ul v-if="riskItems.length > 0" class="risk-list">
          <li v-for="item in riskItems" :key="item">{{ item }}</li>
        </ul>
        <p v-else class="clear-copy">质量门、评价合同与权威冲突检查未留下结构化问题。</p>

        <div v-if="evaluationFixes.length > 0" class="fix-strip">
          <strong>建议修正</strong>
          <span v-for="item in evaluationFixes" :key="item">{{ item }}</span>
        </div>

        <details v-if="revisionLog.length > 0 || reflectionLog.length > 0" class="history-details">
          <summary>查看评价合同返修历史（{{ revisionLog.length + reflectionLog.length }} 条）</summary>
          <div class="history-grid">
            <article v-for="(row, index) in revisionLog" :key="`revision-${index}`">
              <strong>Revision {{ row.round ?? index + 1 }}</strong>
              <span>passed={{ row.passed ?? '-' }}</span>
              <p>{{ unique([...collectText(row.issues), ...collectText(row.defects)]).join('；') || '无详细问题。' }}</p>
            </article>
            <article v-for="(row, index) in reflectionLog" :key="`reflection-${index}`">
              <strong>Reflection {{ row.round ?? index + 1 }}</strong>
              <span>unambiguous={{ row.is_unambiguous ?? '-' }}</span>
              <p>{{ unique(collectText(row.ambiguity_points)).join('；') || '无歧义点。' }}</p>
            </article>
          </div>
        </details>
      </section>
    </template>

    <div v-else class="contract-empty">
      <strong>任务定义尚未启动</strong>
      <p>完成数据认知与 QDI 后，这里会把权威需求编译成任务、评价和交付合同。</p>
    </div>
  </section>
</template>

<style scoped>
.contract-workbench {
  --ink: #163e5a;
  --muted: #607b90;
  --line: #cfdee8;
  --teal: #087a70;
  display: grid;
  gap: 14px;
  min-width: 0;
}

.contract-hero {
  position: relative;
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 28px;
  overflow: hidden;
  padding: 25px 26px;
  border: 1px solid #bbd2dc;
  border-radius: 20px;
  background:
    radial-gradient(circle at 93% 12%, rgba(21, 132, 139, 0.18), transparent 30%),
    linear-gradient(135deg, #f5fbfb 0%, #eef6fa 58%, #f8fbfd 100%);
  box-shadow: 0 18px 44px rgba(35, 76, 100, 0.08);
}

.contract-hero::after {
  position: absolute;
  right: -34px;
  bottom: -76px;
  width: 220px;
  height: 220px;
  border: 1px solid rgba(37, 112, 128, 0.12);
  border-radius: 50%;
  content: '';
}

.hero-copy,
.readiness-board {
  position: relative;
  z-index: 1;
}

.hero-eyebrow,
.card-kicker {
  margin: 0 0 6px;
  color: var(--teal);
  font-size: 11px;
  font-weight: 800;
  letter-spacing: 0.13em;
  text-transform: uppercase;
}

.hero-title-row,
.card-header,
.risk-header,
.phase-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.hero-title {
  margin: 0;
  color: var(--ink);
  font-size: clamp(27px, 3.5vw, 40px);
  letter-spacing: -0.045em;
}

.hero-state,
.phase-status,
.card-badge,
.contract-pass,
.hero-tags span,
.output-files span,
.column-cloud span,
.method-notes span,
.file-meta span {
  border-radius: 999px;
  font-size: 11px;
  font-weight: 700;
}

.hero-state {
  padding: 7px 12px;
}

.hero-state.completed,
.phase-status.completed {
  background: #dff4e9;
  color: #1b6c4e;
}

.hero-state.running,
.phase-status.running {
  background: #deedff;
  color: #245f91;
}

.hero-state.warning,
.phase-status.warning {
  background: #fff0d4;
  color: #93611b;
}

.hero-state.pending,
.phase-status.pending {
  background: #e8eef2;
  color: #647987;
}

.hero-summary {
  max-width: 900px;
  margin: 11px 0 0;
  color: #46677c;
  font-size: 14px;
  line-height: 1.7;
}

.hero-tags,
.output-files,
.column-cloud,
.file-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.hero-tags {
  margin-top: 14px;
}

.hero-tags span {
  padding: 5px 9px;
  border: 1px solid rgba(160, 194, 204, 0.76);
  background: rgba(255, 255, 255, 0.7);
  color: #4b7183;
}

.readiness-board {
  display: grid;
  grid-template-columns: repeat(3, minmax(94px, 1fr));
  gap: 8px;
  align-self: end;
}

.readiness-board div {
  padding: 12px;
  border: 1px solid rgba(174, 204, 213, 0.82);
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.74);
}

.readiness-board span,
.readiness-board strong {
  display: block;
}

.readiness-board span {
  color: #6c8493;
  font-size: 10px;
}

.readiness-board strong {
  margin-top: 5px;
  color: #235a6e;
  font-family: Consolas, monospace;
  font-size: 15px;
}

.phase-rail {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 9px;
}

.phase-card {
  min-width: 0;
  min-height: 156px;
  padding: 15px;
  border: 1px solid #d3e0e8;
  border-top: 3px solid #aebdc7;
  border-radius: 15px;
  background: rgba(255, 255, 255, 0.92);
}

.phase-card.completed {
  border-top-color: #399675;
}

.phase-card.running {
  border-top-color: #3b78b4;
}

.phase-card.warning {
  border-top-color: #d6a348;
}

.phase-index {
  color: #8aa0ae;
  font-family: Consolas, monospace;
  font-size: 12px;
}

.phase-status {
  padding: 4px 8px;
}

.phase-card h3,
.contract-card h3,
.risk-panel h3 {
  margin: 11px 0 0;
  color: var(--ink);
  font-size: 16px;
}

.phase-subtitle {
  margin: 4px 0 0;
  color: #6d8494;
  font-size: 11px;
}

.phase-detail {
  margin: 10px 0 0;
  color: #4e6d80;
  font-size: 12px;
  line-height: 1.55;
}

.contract-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.contract-card,
.risk-panel,
.contract-empty {
  min-width: 0;
  padding: 18px;
  border: 1px solid var(--line);
  border-radius: 17px;
  background: rgba(255, 255, 255, 0.96);
  box-shadow: 0 10px 26px rgba(43, 77, 99, 0.045);
}

.contract-card.wide {
  grid-column: 1 / -1;
}

.card-header h3,
.risk-header h3 {
  margin-top: 0;
}

.card-badge,
.card-count {
  padding: 5px 9px;
  background: #e6f1f3;
  color: #326b72;
}

.card-count {
  display: grid;
  place-items: center;
  min-width: 28px;
  height: 28px;
  border-radius: 10px;
  font-size: 12px;
  font-weight: 800;
}

.goal-copy {
  margin: 14px 0 0;
  color: #2c5268;
  font-size: 16px;
  font-weight: 700;
  line-height: 1.65;
}

.reason-copy,
.output-copy,
.scope-copy {
  margin: 10px 0 0;
  color: #5c7688;
  font-size: 12px;
  line-height: 1.62;
}

.modeling-grid,
.evaluation-columns {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
  margin-top: 15px;
}

.modeling-grid section,
.evaluation-columns section {
  padding: 12px;
  border: 1px solid #d8e5eb;
  border-radius: 12px;
  background: #f7fafc;
}

.modeling-grid strong,
.evaluation-columns strong {
  color: #345d72;
  font-size: 12px;
}

.modeling-grid ul,
.contract-list {
  margin: 9px 0 0;
  padding-left: 19px;
  color: #4b6879;
  font-size: 12px;
  line-height: 1.58;
}

.modeling-grid li,
.contract-list li {
  margin-bottom: 5px;
}

.method-notes {
  display: flex;
  flex-wrap: wrap;
  gap: 7px;
  align-items: center;
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px dashed #d6e2e8;
}

.method-notes strong {
  color: #446679;
  font-size: 11px;
}

.method-notes span {
  padding: 5px 8px;
  background: #edf4f6;
  color: #587482;
}

.file-list {
  display: grid;
  gap: 8px;
  margin-top: 13px;
}

.file-row {
  padding: 11px;
  border: 1px solid #dce7ec;
  border-radius: 12px;
  background: #f9fbfc;
}

.file-row > div:first-child {
  display: flex;
  justify-content: space-between;
  gap: 10px;
}

.file-row strong {
  color: #315a6f;
  font-size: 12px;
  overflow-wrap: anywhere;
}

.file-row > div:first-child span {
  color: #748b99;
  font-size: 10px;
  text-align: right;
}

.file-row p {
  display: -webkit-box;
  margin: 7px 0 0;
  overflow: hidden;
  color: #5a7586;
  font-size: 11px;
  line-height: 1.5;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 3;
}

.file-meta {
  margin-top: 8px;
}

.file-meta span {
  padding: 3px 7px;
  background: #eaf1f4;
  color: #607b89;
}

.more-copy,
.empty-copy,
.clear-copy {
  color: #708898;
  font-size: 12px;
  line-height: 1.55;
}

.contract-list.numbered {
  list-style: decimal-leading-zero;
}

.contract-pass {
  padding: 6px 10px;
  font-family: Consolas, monospace;
}

.contract-pass.passed {
  background: #dff4e8;
  color: #1b6e4e;
}

.contract-pass.review {
  background: #fff0d8;
  color: #92601c;
}

.metric-layout {
  display: grid;
  grid-template-columns: minmax(180px, 0.55fr) minmax(0, 1.45fr);
  gap: 10px;
  margin-top: 14px;
}

.metric-main,
.formula-box {
  padding: 14px;
  border-radius: 13px;
}

.metric-main {
  background: #123f58;
  color: #ffffff;
}

.metric-main span,
.metric-main strong,
.metric-main small {
  display: block;
}

.metric-main span,
.formula-box span {
  font-size: 10px;
  font-weight: 800;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.metric-main span {
  color: #a9d3dc;
}

.metric-main strong {
  margin-top: 8px;
  font-size: 20px;
  overflow-wrap: anywhere;
}

.metric-main small {
  margin-top: 8px;
  color: #c3dce2;
}

.formula-box {
  border: 1px solid #c8dde3;
  background: #eef7f7;
}

.formula-box span {
  color: #4e767b;
}

.formula-box code {
  display: block;
  margin-top: 9px;
  color: #1e5c62;
  font-family: Consolas, monospace;
  font-size: 13px;
  line-height: 1.62;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

.output-files {
  margin-top: 12px;
}

.output-files span {
  padding: 5px 9px;
  background: #173f58;
  color: #e9f5f7;
  font-family: Consolas, monospace;
}

.column-cloud {
  margin-top: 12px;
  padding: 12px;
  border: 1px solid #d7e4e9;
  border-radius: 12px;
  background: #f6fafb;
}

.column-cloud span {
  padding: 5px 8px;
  border: 1px solid #cbdce3;
  background: #ffffff;
  color: #41677a;
  font-family: Consolas, monospace;
}

.risk-panel {
  border-color: #e1c98f;
  background: linear-gradient(135deg, #fffaf0, #ffffff);
}

.risk-panel.clear {
  border-color: #b8dccb;
  background: linear-gradient(135deg, #f2fbf7, #ffffff);
}

.risk-header > span {
  display: grid;
  place-items: center;
  width: 34px;
  height: 34px;
  border-radius: 50%;
  background: #f3dfb3;
  color: #8b5d1e;
  font-weight: 800;
}

.risk-panel.clear .risk-header > span {
  background: #d9f0e5;
  color: #237051;
}

.risk-list {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
  margin: 13px 0 0;
  padding: 0;
  list-style: none;
}

.risk-list li {
  padding: 10px 12px;
  border: 1px solid #ecd9ae;
  border-radius: 11px;
  background: rgba(255, 255, 255, 0.72);
  color: #745c35;
  font-size: 12px;
  line-height: 1.5;
}

.fix-strip {
  display: flex;
  flex-wrap: wrap;
  gap: 7px;
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px dashed #dfc991;
}

.fix-strip strong,
.fix-strip span {
  color: #6e5b38;
  font-size: 11px;
}

.fix-strip span {
  padding: 4px 8px;
  border-radius: 999px;
  background: #fff3d9;
}

.history-details {
  margin-top: 12px;
  border-top: 1px solid rgba(217, 193, 137, 0.65);
  padding-top: 11px;
}

.history-details summary {
  color: #6e5b38;
  font-size: 12px;
  font-weight: 700;
  cursor: pointer;
}

.history-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
  margin-top: 10px;
}

.history-grid article {
  padding: 10px;
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.78);
}

.history-grid strong,
.history-grid span {
  display: block;
  color: #6d5a3a;
  font-size: 11px;
}

.history-grid p {
  margin: 7px 0 0;
  color: #7b6b50;
  font-size: 11px;
  line-height: 1.5;
}

.contract-empty {
  padding: 48px 20px;
  color: var(--ink);
  text-align: center;
}

.contract-empty p {
  margin: 7px 0 0;
  color: var(--muted);
  font-size: 12px;
}

@media (max-width: 1120px) {
  .contract-hero {
    grid-template-columns: 1fr;
  }

  .phase-rail {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 780px) {
  .contract-grid,
  .modeling-grid,
  .evaluation-columns,
  .metric-layout,
  .risk-list,
  .history-grid {
    grid-template-columns: 1fr;
  }

  .contract-card.wide {
    grid-column: auto;
  }

  .readiness-board {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
}

@media (max-width: 560px) {
  .contract-hero,
  .contract-card,
  .risk-panel {
    padding: 15px;
  }

  .hero-title-row {
    align-items: flex-start;
  }

  .phase-rail,
  .readiness-board {
    grid-template-columns: 1fr;
  }

  .file-row > div:first-child {
    display: grid;
  }

  .file-row > div:first-child span {
    text-align: left;
  }
}
</style>
