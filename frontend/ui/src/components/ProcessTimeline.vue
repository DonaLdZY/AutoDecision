<script setup lang="ts">
import { computed, onMounted, onUnmounted, shallowRef, watch } from 'vue'
import type { Task } from '../types'
import { displayTaskName } from '../utils/taskName'
import {
  activeProcessStep,
  componentLabel,
  eventStatusLabel,
  eventTone,
  phaseLabel,
  timelineEventSummary,
  timelineEventTime,
  timelineEventTitle,
} from '../utils/timelinePresentation'
import CognitionTreeNode from './CognitionTreeNode.vue'
import type { CognitionTreeNode as TreeNode, ReadState } from './cognition-tree-types'
import { readStateLabel } from './cognition-tree-types'

const props = defineProps<{
  task?: Task | null
  autoRealizeState?: Record<string, unknown>
  webResearchMetrics?: Record<string, unknown>
  directoryTreeText?: string
  autoRealizeEvents: Record<string, unknown>[]
  autoMlEvents: Record<string, unknown>[]
}>()

const nowTs = shallowRef(Date.now())
let timer: number | null = null
let mounted = false

function syncElapsedTimer() {
  if (timer !== null) window.clearInterval(timer)
  timer = null
  if (mounted && props.task?.status === 'running') {
    timer = window.setInterval(() => {
      nowTs.value = Date.now()
    }, 1000)
  }
}

onMounted(() => {
  mounted = true
  syncElapsedTimer()
})

watch(() => props.task?.status, syncElapsedTimer)

onUnmounted(() => {
  mounted = false
  if (timer !== null) {
    window.clearInterval(timer)
    timer = null
  }
})

const merged = computed(() => {
  const rows = [...props.autoRealizeEvents, ...props.autoMlEvents]
  rows.sort((a, b) => {
    const sa = Number(a.seq ?? -1)
    const sb = Number(b.seq ?? -1)
    if (Number.isFinite(sa) && Number.isFinite(sb) && sa >= 0 && sb >= 0 && sa !== sb) return sa - sb
    return String(a.ts ?? '').localeCompare(String(b.ts ?? ''))
  })
  return rows.slice(-300)
})

