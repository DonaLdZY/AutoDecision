<script setup lang="ts">
import { computed, shallowRef, watch } from 'vue'
import type { MctsNode, SnapshotPayload } from '../types'
import { isPendingNode, nodeReviewState } from '../utils/nodeReviewState'
import DependencyInstallPanel from './DependencyInstallPanel.vue'
import AlgoEvolveSummary from './AlgoEvolveSummary.vue'

const props = defineProps<{
  snapshot?: SnapshotPayload
}>()

type GraphNode = MctsNode & { x: number; y: number; depth: number; order: number }
type GraphEdge = { from: string; to: string; action: 'draft' | 'improve' | 'debug' | 'other' }

const selectedNodeId = shallowRef('')
const nodeW = 170
const nodeH = 72
const xGap = 56
const yGap = 40

const engine = computed(() => String(props.snapshot?.auto_ml?.engine ?? 'algoevolve'))
const isAlgoEvolve = computed(() => ['algoevolve', 'mlevolve'].includes(engine.value))
const nodes = computed(() => props.snapshot?.auto_ml?.nodes ?? [])
const pendingNodes = computed(() => props.snapshot?.auto_ml?.pending_nodes ?? [])
const visiblePendingNodes = computed(() => {
  const seen = new Set(nodes.value.map((node) => node.id))
  return pendingNodes.value.filter((node) => node.id && !seen.has(node.id))
})
const displayNodes = computed(() => [...nodes.value, ...visiblePendingNodes.value])
const bestNodeId = computed(() => props.snapshot?.auto_ml?.best_node_id ?? null)
const bestNodeKind = computed(() => props.snapshot?.auto_ml?.best_node_kind ?? 'delivery')
const bestSolutionCode = computed(() => props.snapshot?.auto_ml?.best_solution_code ?? '')
const bestMetricText = computed(() => props.snapshot?.auto_ml?.best_metric_text ?? '')

const rawStdout = computed(() => props.snapshot?.auto_ml?.frontend_stdout ?? '')
const rawStderr = computed(() => props.snapshot?.auto_ml?.frontend_stderr ?? '')
const serviceStdout = computed(() => props.snapshot?.auto_ml?.service_stdout ?? '')
const serviceStderr = computed(() => props.snapshot?.auto_ml?.service_stderr ?? '')
const mlLog = computed(() => props.snapshot?.auto_ml?.ml_log ?? '')
const verboseLog = computed(() => props.snapshot?.auto_ml?.verbose_log ?? '')

const terminalText = computed(() => {
  if (serviceStderr.value.trim()) return serviceStderr.value
  if (rawStderr.value.trim()) return rawStderr.value
  if (serviceStdout.value.trim()) return serviceStdout.value
  if (rawStdout.value.trim()) return rawStdout.value
  if (mlLog.value.trim()) return mlLog.value
  if (verboseLog.value.trim()) return verboseLog.value
  return ''
})

const nodeMap = computed(() => {
  const map = new Map<string, MctsNode>()
  for (const node of displayNodes.value) map.set(node.id, node)
  return map
})

const childrenMap = computed(() => {
  const map = new Map<string, MctsNode[]>()
  for (const node of displayNodes.value) {
    const parentId = node.parent_id ?? '__root__'
    if (!map.has(parentId)) map.set(parentId, [])
    map.get(parentId)?.push(node)
  }
  for (const arr of map.values()) {
    arr.sort((a, b) => String(a.finish_time ?? '').localeCompare(String(b.finish_time ?? '')))
  }
  return map
})

const roots = computed(() => {
  const out: MctsNode[] = []
  for (const node of displayNodes.value) {
    if (!node.parent_id || !nodeMap.value.has(node.parent_id)) out.push(node)
  }
  out.sort((a, b) => String(a.finish_time ?? '').localeCompare(String(b.finish_time ?? '')))
  return out
})

