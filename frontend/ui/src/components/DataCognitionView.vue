<script setup lang="ts">
import { computed, shallowRef } from 'vue'
import type { SnapshotPayload } from '../types'
import CognitionProbePanel from './CognitionProbePanel.vue'
import CognitionTreeNode from './CognitionTreeNode.vue'
import type { CognitionTreeNode as TreeNode, ReadState } from './cognition-tree-types'

type FileCognitionPayload = {
  json?: Record<string, unknown>
  markdown?: string
}

const props = defineProps<{
  snapshot?: SnapshotPayload
}>()

const selectedPath = shallowRef('__root__')

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value) ? (value as Record<string, unknown>) : {}
}

function asArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : []
}

function normalizeRelPath(value: string) {
  return value.replaceAll('\\', '/').replace(/^\.?\//, '')
}

function hasImageSuffix(path: string) {
  return /\.(jpg|jpeg|png|bmp|gif|webp|tif|tiff)$/i.test(path)
}

const ar = computed(() => props.snapshot?.auto_realize ?? {})
const report = computed(() => asRecord(ar.value.data_cognition_report))
const events = computed(() => (ar.value.events as Record<string, unknown>[] | undefined) ?? [])
const fileCognitionIndex = computed<Record<string, FileCognitionPayload>>(() => ar.value.file_cognition_index ?? {})
const dataDescriptionText = computed(() => String(ar.value.data_description_text ?? ''))
const cognitionCompleted = computed(() => {
  const state = asRecord(ar.value.current_state)
  return String(state.status ?? '').toLowerCase() === 'completed'
})

const normalizedIndex = computed(() => {
  const out: Record<string, FileCognitionPayload> = {}
  for (const [key, value] of Object.entries(fileCognitionIndex.value)) {
    out[normalizeRelPath(key)] = value
  }
  return out
})

function cognitionPayloadFor(path: string) {
  const key = normalizeRelPath(path)
  return normalizedIndex.value[key] ?? normalizedIndex.value[`${key}/`]
}

function hasCognition(path: string) {
  return !!cognitionPayloadFor(path)
}

const sampledPatterns = computed(() => {
  return asArray(report.value.sampled_filename_patterns)
    .map((item) => asRecord(item))
    .filter((item) => Object.keys(item).length > 0)
})

const questionInvestigation = computed(() => {
  const direct = asRecord(ar.value.question_investigation_report)
  if (Object.keys(direct).length > 0) return direct
  return asRecord(report.value.question_investigation)
})

const investigatorEnabled = computed(() => {
  const value = questionInvestigation.value.enabled
  return typeof value === 'boolean' ? value : props.snapshot?.task?.config?.auto_realize?.enable_question_investigator !== false
})

const investigatorQuestions = computed(() => {
  return asArray(questionInvestigation.value.questions)
    .map((item) => asRecord(item))
    .filter((item) => Object.keys(item).length > 0)
})

const investigatorScripts = computed(() => {
  return asArray(questionInvestigation.value.script_requests)
    .map((item) => asRecord(item))
    .filter((item) => Object.keys(item).length > 0)
})

const investigatorResults = computed(() => {
  return asArray(questionInvestigation.value.step_results)
    .map((item) => asRecord(item))
    .filter((item) => Object.keys(item).length > 0)
})

const investigatorAnswers = computed(() => {
  return asArray(questionInvestigation.value.answers)
    .map((item) => asRecord(item))
    .filter((item) => Object.keys(item).length > 0)
})

const investigatorUnresolved = computed(() => asArray(questionInvestigation.value.unresolved_questions).map((item) => String(item)).filter(Boolean))

const investigatorSummary = computed(() => String(questionInvestigation.value.summary ?? '').trim())

const investigatorStatus = computed(() => {
  if (!investigatorEnabled.value) return '已关闭'
  if (investigatorAnswers.value.length > 0) return '已形成结论'
  if (investigatorResults.value.some((item) => String(item.status ?? '') === 'failed')) return '脚本失败待处理'
  if (investigatorResults.value.length > 0) return '脚本已执行'
  if (investigatorQuestions.value.length > 0 || investigatorScripts.value.length > 0) return '调查中'
  return '等待启动'
})

const investigatorResultCounts = computed(() => {
  const counts = { completed: 0, failed: 0, other: 0, repairs: 0 }
  for (const item of investigatorResults.value) {
    const status = String(item.status ?? '').toLowerCase()
    if (status === 'completed') counts.completed += 1
    else if (status === 'failed') counts.failed += 1
    else counts.other += 1
    const result = asRecord(item.result)
    const attempt = Number(result.attempt ?? 1)
    if (Number.isFinite(attempt) && attempt > 1) counts.repairs = Math.max(counts.repairs, attempt - 1)
  }
  return counts
})

function compactResultPreview(item: Record<string, unknown>) {
  const result = asRecord(item.result)
  const error = String(item.error ?? '').trim()
  const payload = Object.keys(result).length > 0 ? result : error
  try {
    const text = typeof payload === 'string' ? payload : JSON.stringify(payload)
    return text.length > 240 ? `${text.slice(0, 240)}...` : text
  } catch {
    return String(payload).slice(0, 240)
  }
}

const filenameSampleGroups = computed(() => {
  return asArray(report.value.filename_sample_groups)
    .map((item) => asRecord(item))
    .filter((item) => Object.keys(item).length > 0)
})

function samplingReview(item: Record<string, unknown>) {
  return asRecord(item.review)
}

function samplingReviewDecision(item: Record<string, unknown>) {
  return String(samplingReview(item).decision ?? 'pending')
}

function samplingReviewReason(item: Record<string, unknown>) {
  const review = samplingReview(item)
  return String(review.reason ?? review.risk ?? '')
}

const skippedByPattern = computed(() => {
  const out = new Set<string>()
  for (const item of sampledPatterns.value) {
    for (const path of asArray(item.skipped)) {
      out.add(normalizeRelPath(String(path)))
    }
  }
  return out
})

const compactImageSamples = computed(() => {
  const out = new Map<string, Set<string>>()
  const dirs = asRecord(report.value.compact_image_dirs)
  for (const [dir, samples] of Object.entries(dirs)) {
    const normalizedDir = normalizeRelPath(dir).replace(/\/$/, '')
    out.set(
      normalizedDir,
      new Set(asArray(samples).map((sample) => normalizeRelPath(String(sample)))),
    )
  }
  return out
})

function isCompactImageSkipped(path: string) {
  if (!hasImageSuffix(path)) return false
  for (const [dir, samples] of compactImageSamples.value.entries()) {
    if (!path.startsWith(`${dir}/`)) continue
    return !samples.has(path)
  }
  return false
}

const readStateByFile = computed(() => {
  const map: Record<string, ReadState> = {}
  for (const path of skippedByPattern.value) map[path] = 'skipped'

  const rows = [...events.value]
  rows.sort((a, b) => Number(a.seq ?? 0) - Number(b.seq ?? 0))
  for (const eventRow of rows) {
    const component = String(eventRow.component ?? '')
    const event = String(eventRow.event ?? '').toUpperCase()
    const fields = asRecord(eventRow.fields)

    if (component === 'module.data_cognition.sampling' && event === 'PATTERN_SAMPLED') {
      for (const skipped of asArray(fields.skipped)) {
        map[normalizeRelPath(String(skipped))] = 'skipped'
      }
      continue
    }

    const file = normalizeRelPath(String(fields.file ?? fields.source ?? ''))
    if (!file) continue

    if (component.startsWith('stage.P1')) {
      if (event === 'READING_FILE') map[file] = 'reading'
      else if (event === 'READ_FAILED') map[file] = 'failed'
      else if (event === 'READ_COMPLETED' && map[file] !== 'failed' && map[file] !== 'read') map[file] = 'reading'
      continue
    }

    if (component === 'module.data_cognition.file_artifact' && event === 'GENERATED_FILE') {
      if (map[file] !== 'failed') map[file] = 'read'
      continue
    }

    if (component === 'agent.file_cognition_summary' && event === 'COMPLETED') {
      if (map[file] !== 'failed') map[file] = 'read'
    }
  }
  for (const key of Object.keys(normalizedIndex.value)) map[normalizeRelPath(key)] = 'read'
  return map
})

function aggregate(node: TreeNode): ReadState {
  if (!node.isDir || node.children.length === 0) return node.readState
  const childStates = node.children.map(aggregate)
  const selfHasCognition = hasCognition(node.path)
  let merged: ReadState
  if (childStates.some((x) => x === 'reading')) merged = 'reading'
  else if (childStates.some((x) => x === 'failed')) merged = 'failed'
  else if (selfHasCognition) merged = 'read'
  else if (childStates.every((x) => x === 'read' || x === 'skipped')) merged = 'read'
  else if (childStates.every((x) => x === 'skipped')) merged = 'skipped'
  else if (childStates.every((x) => x === 'unread')) merged = 'unread'
  else merged = 'partial'
  node.readState = merged
  return merged
}

const tree = computed<TreeNode | null>(() => {
  const text = String(ar.value.directory_tree_text ?? '')
  if (!text.trim()) return null
  const lines = text
    .split('\n')
    .map((line) => line.replace(/\r$/, ''))
    .filter((line) => line.trim().length > 0)
  if (!lines.length) return null

  const root: TreeNode = { name: lines[0].trim(), path: '', isDir: true, children: [], readState: 'unread' }
  const stack: TreeNode[] = [root]
  for (let i = 1; i < lines.length; i += 1) {
    const match = lines[i].match(/^(\s*)- (.+)$/)
    if (!match) continue
    const level = Math.floor(match[1].length / 2) + 1
    const raw = match[2].trim()
    const isDir = raw.endsWith('/')
    const name = isDir ? raw.slice(0, -1) : raw
    const parent = stack[Math.max(0, level - 1)] ?? root
    const path = normalizeRelPath(`${parent.path ? `${parent.path}/` : ''}${name}`)
    const state: ReadState = isDir
      ? (hasCognition(path) ? 'read' : 'unread')
      : (readStateByFile.value[path] ?? (isCompactImageSkipped(path) ? 'skipped' : cognitionCompleted.value ? 'skipped' : 'unread'))
    const node: TreeNode = { name, path, isDir, children: [], readState: state }
    parent.children.push(node)
    stack[level] = node
    stack.length = level + 1
  }
  root.readState = aggregate(root)
  return root
})

function countStates(node: TreeNode | null) {
  const counts: Record<ReadState, number> = {
    unread: 0,
    reading: 0,
    read: 0,
    skipped: 0,
    failed: 0,
    partial: 0,
  }
  if (!node) return counts
  const walk = (current: TreeNode) => {
    if (!current.isDir) counts[current.readState] += 1
    for (const child of current.children) walk(child)
  }
  walk(node)
  return counts
}

const stateCounts = computed(() => countStates(tree.value))
const traceCount = computed(() => {
  let count = 0
  for (const payload of Object.values(normalizedIndex.value)) {
    const metadata = asRecord(payload.json?.source_metadata)
    if (Object.keys(asRecord(metadata.cognition_trace)).length > 0) count += 1
  }
  return count
})
const recentCognitionEvents = computed(() => {
  return [...events.value]
    .filter((row) => {
      const component = String(row.component ?? '').toLowerCase()
      return component.includes('data_cognition') || component.includes('file_cognition') || component.includes('stage.p1')
    })
    .slice(-10)
    .reverse()
})
const selectedPayload = computed<FileCognitionPayload | null>(() => {
  if (selectedPath.value === '__root__') return { markdown: dataDescriptionText.value }
  return cognitionPayloadFor(selectedPath.value) ?? null
})
const selectedDisplayPath = computed(() => {
  if (selectedPath.value === '__root__') return '(root) data_description.md'
  return selectedPath.value
})
const selectedIsRoot = computed(() => selectedPath.value === '__root__')

function onNodePreview(path: string) {
  const key = normalizeRelPath(path)
  if (!hasCognition(key)) return
  selectedPath.value = key
}

function onRootDblclick() {
  selectedPath.value = '__root__'
}

function eventTitle(row: Record<string, unknown>) {
  return `${String(row.component ?? '-')}.${String(row.event ?? '-')}`
}

function eventFile(row: Record<string, unknown>) {
  const fields = asRecord(row.fields)
  return String(fields.file ?? fields.source ?? '')
}
</script>

<template>
  <section class="page">
    <aside class="left">
      <header class="section-header">
        <div>
          <p class="eyebrow">Data Cognition</p>
          <h4>数据目录树</h4>
        </div>
        <button class="root-button" type="button" @click="onRootDblclick">总认知</button>
      </header>

      <section class="status-grid">
        <div class="status-card read"><span>已认知</span><strong>{{ stateCounts.read }}</strong></div>
        <div class="status-card reading"><span>读取中</span><strong>{{ stateCounts.reading }}</strong></div>
        <div class="status-card skipped"><span>抽样跳过</span><strong>{{ stateCounts.skipped }}</strong></div>
        <div class="status-card failed"><span>失败</span><strong>{{ stateCounts.failed }}</strong></div>
      </section>

      <ul v-if="tree" class="root">
        <li>
          <div class="title root-title" @dblclick.stop="onRootDblclick">
            <span class="dot" :class="tree.readState"></span>
            <strong>{{ tree.name }}</strong>
          </div>
          <ul>
            <CognitionTreeNode
              v-for="child in tree.children"
              :key="child.path"
              :node="child"
              :depth="1"
              :bold-when="hasCognition"
              @preview="onNodePreview"
            />
          </ul>
        </li>
      </ul>
      <p v-else class="empty">暂无目录树数据。</p>

      <section v-if="sampledPatterns.length > 0 || filenameSampleGroups.length > 0" class="sampling-panel">
        <h5>抽样与文件名关联</h5>
        <div v-if="sampledPatterns.length > 0" class="sampling-list">
          <article v-for="item in sampledPatterns.slice(0, 6)" :key="`${String(item.directory)}-${String(item.pattern)}`">
            <strong>{{ item.pattern }}</strong>
            <span>{{ item.directory }}：共 {{ item.total }} 个，读取 {{ asArray(item.sampled).length }} 个，跳过 {{ asArray(item.skipped).length }} 个</span>
            <span class="sampling-review">LLM review: {{ samplingReviewDecision(item) }}</span>
            <span v-if="samplingReviewReason(item)" class="sampling-review muted">{{ samplingReviewReason(item) }}</span>
            <small v-if="asArray(item.planned_sampled).length > 0" class="sampling-review muted">planned read {{ asArray(item.planned_sampled).length }}, final read {{ asArray(item.sampled).length }}</small>
          </article>
        </div>
        <div v-if="filenameSampleGroups.length > 0" class="sample-group-note">
          已识别 {{ filenameSampleGroups.length }} 组同一 sample_id 下的多文件组合，例如图片、水平井表、类型井表这类 `{id}+{data_kind}` 结构。
        </div>
      </section>

      <section class="investigator-panel">
        <div class="investigator-head">
          <h5>Question-Driven Investigator</h5>
          <span class="investigator-pill" :class="{ off: !investigatorEnabled }">{{ investigatorStatus }}</span>
        </div>
        <p v-if="investigatorSummary" class="investigator-summary">{{ investigatorSummary }}</p>
        <p v-else class="investigator-summary muted">
          {{ investigatorEnabled ? '默认开启：等待数据认知阶段生成疑问、只读脚本和结论。' : '已在任务配置中关闭。' }}
        </p>
        <div class="investigator-stats">
          <span>疑问 {{ investigatorQuestions.length }}</span>
          <span>脚本 {{ investigatorScripts.length }}</span>
          <span>成功 {{ investigatorResultCounts.completed }}</span>
          <span>失败 {{ investigatorResultCounts.failed }}</span>
          <span>修复 {{ investigatorResultCounts.repairs }}</span>
        </div>
        <div v-if="investigatorQuestions.length > 0" class="investigator-list">
          <strong>当前疑问</strong>
          <article v-for="item in investigatorQuestions.slice(0, 4)" :key="String(item.question_id ?? item.question)">
            <span>{{ String(item.question ?? '') }}</span>
            <small>{{ String(item.category ?? 'other') }} · {{ String(item.priority ?? 'medium') }}</small>
          </article>
        </div>
        <div v-if="investigatorResults.length > 0" class="investigator-list">
          <strong>脚本执行摘要</strong>
          <article v-for="item in investigatorResults.slice(-4).reverse()" :key="String(item.request_id ?? item.question_id)">
            <span>{{ String(item.question_id ?? '-') }} · {{ String(item.status ?? '-') }}</span>
            <small>{{ compactResultPreview(item) }}</small>
          </article>
        </div>
        <div v-if="investigatorAnswers.length > 0" class="investigator-list">
          <strong>最终结论</strong>
          <article v-for="item in investigatorAnswers.slice(0, 4)" :key="String(item.question_id ?? item.answer)">
            <span>{{ String(item.answer ?? '') }}</span>
            <small>{{ String(item.confidence ?? 'medium') }} · {{ asArray(item.evidence).slice(0, 2).join('；') }}</small>
          </article>
        </div>
        <div v-if="investigatorUnresolved.length > 0" class="investigator-list unresolved">
          <strong>未解决问题</strong>
          <article v-for="item in investigatorUnresolved.slice(0, 4)" :key="item">
            <span>{{ item }}</span>
          </article>
        </div>
      </section>

      <section v-if="recentCognitionEvents.length > 0" class="event-panel">
        <h5>最近认知事件</h5>
        <article v-for="eventRow in recentCognitionEvents" :key="`${String(eventRow.seq ?? '')}-${String(eventRow.ts ?? '')}`">
          <strong>{{ eventTitle(eventRow) }}</strong>
          <span>{{ eventFile(eventRow) }}</span>
        </article>
      </section>

      <p class="tip">单击目录展开/收起；双击加粗节点预览认知文档；目录有目录级认知时也可双击预览。</p>
    </aside>

    <main class="right">
      <CognitionProbePanel
        :path="selectedDisplayPath"
        :payload="selectedPayload"
        :is-root="selectedIsRoot"
      />
      <p v-if="!selectedPayload" class="empty">请选择左侧已加粗的认知节点。</p>
      <p class="trace-footnote">本任务已有 {{ traceCount }} 个文件保存了结构化 agent 探查轨迹。</p>
    </main>
  </section>
</template>

<style scoped>
.page {
  display: grid;
  grid-template-columns: minmax(320px, 0.9fr) minmax(420px, 1.2fr);
  gap: 12px;
}

.left,
.right {
  border: 1px solid #d0ddee;
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.94);
  padding: 12px;
  min-height: 520px;
}