const runningElapsed = computed(() => {
  const started = Number(props.task?.run_started_at ?? 0)
  if (!started || started <= 0) return '-'
  const endMs = props.task?.status === 'running' ? nowTs.value : Number(props.task?.updated_at ?? started) * 1000
  const seconds = Math.max(0, Math.floor(endMs / 1000 - started))
  const h = Math.floor(seconds / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  const s = seconds % 60
  if (h > 0) return `${h} 小时 ${m} 分 ${s} 秒`
  if (m > 0) return `${m} 分 ${s} 秒`
  return `${s} 秒`
})

const activeComponentText = computed(() => {
  const state = props.autoRealizeState ?? {}
  const active = state.active_components
  if (Array.isArray(active) && active.length > 0) {
    const first = active[0] as Record<string, unknown>
    return currentActivity(first.component, first.event)
  }
  if (props.task?.phase === 'automl') {
    const latest = [...props.autoMlEvents].reverse().find((x) => String(x.status ?? '') === 'running')
    if (latest) return currentActivity(latest.component, latest.event)
    return '正在搜索方案'
  }
  const latest = [...props.autoRealizeEvents].reverse().find((x) => String(x.status ?? '') === 'running')
  if (latest) return currentActivity(latest.component, latest.event)
  return phaseLabel(props.task?.phase)
})

const activeComponent = computed(() => {
  const state = props.autoRealizeState ?? {}
  const active = state.active_components
  if (Array.isArray(active) && active.length > 0) {
    return String((active[0] as Record<string, unknown>)?.component ?? '')
  }
  const latest = [...props.autoRealizeEvents].reverse().find((event) => {
    return String(event.status ?? '').toLowerCase() === 'running'
  })
  return String(latest?.component ?? '')
})

const webResearchSummary = computed(() => {
  const metrics = props.webResearchMetrics ?? {}
  const status = String(metrics.status ?? '').toLowerCase()
  if (!status || ['disabled', 'skipped', 'not_started'].includes(status)) return null

  const search = (metrics.search ?? {}) as Record<string, unknown>
  const fetchAttempts = Array.isArray(metrics.fetch_attempts) ? metrics.fetch_attempts : []
  const accepted = Number(search.accepted_count ?? 0)
  const elapsed = Number(metrics.elapsed_ms ?? 0)
  const labels: Record<string, string> = {
    success: accepted > 0 ? `找到 ${accepted} 条可用网页资料` : '已完成网页检索',
    cache_hit: '复用了已缓存的网页资料',
    no_relevant_results: '没有找到可用的网页资料',
    error: '网页检索暂不可用，方案搜索仍可继续',
    cache_join_miss: '同一检索正在由其他任务处理',
  }
  return {
    label: labels[status] ?? '网页检索状态已记录',
    elapsed: elapsed > 0 ? `${(elapsed / 1000).toFixed(1)} 秒` : '',
    hosts: Array.isArray(search.source_hosts)
      ? search.source_hosts.filter((host): host is string => typeof host === 'string').slice(0, 5)
      : [],
    fetched: fetchAttempts.filter((attempt) => {
      return String((attempt as Record<string, unknown>).status ?? '') === 'success'
    }).length,
  }
})

function currentActivity(component: unknown, event: unknown) {
  const title = timelineEventTitle({ component, event, status: 'running' }, props.task?.phase)
  return title === '运行状态已更新'
    ? `正在${componentLabel(component, props.task?.phase)}`
    : title
}

function normalizeRelPath(v: string) {
  return v.replaceAll('\\', '/').replace(/^\.?\//, '')
}

const readStateByFile = computed(() => {
  const map: Record<string, ReadState> = {}
  const rows = [...props.autoRealizeEvents]
  rows.sort((a, b) => {
    const sa = Number(a.seq ?? -1)
    const sb = Number(b.seq ?? -1)
    if (Number.isFinite(sa) && Number.isFinite(sb) && sa !== sb) return sa - sb
    return String(a.ts ?? '').localeCompare(String(b.ts ?? ''))
  })
  for (const e of rows) {
    const component = String(e.component ?? '')
    const event = String(e.event ?? '').toUpperCase()
    const fields = (e.fields ?? {}) as Record<string, unknown>

    if (component.startsWith('stage.P1')) {
      const file = normalizeRelPath(String(fields.file ?? ''))
      if (!file) continue
      if (event === 'READING_FILE') {
        map[file] = 'reading'
      } else if (event === 'READ_COMPLETED') {
        if (map[file] !== 'failed' && map[file] !== 'read') map[file] = 'reading'
      } else if (event === 'READ_FAILED') {
        map[file] = 'failed'
      }
      continue
    }

    if (component === 'module.data_cognition.file_artifact' && event === 'GENERATED_FILE') {
      const source = normalizeRelPath(String(fields.source ?? ''))
      if (!source) continue
      if (map[source] !== 'failed') map[source] = 'read'
    }
  }
  return map
})

function aggregateNodeState(node: TreeNode): ReadState {
  if (!node.isDir || node.children.length === 0) return node.readState
  const childStates = node.children.map(aggregateNodeState)
  let merged: ReadState
  if (childStates.some((x) => x === 'reading')) merged = 'reading'
  else if (childStates.some((x) => x === 'failed')) merged = 'failed'
  else if (childStates.every((x) => x === 'read' || x === 'skipped')) merged = 'read'
  else if (childStates.every((x) => x === 'skipped')) merged = 'skipped'
  else if (childStates.every((x) => x === 'unread')) merged = 'unread'
  else merged = 'partial'
  node.readState = merged
  return merged
}

const cognitionTree = computed<TreeNode | null>(() => {
  const text = props.directoryTreeText ?? ''
  if (!text.trim()) return null
  const lines = text
    .split('\n')
    .map((x) => x.replace(/\r$/, ''))
    .filter((x) => x.trim().length > 0)
  if (lines.length === 0) return null

  const root: TreeNode = {
    name: lines[0].trim(),
    path: '',
    isDir: true,
    children: [],
    readState: 'unread',
  }
  const stack: TreeNode[] = [root]

  for (let i = 1; i < lines.length; i += 1) {
    const line = lines[i]
    const m = line.match(/^(\s*)- (.+)$/)
    if (!m) continue
    const spaces = m[1].length
    const level = Math.floor(spaces / 2) + 1
    const rawName = m[2].trim()
    const isDir = rawName.endsWith('/')
    const name = isDir ? rawName.slice(0, -1) : rawName
    const parent = stack[Math.max(0, level - 1)] ?? root
    const base = parent.path ? `${parent.path}/` : ''
    const path = normalizeRelPath(`${base}${name}`)
    const done = String((props.autoRealizeState ?? {}).status ?? '').toLowerCase() === 'completed'
    const state: ReadState = isDir ? 'unread' : (readStateByFile.value[path] ?? (done ? 'skipped' : 'unread'))
    const node: TreeNode = {
      name,
      path,
      isDir,
      children: [],
      readState: state,
    }
    parent.children.push(node)
    stack[level] = node
    stack.length = level + 1
  }

  root.readState = aggregateNodeState(root)
  return root
})

type StepMeta = {
  key: 'data_cognition' | 'task_definition' | 'automl' | 'report'
  label: string
  disabled?: boolean
}

const steps: StepMeta[] = [
  { key: 'data_cognition', label: '1. 数据理解' },
  { key: 'task_definition', label: '2. 任务定义' },
  { key: 'automl', label: '3. 方案搜索' },
  { key: 'report', label: '4. 报告与交付' },
]

const activeStepKey = computed<StepMeta['key'] | null>(() => {
  return activeProcessStep(props.task?.phase, activeComponent.value)
})

function stepClass(step: StepMeta) {
  return {
    todo: !!step.disabled,
    active: activeStepKey.value === step.key && props.task?.status === 'running',
  }
}
</script>

<template>
  <section class="timeline-panel">
    <h3>运行记录</h3>
    <div class="runtime-bar" v-if="task">
      <span>任务：{{ displayTaskName(task.task_name) }}</span>
      <span>当前活动：{{ activeComponentText }}</span>
      <span>运行时长：{{ runningElapsed }}</span>
    </div>

    <div class="steps-hint">
      <span v-for="step in steps" :key="step.key" :class="stepClass(step)">{{ step.label }}</span>
    </div>

    <div class="cognition-tree" v-if="cognitionTree">
      <h4>数据目录</h4>
      <div class="legend">
        <span class="dot unread"></span><span>未读取</span>
        <span class="dot reading"></span><span>正在读取</span>
        <span class="dot read"></span><span>已整理</span>
        <span class="dot skipped"></span><span>抽样未读取</span>
        <span class="dot partial"></span><span>部分读取</span>
      </div>
      <ul class="tree-root">
        <li>
          <span class="node-row">
            <span class="dot" :class="cognitionTree.readState"></span>
            <strong>{{ cognitionTree.name }}</strong>
            <small>{{ readStateLabel(cognitionTree.readState) }}</small>
          </span>
          <ul v-if="cognitionTree.children.length > 0">
            <CognitionTreeNode
              v-for="child in cognitionTree.children"
              :key="child.path"
              :node="child"
              :depth="1"
            />
          </ul>
        </li>
      </ul>
    </div>

    <section v-if="webResearchSummary" class="web-research-summary" aria-label="网页检索结果">
      <div class="web-research-main">
        <strong>{{ webResearchSummary.label }}</strong>
        <span v-if="webResearchSummary.elapsed">耗时 {{ webResearchSummary.elapsed }}</span>
        <span v-if="webResearchSummary.fetched > 0">已读取 {{ webResearchSummary.fetched }} 个网页</span>
      </div>
      <details v-if="webResearchSummary.hosts.length > 0">
        <summary>查看来源网站</summary>
        <ul>
          <li v-for="host in webResearchSummary.hosts" :key="host">{{ host }}</li>
        </ul>
      </details>
    </section>

    <div class="timeline-list" role="list" aria-label="任务运行事件">
      <article v-for="(evt, idx) in merged" :key="`${String(evt.ts)}-${idx}`" class="timeline-item" role="listitem">
        <header>
          <div class="event-heading">
            <strong>{{ timelineEventTitle(evt, task?.phase) }}</strong>
            <span class="event-status" :class="eventTone(evt)">{{ eventStatusLabel(evt) }}</span>
          </div>
          <time>{{ timelineEventTime(evt.ts) }}</time>
        </header>
        <p v-if="timelineEventSummary(evt)" class="event-summary">{{ timelineEventSummary(evt) }}</p>
        <details>
          <summary>技术详情</summary>
          <pre>{{ JSON.stringify({ component: evt.component, event: evt.event, fields: evt.fields, classification: evt.classification }, null, 2) }}</pre>
        </details>
      </article>
    </div>
  </section>
</template>

<style scoped>
.timeline-panel {
  background: #ffffff;
  border: 1px solid #d2d2d7;
  border-radius: 4px;
  padding: 14px;
}

.timeline-panel h3 {
  margin: 0 0 8px;
}

.runtime-bar {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
  margin-bottom: 8px;
}

.runtime-bar span {
  padding: 3px 8px;
  border-radius: 3px;
  background: #f5f5f7;
  font-size: 12px;
  color: #424247;
}

.steps-hint {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 12px;
}

.steps-hint span {
  padding: 3px 8px;
  border-radius: 3px;
  background: #f5f5f7;
  font-size: 12px;
  color: #626267;
}

.steps-hint .todo {
  background: #f5f5f7;
  color: #86868b;
}

.steps-hint .active {
  background: #eaf3ff;
  color: #0066cc;
  border: 1px solid #9ac7ff;
}

.cognition-tree {
  margin-bottom: 12px;
  border: 1px solid #d2d2d7;
  border-radius: 4px;
  background: #ffffff;
  padding: 10px;
}

.cognition-tree h4 {
  margin: 0 0 8px;
  color: #2c4d77;
}

.legend {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 8px;
  font-size: 12px;
  color: #526585;
}

.tree-root,
.tree-root ul {
  margin: 0;
  padding-left: 16px;
}

.node-row {
  display: inline-flex;
  gap: 6px;
  align-items: center;
  font-size: 13px;
  color: #2f4a72;
  line-height: 1.5;
}

.node-row small {
  color: #637ea6;
}

.web-research-summary {
  margin-bottom: 12px;
  padding: 10px 12px;
  border: 1px solid #d2d2d7;
  border-left: 3px solid #0071e3;
  background: #f5f5f7;
  color: #1d1d1f;
  font-size: 12px;
}

.web-research-main {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 14px;
  align-items: baseline;
}

.web-research-main span,
.web-research-summary details {
  color: #626267;
}

.web-research-summary details {
  margin-top: 7px;
}

.web-research-summary summary {
  width: fit-content;
  cursor: pointer;
}

.web-research-summary ul {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 18px;
  margin: 7px 0 0;
  padding-left: 18px;
}

.dot {
  width: 9px;
  height: 9px;
  border-radius: 50%;
  display: inline-block;
  background: #b0b8c5;
}

.dot.unread {
  background: #9ba9bc;
}

.dot.read {
  background: #28a745;
}

.dot.reading {
  background: #2b74ff;
  box-shadow: 0 0 0 3px rgba(43, 116, 255, 0.2);
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

.timeline-list {
  display: grid;
  gap: 8px;
  max-height: 440px;
  overflow: auto;
}

.timeline-item {
  border: 1px solid #d2d2d7;
  background: #fff;
  border-radius: 4px;
  padding: 8px;
}

.timeline-item header {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  justify-content: space-between;
  gap: 12px;
}

.event-heading {
  display: flex;
  min-width: 0;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
}

.event-heading strong {
  color: #213f6f;
}

.timeline-item time {
  color: #7083a8;
  font-size: 12px;
  white-space: nowrap;
}

.event-status {
  flex: none;
  padding: 1px 6px;
  border-radius: 4px;
  font-size: 12px;
}

.event-status.running { color: #175a9a; background: #e8f3ff; }
.event-status.success { color: #247047; background: #eaf5ec; }
.event-status.warning { color: #885f16; background: #fff4d9; }
.event-status.failed { color: #9a3e36; background: #fff0ed; }
.event-status.info { color: #596879; background: #f0f2f5; }

.event-summary {
  margin: 5px 0;
  color: #526585;
  font-size: 12px;
  overflow-wrap: anywhere;
}

.timeline-item details {
  margin-top: 5px;
  color: #68788b;
  font-size: 12px;
}

.timeline-item details summary {
  cursor: pointer;
}

.timeline-item pre {
  margin: 0;
  font-size: 12px;
  background: #f5f5f7;
  border-radius: 4px;
  padding: 6px;
  overflow: auto;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

@media (max-width: 600px) {
  .timeline-item header { grid-template-columns: minmax(0, 1fr); }
  .timeline-item time { white-space: normal; }
}
</style>
