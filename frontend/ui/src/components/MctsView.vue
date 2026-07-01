<script setup lang="ts">
import { computed, shallowRef, watch } from 'vue'
import type { MctsNode } from '../types'

const props = defineProps<{
  nodes: MctsNode[]
  bestNodeId?: string | null
}>()

type GraphNode = MctsNode & { x: number; y: number; depth: number; order: number }
type GraphEdge = { from: string; to: string }

const selectedNodeId = shallowRef('')
const canvasWidth = 1100
const nodeW = 170
const nodeH = 72
const xGap = 56
const yGap = 40

const nodeMap = computed(() => {
  const map = new Map<string, MctsNode>()
  for (const n of props.nodes) {
    map.set(n.id, n)
  }
  return map
})

const childrenMap = computed(() => {
  const m = new Map<string, MctsNode[]>()
  for (const n of props.nodes) {
    const pid = n.parent_id ?? '__root__'
    if (!m.has(pid)) m.set(pid, [])
    m.get(pid)!.push(n)
  }
  for (const v of m.values()) {
    v.sort((a, b) => String(a.finish_time ?? '').localeCompare(String(b.finish_time ?? '')))
  }
  return m
})

const roots = computed(() => {
  const orphans: MctsNode[] = []
  for (const n of props.nodes) {
    if (!n.parent_id || !nodeMap.value.has(n.parent_id)) {
      orphans.push(n)
    }
  }
  orphans.sort((a, b) => String(a.finish_time ?? '').localeCompare(String(b.finish_time ?? '')))
  return orphans
})

function assignDepth(root: MctsNode, depth: number, depthMap: Map<string, number>, visited: Set<string>) {
  if (visited.has(root.id)) return
  visited.add(root.id)
  depthMap.set(root.id, depth)
  const children = childrenMap.value.get(root.id) ?? []
  for (const c of children) {
    assignDepth(c, depth + 1, depthMap, visited)
  }
}

const graph = computed(() => {
  const depthMap = new Map<string, number>()
  const visited = new Set<string>()
  for (const r of roots.value) {
    assignDepth(r, 0, depthMap, visited)
  }
  // fallback for isolated nodes
  for (const n of props.nodes) {
    if (!depthMap.has(n.id)) depthMap.set(n.id, 0)
  }

  const levelMap = new Map<number, MctsNode[]>()
  for (const n of props.nodes) {
    const d = depthMap.get(n.id) ?? 0
    if (!levelMap.has(d)) levelMap.set(d, [])
    levelMap.get(d)!.push(n)
  }
  for (const arr of levelMap.values()) {
    arr.sort((a, b) => String(a.finish_time ?? '').localeCompare(String(b.finish_time ?? '')))
  }

  const depthKeys = [...levelMap.keys()].sort((a, b) => a - b)
  const outNodes: GraphNode[] = []
  for (const d of depthKeys) {
    const arr = levelMap.get(d) ?? []
    for (let i = 0; i < arr.length; i++) {
      const n = arr[i]
      outNodes.push({
        ...n,
        depth: d,
        order: i,
        x: d * (nodeW + xGap) + 20,
        y: i * (nodeH + yGap) + 20,
      })
    }
  }

  const outEdges: GraphEdge[] = []
  for (const n of props.nodes) {
    if (n.parent_id && nodeMap.value.has(n.parent_id)) {
      outEdges.push({ from: n.parent_id, to: n.id })
    }
  }

  const maxDepth = depthKeys.length > 0 ? Math.max(...depthKeys) : 0
  const maxRows = Math.max(...(depthKeys.map((d) => (levelMap.get(d) ?? []).length)), 1)
  const width = Math.max(canvasWidth, 40 + (maxDepth + 1) * (nodeW + xGap))
  const height = Math.max(380, 40 + maxRows * (nodeH + yGap))
  return { nodes: outNodes, edges: outEdges, width, height }
})

watch(
  () => props.nodes,
  (nodes) => {
    if (nodes.length === 0) {
      selectedNodeId.value = ''
      return
    }
    if (!selectedNodeId.value || !nodes.some((n) => n.id === selectedNodeId.value)) {
      selectedNodeId.value = props.bestNodeId || nodes[nodes.length - 1].id
    }
  },
  { immediate: true, deep: true },
)