.section-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.eyebrow {
  margin: 0 0 4px;
  color: #6c84a8;
  font-size: 12px;
}

h4,
h5 {
  margin: 0;
  color: #254a76;
}

.root-button {
  border: 1px solid #b9cbea;
  border-radius: 999px;
  background: #eef5ff;
  color: #315b8a;
  cursor: pointer;
  padding: 5px 10px;
}

.status-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 8px;
  margin: 12px 0;
}

.status-card {
  border-radius: 12px;
  padding: 8px;
  background: #f2f6fc;
  border: 1px solid #d8e3f1;
}

.status-card span {
  display: block;
  font-size: 12px;
  color: #607b9f;
}

.status-card strong {
  display: block;
  margin-top: 4px;
  color: #294e78;
}

.status-card.read {
  background: #eaf8ef;
}

.status-card.reading {
  background: #edf4ff;
}

.status-card.skipped {
  background: #f1f4f8;
}

.status-card.failed {
  background: #fff0f0;
}

.root,
.root ul {
  margin: 0;
  padding-left: 14px;
}

.title {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-weight: 700;
  color: #2f4b72;
}

.root-title {
  cursor: pointer;
}

.root-title:hover {
  text-decoration: underline;
}

.dot {
  width: 9px;
  height: 9px;
  border-radius: 50%;
  display: inline-block;
  background: #9ba9bc;
}

