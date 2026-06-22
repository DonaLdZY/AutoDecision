<script setup lang="ts">
import { computed } from 'vue'
import type { SnapshotPayload } from '../types'

type StepStatus = 'pending' | 'running' | 'completed' | 'failed' | 'warning'

type ProcessStep = {
  id: string
  label: string
  agent: string
  status: StepStatus
  detail: string
  tags: string[]
}

const props = defineProps<{
  snapshot?: SnapshotPayload
  activeStepRunning?: boolean
}>()

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value) ? (value as Record<string, unknown>) : {}
}

function asArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : []
}

function asStringList(value: unknown): string[] {
  return asArray(value)
    .map((item) => String(item ?? '').trim())
    .filter(Boolean)
}

function compactJson(value: unknown) {
  try {
    return JSON.stringify(value ?? {}, null, 2)
  } catch {
    return String(value ?? '')
  }
}

function truncateText(value: unknown, limit = 360) {
  const text = String(value ?? '').trim()
  if (text.length <= limit) return text
  return `${text.slice(0, limit)}...`
}

function statusLabel(status: StepStatus) {
  const labels: Record<StepStatus, string> = {
    pending: '等待',
    running: '进行中',
    completed: '已完成',
    failed: '失败',
    warning: '需关注',
  }
  return labels[status]
}

const ar = computed(() => props.snapshot?.auto_realize ?? {})
const taskDefinitionReport = computed(() => asRecord(ar.value.task_definition_report))
const evaluationContractReport = computed(() => asRecord(ar.value.evaluation_contract_report))
const mainTaskProtocol = computed(() => {
  const fromSnapshot = asRecord(ar.value.main_task_protocol)
  if (Object.keys(fromSnapshot).length > 0) return fromSnapshot
  return asRecord(taskDefinitionReport.value.main_task_protocol)
})
const automlContextPack = computed(() => {
  const fromSnapshot = asRecord(ar.value.automl_context_pack)
  if (Object.keys(fromSnapshot).length > 0) return fromSnapshot
  return asRecord(taskDefinitionReport.value.automl_context_pack)
})
const events = computed(() => (ar.value.events ?? []) as Record<string, unknown>[])
const relevantEvents = computed(() => {
  return events.value
    .filter((row) => {
      const component = String(row.component ?? '')
      return component.includes('task_definition') || component === 'checker.sample_submission'
    })
    .slice(-80)
    .reverse()
})

