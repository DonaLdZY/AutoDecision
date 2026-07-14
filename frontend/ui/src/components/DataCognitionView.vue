<script setup lang="ts">
import { computed, shallowRef } from 'vue'
import type { SnapshotPayload } from '../types'
import { deriveCognitionProgress } from '../utils/cognitionProgress'
import CognitionProbePanel from './CognitionProbePanel.vue'
import CognitionTreeNode from './CognitionTreeNode.vue'
import QDIWorkbench from './QDIWorkbench.vue'
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
const currentState = computed(() => asRecord(ar.value.current_state))
const cognitionCompleted = computed(() => {
  return String(currentState.value.status ?? '').toLowerCase() === 'completed'
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
const cognitionProgress = computed(() => deriveCognitionProgress(events.value, {
  totalFiles: Object.values(stateCounts.value).reduce((sum, count) => sum + count, 0),
  completedFiles: stateCounts.value.read,
  failedFiles: stateCounts.value.failed,
  reportAvailable: Object.keys(report.value).length > 0,
}))
const traceCount = computed(() => {
  let count = 0
  for (const payload of Object.values(normalizedIndex.value)) {
    const metadata = asRecord(payload.json?.source_metadata)
    if (Object.keys(asRecord(metadata.cognition_trace)).length > 0) count += 1
  }
  return count
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

</script>

<template>
  <section class="page">
    <section class="overall-progress" :class="cognitionProgress.status">
      <div class="progress-heading">
        <div>
          <p class="eyebrow">Live Cognition Progress</p>
          <div class="progress-title-row">
            <h3>数据总体认知</h3>
            <span class="overall-state" :class="cognitionProgress.status">{{ cognitionProgress.statusLabel }}</span>
          </div>
          <p class="current-activity">
            <span v-if="cognitionProgress.status === 'running'" class="activity-pulse" aria-hidden="true"></span>
            {{ cognitionProgress.activityLabel }}
          </p>
        </div>
        <div class="progress-number">
          <strong>{{ cognitionProgress.percent }}%</strong>
          <span v-if="cognitionProgress.lastUpdate">更新于 {{ cognitionProgress.lastUpdate }}</span>
        </div>
      </div>

      <div class="progress-track" aria-label="数据总体认知进度">
        <span :style="{ width: `${cognitionProgress.percent}%` }"></span>
      </div>

      <div class="stage-strip">
        <article v-for="(stage, index) in cognitionProgress.stages" :key="stage.key" :class="stage.status">
          <span class="stage-index">{{ String(index + 1).padStart(2, '0') }}</span>
          <div>
            <strong>{{ stage.label }}</strong>
            <small>{{ stage.detail }}</small>
          </div>
          <span class="stage-dot" aria-hidden="true"></span>
        </article>
      </div>
    </section>

    <div class="cognition-grid">
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
    </div>

    <QDIWorkbench
      :report="questionInvestigation"
      :events="events"
      :current-state="currentState"
      :enabled="investigatorEnabled"
    />
  </section>
</template>

<style scoped>
.page {
  display: grid;
  gap: 16px;
}

.overall-progress {
  overflow: hidden;
  border: 1px solid #c7dce4;
  border-radius: 20px;
  padding: 20px 22px;
  background:
    radial-gradient(circle at 92% 0%, rgba(12, 128, 119, 0.14), transparent 27%),
    linear-gradient(140deg, #f8fcfb 0%, #f0f7fa 58%, #edf5f4 100%);
  box-shadow: 0 16px 38px rgba(27, 76, 96, 0.07);
}

.overall-progress.completed {
  border-color: #b9d9ca;
}

.overall-progress.failed {
  border-color: #efc5bd;
}

.progress-heading,
.progress-title-row,
.current-activity,
.stage-strip article {
  display: flex;
  align-items: center;
}

.progress-heading {
  justify-content: space-between;
  gap: 20px;
}

.progress-title-row {
  flex-wrap: wrap;
  gap: 10px;
}

.progress-title-row h3 {
  margin: 2px 0 0;
  color: #173f55;
  font-size: 22px;
}

.overall-state {
  border-radius: 999px;
  padding: 4px 10px;
  background: #e8eef1;
  color: #587181;
  font-size: 11px;
  font-weight: 800;
}

.overall-state.running {
  background: #dff3ef;
  color: #08766d;
}

.overall-state.completed {
  background: #dff2e7;
  color: #267052;
}

.overall-state.failed {
  background: #fde8e4;
  color: #a24439;
}

.current-activity {
  gap: 8px;
  margin: 9px 0 0;
  color: #4b6c7e;
  font-size: 13px;
}

.activity-pulse {
  width: 8px;
  height: 8px;
  flex: 0 0 auto;
  border-radius: 50%;
  background: #0b8f83;
  box-shadow: 0 0 0 0 rgba(11, 143, 131, 0.35);
  animation: cognition-pulse 1.8s infinite;
}

.progress-number {
  display: grid;
  justify-items: end;
  gap: 2px;
  color: #6b8492;
  font-size: 11px;
}

.progress-number strong {
  color: #164f62;
  font-family: Georgia, serif;
  font-size: 30px;
  line-height: 1;
}

.progress-track {
  height: 7px;
  margin-top: 17px;
  overflow: hidden;
  border-radius: 999px;
  background: #dce8eb;
}

.progress-track span {
  display: block;
  height: 100%;
  border-radius: inherit;
  background: linear-gradient(90deg, #197c86, #0d9b81);
  transition: width 500ms ease;
}

.stage-strip {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 8px;
  margin-top: 14px;
}

.stage-strip article {
  position: relative;
  min-width: 0;
  gap: 9px;
  border: 1px solid #d5e2e6;
  border-radius: 12px;
  padding: 10px 28px 10px 10px;
  background: rgba(255, 255, 255, 0.68);
}

.stage-strip article.running {
  border-color: #8fc9c2;
  background: #ecf8f5;
}

.stage-strip article.completed {
  border-color: #c1dece;
  background: #f2faf5;
}

.stage-strip article.failed {
  border-color: #efc7c0;
  background: #fff4f1;
}

.stage-index {
  color: #87a0ab;
  font-family: Consolas, monospace;
  font-size: 10px;
  font-weight: 800;
}

.stage-strip article > div {
  display: grid;
  min-width: 0;
  gap: 3px;
}

.stage-strip strong {
  overflow: hidden;
  color: #31596c;
  font-size: 12px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.stage-strip small {
  overflow: hidden;
  color: #738b98;
  font-size: 10px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.stage-dot {
  position: absolute;
  top: 12px;
  right: 10px;
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #b6c4ca;
}

.running .stage-dot {
  background: #0c9284;
  animation: cognition-pulse 1.8s infinite;
}

.completed .stage-dot {
  background: #3d9a69;
}

.failed .stage-dot {
  background: #c45243;
}

@keyframes cognition-pulse {
  70% { box-shadow: 0 0 0 7px rgba(11, 143, 131, 0); }
  100% { box-shadow: 0 0 0 0 rgba(11, 143, 131, 0); }
}

.cognition-grid {
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
  .stage-strip {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }

  .cognition-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 720px) {
  .progress-heading {
    align-items: flex-start;
  }

  .progress-number {
    flex: 0 0 auto;
  }

  .stage-strip {
    grid-template-columns: 1fr;
  }

  .status-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
</style>