.dot.read {
  background: #28a745;
}

.dot.reading {
  background: #2b74ff;
}

.dot.skipped {
  background: #8c9aab;
}

.dot.failed {
  background: #d33d3d;
}

.dot.partial {
  background: #d18a2d;
}

.sampling-panel {
  margin-top: 14px;
  border: 1px solid #d8e3f2;
  border-radius: 12px;
  background: #f8fbff;
  padding: 10px;
}

.event-panel {
  margin-top: 10px;
  border: 1px solid #d8e3f2;
  border-radius: 12px;
  background: #fffdf8;
  padding: 10px;
}

.investigator-panel {
  margin-top: 10px;
  border: 1px solid #cfe0d6;
  border-radius: 12px;
  background: linear-gradient(135deg, #f4fff8 0%, #f8fbff 100%);
  padding: 10px;
}

.investigator-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.investigator-pill {
  border-radius: 999px;
  background: #dff6e7;
  color: #21613a;
  font-size: 11px;
  padding: 3px 8px;
}

.investigator-pill.off {
  background: #eef1f5;
  color: #67788f;
}

.investigator-summary {
  margin: 8px 0;
  color: #365f48;
  font-size: 12px;
  line-height: 1.5;
}

.investigator-summary.muted {
  color: #667f94;
}

.investigator-stats {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin: 8px 0;
}

.investigator-stats span {
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.82);
  border: 1px solid #d4e6dc;
  color: #315b45;
  font-size: 11px;
  padding: 3px 7px;
}