const originalRequirementsText = computed(() => String(ar.value.original_requirements_text ?? '').trim())
const descriptionText = computed(() => String(ar.value.description_text ?? '').trim())
const taskHint = computed(() => String(taskDefinitionReport.value.task_hint ?? props.snapshot?.task?.config?.auto_realize?.task_hint ?? '').trim())
const plan = computed(() => asRecord(taskDefinitionReport.value.plan))
const planObjectives = computed(() => asStringList(plan.value.objectives))
const planPhases = computed(() => asArray(plan.value.phases).map((item) => asRecord(item)))
const taskClassification = computed(() => asRecord(taskDefinitionReport.value.task_classification))
const downstreamContext = computed(() => asRecord(taskDefinitionReport.value.downstream_context))
const authoritativeTaskMemory = computed(() => {
  const fromSnapshot = asRecord(ar.value.authoritative_task_memory)
  if (Object.keys(fromSnapshot).length > 0) return fromSnapshot
  return asRecord(downstreamContext.value.authoritative_memory)
})
const agentContextPack = computed(() => {
  const fromSnapshot = asRecord(ar.value.agent_context_pack)
  if (Object.keys(fromSnapshot).length > 0) return fromSnapshot
  return asRecord(downstreamContext.value.agent_context_pack)
})
const contextRoutes = computed(() => {
  const fromPack = asRecord(agentContextPack.value.context_routes)
  if (Object.keys(fromPack).length > 0) return fromPack
  return asRecord(downstreamContext.value.context_routes)
})
const descriptionRoute = computed(() => asRecord(contextRoutes.value.description_writer))
const contextPriorityOrder = computed(() => asStringList(agentContextPack.value.priority_order))
const doNotInventRules = computed(() => asStringList(agentContextPack.value.do_not_invent))
const authoritySourceFiles = computed(() => asStringList(authoritativeTaskMemory.value.source_files))
const submissionContract = computed(() => {
  const fromPack = asRecord(agentContextPack.value.submission_contract)
  if (Object.keys(fromPack).length > 0) return fromPack
  return asRecord(downstreamContext.value.authoritative_submission_contract)
})
const artifacts = computed(() => asRecord(taskDefinitionReport.value.artifacts))
const defectsAfterGate = computed(() => asStringList(taskDefinitionReport.value.defects_after_gate))
const retrievedKnowledge = computed(() => {
  const fromSnapshot = asArray(ar.value.retrieved_knowledge)
  if (fromSnapshot.length > 0) return fromSnapshot.map((item) => asRecord(item))
  return asArray(downstreamContext.value.retrieved_knowledge).map((item) => asRecord(item))
})
const generatedSubmissionColumns = computed(() => {
  const generated = asStringList(downstreamContext.value.generated_submission_columns)
  if (generated.length > 0) return generated
  return asStringList(downstreamContext.value.submission_columns)
})
const actualGeneratedSubmissionColumns = computed(() => asStringList(downstreamContext.value.generated_submission_columns))
const submissionReport = computed(() => asRecord(ar.value.submission_report))
const sampleSubmissionRequested = computed(() => {
  const fromContext = downstreamContext.value.sample_submission_generation_requested
  if (typeof fromContext === 'boolean') return fromContext
  return props.snapshot?.task?.config?.auto_realize?.generate_sample_submission !== false
})
const sampleSubmissionSource = computed(() => {
  return String(submissionReport.value.source ?? downstreamContext.value.sample_submission_generation_status ?? '').trim()
})
const sampleSubmissionIssues = computed(() => {
  const fromReport = asStringList(submissionReport.value.issues)
  if (fromReport.length > 0) return fromReport
  return asStringList(downstreamContext.value.sample_submission_generation_issues)
})
const sampleSubmissionAvailable = computed(() => {
  if (Boolean(downstreamContext.value.sample_submission_available)) return true
  return actualGeneratedSubmissionColumns.value.length > 0 || Boolean(artifacts.value.sample_submission)
})
const sampleSubmissionSoftSkipped = computed(() => {
  return sampleSubmissionRequested.value
    && !sampleSubmissionAvailable.value
    && sampleSubmissionSource.value === 'skipped_generation_failed'
})
const sampleSubmissionSkipped = computed(() => {
  return [
    'not_applicable',
    'skipped_no_authoritative_contract',
    'disabled_by_config',
    'skipped_generation_failed',
    'not_required_by_problem_paradigm',
  ].includes(sampleSubmissionSource.value)
})
const sampleSubmissionDetail = computed(() => {
  if (!sampleSubmissionRequested.value || sampleSubmissionSource.value === 'disabled_by_config') {
    return '已按配置跳过 sample_submission.csv 生成；下游以 description.md 中的任务定义和评估协议为准。'
  }
  if (sampleSubmissionAvailable.value) {
    return generatedSubmissionColumns.value.length > 0
      ? `已生成或识别提交列：${generatedSubmissionColumns.value.join(', ')}。`
      : '已复用官方 sample_submission.csv。'
  }
  if (sampleSubmissionSoftSkipped.value) {
    const reason = String(submissionReport.value.reason ?? '').trim()
    const issueText = sampleSubmissionIssues.value.slice(0, 2).join('；')
    return `sample_submission.csv 多轮生成/检查后仍未通过，已软跳过，不中断任务定义。${reason || issueText || ''}`
  }
  if (sampleSubmissionSkipped.value) {
    const reason = String(submissionReport.value.reason ?? '').trim()
    return reason || '未发现权威提交合同，已跳过 sample_submission.csv 生成。'
  }
  return '由 LLM 生成提交样例，并通过 checker 校验列顺序和 DataFrame 合法性。'
})
const sampleSubmissionTags = computed(() => {
  if (!sampleSubmissionRequested.value) return ['disabled']
  if (sampleSubmissionAvailable.value) return generatedSubmissionColumns.value.slice(0, 4)
  const tags = [sampleSubmissionSource.value || 'pending', ...sampleSubmissionIssues.value.slice(0, 3)]
  return tags.filter(Boolean)
})