function assignDepth(root: MctsNode, depth: number, depthMap: Map<string, number>, visited: Set<string>) {
  if (visited.has(root.id)) return
  visited.add(root.id)
  depthMap.set(root.id, depth)
  const children = childrenMap.value.get(root.id) ?? []
  for (const child of children) assignDepth(child, depth + 1, depthMap, visited)
}

function actionOf(stage?: string | null): GraphEdge['action'] {
  const normalized = String(stage ?? '').toLowerCase()
  if (normalized.includes('draft')) return 'draft'
  if (normalized.includes('improve') || normalized.includes('evolution') || normalized.includes('fusion')) return 'improve'
  if (normalized.includes('debug') || normalized.includes('bug')) return 'debug'
  return 'other'
}

const graph = computed(() => {
  const depthMap = new Map<string, number>()
  const visited = new Set<string>()
  for (const root of roots.value) assignDepth(root, 0, depthMap, visited)
  for (const node of displayNodes.value) {
    if (!depthMap.has(node.id)) depthMap.set(node.id, 0)
  }

  const levelMap = new Map<number, MctsNode[]>()
  for (const node of displayNodes.value) {
    const depth = depthMap.get(node.id) ?? 0
    if (!levelMap.has(depth)) levelMap.set(depth, [])
    levelMap.get(depth)?.push(node)
  }
  for (const arr of levelMap.values()) {
    arr.sort((a, b) => String(a.finish_time ?? '').localeCompare(String(b.finish_time ?? '')))
  }

  const depthKeys = [...levelMap.keys()].sort((a, b) => a - b)
  const graphNodes: GraphNode[] = []
  for (const depth of depthKeys) {
    const arr = levelMap.get(depth) ?? []
    for (let i = 0; i < arr.length; i += 1) {
      const node = arr[i]
      graphNodes.push({
        ...node,
        depth,
        order: i,
        x: depth * (nodeW + xGap) + 20,
        y: i * (nodeH + yGap) + 20,
      })
    }
  }

  const edges: GraphEdge[] = []
  for (const node of displayNodes.value) {
    if (!node.parent_id || !nodeMap.value.has(node.parent_id)) continue
    edges.push({ from: node.parent_id, to: node.id, action: actionOf(node.stage) })
  }

  const maxDepth = depthKeys.length ? Math.max(...depthKeys) : 0
  const maxRows = Math.max(1, ...depthKeys.map((depth) => (levelMap.get(depth) ?? []).length))
  const width = Math.max(920, 40 + (maxDepth + 1) * (nodeW + xGap))
  const height = Math.max(380, 40 + maxRows * (nodeH + yGap))
  return { nodes: graphNodes, edges, width, height }
})

watch(
  () => displayNodes.value,
  (rows) => {
    if (!rows.length) {
      selectedNodeId.value = ''
      return
    }
    if (!selectedNodeId.value || !rows.some((item) => item.id === selectedNodeId.value)) {
      selectedNodeId.value = bestNodeId.value || rows[rows.length - 1].id
    }
  },
  { immediate: true, deep: true },
)

const graphNodeMap = computed(() => {
  const map = new Map<string, GraphNode>()
  for (const node of graph.value.nodes) map.set(node.id, node)
  return map
})

const selectedNode = computed(() => displayNodes.value.find((node) => node.id === selectedNodeId.value) ?? null)

function edgePath(from: string, to: string): string {
  const source = graphNodeMap.value.get(from)
  const target = graphNodeMap.value.get(to)
  if (!source || !target) return ''
  const x1 = source.x + nodeW
  const y1 = source.y + nodeH / 2
  const x2 = target.x
  const y2 = target.y + nodeH / 2
  const midX = (x1 + x2) / 2
  return `M ${x1} ${y1} C ${midX} ${y1}, ${midX} ${y2}, ${x2} ${y2}`
}

