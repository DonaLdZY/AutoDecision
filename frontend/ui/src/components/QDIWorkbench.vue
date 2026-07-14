<script setup lang="ts">
import { computed, shallowRef, watch } from 'vue'
import {
  asArray,
  asRecord,
  deriveQdiLiveProgress,
  isResolvedQdiStatus,
  normalizeQdiQuestions,
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
const terminalCount = computed(() => questions.value.filter((row) => {
  return !['pending', 'investigating', 'in_progress', 'refined'].includes(row.status)
}).length)
const successfulScripts = computed(() => Math.max(
  liveProgress.value.scriptSuccesses,
  stepResults.value.filter((row) => String(row.status ?? '').toLowerCase() === 'completed').length,
))
const failedScripts = computed(() => Math.max(
  liveProgress.value.scriptFailures,
  stepResults.value.filter((row) => String(row.status ?? '').toLowerCase() === 'failed').length,
))
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
  if (terminalCount.value === questions.value.length) return { label: '调查完成', tone: 'complete' }
  if (pipelineStatus.value === 'running') return { label: '调查进行中', tone: 'running' }
  return { label: '调查进行中', tone: 'running' }
})

const currentActionLabel = computed(() => {
  const action = liveProgress.value.currentAction
  if (!action) return ''
  const labels: Record<string, string> = {
    decide_next_action: '决定下一步',
    request_script: '执行只读脚本',
    request_context: '取回相关认知卡片',
    search_document: '检索文档',
    read_document_chunks: '读取文档片段',
    read_qdi_artifact_excerpt: '读取历史证据片段',
    answer: '形成结论',
    give_up: '记录未解决原因',
  }
  return labels[action] ?? action.replaceAll('_', ' ')
})

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

function resultArtifact(row: Record<string, unknown>) {
  const result = asRecord(row.result)
  return asRecord(result._full_result_artifact)
}

function resultPreview(row: Record<string, unknown>) {
  const result = asRecord(row.result)
  const artifact = resultArtifact(row)
  const visible = artifact.visible_excerpt ?? result.visible_excerpt ?? row.error ?? result
  return compactJson(visible, 1400)
}

function actionName(row: Record<string, unknown>) {
  return String(row.action ?? row.event_type ?? 'investigate').replaceAll('_', ' ')
}

function scriptTitle(row: Record<string, unknown>, index: number) {
  return String(row.goal ?? row.reason ?? row.question_id ?? `脚本 ${index + 1}`)
}
</script>