.investigator-list {
  display: grid;
  gap: 6px;
  margin-top: 8px;
  color: #365f48;
  font-size: 12px;
}

.investigator-list article {
  display: grid;
  gap: 2px;
  border-top: 1px dashed #cfdfd5;
  padding-top: 6px;
}

.investigator-list small {
  color: #61798e;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.investigator-list.unresolved {
  color: #8a542f;
}

.event-panel article {
  display: grid;
  gap: 2px;
  padding: 6px 0;
  border-bottom: 1px dashed #d9e2ef;
  color: #405f84;
  font-size: 12px;
}

.event-panel article:last-child {
  border-bottom: 0;
}

.event-panel strong {
  color: #244b78;
}

.event-panel span {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.sampling-list {
  display: grid;
  gap: 7px;
  margin-top: 8px;
}

.sampling-list article {
  display: grid;
  gap: 2px;
  color: #405f84;
  font-size: 12px;
}

.sampling-review {
  color: #2f5f3e;
  font-size: 11px;
}

.sampling-review.muted {
  color: #657a95;
}

.sample-group-note {
  margin-top: 8px;
  color: #405f84;
  font-size: 12px;
  line-height: 1.5;
}

.tip,
.trace-footnote {
  margin: 10px 0 0;
  color: #57739a;
  font-size: 12px;
}

.empty {
  color: #597cae;
}

@media (max-width: 1100px) {
  .page {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 720px) {
  .status-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
</style>