function nodeClass(node: MctsNode): string[] {
  const classes = ['node-card']
  const reviewState = nodeReviewState(node)
  if (reviewState === 'pending') classes.push('pending')
  else if (reviewState === 'success') classes.push('ok')
  else if (reviewState === 'bug') classes.push('buggy')
  else classes.push('unknown')
  if (node.id === selectedNodeId.value) classes.push('selected')
  if (bestNodeId.value && node.id === bestNodeId.value) classes.push('best')
  return classes
}

function edgeClass(action: GraphEdge['action']) {
  if (action === 'draft') return 'edge-draft'
  if (action === 'improve') return 'edge-improve'
  if (action === 'debug') return 'edge-debug'
  return 'edge-other'
}

function shortMetric(value: number | null | undefined): string {
  if (value === null || value === undefined) return '-'
  return Number(value).toFixed(4)
}

function nodeMetricLabel(node: MctsNode): string {
  if (!isPendingNode(node)) return shortMetric(node.metric)
  if (String(node.status ?? '') === 'generating') return 'generating'
  if (String(node.status ?? '') === 'failed') return 'failed'
  return String(node.status ?? '') === 'executing' ? 'executing' : 'pending'
}

function hasParserDetails(node: MctsNode): boolean {
  return Boolean(node.parser_analysis || node.decision_signals)
}

function displayInsight(node: MctsNode): string {
  return String(node.llm_insight || node.insight || '').trim() || '-'
}

function formatDecisionSignals(signals: Record<string, unknown> | null | undefined): string {
  if (!signals) return ''
  try {
    return JSON.stringify(signals, null, 2)
  } catch {
    return String(signals)
  }
}
</script>