const evaluationFinal = computed(() => {
  const final = asRecord(evaluationContractReport.value.final)
  if (Object.keys(final).length > 0) return final
  return asRecord(taskDefinitionReport.value.evaluation_contract)
})
const revisionLog = computed(() => asArray(evaluationContractReport.value.revision_log).map((item) => asRecord(item)))
const reflectionLog = computed(() => asArray(evaluationContractReport.value.reflection_log).map((item) => asRecord(item)))
const latestReflection = computed(() => reflectionLog.value[reflectionLog.value.length - 1] ?? {})
const evaluationIssues = computed(() => asStringList(evaluationFinal.value.issues))
const evaluationFixes = computed(() => asStringList(evaluationFinal.value.fixes))

function eventRows(componentName: string, exact: boolean) {
  return events.value.filter((row) => {
    const component = String(row.component ?? '')
    return exact ? component === componentName : component.includes(componentName)
  })
}

function rowEvent(row: Record<string, unknown>) {
  return String(row.event ?? '').toUpperCase()
}

function eventStatus(componentName: string, exact: boolean, completedEvents = ['COMPLETED']): StepStatus {
  const rows = eventRows(componentName, exact)
  if (rows.some((row) => ['FAILED', 'ERROR'].includes(rowEvent(row)))) return 'failed'
  if (rows.some((row) => completedEvents.includes(rowEvent(row)))) return 'completed'
  if (rows.some((row) => ['ACTIVATED', 'GENERATING_FILE', 'REVIEWED'].includes(rowEvent(row)))) return 'running'
  return props.activeStepRunning ? 'running' : 'pending'
}

function fileEventStatus(fileName: string, completedArtifact: boolean): StepStatus {
  if (completedArtifact) return 'completed'
  const rows = events.value.filter((row) => {
    if (String(row.component ?? '') !== 'module.task_definition') return false
    const fields = asRecord(row.fields)
    return String(fields.file ?? '') === fileName || String(fields.file ?? '') === `realize_report/${fileName}`
  })
  if (rows.some((row) => ['FAILED', 'ERROR'].includes(rowEvent(row)))) return 'failed'
  if (rows.some((row) => rowEvent(row) === 'GENERATED_FILE')) return 'completed'
  if (rows.some((row) => rowEvent(row) === 'SKIPPED')) return 'completed'
  if (rows.some((row) => rowEvent(row) === 'GENERATING_FILE')) return 'running'
  return props.activeStepRunning ? 'running' : 'pending'
}

const evaluationStatus = computed<StepStatus>(() => {
  if (!Object.keys(evaluationFinal.value).length) return eventStatus('module.task_definition.evaluation_contract', false)
  if (Boolean(evaluationFinal.value.passed)) return 'completed'
  return 'warning'
})
const reflectionStatus = computed<StepStatus>(() => {
  if (reflectionLog.value.length === 0) return eventStatus('module.task_definition.eval_reflector', false)
  if (Boolean(latestReflection.value.is_unambiguous)) return 'completed'
  return 'warning'
})
const sampleSubmissionStatus = computed<StepStatus>(() => {
  if (sampleSubmissionSoftSkipped.value) return 'warning'
  if (!sampleSubmissionRequested.value || sampleSubmissionSource.value === 'disabled_by_config') return 'completed'
  if (sampleSubmissionSkipped.value && !sampleSubmissionAvailable.value) return 'completed'
  if (sampleSubmissionAvailable.value) return 'completed'
  return fileEventStatus('sample_submission.csv', false)
})
const finalDescriptionStatus = computed<StepStatus>(() => {
  return fileEventStatus('description.md', Boolean(descriptionText.value || artifacts.value.description))
})
const protocolStatus = computed<StepStatus>(() => {
  return Object.keys(mainTaskProtocol.value).length > 0 || Object.keys(automlContextPack.value).length > 0
    ? 'completed'
    : fileEventStatus('main_task_protocol.json', false)
})