<template>
  <section class="qdi-workbench">
    <header class="qdi-hero">
      <div class="qdi-hero-copy">
        <p class="qdi-eyebrow">Question-Driven Investigation</p>
        <div class="qdi-title-row">
          <h3 class="qdi-title">QDI 调查终点</h3>
          <span class="qdi-state" :class="workbenchStatus.tone">{{ workbenchStatus.label }}</span>
        </div>
        <p class="qdi-summary">
          {{ reportSummary || (enabled ? '围绕阻塞建模的问题执行只读探查，并把证据、结论与剩余不确定性传给任务定义阶段。' : '当前任务未启用 QDI。') }}
        </p>
      </div>

      <div class="qdi-metrics" aria-label="QDI 调查统计">
        <div><span>问题</span><strong>{{ questions.length || liveProgress.queuedQuestions }}</strong></div>
        <div><span>已解决</span><strong>{{ resolvedCount }}</strong></div>
        <div><span>调查动作</span><strong>{{ liveProgress.actionDecisions }}</strong></div>
        <div><span>脚本成功</span><strong>{{ successfulScripts }}</strong></div>
        <div><span>脚本失败</span><strong>{{ failedScripts }}</strong></div>
        <div><span>脚本修复</span><strong>{{ liveProgress.repairCalls }}</strong></div>
      </div>
    </header>

    <div v-if="liveProgress.started" class="qdi-live-ribbon" :class="{ active: liveProgress.active }">
      <span class="live-orb" aria-hidden="true"></span>
      <div class="live-copy">
        <strong>{{ liveProgress.activityLabel }}</strong>
        <span v-if="currentQuestion">当前问题：{{ currentQuestion.question }}</span>
        <span v-else-if="liveProgress.currentQuestionId">当前问题：{{ liveProgress.currentQuestionId }}</span>
      </div>
      <div class="live-meta">
        <span v-if="currentActionLabel">{{ currentActionLabel }}</span>
        <span v-if="liveProgress.actionRound > 0">第 {{ liveProgress.actionRound }} 轮</span>
        <span v-if="liveProgress.lastUpdate">{{ liveProgress.lastUpdate }}</span>
      </div>
    </div>

    <div v-if="questions.length > 0" class="qdi-body">
      <aside class="question-rail">
        <div class="rail-heading">
          <span>调查问题</span>
          <small>{{ resolvedCount }}/{{ questions.length }} resolved</small>
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
            <small>{{ question.category }} · {{ question.priority }}</small>
          </span>
          <span class="question-status" :class="statusTone(question.status)">{{ statusLabel(question.status) }}</span>
        </button>
      </aside>

      <main v-if="selectedQuestion" class="question-detail">
        <section class="detail-lead">
          <div class="detail-kickers">
            <span>{{ selectedQuestion.category }}</span>
            <span>优先级 {{ selectedQuestion.priority }}</span>
            <span v-if="selectedQuestion.confidence">置信度 {{ selectedQuestion.confidence }}</span>
            <span v-if="selectedQuestion.depth > 0">追问深度 {{ selectedQuestion.depth }}</span>
          </div>
          <h4 class="detail-title">{{ selectedQuestion.question }}</h4>
          <p v-if="selectedQuestion.whyBlocking" class="blocking-note">为什么需要调查：{{ selectedQuestion.whyBlocking }}</p>
        </section>

        <section class="conclusion-card" :class="statusTone(selectedQuestion.status)">
          <div class="card-heading">
            <div>
              <p class="section-kicker">Final Finding</p>
              <h5 class="section-title">最终结论</h5>
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
              <span>{{ selectedQuestion.evidence.length }}</span>
            </div>
            <ol v-if="selectedQuestion.evidence.length > 0" class="numbered-list">
              <li v-for="item in selectedQuestion.evidence" :key="item">{{ item }}</li>
            </ol>
            <p v-else class="empty-copy">旧版报告未保存结构化证据。</p>
          </section>

          <section class="evidence-card">
            <div class="card-heading compact">
              <h5 class="section-title">下游注意事项</h5>
              <span>{{ selectedQuestion.downstreamNotes.length }}</span>
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
              <p class="section-kicker">Working Memory</p>
              <h5 class="section-title">调查工作记忆</h5>
            </div>
            <span>更新至动作 {{ selectedMemory.last_updated_sequence ?? '-' }}</span>
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
              <p class="section-kicker">Investigation Timeline</p>
              <h5 class="section-title">探索轨迹</h5>
            </div>
            <span>{{ selectedTimeline.length }} 个动作</span>
          </div>
          <div v-if="selectedTimeline.length > 0" class="timeline-list">
            <article v-for="entry in selectedTimeline" :key="`${selectedQuestion.id}-${entry.sequence}`" class="timeline-entry">
              <div class="timeline-marker">{{ entry.sequence }}</div>
              <div class="timeline-content">
                <div class="timeline-heading">
                  <strong>{{ actionName(entry.action) }}</strong>
                  <span>{{ String(entry.action.status ?? entry.action.result ?? 'completed') }}</span>
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
                <div v-if="textList(entry.digest.evidence_refs).length > 0" class="artifact-row">
                  <span v-for="ref in textList(entry.digest.evidence_refs)" :key="ref">{{ ref }}</span>
                </div>
              </div>
            </article>
          </div>
          <p v-else class="empty-copy">旧版报告未保存动作摘要，仍可查看下方脚本执行记录。</p>
        </section>

        <section v-if="selectedResults.length > 0 || selectedScripts.length > 0" class="execution-card">
          <div class="card-heading">
            <div>
              <p class="section-kicker">Execution Evidence</p>
              <h5 class="section-title">脚本与执行结果</h5>
            </div>
            <span>{{ selectedResults.length }} 次执行</span>
          </div>

          <div class="execution-list">
            <details v-for="(row, index) in selectedResults" :key="String(row.request_id ?? `result-${index}`)" class="execution-item">
              <summary>
                <span>{{ String(row.request_id ?? `执行 ${index + 1}`) }}</span>
                <span class="execution-status" :class="String(row.status ?? '').toLowerCase()">{{ row.status ?? 'unknown' }}</span>
                <span v-if="row.output_truncated" class="truncated-label">输出已截断</span>
              </summary>
              <div class="execution-meta">
                <span v-if="row.original_output_chars">原始 {{ row.original_output_chars }} 字符</span>
                <span v-if="row.visible_output_chars">可见 {{ row.visible_output_chars }} 字符</span>
                <span v-if="resultArtifact(row).artifact_id">artifact {{ resultArtifact(row).artifact_id }}</span>
              </div>
              <pre>{{ resultPreview(row) }}</pre>
            </details>

            <details v-for="(row, index) in selectedScripts" :key="String(row.request_id ?? `script-${index}`)" class="execution-item script-item">
              <summary>
                <span>{{ scriptTitle(row, index) }}</span>
                <span>查看只读脚本</span>
              </summary>
              <div class="execution-meta">
                <span v-for="file in textList(row.input_files).slice(0, 6)" :key="file">{{ file }}</span>
              </div>
              <pre>{{ String(row.python_code ?? '报告未保存脚本源码。').slice(0, 8000) }}</pre>
            </details>
          </div>
        </section>

        <section v-if="selectedQuestion.usedFiles.length > 0" class="used-files-card">
          <strong>本问题使用的数据文件</strong>
          <div class="artifact-row">
            <span v-for="file in selectedQuestion.usedFiles" :key="file">{{ file }}</span>
          </div>
        </section>
      </main>
    </div>

    <div v-else class="qdi-empty">
      <strong>{{ enabled ? (liveProgress.active ? 'QDI 正在准备调查记录' : 'QDI 尚未产生调查记录') : 'QDI 已在任务配置中关闭' }}</strong>
      <p>{{ enabled ? (liveProgress.active ? liveProgress.activityLabel : '数据认知完成并产生阻塞问题后，这里会展示调查轨迹、证据和最终结论。') : '文件认知结果仍可在上方浏览。' }}</p>
    </div>
  </section>