<template>
  <section class="page">
    <div class="left">
      <h4>{{ isAlgoEvolve ? 'AlgoEvolve 搜索图' : 'MCTS 搜索树' }}</h4>
      <div class="legend">
        <span class="dot ok"></span><span>Reviewer 通过</span>
        <span class="dot buggy"></span><span>Reviewer 判定有 bug</span>
        <span class="dot unknown"></span><span>尚未评审</span>
        <span class="dot best"></span><span>当前最佳</span>
        <span class="dot pending"></span><span>生成中 / 待执行</span>
      </div>
      <div class="legend">
        <span class="line draft"></span><span>draft</span>
        <span class="line improve"></span><span>improve / evolution / fusion</span>
        <span class="line debug"></span><span>debug</span>
      </div>
      <div v-if="graph.nodes.length > 0" class="tree-wrap">
        <svg :width="graph.width" :height="graph.height">
          <g>
            <path
              v-for="edge in graph.edges"
              :key="`${edge.from}-${edge.to}`"
              :d="edgePath(edge.from, edge.to)"
              class="tree-edge"
              :class="edgeClass(edge.action)"
            />
          </g>
          <g v-for="node in graph.nodes" :key="node.id" class="tree-node" @click="selectedNodeId = node.id">
            <rect :x="node.x" :y="node.y" :width="nodeW" :height="nodeH" rx="10" :class="nodeClass(node)" />
            <text :x="node.x + 10" :y="node.y + 20" class="node-title">{{ node.stage || 'node' }}</text>
            <text :x="node.x + 10" :y="node.y + 38" class="node-meta">score={{ nodeMetricLabel(node) }}</text>
            <text :x="node.x + 10" :y="node.y + 54" class="node-meta">uct={{ shortMetric(node.uct) }}</text>
            <text :x="node.x + 10" :y="node.y + 68" class="node-meta">v={{ node.visits ?? 0 }}</text>
          </g>
        </svg>
      </div>
      <div v-else class="empty">暂无 AutoML 节点</div>
    </div>

    <div class="right">
      <h4>节点详情</h4>
      <div v-if="selectedNode">
        <div class="meta">
          <span>id: {{ selectedNode.id }}</span>
          <span>parent: {{ selectedNode.parent_id || '-' }}</span>
          <span>stage: {{ selectedNode.stage || '-' }}</span>
          <span>score: {{ selectedNode.metric ?? '-' }}</span>
          <span v-if="selectedNode.status">status: {{ selectedNode.status }}</span>
          <span>uct: {{ selectedNode.uct ?? '-' }}</span>
          <span>visits: {{ selectedNode.visits ?? 0 }}</span>
          <span v-if="selectedNode.branch_id !== undefined">branch: {{ selectedNode.branch_id ?? '-' }}</span>
          <span v-if="selectedNode.exec_time !== undefined">exec: {{ selectedNode.exec_time ?? '-' }}s</span>
          <span>buggy: {{ selectedNode.is_buggy }}</span>
          <span>valid: {{ selectedNode.is_valid }}</span>
          <span>search: {{ selectedNode.search_eligible }}</span>
          <span>delivery: {{ selectedNode.delivery_ready }}</span>
          <span>certified: {{ selectedNode.delivery_certified }}</span>
          <span v-if="selectedNode.id === bestNodeId">
            best: {{ bestNodeKind === 'provisional' ? 'provisional' : 'delivery' }}
          </span>
          <span>method: {{ selectedNode.method_mode || '-' }}</span>
        </div>
        <article class="block"><h5>Plan</h5><pre>{{ selectedNode.plan || '-' }}</pre></article>
        <article class="block"><h5>Code</h5><pre>{{ selectedNode.code || '-' }}</pre></article>
        <article class="block"><h5>运行结果</h5><pre>{{ selectedNode.result || '-' }}</pre></article>
        <article class="block insight-block"><h5>方案洞察</h5><pre>{{ displayInsight(selectedNode) }}</pre></article>
        <details v-if="hasParserDetails(selectedNode)" class="diagnostic-details">
          <summary>运行诊断详情</summary>
          <h5 v-if="selectedNode.parser_analysis">解析摘要</h5>
          <pre v-if="selectedNode.parser_analysis">{{ selectedNode.parser_analysis }}</pre>
          <h5 v-if="selectedNode.decision_signals">结构化信号</h5>
          <pre v-if="selectedNode.decision_signals">{{ formatDecisionSignals(selectedNode.decision_signals) }}</pre>
        </details>
      </div>
      <div v-else class="empty">请选择左侧一个节点</div>
    </div>
  </section>

  <section class="terminal-panel">
    <div class="terminal-header">原始终端输出</div>
    <pre class="terminal-content">{{ terminalText || '暂无终端输出' }}</pre>
  </section>

  <section v-if="bestSolutionCode || bestMetricText" class="terminal-panel best-solution-panel">
    <div class="terminal-header">当前最优方案</div>
    <pre v-if="bestMetricText" class="terminal-content">{{ bestMetricText }}</pre>
    <pre v-if="bestSolutionCode" class="terminal-content">{{ bestSolutionCode }}</pre>
  </section>

  <DependencyInstallPanel
    :summary="snapshot?.auto_ml?.dependency_installation_summary"
    :detail-text="snapshot?.auto_ml?.dependency_installations"
  />

  <AlgoEvolveSummary :snapshot="snapshot" />
</template>

<style scoped>
.page {
  display: grid;
  grid-template-columns: 1.15fr 0.85fr;
  gap: 10px;
  min-width: 0;
  max-width: 100%;
}

.left,
.right {
  border: 1px solid #d0ddee;
  border-radius: 10px;
  background: #fff;
  padding: 10px;
  min-height: 440px;
  min-width: 0;
  overflow: hidden;
}

h4 {
  margin: 0 0 8px;
  color: #254a76;
}

.legend {
  display: flex;
  gap: 6px;
  align-items: center;
  font-size: 12px;
  color: #416089;
  margin-bottom: 6px;
  flex-wrap: wrap;
}

.dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  display: inline-block;
}

.dot.ok {
  background: #2aa05c;
}

.dot.buggy {
  background: #d14b4b;
}

.dot.unknown {
  background: #a9b1b8;
}

.dot.best {
  background: #d3a11f;
}

