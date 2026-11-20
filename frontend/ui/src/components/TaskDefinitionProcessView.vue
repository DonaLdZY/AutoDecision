<script setup lang="ts">
import { computed } from 'vue'
import type { SnapshotPayload } from '../types'

type ContractStatus = 'pending' | 'running' | 'completed' | 'warning'

type ContractPhase = {
  id: string
  index: string
  title: string
  status: ContractStatus
  detail: string
}

type DataFileView = {
  path: string
  role: string
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
    pending: '待生成',
    running: '处理中',
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

const paradigmLabel = computed(() => {
  const value = paradigm.value.trim()
  if (/[\u3400-\u9fff]/.test(value)) return value
  const labels: Record<string, string> = {
    classification: '分类',
    decision_optimization: '决策优化',
    forecasting: '预测',
    hybrid: '混合建模',
    optimization: '优化决策',
    regression: '回归',
    reinforcement_learning: '强化学习',
    supervised_learning: '监督学习',
    time_series_forecasting: '时间序列预测',
  }
  return labels[value.toLowerCase()] ?? '任务类型待确认'
})

function fileRoleLabel(value: string) {
  if (/[\u3400-\u9fff]/.test(value)) return value
  const role = value.trim().toLowerCase().replaceAll('-', '_').replaceAll(' ', '_')
  const labels: Record<string, string> = {
    feature: '特征数据',
    features: '特征数据',
    input: '输入数据',
    label: '目标数据',
    sample_submission: '提交样例',
    submission: '提交样例',
    target: '目标数据',
    test: '待预测数据',
    train: '训练数据',
  }
  return labels[role] ?? '数据文件'
}

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
    title: '需求来源',
    status: authorityStatus.value,
    detail: originalRequirementsText.value
      ? `已保留 ${originalRequirementsText.value.length} 字原始需求，并登记 ${authoritySources.value.length} 条权威来源或优先级。`
      : '等待读取原始需求与权威说明。',
  },
  {
    id: 'modeling',
    index: '02',
    title: '任务与数据',
    status: modelingStatus.value,
    detail: `${paradigmLabel.value}；已整理 ${dataFiles.value.length} 个数据文件。`,
  },
  {
    id: 'evaluation',
    index: '03',
    title: '评价标准',
    status: evaluationStatus.value,
    detail: Object.keys(evaluationFinal.value).length > 0
      ? `${primaryMetric.value}${metricDirection.value ? ` · ${metricDirection.value}` : ''}；${constraints.value.length} 条约束。`
      : '等待生成可执行的评价公式和非法解处理规则。',
  },
  {
    id: 'delivery',
    index: '04',
    title: '结果与交付',
    status: deliveryStatus.value,
    detail: descriptionText.value
      ? `任务说明已生成；搜索所需的任务信息${automlContextText.value ? '已齐备' : '尚待补齐'}。`
      : '等待固化任务书、输出格式与机器上下文。',
  },
])

const overallStatus = computed(() => {
  if (deliveryStatus.value === 'completed' && evaluationPassed.value && riskItems.value.length === 0) {
    return { label: '任务定义已就绪', tone: 'completed' as ContractStatus }
  }
  if (riskItems.value.length > 0 || evaluationStatus.value === 'warning' || deliveryStatus.value === 'warning') {
    return { label: '存在待确认项', tone: 'warning' as ContractStatus }
  }
  if (props.activeStepRunning) return { label: '任务定义处理中', tone: 'running' as ContractStatus }
  return { label: '等待任务定义', tone: 'pending' as ContractStatus }
})

