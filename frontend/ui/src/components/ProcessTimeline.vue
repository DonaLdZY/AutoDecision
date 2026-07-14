<script setup lang="ts">
import { computed, onMounted, onUnmounted, shallowRef } from 'vue'
import type { Task } from '../types'
import CognitionTreeNode from './CognitionTreeNode.vue'
import type { CognitionTreeNode as TreeNode, ReadState } from './cognition-tree-types'
import { readStateLabel } from './cognition-tree-types'

const props = defineProps<{
  task?: Task | null
  autoRealizeState?: Record<string, unknown>
  directoryTreeText?: string
  autoRealizeEvents: Record<string, unknown>[]
  autoMlEvents: Record<string, unknown>[]
}>()

const nowTs = shallowRef(Date.now())
let timer: number | null = null

onMounted(() => {
  timer = window.setInterval(() => {
    nowTs.value = Date.now()
  }, 1000)
})

onUnmounted(() => {
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
  if (h > 0) return `${h}h ${m}m ${s}s`
  if (m > 0) return `${m}m ${s}s`
  return `${s}s`
})

const activeComponentText = computed(() => {
  const state = props.autoRealizeState ?? {}
  const active = state.active_components
  if (Array.isArray(active) && active.length > 0) {
    const first = active[0] as Record<string, unknown>
    return `${String(first.component ?? '-')}.${String(first.event ?? '-')}`
  }
  if (props.task?.phase === 'automl') {
    const latest = [...props.autoMlEvents].reverse().find((x) => String(x.status ?? '') === 'running')
    if (latest) return `${String(latest.component ?? '-')}.${String(latest.event ?? '-')}`
    return 'AutoML.search'
  }
  const latest = [...props.autoRealizeEvents].reverse().find((x) => String(x.status ?? '') === 'running')
  if (latest) return `${String(latest.component ?? '-')}.${String(latest.event ?? '-')}`
  return props.task?.phase ?? '-'
})

function eventTitle(e: Record<string, unknown>) {
  return `${String(e.component ?? '-')}.${String(e.event ?? '-')}`
}

function eventMeta(e: Record<string, unknown>) {
  const status = e.status ?? (e.classification ? (e.classification as Record<string, unknown>).layer : '')
  return String(status ?? '-')
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

    // 闃舵1: 鏂囦欢姝ｅ湪璇诲彇
    if (component.startsWith('stage.P1')) {
      const file = normalizeRelPath(String(fields.file ?? ''))
      if (!file) continue
      if (event === 'READING_FILE') {
        map[file] = 'reading'
      } else if (event === 'READ_COMPLETED') {
        // File IO finished, but cognition is still pending until the artifact is generated.
        if (map[file] !== 'failed' && map[file] !== 'read') map[file] = 'reading'
      } else if (event === 'READ_FAILED') {
        map[file] = 'failed'
      }
      continue
    }

    // Cognition artifact generation is the point where a file becomes fully read.
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
  { key: 'data_cognition', label: '1. 鏁版嵁鐞嗚В' },
  { key: 'task_definition', label: '2. 浠诲姟瀹氫箟' },
  { key: 'automl', label: '3. 鑷姩鏈哄櫒瀛︿範' },
  { key: 'report', label: '4. 鎶ュ憡鐢熸垚(鏈紑鍙?' },
]

const activeStepKey = computed<StepMeta['key'] | null>(() => {
  const c = activeComponentText.value.toLowerCase()
  const phase = String(props.task?.phase ?? '').toLowerCase()
  if (c.includes('data_cognition') || c.includes('stage.p1') || phase.includes('autorealize')) return 'data_cognition'
  if (c.includes('task_definition') || c.includes('stage.p2')) return 'task_definition'
  if (c.includes('mcts') || c.includes('automl') || phase.includes('automl')) return 'automl'
  if (phase.includes('report')) return 'report'
  return null
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
    <h3>娴佺▼鏃堕棿绾?/h3>
    <div class="runtime-bar" v-if="task">
      <span>褰撳墠浠诲姟: {{ task.task_name }}</span>
      <span>褰撳墠鎵ц: {{ activeComponentText }}</span>
      <span>宸茶繍琛? {{ runningElapsed }}</span>
    </div>

    <div class="steps-hint">
      <span v-for="step in steps" :key="step.key" :class="stepClass(step)">{{ step.label }}</span>
    </div>

    <div class="cognition-tree" v-if="cognitionTree">
      <h4>鏁版嵁鐞嗚В鐩綍鏍?/h4>
      <div class="legend">
        <span class="dot unread"></span><span>鏈</span>
        <span class="dot reading"></span><span>璇诲彇涓?/span>
        <span class="dot read"></span><span>璇诲畬(璁ょ煡宸蹭骇鍑?</span>
        <span class="dot skipped"></span><span>涓嶈(鎶芥牱)</span>
        <span class="dot partial"></span><span>閮ㄥ垎宸茶</span>
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

    <div class="timeline-list">
      <article v-for="(evt, idx) in merged" :key="`${String(evt.ts)}-${idx}`" class="timeline-item">
        <header>
          <strong>{{ eventTitle(evt) }}</strong>
          <small>{{ String(evt.ts ?? '-') }}</small>
        </header>
        <div class="meta">{{ eventMeta(evt) }}</div>
        <pre class="fields">{{ JSON.stringify(evt.fields ?? {}, null, 2) }}</pre>
      </article>
    </div>
  </section>
</template>

<style scoped>
.timeline-panel {
  background: #fffef7;
  border: 1px solid #eedfb1;
  border-radius: 14px;
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
  border-radius: 999px;
  background: #f2eac9;
  font-size: 12px;
  color: #5f4a0f;
}

.steps-hint {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 12px;
}

.steps-hint span {
  padding: 3px 8px;
  border-radius: 999px;
  background: #f2eac9;
  font-size: 12px;
  color: #5f4a0f;
}

.steps-hint .todo {
  background: #ffe4d1;
  color: #8b3f0b;
}

.steps-hint .active {
  background: #d6ffe9;
  color: #15633f;
  border: 1px solid #7fdbad;
}

.cognition-tree {
  margin-bottom: 12px;
  border: 1px solid #e7d6a0;
  border-radius: 10px;
  background: #fffdf2;
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
  border: 1px solid #eadbb0;
  background: #fff;
  border-radius: 10px;
  padding: 8px;
}

.timeline-item header {
  display: flex;
  justify-content: space-between;
  gap: 12px;
}

.timeline-item strong {
  color: #213f6f;
}

.timeline-item small {
  color: #7083a8;
}

.meta {
  margin: 4px 0;
  color: #526585;
  font-size: 12px;
}

.fields {
  margin: 0;
  font-size: 12px;
  background: #fbf9ee;
  border-radius: 8px;
  padding: 6px;
  overflow: auto;
}
</style>
