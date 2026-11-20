<script setup lang="ts">
import { computed, shallowRef, watch } from 'vue'
import {
  asArray,
  asRecord,
  deriveQdiLiveProgress,
  isResolvedQdiStatus,
  isTerminalQdiStatus,
  normalizeQdiQuestions,
  qdiCategoryLabel,
  qdiFileName,
  qdiPriorityLabel,
  textList,
} from '../utils/qdiPresentation'
import type { QdiQuestionView } from '../utils/qdiPresentation'

const props = withDefaults(defineProps<{
  report?: Record<string, unknown>
  events?: Record<string, unknown>[]
  currentState?: Record<string, unknown>
  enabled?: boolean
}>(), {
  report: () => ({}),
  events: () => [],
  currentState: () => ({}),
  enabled: true,
})

const selectedQuestionId = shallowRef('')

const liveProgress = computed(() => deriveQdiLiveProgress(props.events, props.report))
const questions = computed<QdiQuestionView[]>(() => {
  const merged = new Map<string, QdiQuestionView>()
  for (const question of liveProgress.value.eventQuestions) merged.set(question.id, question)
  for (const question of normalizeQdiQuestions(props.report)) merged.set(question.id, question)
  return [...merged.values()]
})
const scriptRequests = computed(() => asArray(props.report.script_requests).map(asRecord))
const stepResults = computed(() => asArray(props.report.step_results).map(asRecord))
const actionHistory = computed(() => asArray(props.report.action_history).map(asRecord))
const digestCards = computed(() => asArray(props.report.action_digest_cards).map(asRecord))
const workingMemoryCards = computed(() => asArray(props.report.working_memory_cards).map(asRecord))
const reportSummary = computed(() => String(props.report.summary ?? '').trim())

watch(questions, (rows) => {
  if (rows.some((row) => row.id === selectedQuestionId.value)) return
  selectedQuestionId.value = rows[0]?.id ?? ''
}, { immediate: true })

const selectedQuestion = computed(() => {
  return questions.value.find((row) => row.id === selectedQuestionId.value) ?? null
})

const resolvedCount = computed(() => questions.value.filter((row) => isResolvedQdiStatus(row.status)).length)
const unresolvedCount = computed(() => questions.value.filter((row) => row.status === 'unresolved' || Boolean(row.unresolvedReason)).length)
const terminalCount = computed(() => questions.value.filter((row) => isTerminalQdiStatus(row.status)).length)
const currentQuestion = computed(() => {
  return questions.value.find((row) => row.id === liveProgress.value.currentQuestionId) ?? null
})
const pipelineStatus = computed(() => String(props.currentState.status ?? '').toLowerCase())

const workbenchStatus = computed(() => {
  if (!props.enabled) return { label: '已关闭', tone: 'idle' }
  if (liveProgress.value.active) return { label: '调查进行中', tone: 'running' }
  if (questions.value.length === 0) return { label: '等待调查', tone: 'idle' }
  if (unresolvedCount.value > 0) return { label: '有待确认项', tone: 'warning' }
  if (resolvedCount.value === questions.value.length) return { label: '调查完成', tone: 'complete' }
  if (terminalCount.value === questions.value.length) return { label: '调查结束，结论待复核', tone: 'warning' }
  if (pipelineStatus.value === 'running') return { label: '调查进行中', tone: 'running' }
  return { label: '调查进行中', tone: 'running' }
})

const currentActionLabel = computed(() => {
  const action = liveProgress.value.currentAction
  if (!action) return ''
  const labels: Record<string, string> = {
    decide_next_action: '决定下一步',
    request_script: '执行只读脚本',
    request_checks: '批量核查数据',
    planner_direct_answer: '引用权威原文',
    request_context: '取回相关认知卡片',
    search_document: '检索文档',
    read_document_chunks: '读取文档片段',
    read_qdi_artifact_excerpt: '读取历史证据片段',
    answer: '形成结论',
    give_up: '记录未解决原因',
  }
  return labels[action] ?? '调查处理中'
})

function confidenceLabel(value: unknown) {
  if (typeof value === 'number' && Number.isFinite(value)) {
    return `${Math.round((value <= 1 ? value : value / 100) * 100)}%`
  }
  return String(value ?? '').trim()
}