</template>

<style scoped>
.qdi-workbench {
  --qdi-ink: #153c57;
  --qdi-muted: #607d91;
  --qdi-line: #cfe0e7;
  --qdi-teal: #087f73;
  --qdi-blue: #1e5d8d;
  overflow: hidden;
  border: 1px solid #bdd4dd;
  border-radius: 20px;
  background:
    radial-gradient(circle at 92% 6%, rgba(30, 138, 153, 0.14), transparent 27%),
    linear-gradient(145deg, #f7fcfc 0%, #f5f9fd 56%, #edf6f7 100%);
  box-shadow: 0 18px 44px rgba(28, 66, 91, 0.08);
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
  letter-spacing: 0.13em;
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
  font-size: clamp(24px, 3vw, 34px);
  letter-spacing: -0.04em;
}

.qdi-state,
.question-status,
.detail-kickers span,
.artifact-row span,
.execution-meta span {
  border-radius: 999px;
  font-size: 11px;
  font-weight: 700;
}

.qdi-state {
  padding: 6px 11px;
}

.qdi-state.complete,
.question-status.complete {
  background: #dff4ea;
  color: #166a4d;
}

.qdi-state.running,
.question-status.running {
  background: #dfeeff;
  color: #245f91;
}

.qdi-state.warning,
.question-status.warning {
  background: #fff0d4;
  color: #91601a;
}

.qdi-state.idle,
.question-status.idle {
  background: #e9eef2;
  color: #607283;
}

.qdi-summary {
  margin: 10px 0 0;
  color: #46687d;
  font-size: 14px;
  line-height: 1.65;
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
  background: rgba(235, 244, 247, 0.78);
}

.qdi-live-ribbon.active {
  background: linear-gradient(90deg, rgba(224, 246, 241, 0.9), rgba(237, 247, 250, 0.86));
}

.live-orb {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: #6d8795;
}

.qdi-live-ribbon.active .live-orb {
  background: #0b9081;
  box-shadow: 0 0 0 0 rgba(11, 144, 129, 0.32);
  animation: qdi-live-pulse 1.8s infinite;
}

.live-copy {
  display: grid;
  min-width: 0;
  gap: 2px;
}

.live-copy strong {
  color: #24566a;
  font-size: 12px;
}

.live-copy span {
  overflow: hidden;
  color: #65808f;
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
  border-radius: 999px;
  padding: 4px 8px;
  background: rgba(255, 255, 255, 0.76);
  color: #4c6f80;
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
  background: rgba(237, 247, 248, 0.62);
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
  border-radius: 14px;
  background: transparent;
  color: inherit;
  text-align: left;
  cursor: pointer;
  transition: transform 160ms ease, border-color 160ms ease, background 160ms ease;
}

.question-button:hover {
  transform: translateX(2px);
  border-color: #c3d9df;
  background: rgba(255, 255, 255, 0.68);
}

.question-button.active {
  border-color: #88b8be;
  background: #ffffff;
  box-shadow: 0 9px 24px rgba(31, 80, 94, 0.09);
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
  color: #294d62;
  font-size: 12px;
  line-height: 1.45;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 3;
}

.question-copy small {
  color: #718a9a;
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
  background: #e7f0f4;
  color: #527186;
}

.detail-title {
  margin: 10px 0 0;
  color: var(--qdi-ink);
  font-size: clamp(18px, 2vw, 24px);
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
  border-radius: 16px;
  background: rgba(255, 255, 255, 0.86);
  padding: 16px;
}

.conclusion-card.complete {
  border-color: #a8d8c5;
  background: linear-gradient(145deg, #f3fcf8, #ffffff);
}

.conclusion-card.warning {
  border-color: #ead19d;
  background: linear-gradient(145deg, #fffaf0, #ffffff);
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
  color: #294f63;
  font-size: 14px;
  line-height: 1.72;
  white-space: pre-wrap;
}

.uncertainty-note {
  margin-top: 14px;
  padding: 11px 12px;
  border-radius: 11px;
  background: #fff7e7;
  color: #7a5a28;
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
  border-radius: 12px;
  background: #f5f9fb;
}

.memory-grid strong {
  color: #345c70;
  font-size: 12px;
}

.next-focus {
  margin: 12px 0 0;
  padding: 10px 12px;
  border-radius: 10px;
  background: #e9f4f3;
  color: #22675f;
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
  background: #b8d2d8;
  content: '';
}

.timeline-marker {
  z-index: 1;
  display: grid;
  place-items: center;
  width: 30px;
  height: 30px;
  border-radius: 50%;
  background: #1b7d79;
  color: #ffffff;
  font-family: Consolas, monospace;
  font-size: 11px;
  font-weight: 800;
}

.timeline-content {
  min-width: 0;
  padding: 10px 12px;
  border: 1px solid #d8e5e9;
  border-radius: 12px;
  background: #fbfdfd;
}

.timeline-heading strong {
  color: #2b566a;
  font-size: 12px;
  text-transform: capitalize;
}

.timeline-heading span {
  color: #76909f;
  font-size: 10px;
}

.timeline-summary,
.timeline-findings p {
  margin: 7px 0 0;
  color: #4a6a7d;
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
  border: 1px solid #d9e5e9;
  border-radius: 11px;
  background: #f9fbfc;
}

.execution-item summary {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
  padding: 10px 12px;
  color: #355d72;
  font-size: 12px;
  cursor: pointer;
}

.execution-status {
  border-radius: 999px;
  padding: 3px 7px;
  background: #e7eef2;
  color: #607888;
}

.execution-status.completed {
  background: #def3e8;
  color: #237052;
}

.execution-status.failed {
  background: #fde8e5;
  color: #a4473c;
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
  border-radius: 9px;
  background: #102a38;
  color: #dceff2;
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
  padding: 34px 26px;
  color: var(--qdi-ink);
}

.qdi-empty p {
  margin: 7px 0 0;
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
</style>