const graphNodeMap = computed(() => {
  const map = new Map<string, GraphNode>()
  for (const n of graph.value.nodes) map.set(n.id, n)
  return map
})

const selectedNode = computed(() => props.nodes.find((x) => x.id === selectedNodeId.value) ?? null)

function edgePath(from: string, to: string): string {
  const a = graphNodeMap.value.get(from)
  const b = graphNodeMap.value.get(to)
  if (!a || !b) return ''
  const x1 = a.x + nodeW
  const y1 = a.y + nodeH / 2
  const x2 = b.x
  const y2 = b.y + nodeH / 2
  const mx = (x1 + x2) / 2
  return `M ${x1} ${y1} C ${mx} ${y1}, ${mx} ${y2}, ${x2} ${y2}`
}

function nodeClass(node: MctsNode): string[] {
  const cls = ['node-card']
  cls.push(`stage-${node.stage ?? 'other'}`)
  if (isPendingNode(node)) cls.push('pending')
  if (node.id === selectedNodeId.value) cls.push('selected')
  if (props.bestNodeId && node.id === props.bestNodeId) cls.push('best')
  return cls
}

function shortMetric(v: number | null | undefined): string {
  if (v === null || v === undefined) return '-'
  return Number(v).toFixed(4)
}

function isPendingNode(node: MctsNode): boolean {
  const status = String(node.status ?? '')
  return Boolean(node.pending_execution) || ['generating', 'pending_execution', 'executing', 'cancelled', 'failed'].includes(status)
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
  <section class="mcts-panel">
    <h3>AutoML MCTS 连线树图</h3>
    <p class="sub">父子关系可视化：从根节点持续扩展，颜色区分 draft/improve/debug，点击节点查看详情。</p>

    <div class="tree-wrap" v-if="graph.nodes.length > 0">
      <svg :width="graph.width" :height="graph.height">
        <g>
          <path
            v-for="e in graph.edges"
            :key="`${e.from}-${e.to}`"
            :d="edgePath(e.from, e.to)"
            class="tree-edge"
          />
        </g>
        <g v-for="n in graph.nodes" :key="n.id" class="tree-node" @click="selectedNodeId = n.id">
          <rect
            :x="n.x"
            :y="n.y"
            :width="nodeW"
            :height="nodeH"
            rx="10"
            :class="nodeClass(n)"
          />
          <text :x="n.x + 10" :y="n.y + 20" class="node-title">
            {{ n.stage || 'node' }}<tspan v-if="n.id === bestNodeId"> · BEST</tspan>
          </text>
          <text :x="n.x + 10" :y="n.y + 38" class="node-meta">m={{ nodeMetricLabel(n) }}</text>
          <text :x="n.x + 10" :y="n.y + 54" class="node-meta">uct={{ shortMetric(n.uct) }}</text>
          <text :x="n.x + 10" :y="n.y + 68" class="node-meta">v={{ n.visits ?? 0 }} r={{ shortMetric(n.total_reward) }}</text>
        </g>
      </svg>
    </div>
    <div v-else class="empty-tree">暂无节点</div>

    <div class="detail" v-if="selectedNode">
      <h4>节点 {{ selectedNode.id }}</h4>
      <div class="meta-row">
        <span>parent: {{ selectedNode.parent_id || '-' }}</span>
        <span>stage: {{ selectedNode.stage }}</span>
        <span>metric: {{ selectedNode.metric ?? '-' }}</span>
        <span v-if="selectedNode.status">status: {{ selectedNode.status }}</span>
        <span>uct: {{ selectedNode.uct ?? '-' }}</span>
      </div>
      <div class="meta-row">
        <span>visits: {{ selectedNode.visits ?? 0 }}</span>
        <span>reward: {{ selectedNode.total_reward ?? 0 }}</span>
        <span>is_buggy: {{ selectedNode.is_buggy }}</span>
        <span>is_valid: {{ selectedNode.is_valid }}</span>
      </div>
      <div class="blocks">
        <article>
          <h5>Plan</h5>
          <pre>{{ selectedNode.plan || '-' }}</pre>
        </article>
        <article>
          <h5>Code</h5>
          <pre>{{ selectedNode.code || '-' }}</pre>
        </article>
        <article>
          <h5>运行结果</h5>
          <pre>{{ selectedNode.result || '-' }}</pre>
        </article>
        <article>
          <h5>LLM Insight</h5>
          <pre>{{ displayInsight(selectedNode) }}</pre>
        </article>
        <details v-if="hasParserDetails(selectedNode)" class="parser-details">
          <summary>程序解析事实（给后续节点看的硬事实）</summary>
          <h5 v-if="selectedNode.parser_analysis">Parser Analysis</h5>
          <pre v-if="selectedNode.parser_analysis">{{ selectedNode.parser_analysis }}</pre>
          <h5 v-if="selectedNode.decision_signals">Decision Signals</h5>
          <pre v-if="selectedNode.decision_signals">{{ formatDecisionSignals(selectedNode.decision_signals) }}</pre>
        </details>
      </div>
    </div>
  </section>
</template>

<style scoped>
.mcts-panel {
  background: #f9fff8;
  border: 1px solid #cae7c7;
  border-radius: 14px;
  padding: 14px;
  min-width: 0;
  max-width: 100%;
  overflow: hidden;
}

.sub {
  margin: 6px 0 10px;
  color: #3d6b3a;
  font-size: 13px;
}

.tree-wrap {
  width: 100%;
  max-width: 100%;
  min-width: 0;
  overflow: auto;
  border: 1px solid #c7dfc4;
  border-radius: 10px;
  background: #ffffff;
  max-height: 500px;
  overscroll-behavior: contain;
  scrollbar-gutter: stable both-edges;
}

.tree-wrap svg {
  display: block;
  max-width: none;
}

.tree-edge {
  fill: none;
  stroke: #88aa8d;
  stroke-width: 1.6;
  opacity: 0.9;
}

.tree-node {
  cursor: pointer;
}

.node-card {
  stroke-width: 1.4;
}

.stage-draft {
  fill: #e8f1ff;
  stroke: #7da7df;
}

.stage-improve {
  fill: #e8fff1;
  stroke: #75b684;
}

.stage-debug {
  fill: #ffe9e9;
  stroke: #d98b8b;
}

.stage-other {
  fill: #f2f2f2;
  stroke: #b6b6b6;
}

.pending {
  fill: #f1f3f5;
  stroke: #8d98a7;
  stroke-dasharray: 5 4;
}

.selected {
  stroke: #0b5d2c;
  stroke-width: 2.4;
}

.best {
  stroke: #1c6e89;
  stroke-width: 2.4;
}

.node-title {
  font-size: 12px;
  fill: #20404b;
  font-weight: 600;
}

.node-meta {
  font-size: 11px;
  fill: #365a65;
}

.empty-tree {
  border: 1px dashed #a9c8a8;
  border-radius: 10px;
  padding: 20px;
  color: #54725b;
}

.detail {
  margin-top: 10px;
  border: 1px solid #bfdab8;
  border-radius: 10px;
  background: #fff;
  padding: 10px;
}

.meta-row {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  font-size: 12px;
  margin-bottom: 8px;
  color: #2e4f39;
}

.blocks {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
}

.blocks article {
  border: 1px solid #d4e9d2;
  border-radius: 8px;
  padding: 8px;
  min-height: 120px;
}

.blocks .parser-details {
  border: 1px solid #d4e9d2;
  border-radius: 8px;
  padding: 8px;
  min-height: 120px;
}

.blocks h5 {
  margin: 0 0 6px;
}

.parser-details summary {
  cursor: pointer;
  color: #2e5933;
  font-size: 12px;
  font-weight: 700;
}

.parser-details h5 {
  margin-top: 8px;
}

.blocks pre {
  margin: 0;
  white-space: pre-wrap;
  overflow: auto;
  max-height: 220px;
  font-size: 12px;
}

@media (max-width: 1100px) {
  .blocks {
    grid-template-columns: 1fr;
  }
}
</style>