function actionStatusLabel(value: unknown) {
  const status = String(value ?? '').toLowerCase()
  if (['completed', 'success', 'resolved'].includes(status)) return '已完成'
  if (['running', 'in_progress', 'started'].includes(status)) return '进行中'
  if (['failed', 'error'].includes(status)) return '失败'
  if (['unresolved', 'pending'].includes(status)) return '待处理'
  return '已记录'
}

const selectedScripts = computed(() => {
  const id = selectedQuestionId.value
  return scriptRequests.value.filter((row) => String(row.question_id ?? '') === id)
})

const selectedResults = computed(() => {
  const id = selectedQuestionId.value
  return stepResults.value.filter((row) => String(row.question_id ?? '') === id)
})

const selectedMemory = computed(() => {
  const rows = workingMemoryCards.value
    .filter((row) => String(row.question_id ?? '') === selectedQuestionId.value)
    .sort((a, b) => Number(b.last_updated_sequence ?? 0) - Number(a.last_updated_sequence ?? 0))
  return rows[0] ?? {}
})

const selectedTimeline = computed(() => {
  const id = selectedQuestionId.value
  const digests = new Map<number, Record<string, unknown>>()
  for (const row of digestCards.value) {
    if (String(row.question_id ?? '') !== id) continue
    digests.set(Number(row.digest_for_sequence ?? row.sequence ?? 0), row)
  }

  const timeline = actionHistory.value
    .filter((row) => String(row.question_id ?? '') === id)
    .map((row, index) => {
      const sequence = Number(row.sequence ?? index + 1)
      return { action: row, digest: digests.get(sequence) ?? {}, sequence }
    })

  for (const [sequence, digest] of digests.entries()) {
    if (timeline.some((row) => row.sequence === sequence)) continue
    timeline.push({ action: {}, digest, sequence })
  }
  return timeline.sort((a, b) => a.sequence - b.sequence)
})

function selectQuestion(id: string) {
  selectedQuestionId.value = id
}

function statusLabel(status: string) {
  const normalized = status.toLowerCase()
  if (isResolvedQdiStatus(normalized)) return '已解决'
  if (normalized === 'unresolved') return '未解决'
  if (normalized === 'failed') return '失败'
  if (normalized === 'running' || normalized === 'in_progress') return '调查中'
  return '待调查'
}

function statusTone(status: string) {
  const normalized = status.toLowerCase()
  if (isResolvedQdiStatus(normalized)) return 'complete'
  if (normalized === 'unresolved' || normalized === 'failed') return 'warning'
  if (normalized === 'running' || normalized === 'in_progress') return 'running'
  return 'idle'
}

function compactJson(value: unknown, limit = 1800) {
  let text = ''
  try {
    text = JSON.stringify(value ?? {}, null, 2)
  } catch {
    text = String(value ?? '')
  }
  return text.length > limit ? `${text.slice(0, limit)}\n... 已在界面截断` : text
}