const processSteps = computed<ProcessStep[]>(() => {
  const hasTaskReport = Object.keys(taskDefinitionReport.value).length > 0
  const originalStatus: StepStatus = originalRequirementsText.value || taskHint.value
    ? 'completed'
    : eventStatus('module.task_definition', true, ['CREATED', 'ACTIVATED', 'COMPLETED'])
  const plannerStatus: StepStatus = Object.keys(plan.value).length > 0
    ? 'completed'
    : eventStatus('module.task_definition.intent', true)
  const classifierStatus: StepStatus = Object.keys(taskClassification.value).length > 0
    ? 'completed'
    : eventStatus('module.task_definition.classifier', true)
  const contextStatus: StepStatus = Object.keys(agentContextPack.value).length > 0 || authoritySourceFiles.value.length > 0
    ? 'completed'
    : eventStatus('module.data_cognition.authority', true)
  const knowledgeStatus: StepStatus = retrievedKnowledge.value.length > 0 || hasTaskReport
    ? 'completed'
    : eventStatus('module.task_definition', true)
  const qualityStatus: StepStatus = hasTaskReport || descriptionText.value
    ? (defectsAfterGate.value.length > 0 ? 'warning' : 'completed')
    : eventStatus('module.task_definition.quality_gate', true)

  return [
    {
      id: 'requirements',
      label: '原始需求读取',
      agent: 'Requirement Reader',
      status: originalStatus,
      detail: originalRequirementsText.value
        ? `已保存 original_requirements.txt，约 ${originalRequirementsText.value.length} 字。`
        : '等待从任务提示与原始需求文件汇总赛题目标。',
      tags: taskHint.value ? ['task_hint'] : [],
    },
    {
      id: 'planner',
      label: 'Planner 兼容计划',
      agent: 'Intent Architect',
      status: plannerStatus,
      detail: planObjectives.value[0] ?? '低成本模式下保留兼容计划对象，主事实源由范式分类和协议包接管。',
      tags: [`目标 ${planObjectives.value.length}`, `阶段 ${planPhases.value.length}`],
    },
    {
      id: 'classifier',
      label: '任务范式分类',
      agent: 'Problem Paradigm Classifier',
      status: classifierStatus,
      detail: String(taskClassification.value.reasoning ?? '判断 ML/DL、优化、RL、混合或可执行未知范式。'),
      tags: [
        String(taskClassification.value.task_type ?? '').trim(),
        String(taskClassification.value.primary_metric ?? '').trim(),
      ].filter(Boolean),
    },
    {
      id: 'context-router',
      label: '权威上下文路由',
      agent: 'Context Router',
      status: contextStatus,
      detail: contextPriorityOrder.value.length > 0
        ? `已固定 ${contextPriorityOrder.value.length} 条上下文优先级，并为 description/evaluation/sample builder/AutoML 分配证据。`
        : '等待数据认知阶段写入 authoritative_task_memory.json 与 agent_context_pack.json。',
      tags: [
        authoritySourceFiles.value.length > 0 ? `权威源 ${authoritySourceFiles.value.length}` : '',
        Boolean(submissionContract.value.is_defined) ? '提交合同已定义' : '未定义提交合同',
      ].filter(Boolean),
    },
    {
      id: 'knowledge',
      label: '相关知识检索',
      agent: 'Knowledge Retriever',
      status: knowledgeStatus,
      detail: retrievedKnowledge.value.length > 0
        ? `已召回 ${retrievedKnowledge.value.length} 条与指标、约束、字段和文件摘要相关的证据。`
        : '等待根据数据认知结果检索指标、约束与字段证据。',
      tags: retrievedKnowledge.value.slice(0, 3).map((item) => String(item.kind ?? item.source ?? 'evidence')),
    },
    {
      id: 'sample',
      label: 'sample_submission 生成/跳过',
      agent: 'Submission Builder',
      status: sampleSubmissionStatus.value,
      detail: sampleSubmissionDetail.value,
      tags: sampleSubmissionTags.value,
    },
    {
      id: 'quality',
      label: 'description 初稿与质量门',
      agent: 'Description Writer',
      status: qualityStatus,
      detail: defectsAfterGate.value.length > 0
        ? `质量门仍记录 ${defectsAfterGate.value.length} 条需关注项。`
        : '按数据认知、原始需求与任务协议生成赛题描述初稿。',
      tags: defectsAfterGate.value.slice(0, 2),
    },
    {
      id: 'evaluation',
      label: 'Evaluation Contract Agent',
      agent: 'Metric Auditor',
      status: evaluationStatus.value,
      detail: String(evaluationFinal.value.rationale ?? evaluationFinal.value.metric_formula ?? '审查指标是否唯一、可执行、不可作弊。'),
      tags: [
        String(evaluationFinal.value.primary_metric ?? '').trim(),
        String(evaluationFinal.value.metric_direction ?? '').trim(),
        `返修 ${revisionLog.value.length}`,
      ].filter(Boolean),
    },
    {
      id: 'reflection',
      label: 'Evaluation 分段反思',
      agent: 'Ambiguity Reflector',
      status: reflectionStatus.value,
      detail: reflectionLog.value.length > 0
        ? `已反思 ${reflectionLog.value.length} 轮，最后一轮 ${Boolean(latestReflection.value.is_unambiguous) ? '认为无歧义' : '仍有歧义点'}。`
        : '单独检查 Evaluation 与 Submission Format 两段是否严谨。',
      tags: asStringList(latestReflection.value.ambiguity_points).slice(0, 2),
    },
    {
      id: 'main-protocol',
      label: '主协议与 AutoML Context',
      agent: 'Protocol Renderer',
      status: protocolStatus.value,
      detail: Object.keys(mainTaskProtocol.value).length > 0
        ? '已生成 main_task_protocol.json，并派生机器读版 automl_context_pack / automl_context.md。'
        : '等待写入统一主任务协议和 AutoML 机器上下文。',
      tags: [
        String(mainTaskProtocol.value.schema_version ?? '').trim(),
        String(automlContextPack.value.problem_paradigm ?? '').trim(),
      ].filter(Boolean),
    },
    {
      id: 'final',
      label: '最终 description.md 写入',
      agent: 'Artifact Writer',
      status: finalDescriptionStatus.value,
      detail: descriptionText.value
        ? `最终赛题描述已写入，约 ${descriptionText.value.length} 字。`
        : '等待把返修后的 Evaluation 和 Submission Format 同步回 description.md。',
      tags: [String(artifacts.value.description ?? '').trim()].filter(Boolean),
    },
  ]
})