.dot.pending {
  background: #9aa3af;
}

.line {
  width: 24px;
  height: 3px;
  display: inline-block;
}

.line.draft {
  background: #3a77d5;
}

.line.improve {
  background: #3ca15f;
}

.line.debug {
  background: #cb4d4d;
}

.tree-wrap {
  width: 100%;
  max-width: 100%;
  min-width: 0;
  overflow: auto;
  border: 1px solid #cedcf0;
  border-radius: 8px;
  max-height: 540px;
  overscroll-behavior: contain;
  scrollbar-gutter: stable both-edges;
}

.tree-wrap svg {
  display: block;
  max-width: none;
}

.tree-edge {
  fill: none;
  stroke-width: 1.6;
}

.edge-draft {
  stroke: #3a77d5;
}

.edge-improve {
  stroke: #3ca15f;
}

.edge-debug {
  stroke: #cb4d4d;
}

.edge-other {
  stroke: #9aa8bc;
}

.tree-node {
  cursor: pointer;
}

.node-card {
  stroke-width: 1.4;
}

.node-card.ok {
  fill: #e7f9ef;
  stroke: #6bb58a;
}

.node-card.buggy {
  fill: #ffeaea;
  stroke: #d48a8a;
}

.node-card.unknown {
  fill: #eef2f7;
  stroke: #b8c3d2;
}

.node-card.pending {
  fill: #f1f3f5;
  stroke: #8d98a7;
  stroke-dasharray: 5 4;
}

.node-card.selected {
  stroke-width: 2.6;
  stroke: #2f5f9f;
}

.node-card.best {
  stroke: #cfa53f;
  stroke-width: 2.8;
}

.node-title {
  font-size: 12px;
  fill: #24466b;
  font-weight: 600;
}

.node-meta {
  font-size: 11px;
  fill: #406486;
}

.meta {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  font-size: 12px;
  color: #3e5f87;
  margin-bottom: 8px;
}

.block {
  border: 1px solid #d7e2f2;
  border-radius: 8px;
  margin-bottom: 8px;
  padding: 8px;
}

.block h5 {
  margin: 0 0 6px;
}

.insight-block {
  border-color: #bfd3ea;
  background: #f8fbff;
}

.diagnostic-details {
  margin: 2px 0 8px;
  padding: 5px 8px;
  border-top: 1px solid #e3eaf3;
  color: #6f8095;
}

.diagnostic-details summary {
  cursor: pointer;
  width: fit-content;
  color: #718198;
  font-size: 11px;
  font-weight: 500;
}

.diagnostic-details h5 {
  margin-top: 8px;
  color: #64758b;
  font-size: 11px;
  font-weight: 600;
}

.diagnostic-details pre {
  margin: 0;
  max-height: 150px;
  overflow: auto;
  color: #718198;
  font-size: 11px;
  line-height: 1.45;
  white-space: pre-wrap;
}

.block pre {
  margin: 0;
  white-space: pre-wrap;
  overflow: auto;
  max-height: 180px;
  font-size: 12px;
}

.terminal-panel {
  margin-top: 10px;
  border: 1px solid #2c3c51;
  border-radius: 10px;
  overflow: hidden;
  background: #111b26;
}

.terminal-header {
  padding: 8px 10px;
  font-size: 12px;
  color: #d7e7fb;
  background: #1a2a3a;
  border-bottom: 1px solid #31465f;
}

.terminal-content {
  margin: 0;
  padding: 10px;
  color: #d7f7e4;
  font-size: 12px;
  line-height: 1.45;
  max-height: 260px;
  overflow: auto;
  white-space: pre-wrap;
}

.best-solution-panel .terminal-content + .terminal-content {
  border-top: 1px solid rgba(255, 255, 255, 0.08);
}

.empty {
  color: #587aa8;
}

@media (max-width: 1100px) {
  .page {
    grid-template-columns: 1fr;
  }
}
</style>