const contractSummary = computed(() => firstText(
  taskOverview.value,
  taskGoal.value,
  '任务定义信息将在分析完成后显示。',
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
        <div class="hero-title-row">
          <h2 class="hero-title">任务定义</h2>
          <span class="hero-state" :class="overallStatus.tone">{{ overallStatus.label }}</span>
        </div>
        <p class="hero-summary">{{ contractSummary }}</p>
        <div class="hero-tags">
          <span>{{ paradigmLabel }}</span>
          <span v-if="primaryMetric !== '待定义'">指标 {{ primaryMetric }}</span>
          <span>{{ dataFiles.length }} 个数据文件</span>
          <span>{{ riskItems.length }} 个待确认项</span>
        </div>
      </div>

      <div class="readiness-board">
        <div>
          <span>任务书</span>
          <strong>{{ descriptionText ? '已生成' : '待生成' }}</strong>
        </div>
        <div>
          <span>评价规则</span>
          <strong>{{ evaluationPassed ? '已通过' : Object.keys(evaluationFinal).length ? '待确认' : '待生成' }}</strong>
        </div>
        <div>
          <span>搜索信息</span>
          <strong>{{ automlContextText ? '已齐备' : '待补齐' }}</strong>
        </div>
      </div>
    </header>

    <template v-if="hasContent">
      <section class="phase-rail" aria-label="任务定义进度">
        <article v-for="phase in phases" :key="phase.id" class="phase-card" :class="phase.status">
          <div class="phase-top">
            <span class="phase-index">{{ phase.index }}</span>
            <span class="phase-status" :class="phase.status">{{ statusLabel(phase.status) }}</span>
          </div>
          <h3>{{ phase.title }}</h3>
          <p class="phase-detail">{{ phase.detail }}</p>
        </article>
      </section>

      <section class="contract-grid">
        <article class="contract-card modeling-card wide">
          <header class="card-header">
            <div>
              <h3>任务目标与方法范围</h3>
            </div>
            <span class="card-badge">{{ paradigmLabel }}</span>
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
            <strong>方法说明</strong>
            <span v-for="note in methodNotes" :key="note">{{ note }}</span>
          </div>
        </article>

        <article class="contract-card data-card">
          <header class="card-header">
            <div>
              <h3>使用的数据</h3>
            </div>
            <span class="card-count">{{ dataFiles.length }}</span>
          </header>
          <div v-if="dataFiles.length > 0" class="file-list">
            <article v-for="file in dataFiles.slice(0, 8)" :key="file.path" class="file-row">
              <div>
                <strong>{{ file.path }}</strong>
                <span>{{ fileRoleLabel(file.role) }}</span>
              </div>
              <p v-if="file.summary">{{ file.summary }}</p>
              <div class="file-meta">
                <span v-if="file.sheets.length > 0">工作表 {{ file.sheets.join(', ') }}</span>
                <span v-if="file.fieldCount > 0">{{ file.fieldCount }} 个字段</span>
              </div>
            </article>
            <p v-if="dataFiles.length > 8" class="more-copy">其余 {{ dataFiles.length - 8 }} 个文件已写入最终数据访问协议。</p>
          </div>
          <p v-else class="empty-copy">数据清单尚未生成。</p>
        </article>

        <article class="contract-card constraint-card">
          <header class="card-header">
            <div>
              <h3>业务约束</h3>
            </div>
            <span class="card-count">{{ constraints.length }}</span>
          </header>
          <ol v-if="constraints.length > 0" class="contract-list numbered">
            <li v-for="item in constraints" :key="item">{{ item }}</li>
          </ol>
          <p v-else class="empty-copy">暂未整理业务约束。</p>
        </article>

        <article class="contract-card evaluation-card wide">
          <header class="card-header">
            <div>
              <h3>评价标准</h3>
            </div>
            <span class="contract-pass" :class="evaluationPassed ? 'passed' : 'review'">
              {{ evaluationPassed ? '已通过' : Object.keys(evaluationFinal).length ? '待确认' : '待生成' }}
            </span>
          </header>

          <div class="metric-layout">
            <div class="metric-main">
              <span>评价指标</span>
              <strong>{{ primaryMetric }}</strong>
              <small v-if="metricDirection">{{ metricDirection }}</small>
            </div>
            <div class="formula-box">
              <span>评分公式</span>
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
              <h3>输出与交付</h3>
            </div>
            <span class="card-badge">{{ outputColumns.length }} 个字段</span>
          </header>
          <p class="output-copy">{{ outputSummary }}</p>

          <div v-if="outputFiles.length > 0" class="output-files">
            <span v-for="file in outputFiles" :key="file">{{ file }}</span>
          </div>

          <div v-if="outputColumns.length > 0" class="column-cloud">
            <span v-for="column in outputColumns" :key="column">{{ column }}</span>
          </div>
          <p v-else class="empty-copy">尚未定义固定结果字段，具体要求见任务说明。</p>
        </article>
      </section>

      <section class="risk-panel" :class="{ clear: riskItems.length === 0 }">
        <header class="risk-header">
          <div>
            <h3>{{ riskItems.length > 0 ? '待确认问题' : '暂无待确认问题' }}</h3>
          </div>
          <span>{{ riskItems.length }}</span>
        </header>

        <ul v-if="riskItems.length > 0" class="risk-list">
          <li v-for="item in riskItems" :key="item">{{ item }}</li>
        </ul>
        <p v-else class="clear-copy">当前没有需要人工确认的问题。</p>

        <div v-if="evaluationFixes.length > 0" class="fix-strip">
          <strong>建议修正</strong>
          <span v-for="item in evaluationFixes" :key="item">{{ item }}</span>
        </div>

        <details v-if="revisionLog.length > 0 || reflectionLog.length > 0" class="history-details">
          <summary>查看评价规则修订记录（{{ revisionLog.length + reflectionLog.length }} 条）</summary>
          <div class="history-grid">
            <article v-for="(row, index) in revisionLog" :key="`revision-${index}`">
              <strong>第 {{ row.round ?? index + 1 }} 次修订</strong>
              <span>{{ row.passed === true ? '已通过' : row.passed === false ? '未通过' : '结果未记录' }}</span>
              <p>{{ unique([...collectText(row.issues), ...collectText(row.defects)]).join('；') || '无详细问题。' }}</p>
            </article>
            <article v-for="(row, index) in reflectionLog" :key="`reflection-${index}`">
              <strong>第 {{ row.round ?? index + 1 }} 次复核</strong>
              <span>{{ row.is_unambiguous === true ? '未发现歧义' : row.is_unambiguous === false ? '发现歧义' : '结果未记录' }}</span>
              <p>{{ unique(collectText(row.ambiguity_points)).join('；') || '无歧义点。' }}</p>
            </article>
          </div>
        </details>
      </section>
    </template>

    <div v-else class="contract-empty">
      <strong>尚无任务定义结果</strong>
      <p>完成数据分析后，这里会显示已整理的目标、数据、评价标准和交付要求。</p>
    </div>
  </section>
</template>

<style scoped>
.contract-workbench {
  --ink: #1d1d1f;
  --muted: #6e6e73;
  --line: #d2d2d7;
  --teal: #0071e3;
  display: grid;
  gap: 22px;
  min-width: 0;
}

.contract-hero {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 24px;
  padding: 4px 0 20px;
  border-bottom: 1px solid var(--line);
}

.hero-copy,
.readiness-board {
  min-width: 0;
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
  font-size: 27px;
  font-weight: 650;
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
  border-radius: 4px;
  font-size: 11px;
  font-weight: 700;
}

.hero-state {
  padding: 4px 8px;
  border-radius: 4px;
}

.hero-state.completed,
.phase-status.completed {
  background: #e8f5ec;
  color: #1b6c4e;
}

.hero-state.running,
.phase-status.running {
  background: #e8f2ff;
  color: #075db5;
}

.hero-state.warning,
.phase-status.warning {
  background: #fff4d6;
  color: #93611b;
}

.hero-state.pending,
.phase-status.pending {
  background: #f5f5f7;
  color: #6e6e73;
}

.hero-summary {
  max-width: 900px;
  margin: 11px 0 0;
  color: #424245;
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
  padding: 4px 7px;
  border: 1px solid #d2d2d7;
  border-radius: 4px;
  background: #fff;
  color: #515154;
}

.readiness-board {
  display: grid;
  grid-template-columns: repeat(3, minmax(94px, 1fr));
  gap: 0;
  align-self: end;
}

.readiness-board div {
  padding: 4px 12px;
  border-left: 1px solid var(--line);
}

.readiness-board span,
.readiness-board strong {
  display: block;
}

.readiness-board span {
  color: var(--muted);
  font-size: 10px;
}

.readiness-board strong {
  margin-top: 5px;
  color: #1d1d1f;
  font-size: 15px;
}

.phase-rail {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 0;
  border-top: 1px solid var(--line);
  border-bottom: 1px solid var(--line);
}

.phase-card {
  min-width: 0;
  min-height: 124px;
  padding: 14px 12px;
  border-right: 1px solid var(--line);
  background: transparent;
}

.phase-card:last-child {
  border-right: 0;
}

.phase-index {
  color: #86868b;
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
  font-size: 15px;
}

.phase-detail {
  margin: 8px 0 0;
  color: #6e6e73;
  font-size: 12px;
  line-height: 1.55;
}

.contract-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 20px 28px;
}

.contract-card,
.risk-panel,
.contract-empty {
  min-width: 0;
  padding: 16px 0;
  border-bottom: 1px solid var(--line);
  background: transparent;
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
  padding: 4px 7px;
  border: 1px solid var(--line);
  border-radius: 4px;
  background: #fff;
  color: #424245;
}

.card-count {
  display: grid;
  place-items: center;
  min-width: 28px;
  height: 28px;
  border-radius: 4px;
  font-size: 12px;
  font-weight: 800;
}

.goal-copy {
  margin: 14px 0 0;
  color: #1d1d1f;
  font-size: 16px;
  font-weight: 700;
  line-height: 1.65;
}

.reason-copy,
.output-copy,
.scope-copy {
  margin: 10px 0 0;
  color: #515154;
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
  padding: 10px 0;
  border-top: 1px solid var(--line);
  background: transparent;
}

.modeling-grid strong,
.evaluation-columns strong {
  color: #1d1d1f;
  font-size: 12px;
}

.modeling-grid ul,
.contract-list {
  margin: 9px 0 0;
  padding-left: 19px;
  color: #424245;
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
  border-top: 1px solid var(--line);
}

.method-notes strong {
  color: #1d1d1f;
  font-size: 11px;
}

.method-notes span {
  padding: 5px 8px;
  background: #f5f5f7;
  color: #515154;
}

.file-list {
  display: grid;
  gap: 8px;
  margin-top: 13px;
}

.file-row {
  padding: 10px 0;
  border-bottom: 1px solid var(--line);
  background: transparent;
}

.file-row > div:first-child {
  display: flex;
  justify-content: space-between;
  gap: 10px;
}

.file-row strong {
  color: #1d1d1f;
  font-size: 12px;
  overflow-wrap: anywhere;
}

.file-row > div:first-child span {
  color: #6e6e73;
  font-size: 10px;
  text-align: right;
}

.file-row p {
  display: -webkit-box;
  margin: 7px 0 0;
  overflow: hidden;
  color: #515154;
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
  background: #f5f5f7;
  color: #515154;
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
  border-radius: 4px;
}

.contract-pass.passed {
  background: #e8f5ec;
  color: #1b6e4e;
}

.contract-pass.review {
  background: #fff4d6;
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
  padding: 12px 0;
}

.metric-main {
  color: #1d1d1f;
}

.metric-main span,
.metric-main strong,
.metric-main small {
  display: block;
}

.metric-main span,
.formula-box span {
  font-size: 10px;
  font-weight: 600;
}

.metric-main span {
  color: #6e6e73;
}

.metric-main strong {
  margin-top: 8px;
  font-size: 20px;
  overflow-wrap: anywhere;
}

.metric-main small {
  margin-top: 8px;
  color: #6e6e73;
}

.formula-box {
  border-top: 1px solid var(--line);
  border-bottom: 1px solid var(--line);
  background: #f5f5f7;
}

.formula-box span {
  color: #6e6e73;
}

.formula-box code {
  display: block;
  margin-top: 9px;
  color: #1d1d1f;
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
  padding: 4px 7px;
  background: #f5f5f7;
  color: #424245;
  font-family: Consolas, monospace;
}

.column-cloud {
  margin-top: 12px;
  padding: 10px 0;
  border-top: 1px solid var(--line);
  border-bottom: 1px solid var(--line);
  background: transparent;
}

.column-cloud span {
  padding: 3px 0;
  background: #ffffff;
  color: #515154;
  font-family: Consolas, monospace;
}

.risk-panel {
  border-color: var(--line);
  background: transparent;
}

.risk-panel.clear {
  border-color: var(--line);
  background: transparent;
}

.risk-header > span {
  display: grid;
  place-items: center;
  width: 34px;
  height: 34px;
  border-radius: 4px;
  background: #fff4d6;
  color: #8b5d1e;
  font-weight: 800;
}

.risk-panel.clear .risk-header > span {
  background: #e8f5ec;
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
  padding: 9px 0;
  border-bottom: 1px solid var(--line);
  background: transparent;
  color: #424245;
  font-size: 12px;
  line-height: 1.5;
}

.fix-strip {
  display: flex;
  flex-wrap: wrap;
  gap: 7px;
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px solid var(--line);
}

.fix-strip strong,
.fix-strip span {
  color: #515154;
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
  color: #515154;
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
  padding: 10px 0;
  border-bottom: 1px solid var(--line);
  background: transparent;
}

.history-grid strong,
.history-grid span {
  display: block;
  color: #424245;
  font-size: 11px;
}

.history-grid p {
  margin: 7px 0 0;
  color: #6e6e73;
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
    padding: 12px 0;
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