const originalPreview = computed(() => truncateText(originalRequirementsText.value || taskHint.value, 900))
const planPreview = computed(() => compactJson({
  objectives: planObjectives.value,
  phases: planPhases.value.map((phase) => ({
    title: phase.title ?? phase.phase_id,
    objective: phase.objective,
    outputs: phase.outputs,
  })),
  evaluation_metric: plan.value.evaluation_metric,
  submission_spec: plan.value.submission_spec,
}))
const classifierPreview = computed(() => compactJson(taskClassification.value))
const contextRouterPreview = computed(() => compactJson({
  authoritative_sources: authoritySourceFiles.value,
  submission_contract: {
    is_defined: submissionContract.value.is_defined,
    is_authoritative: submissionContract.value.is_authoritative,
    source: submissionContract.value.source,
    columns: submissionContract.value.columns,
  },
  priority_order: contextPriorityOrder.value,
  do_not_invent: doNotInventRules.value,
  description_route: descriptionRoute.value,
}))
const evaluationPreview = computed(() => compactJson({
  passed: evaluationFinal.value.passed,
  primary_metric: evaluationFinal.value.primary_metric,
  metric_direction: evaluationFinal.value.metric_direction,
  metric_formula: evaluationFinal.value.metric_formula,
  submission_checks: evaluationFinal.value.submission_checks,
  invalid_solution_rules: evaluationFinal.value.invalid_solution_rules,
}))
const protocolPreview = computed(() => compactJson({
  schema_version: mainTaskProtocol.value.schema_version,
  problem_paradigm: asRecord(mainTaskProtocol.value.problem_paradigm).problem_paradigm,
  authority_conflicts: mainTaskProtocol.value.authority_conflicts,
  downstream_context_evidence: mainTaskProtocol.value.downstream_context_evidence,
  automl_context: {
    schema_version: automlContextPack.value.schema_version,
    problem_paradigm: automlContextPack.value.problem_paradigm,
    data_access_entries: asArray(automlContextPack.value.data_access).length,
  },
}))
const latestEvents = computed(() => relevantEvents.value.slice(0, 14))

function eventTitle(row: Record<string, unknown>) {
  return `${String(row.component ?? '-')}.${String(row.event ?? '-')}`
}

function eventDetail(row: Record<string, unknown>) {
  const fields = asRecord(row.fields)
  const pieces = [
    fields.file ? `file=${fields.file}` : '',
    fields.round ? `round=${fields.round}` : '',
    fields.passed !== undefined ? `passed=${fields.passed}` : '',
    fields.defects !== undefined ? `defects=${fields.defects}` : '',
    fields.issues !== undefined ? `issues=${fields.issues}` : '',
    fields.primary_metric ? `metric=${fields.primary_metric}` : '',
  ].filter(Boolean)
  return pieces.join(' | ')
}
</script>

