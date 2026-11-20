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

function samplingReviewLabel(item: Record<string, unknown>) {
  const decision = String(samplingReview(item).decision ?? '').toLowerCase()
  if (decision === 'deterministic_accept' || decision === 'accept_sampling') return '抽样已确认'
  if (decision === 'accept_sampling_with_extra_files') return '已补充样本'
  if (decision.startsWith('force_full_read')) return '改为完整读取'
  return '已完成复核'
}

function samplingReviewReason(item: Record<string, unknown>) {
  const review = samplingReview(item)
  const reason = String(review.reason ?? review.risk ?? '').trim()
  if (reason.includes('low-token mode accepts rule-verified same-pattern sampling')) {
    return '轻量模式按文件规则确认抽样，未调用语言模型复核。'
  }
  if (reason.includes('LLM did not return a review item for this pattern_id')) {
    return '未取得复核结果，因此改为完整读取。'
  }
  return /[\u3400-\u9fff]/.test(reason) ? reason : ''
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
          <div class="title root-title" role="button" tabindex="0" @click="onRootDblclick" @keydown.enter="onRootDblclick">
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
        <h5>重复文件抽样</h5>
        <div v-if="sampledPatterns.length > 0" class="sampling-list">
          <article v-for="item in sampledPatterns.slice(0, 6)" :key="`${String(item.directory)}-${String(item.pattern)}`">
            <strong>{{ item.directory || '同类文件' }}</strong>
            <span>共 {{ item.total }} 个，读取 {{ asArray(item.sampled).length }} 个，跳过 {{ asArray(item.skipped).length }} 个</span>
            <span class="sampling-review">{{ samplingReviewLabel(item) }}</span>
            <span v-if="samplingReviewReason(item)" class="sampling-review muted">{{ samplingReviewReason(item) }}</span>
          </article>
        </div>
        <div v-if="filenameSampleGroups.length > 0" class="sample-group-note">
          已识别 {{ filenameSampleGroups.length }} 组按编号关联的多文件数据。
        </div>
      </section>

      </aside>

      <main class="right">
        <CognitionProbePanel
          :path="selectedDisplayPath"
          :payload="selectedPayload"
          :is-root="selectedIsRoot"
        />
        <p v-if="!selectedPayload" class="empty">暂无文件认知记录</p>
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
  border: 1px solid #d2d2d7;
  border-radius: 8px;
  padding: 20px 22px;
  background: #fff;
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
  border-radius: 4px;
  padding: 4px 8px;
  background: #f5f5f7;
  color: #6e6e73;
  font-size: 11px;
  font-weight: 800;
}

.overall-state.running {
  background: #e8f2ff;
  color: #075db5;
}

.overall-state.completed {
  background: #e8f5ec;
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
  color: #1d1d1f;
  font-size: 30px;
  line-height: 1;
}

.progress-track {
  height: 4px;
  margin-top: 17px;
  overflow: hidden;
  border-radius: 999px;
  background: #e8e8ed;
}

.progress-track span {
  display: block;
  height: 100%;
  border-radius: inherit;
  background: #0071e3;
  transition: width 500ms ease;
}

.stage-strip {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 0;
  margin-top: 14px;
  border-top: 1px solid #d2d2d7;
  border-bottom: 1px solid #d2d2d7;
}

.stage-strip article {
  position: relative;
  min-width: 0;
  gap: 9px;
  border-right: 1px solid #d2d2d7;
  padding: 10px 24px 10px 10px;
  background: #fff;
}

.stage-strip article.running {
  background: #f5f9ff;
}

.stage-strip article.completed {
  background: #f5faf6;
}

.stage-strip article.failed {
  background: #fff7f5;
}

.stage-strip article:last-child {
  border-right: 0;
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
  border-top: 1px solid #d2d2d7;
  border-bottom: 1px solid #d2d2d7;
  background: #fff;
  padding: 12px 16px;
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
  border: 1px solid #d2d2d7;
  border-radius: 5px;
  background: #fff;
  color: #075db5;
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
  border-radius: 5px;
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
  border-top: 1px solid #d2d2d7;
  border-bottom: 1px solid #d2d2d7;
  background: #fff;
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

.tip {
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