function compactText(value: string, limit = 1400) {
  const text = value.trim()
  if (!text) return ''
  if (/^[\[{]/.test(text)) {
    try {
      return readableResult(JSON.parse(text), limit)
    } catch {
      // Preserve non-JSON output as text.
    }
  }
  return text.length > limit ? `${text.slice(0, limit)}\n…` : text
}

function readableResult(value: unknown, limit = 1400): string {
  if (typeof value === 'string') return compactText(value, limit)
  if (typeof value === 'number' || typeof value === 'boolean') return String(value)
  if (Array.isArray(value)) {
    const lines = value.slice(0, 12).map((item) => {
      return typeof item === 'string' ? item : readableResult(item, 220)
    }).filter(Boolean)
    return lines.join('\n') || '检查已完成。'
  }

  const row = asRecord(value)
  const fields: [string, string[]][] = [
    ['结论', ['conclusion', 'summary', 'message', 'answer', 'status']],
    ['数量', ['count', 'rows', 'matched_rows', 'records']],
    ['字段', ['columns', 'fields']],
    ['异常', ['error', 'reason', 'warning']],
  ]
  const lines = fields.flatMap(([label, keys]) => {
    const key = keys.find((candidate) => row[candidate] !== undefined && row[candidate] !== null)
    if (!key) return []
    const raw = row[key]
    const text = Array.isArray(raw) ? raw.join('、') : String(raw)
    return text ? [`${label}：${text}`] : []
  })
  return lines.join('\n').slice(0, limit) || '检查已完成，详细结构化结果已保存在运行记录中。'
}

function resultArtifact(row: Record<string, unknown>) {
  const result = asRecord(row.result)
  return asRecord(result._full_result_artifact)
}

function resultPreview(row: Record<string, unknown>) {
  const result = asRecord(row.result)
  const artifact = resultArtifact(row)
  const visible = artifact.visible_excerpt
    ?? result.visible_excerpt
    ?? result.stdout
    ?? result.summary
    ?? row.error
  return visible === undefined ? '检查已完成，详细结构化结果已保存在运行记录中。' : readableResult(visible)
}

function resultDetails(row: Record<string, unknown>) {
  return compactJson(row.result ?? { error: row.error }, 8000)
}

function actionName(row: Record<string, unknown>) {
  const action = String(row.action ?? row.event_type ?? '')
  const labels: Record<string, string> = {
    decide_next_action: '选择调查方向',
    request_script: '检查数据',
    request_checks: '核对数据概况',
    planner_direct_answer: '查阅公开资料',
    request_context: '读取相关数据说明',
    search_document: '搜索项目文档',
    read_document_chunks: '阅读项目文档',
    read_qdi_artifact_excerpt: '回看已有调查结果',
    answer: '形成结论',
    give_up: '记录待解决问题',
    refine_current_question: '细化调查问题',
  }
  return labels[action] ?? '调查步骤'
}

function scriptTitle(row: Record<string, unknown>, index: number) {
  return String(row.goal ?? row.reason ?? `检查脚本 ${index + 1}`)
}

function fileLabel(value: string) {
  return qdiFileName(value)
}
</script>

<template>
  <section class="qdi-workbench">
    <header v-if="questions.length > 0 || reportSummary" class="qdi-hero">
      <div class="qdi-hero-copy">
        <div class="qdi-title-row">
          <h3 class="qdi-title">问题调查</h3>
          <span class="qdi-state" :class="workbenchStatus.tone">{{ workbenchStatus.label }}</span>
        </div>
        <p v-if="reportSummary" class="qdi-summary"><strong>调查小结</strong>{{ reportSummary }}</p>
      </div>

      <div v-if="questions.length > 0" class="qdi-counts" aria-label="问题处理情况">
        <span>{{ questions.length }} 项问题</span>
        <span>{{ resolvedCount }} 项已解决</span>
        <span v-if="unresolvedCount > 0">{{ unresolvedCount }} 项待确认</span>
      </div>
    </header>

    <div v-if="liveProgress.started" class="qdi-live-ribbon" :class="{ active: liveProgress.active }">
      <span class="live-orb" aria-hidden="true"></span>
      <div class="live-copy">
        <strong>{{ liveProgress.activityLabel }}</strong>
        <span v-if="currentQuestion">当前问题：{{ currentQuestion.question }}</span>
      </div>
      <div class="live-meta">
        <span v-if="currentActionLabel">{{ currentActionLabel }}</span>
      </div>
    </div>

    <div v-if="questions.length > 0" class="qdi-body">
      <aside class="question-rail">
        <div class="rail-heading">
          <span>调查问题</span>
          <small>{{ resolvedCount }}/{{ questions.length }} 项已解决</small>
        </div>
        <button
          v-for="(question, index) in questions"
          :key="question.id"
          class="question-button"
          :class="{ active: question.id === selectedQuestionId }"
          type="button"
          @click="selectQuestion(question.id)"
        >
          <span class="question-index">{{ String(index + 1).padStart(2, '0') }}</span>
          <span class="question-copy">
            <strong>{{ question.question }}</strong>
          <small>{{ qdiCategoryLabel(question.category) }} · {{ qdiPriorityLabel(question.priority) }}</small>
          </span>
          <span class="question-status" :class="statusTone(question.status)">{{ statusLabel(question.status) }}</span>
        </button>
      </aside>

      <main v-if="selectedQuestion" class="question-detail">
        <section class="detail-lead">
          <div class="detail-kickers">
            <span>{{ qdiCategoryLabel(selectedQuestion.category) }}</span>
            <span>{{ qdiPriorityLabel(selectedQuestion.priority) }}</span>
            <span v-if="confidenceLabel(selectedQuestion.confidence)">置信度 {{ confidenceLabel(selectedQuestion.confidence) }}</span>
          </div>
          <h4 class="detail-title">{{ selectedQuestion.question }}</h4>
          <p v-if="selectedQuestion.whyBlocking" class="blocking-note">待确认原因：{{ selectedQuestion.whyBlocking }}</p>
        </section>

        <section class="conclusion-card" :class="statusTone(selectedQuestion.status)">
          <div class="card-heading">
            <div>
              <h5 class="section-title">结论</h5>
            </div>
            <span class="question-status" :class="statusTone(selectedQuestion.status)">{{ statusLabel(selectedQuestion.status) }}</span>
          </div>
          <p class="conclusion-text">
            {{ selectedQuestion.answer || selectedQuestion.unresolvedReason || '尚未形成最终结论。' }}
          </p>
          <div v-if="selectedQuestion.remainingUncertainty" class="uncertainty-note">
            <strong>剩余不确定性</strong>
            <p>{{ selectedQuestion.remainingUncertainty }}</p>
          </div>
        </section>

        <div class="evidence-grid">
          <section class="evidence-card">
            <div class="card-heading compact">
              <h5 class="section-title">证据</h5>
            </div>
            <ol v-if="selectedQuestion.evidence.length > 0" class="numbered-list">
              <li v-for="item in selectedQuestion.evidence" :key="item">{{ item }}</li>
            </ol>
            <p v-else class="empty-copy">旧版报告未保存结构化证据。</p>
          </section>

          <section class="evidence-card">
            <div class="card-heading compact">
              <h5 class="section-title">下游注意事项</h5>
            </div>
            <ul v-if="selectedQuestion.downstreamNotes.length > 0" class="plain-list">
              <li v-for="item in selectedQuestion.downstreamNotes" :key="item">{{ item }}</li>
            </ul>
            <p v-else class="empty-copy">暂无额外下游说明。</p>
          </section>
        </div>

        <section v-if="Object.keys(selectedMemory).length > 0" class="memory-card">
          <div class="card-heading">
            <div>
              <h5 class="section-title">调查依据</h5>
            </div>
          </div>
          <div class="memory-grid">
            <div>
              <strong>已确认事实</strong>
              <ul class="plain-list"><li v-for="item in textList(selectedMemory.confirmed_facts)" :key="item">{{ item }}</li></ul>
            </div>
            <div>
              <strong>临时结论</strong>
              <ul class="plain-list"><li v-for="item in textList(selectedMemory.temporary_conclusions)" :key="item">{{ item }}</li></ul>
            </div>
            <div>
              <strong>仍需补齐</strong>
              <ul class="plain-list"><li v-for="item in textList(selectedMemory.open_gaps)" :key="item">{{ item }}</li></ul>
            </div>
            <div>
              <strong>已排除假设</strong>
              <ul class="plain-list"><li v-for="item in textList(selectedMemory.invalidated_hypotheses)" :key="item">{{ item }}</li></ul>
            </div>
          </div>
          <p v-if="selectedMemory.recommended_next_focus" class="next-focus">
            建议下一步：{{ selectedMemory.recommended_next_focus }}
          </p>
        </section>

        <section class="timeline-card">
          <div class="card-heading">
            <div>
              <h5 class="section-title">调查过程</h5>
            </div>
          </div>
          <div v-if="selectedTimeline.length > 0" class="timeline-list">
            <article v-for="entry in selectedTimeline" :key="`${selectedQuestion.id}-${entry.sequence}`" class="timeline-entry">
              <div class="timeline-marker">{{ entry.sequence }}</div>
              <div class="timeline-content">
                <div class="timeline-heading">
                  <strong>{{ actionName(entry.action) }}</strong>
                  <span>{{ actionStatusLabel(entry.action.status ?? entry.action.result) }}</span>
                </div>
                <p v-if="entry.digest.what_was_done" class="timeline-summary">{{ entry.digest.what_was_done }}</p>
                <p v-else-if="entry.action.notes" class="timeline-summary">{{ entry.action.notes }}</p>
                <ul v-if="textList(entry.digest.key_outputs).length > 0" class="plain-list compact-list">
                  <li v-for="item in textList(entry.digest.key_outputs)" :key="item">{{ item }}</li>
                </ul>
                <div v-if="entry.digest.temporary_conclusion || entry.digest.remaining_gap" class="timeline-findings">
                  <p v-if="entry.digest.temporary_conclusion"><strong>临时结论：</strong>{{ entry.digest.temporary_conclusion }}</p>
                  <p v-if="entry.digest.remaining_gap"><strong>剩余缺口：</strong>{{ entry.digest.remaining_gap }}</p>
                </div>
              </div>
            </article>
          </div>
          <p v-else class="empty-copy">旧版报告未保存动作摘要，仍可查看下方脚本执行记录。</p>
        </section>

        <section v-if="selectedResults.length > 0 || selectedScripts.length > 0" class="execution-card">
          <div class="card-heading">
            <div>
              <h5 class="section-title">数据检查</h5>
            </div>
            <span v-if="selectedResults.length > 0">{{ selectedResults.length }} 次检查</span>
          </div>

          <div class="execution-list">
            <details v-for="(row, index) in selectedResults" :key="String(row.request_id ?? `result-${index}`)" class="execution-item">
              <summary>
                <span>第 {{ index + 1 }} 次检查</span>
                <span class="execution-status" :class="String(row.status ?? '').toLowerCase()">{{ actionStatusLabel(row.status) }}</span>
                <span v-if="row.output_truncated" class="truncated-label">结果过长，已缩短显示</span>
              </summary>
              <p class="execution-result">{{ resultPreview(row) }}</p>
              <details class="technical-result">
                <summary>查看技术数据</summary>
                <pre>{{ resultDetails(row) }}</pre>
              </details>
            </details>

            <details v-for="(row, index) in selectedScripts" :key="String(row.request_id ?? `script-${index}`)" class="execution-item script-item">
              <summary>
                <span>{{ scriptTitle(row, index) }}</span>
                <span>查看检查脚本</span>
              </summary>
              <div class="execution-meta">
                <span v-for="file in textList(row.input_files).slice(0, 6)" :key="file">{{ fileLabel(file) }}</span>
              </div>
              <pre>{{ String(row.python_code ?? '报告未保存脚本源码。').slice(0, 8000) }}</pre>
            </details>
          </div>
        </section>

        <section v-if="selectedQuestion.usedFiles.length > 0" class="used-files-card">
          <strong>本问题使用的数据文件</strong>
          <div class="artifact-row">
            <span v-for="file in selectedQuestion.usedFiles" :key="file" :title="file">{{ qdiFileName(file) }}</span>
          </div>
        </section>
      </main>
    </div>

    <div v-else class="qdi-empty">
      <h3>问题调查</h3>
      <p>{{ reportSummary || (enabled ? (liveProgress.active ? liveProgress.activityLabel : '暂无待调查问题') : '本任务未启用问题调查') }}</p>
    </div>
  </section>
</template>

<style scoped>
.qdi-workbench {
  --qdi-ink: #1d1d1f;
  --qdi-muted: #6e6e73;
  --qdi-line: #d2d2d7;
  --qdi-teal: #0066cc;
  --qdi-blue: #0071e3;
  overflow: hidden;
  border-top: 1px solid var(--qdi-line);
  background: #ffffff;
}

.qdi-hero {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 28px;
  align-items: end;
  padding: 24px 26px 22px;
  border-bottom: 1px solid rgba(174, 205, 214, 0.72);
}

.qdi-hero-copy {
  max-width: 880px;
}

.qdi-eyebrow,
.section-kicker {
  margin: 0 0 6px;
  color: var(--qdi-teal);
  font-size: 11px;
  font-weight: 800;
  text-transform: uppercase;
}

.qdi-title-row,
.card-heading,
.timeline-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.qdi-title {
  margin: 0;
  color: var(--qdi-ink);
  font-size: 22px;
}

.qdi-state,
.question-status,
.detail-kickers span,
.artifact-row span,
.execution-meta span {
  border-radius: 4px;
  font-size: 11px;
  font-weight: 700;
}

.qdi-state {
  padding: 6px 11px;
}

.qdi-state.complete,
.question-status.complete {
  background: #e8f5ed;
  color: #216e3a;
}

.qdi-state.running,
.question-status.running {
  background: #eaf3ff;
  color: #0066cc;
}

.qdi-state.warning,
.question-status.warning {
  background: #fff5df;
  color: #805b00;
}

.qdi-state.idle,
.question-status.idle {
  background: #f5f5f7;
  color: #626267;
}

.qdi-summary {
  display: grid;
  gap: 4px;
  margin: 10px 0 0;
  color: #424247;
  font-size: 14px;
  line-height: 1.65;
}

.qdi-summary strong {
  color: #6e6e73;
  font-size: 11px;
  font-weight: 600;
}

.qdi-counts {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 16px;
  align-self: center;
  color: #626267;
  font-size: 12px;
  font-variant-numeric: tabular-nums;
}

.qdi-metrics {
  display: grid;
  grid-template-columns: repeat(6, minmax(74px, 1fr));
  gap: 8px;
}

.qdi-metrics div {
  min-width: 76px;
  padding: 10px 12px;
  border: 1px solid rgba(185, 211, 219, 0.8);
  border-radius: 13px;
  background: rgba(255, 255, 255, 0.72);
}

.qdi-metrics span,
.qdi-metrics strong {
  display: block;
}

.qdi-metrics span {
  color: var(--qdi-muted);
  font-size: 10px;
}

.qdi-metrics strong {
  margin-top: 3px;
  color: var(--qdi-ink);
  font-size: 20px;
}

.qdi-live-ribbon {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  gap: 12px;
  align-items: center;
  padding: 11px 26px;
  border-bottom: 1px solid rgba(174, 205, 214, 0.72);
  background: #f5f5f7;
}

.qdi-live-ribbon.active {
  background: #eaf3ff;
}

.live-orb {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: #86868b;
}

.qdi-live-ribbon.active .live-orb {
  background: #0071e3;
  box-shadow: 0 0 0 0 rgba(0, 113, 227, 0.24);
  animation: qdi-live-pulse 1.8s infinite;
}

.live-copy {
  display: grid;
  min-width: 0;
  gap: 2px;
}

.live-copy strong {
  color: #1d1d1f;
  font-size: 12px;
}

.live-copy span {
  overflow: hidden;
  color: #626267;
  font-size: 11px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.live-meta {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 6px;
}

.live-meta span {
  border-radius: 4px;
  padding: 4px 8px;
  background: #ffffff;
  color: #424247;
  font-size: 10px;
}

@keyframes qdi-live-pulse {
  70% { box-shadow: 0 0 0 8px rgba(11, 144, 129, 0); }
  100% { box-shadow: 0 0 0 0 rgba(11, 144, 129, 0); }
}

.qdi-body {
  display: grid;
  grid-template-columns: minmax(270px, 0.76fr) minmax(0, 2.24fr);
  min-height: 620px;
}

.question-rail {
  max-height: 940px;
  overflow: auto;
  padding: 16px;
  border-right: 1px solid var(--qdi-line);
  background: #f5f5f7;
}

.rail-heading {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  padding: 2px 4px 12px;
  color: var(--qdi-ink);
  font-weight: 800;
}

.rail-heading small {
  color: var(--qdi-muted);
  font-weight: 600;
}

.question-button {
  display: grid;
  grid-template-columns: 30px minmax(0, 1fr) auto;
  gap: 10px;
  align-items: start;
  width: 100%;
  margin-bottom: 8px;
  padding: 12px;
  border: 1px solid transparent;
  border-radius: 4px;
  background: transparent;
  color: inherit;
  text-align: left;
  cursor: pointer;
  transition: transform 160ms ease, border-color 160ms ease, background 160ms ease;
}

.question-button:hover {
  border-color: #d2d2d7;
  background: #ffffff;
}

.question-button.active {
  border-color: #0071e3;
  background: #ffffff;
  box-shadow: inset 3px 0 #0071e3;
}

.question-index {
  color: #7b98a9;
  font-family: Consolas, monospace;
  font-size: 12px;
}

.question-copy {
  display: grid;
  gap: 6px;
  min-width: 0;
}

.question-copy strong {
  display: -webkit-box;
  overflow: hidden;
  color: #1d1d1f;
  font-size: 12px;
  line-height: 1.45;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 3;
}

.question-copy small {
  color: #6e6e73;
  font-size: 10px;
}

.question-status {
  padding: 4px 7px;
  white-space: nowrap;
}

.question-detail {
  display: grid;
  align-content: start;
  gap: 14px;
  min-width: 0;
  max-height: 940px;
  overflow: auto;
  padding: 22px;
}

.detail-lead {
  padding: 2px 2px 4px;
}

.detail-kickers,
.artifact-row,
.execution-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.detail-kickers span,
.artifact-row span,
.execution-meta span {
  padding: 4px 8px;
  border-radius: 4px;
  background: #f5f5f7;
  color: #424247;
}

.detail-title {
  margin: 10px 0 0;
  color: var(--qdi-ink);
  font-size: 21px;
  line-height: 1.42;
}

.blocking-note {
  margin: 10px 0 0;
  padding-left: 12px;
  border-left: 3px solid #e6ad4a;
  color: #6d5c40;
  font-size: 13px;
  line-height: 1.6;
}

.conclusion-card,
.evidence-card,
.memory-card,
.timeline-card,
.execution-card,
.used-files-card {
  border: 1px solid var(--qdi-line);
  border-radius: 4px;
  background: #ffffff;
  padding: 16px;
}

.conclusion-card.complete {
  border-left: 3px solid #34a853;
}

.conclusion-card.warning {
  border-left: 3px solid #d89900;
}

.section-title {
  margin: 0;
  color: var(--qdi-ink);
  font-size: 15px;
}

.card-heading > span {
  color: #6e8797;
  font-size: 11px;
}

.card-heading.compact {
  padding-bottom: 8px;
  border-bottom: 1px solid #e0e9ed;
}

.conclusion-text {
  margin: 14px 0 0;
  color: #303034;
  font-size: 14px;
  line-height: 1.72;
  white-space: pre-wrap;
}

.uncertainty-note {
  margin-top: 14px;
  padding: 11px 12px;
  border-radius: 4px;
  background: #fff8e6;
  color: #6e5200;
}

.uncertainty-note p {
  margin: 5px 0 0;
  line-height: 1.55;
}

.evidence-grid,
.memory-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.numbered-list,
.plain-list {
  margin: 10px 0 0;
  padding-left: 20px;
  color: #3e6074;
  font-size: 12px;
  line-height: 1.6;
}

.plain-list li,
.numbered-list li {
  margin-bottom: 5px;
}

.memory-grid {
  margin-top: 12px;
}

.memory-grid > div {
  min-width: 0;
  padding: 11px;
  border-radius: 4px;
  background: #f5f5f7;
}

.memory-grid strong {
  color: #303034;
  font-size: 12px;
}

.next-focus {
  margin: 12px 0 0;
  padding: 10px 12px;
  border-radius: 4px;
  background: #eaf3ff;
  color: #004f9e;
  font-size: 12px;
}

.timeline-list {
  display: grid;
  gap: 0;
  margin-top: 14px;
}

.timeline-entry {
  position: relative;
  display: grid;
  grid-template-columns: 32px minmax(0, 1fr);
  gap: 12px;
  padding-bottom: 18px;
}

.timeline-entry:not(:last-child)::before {
  position: absolute;
  top: 28px;
  bottom: 0;
  left: 15px;
  width: 1px;
  background: #d2d2d7;
  content: '';
}

.timeline-marker {
  z-index: 1;
  display: grid;
  place-items: center;
  width: 30px;
  height: 30px;
  border-radius: 4px;
  background: #0071e3;
  color: #ffffff;
  font-family: Consolas, monospace;
  font-size: 11px;
  font-weight: 800;
}

.timeline-content {
  min-width: 0;
  padding: 10px 12px;
  border: 1px solid #d2d2d7;
  border-radius: 4px;
  background: #ffffff;
}

.timeline-heading strong {
  color: #1d1d1f;
  font-size: 12px;
  text-transform: capitalize;
}

.timeline-heading span {
  color: #6e6e73;
  font-size: 10px;
}

.timeline-summary,
.timeline-findings p {
  margin: 7px 0 0;
  color: #424247;
  font-size: 12px;
  line-height: 1.58;
}

.compact-list {
  margin-top: 8px;
}

.timeline-findings {
  margin-top: 8px;
  padding-top: 2px;
  border-top: 1px dashed #d6e3e7;
}

.execution-list {
  display: grid;
  gap: 8px;
  margin-top: 12px;
}

.execution-item {
  border: 1px solid #d2d2d7;
  border-radius: 4px;
  background: #ffffff;
}

.execution-item summary {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
  padding: 10px 12px;
  color: #303034;
  font-size: 12px;
  cursor: pointer;
}

.execution-status {
  border-radius: 4px;
  padding: 3px 7px;
  background: #f5f5f7;
  color: #626267;
}

.execution-status.completed {
  background: #e8f5ed;
  color: #216e3a;
}

.execution-status.failed {
  background: #fff0ed;
  color: #a12f23;
}

.truncated-label {
  color: #a26b1f;
  font-weight: 700;
}

.execution-meta {
  padding: 0 12px 8px;
}

.execution-item pre {
  max-height: 380px;
  margin: 0 12px 12px;
  overflow: auto;
  padding: 11px;
  border: 1px solid #d2d2d7;
  border-radius: 4px;
  background: #f5f5f7;
  color: #303034;
  font-family: Consolas, monospace;
  font-size: 11px;
  line-height: 1.5;
  white-space: pre-wrap;
  word-break: break-word;
}

.script-item summary > span:last-child {
  color: #708795;
  font-size: 10px;
}

.used-files-card > strong {
  display: block;
  margin-bottom: 9px;
  color: #345c70;
  font-size: 12px;
}

.empty-copy,
.qdi-empty p {
  color: #718a99;
  font-size: 12px;
  line-height: 1.55;
}

.qdi-empty {
  display: grid;
  gap: 6px;
  padding: 22px 0;
  color: var(--qdi-ink);
}

.qdi-empty h3 {
  margin: 0;
  font-size: 16px;
  font-weight: 600;
}

.qdi-empty p {
  margin: 0;
  color: var(--qdi-muted);
  font-size: 13px;
}

.execution-result {
  margin: 0;
  padding: 12px;
  color: #303034;
  font-size: 12px;
  line-height: 1.65;
  white-space: pre-wrap;
}

.technical-result {
  margin: 0 12px 12px;
  padding-top: 8px;
  border-top: 1px solid #d2d2d7;
  color: #626267;
  font-size: 11px;
}

.technical-result summary {
  width: fit-content;
  cursor: pointer;
}

.technical-result pre {
  margin: 8px 0 0;
  padding: 10px;
  border: 1px solid #d2d2d7;
  background: #f5f5f7;
  color: #303034;
  font: 11px/1.55 Consolas, 'Cascadia Code', monospace;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

@media (max-width: 1180px) {
  .qdi-hero {
    grid-template-columns: 1fr;
  }

  .qdi-metrics {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }

  .qdi-body {
    grid-template-columns: minmax(240px, 0.82fr) minmax(0, 1.8fr);
  }
}

@media (max-width: 860px) {
  .qdi-body {
    grid-template-columns: 1fr;
  }

  .question-rail {
    max-height: 380px;
    border-right: 0;
    border-bottom: 1px solid var(--qdi-line);
  }

  .question-detail {
    max-height: none;
  }

  .evidence-grid,
  .memory-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 620px) {
  .qdi-hero,
  .question-detail {
    padding: 16px;
  }

  .qdi-title-row {
    align-items: flex-start;
  }

  .qdi-metrics {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .qdi-live-ribbon {
    grid-template-columns: auto minmax(0, 1fr);
    padding: 11px 16px;
  }

  .live-meta {
    grid-column: 2;
    justify-content: flex-start;
  }

  .question-button {
    grid-template-columns: 26px minmax(0, 1fr);
  }

  .question-status {
    grid-column: 2;
    justify-self: start;
  }
}

@media (prefers-reduced-motion: reduce) {
  .qdi-live-ribbon.active .live-orb { animation: none; }
}
</style>