<template>
  <section class="process-panel">
    <header class="process-header">
      <div>
        <p class="eyebrow">Task Definition Trace</p>
        <h4>赛题描述生成过程</h4>
      </div>
      <span class="report-pill">{{ Object.keys(taskDefinitionReport).length > 0 ? 'report ready' : 'waiting report' }}</span>
    </header>

    <div class="step-grid">
      <article v-for="step in processSteps" :key="step.id" class="step-card" :class="step.status">
        <div class="step-top">
          <span class="step-dot" :class="step.status"></span>
          <span class="step-status" :class="step.status">{{ statusLabel(step.status) }}</span>
        </div>
        <h5>{{ step.label }}</h5>
        <p class="agent">{{ step.agent }}</p>
        <p class="detail">{{ truncateText(step.detail, 180) }}</p>
        <div v-if="step.tags.length > 0" class="tag-row">
          <span v-for="tag in step.tags.slice(0, 4)" :key="`${step.id}-${tag}`">{{ truncateText(tag, 42) }}</span>
        </div>
      </article>
    </div>

    <div class="detail-grid">
      <article class="detail-card">
        <h5>原始需求</h5>
        <pre>{{ originalPreview || '尚未读取 original_requirements.txt 或 task_hint。' }}</pre>
      </article>

      <article class="detail-card">
        <h5>Planner 兼容计划</h5>
        <pre>{{ Object.keys(plan).length > 0 ? planPreview : 'Planner 计划尚未生成。' }}</pre>
      </article>

      <article class="detail-card">
        <h5>任务分类/范式输出</h5>
        <pre>{{ Object.keys(taskClassification).length > 0 ? classifierPreview : '任务分类器尚未完成。' }}</pre>
      </article>

      <article class="detail-card">
        <h5>权威上下文路由</h5>
        <pre>{{ Object.keys(agentContextPack).length > 0 ? contextRouterPreview : '上下文包尚未生成；等待数据认知阶段写入 agent_context_pack.json。' }}</pre>
      </article>

      <article class="detail-card">
        <h5>主协议与 AutoML Context</h5>
        <pre>{{ Object.keys(mainTaskProtocol).length > 0 || Object.keys(automlContextPack).length > 0 ? protocolPreview : '等待生成 main_task_protocol.json 与 automl_context_pack.json。' }}</pre>
      </article>

      <article class="detail-card">
        <h5>Evaluation Contract</h5>
        <pre>{{ Object.keys(evaluationFinal).length > 0 ? evaluationPreview : 'Evaluation Contract Agent 尚未产出报告。' }}</pre>
      </article>

      <article class="detail-card">
        <h5>返修记录</h5>
        <div v-if="revisionLog.length > 0" class="round-list">
          <article v-for="row in revisionLog.slice(-6)" :key="`revision-${String(row.round)}-${String(row.source)}`">
            <strong>Round {{ row.round }} | {{ row.source }}</strong>
            <span :class="Boolean(row.passed) ? 'ok-text' : 'warn-text'">passed={{ row.passed }}</span>
            <p>{{ truncateText(asStringList(row.issues).join('；') || asStringList(row.defects).join('；') || '无详细问题。', 260) }}</p>
          </article>
        </div>
        <p v-else class="empty">暂无返修记录。</p>
      </article>

      <article class="detail-card">
        <h5>Evaluation 反思</h5>
        <div v-if="reflectionLog.length > 0" class="round-list">
          <article v-for="row in reflectionLog.slice(-6)" :key="`reflection-${String(row.round)}`">
            <strong>Round {{ row.round }}</strong>
            <span :class="Boolean(row.is_unambiguous) ? 'ok-text' : 'warn-text'">unambiguous={{ row.is_unambiguous }}</span>
            <p>{{ truncateText(asStringList(row.ambiguity_points).join('；') || '无歧义点。', 260) }}</p>
          </article>
        </div>
        <p v-else class="empty">暂无分段反思记录。</p>
      </article>

      <article class="detail-card wide">
        <h5>最近赛题描述事件</h5>
        <div v-if="latestEvents.length > 0" class="event-list">
          <article v-for="row in latestEvents" :key="`${String(row.seq ?? '')}-${String(row.ts ?? '')}`">
            <strong>{{ eventTitle(row) }}</strong>
            <span>{{ eventDetail(row) || String(row.ts ?? '') }}</span>
          </article>
        </div>
        <p v-else class="empty">暂无 task_definition 事件。</p>
      </article>

      <article v-if="evaluationIssues.length > 0 || evaluationFixes.length > 0" class="detail-card wide">
        <h5>当前 Evaluation 关注点</h5>
        <div class="issue-grid">
          <div>
            <strong>Issues</strong>
            <p>{{ truncateText(evaluationIssues.join('；') || '无', 520) }}</p>
          </div>
          <div>
            <strong>Fixes</strong>
            <p>{{ truncateText(evaluationFixes.join('；') || '无', 520) }}</p>
          </div>
        </div>
      </article>
    </div>
  </section>
</template>

<style scoped>
.process-panel {
  display: grid;
  gap: 12px;
  min-width: 0;
  max-width: 100%;
  overflow-x: hidden;
}

.process-header,
.detail-card,
.step-card {
  border: 1px solid #d0ddee;
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.96);
  box-sizing: border-box;
  min-width: 0;
  max-width: 100%;
}

.process-header {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: flex-start;
  padding: 12px;
  overflow-wrap: anywhere;
}

.eyebrow {
  margin: 0 0 4px;
  color: #6a82a5;
  font-size: 12px;
}

h4,
h5 {
  margin: 0;
  color: #244a74;
}

.report-pill,
.step-status,
.tag-row span {
  border-radius: 999px;
  padding: 4px 9px;
  font-size: 12px;
}

.report-pill {
  background: #eef5ff;
  color: #315b8a;
}

.step-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
  min-width: 0;
  max-width: 100%;
}

.step-card {
  padding: 11px;
  min-height: 154px;
  border-color: #d7e2f1;
}

.step-card.completed {
  border-color: #b9dfc3;
}

.step-card.running {
  border-color: #9fc0ff;
}

.step-card.warning {
  border-color: #f0d48a;
}

.step-card.failed {
  border-color: #efb0b0;
}

.step-top {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}

.step-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: #99a9be;
}

.step-dot.completed {
  background: #2da65a;
}

.step-dot.running {
  background: #2f73ff;
}

.step-dot.warning {
  background: #d39022;
}

.step-dot.failed {
  background: #dc4848;
}

.step-status {
  background: #eef3fb;
  color: #4c678a;
}

.step-status.completed {
  background: #e5f7ec;
  color: #24753f;
}

.step-status.running {
  background: #e7efff;
  color: #265dd1;
}

.step-status.warning {
  background: #fff7dd;
  color: #8a5b11;
}

.step-status.failed {
  background: #fff0f0;
  color: #ad3333;
}

.agent {
  margin: 6px 0;
  color: #6a7f9b;
  font-size: 12px;
}

.detail {
  margin: 0;
  color: #365273;
  line-height: 1.45;
  font-size: 13px;
}

.tag-row {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 8px;
}

.tag-row span {
  background: #edf4ff;
  color: #315b8a;
  overflow-wrap: anywhere;
}

.detail-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}

.detail-card {
  padding: 12px;
  overflow: hidden;
}

.detail-card.wide {
  grid-column: 1 / -1;
}

.detail-card pre {
  margin: 10px 0 0;
  padding: 10px;
  border-radius: 10px;
  background: #f6f9fe;
  color: #27435f;
  max-height: 280px;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-word;
  font-size: 12px;
  line-height: 1.45;
}

.round-list,
.event-list,
.issue-grid {
  display: grid;
  gap: 8px;
  margin-top: 10px;
}

.round-list article,
.event-list article {
  border-top: 1px dashed #d5e0ef;
  padding-top: 8px;
  color: #365273;
  font-size: 13px;
}

.round-list strong,
.event-list strong {
  display: block;
  color: #244a74;
}

.round-list span,
.event-list span {
  color: #677f9e;
  overflow-wrap: anywhere;
}

.ok-text {
  color: #207d43 !important;
}

.warn-text {
  color: #9b6118 !important;
}

.issue-grid {
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.issue-grid div {
  border-radius: 12px;
  border: 1px solid #d9e4f2;
  background: #f8fbff;
  padding: 10px;
}

.issue-grid p,
.empty {
  color: #5d789c;
  line-height: 1.5;
}

@media (max-width: 1100px) {
  .step-grid,
  .detail-grid,
  .issue-grid {
    grid-template-columns: 1fr;
  }
}
</style>
