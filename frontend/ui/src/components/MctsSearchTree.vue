<script setup lang="ts">
import { computed, nextTick, shallowRef, useTemplateRef } from 'vue'
import type { MctsNode } from '../types'
import { isPendingNode, nodeReviewState } from '../utils/nodeReviewState'
import {
  buildMctsTreeLayout,
  type MctsEdgeAction,
  type MctsLayoutNode,
} from '../utils/mctsTreeLayout'

const props = defineProps<{
  nodes: MctsNode[]
  bestNodeId?: string | null
  selectedNodeId?: string | null
}>()

const emit = defineEmits<{
  select: [nodeId: string]
}>()

const nodeRadius = 22
const minZoom = 0.5
const maxZoom = 2
const zoomStep = 0.1
const zoom = shallowRef(1)
const treeViewport = useTemplateRef<HTMLDivElement>('treeViewport')
const graph = computed(() => buildMctsTreeLayout(props.nodes))
const graphNodeMap = computed(() => new Map(graph.value.nodes.map((node) => [node.id, node])))
const scaledWidth = computed(() => graph.value.width * zoom.value)
const scaledHeight = computed(() => graph.value.height * zoom.value)
const zoomPercent = computed(() => Math.round(zoom.value * 100))
const canZoomIn = computed(() => zoom.value < maxZoom)
const canZoomOut = computed(() => zoom.value > minZoom)

function edgePath(from: string, to: string): string {
  const source = graphNodeMap.value.get(from)
  const target = graphNodeMap.value.get(to)
  if (!source || !target) return ''
  const startY = source.y + nodeRadius
  const endY = target.y - nodeRadius
  const midY = (startY + endY) / 2
  return `M ${source.x} ${startY} C ${source.x} ${midY}, ${target.x} ${midY}, ${target.x} ${endY}`
}

function nodeClass(node: MctsNode): string[] {
  const classes = ['node-circle']
  const reviewState = nodeReviewState(node)
  if (reviewState === 'pending') classes.push('pending')
  else if (reviewState === 'success') classes.push('ok')
  else if (reviewState === 'bug') classes.push('buggy')
  else classes.push('unknown')
  if (node.id === props.selectedNodeId) classes.push('selected')
  if (props.bestNodeId && node.id === props.bestNodeId) classes.push('best')
  return classes
}

function edgeClass(action: MctsEdgeAction): string {
  if (action === 'draft') return 'edge-draft'
  if (action === 'improve') return 'edge-improve'
  if (action === 'debug') return 'edge-debug'
  return 'edge-other'
}

function shortMetric(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) return 'N/A'
  const numeric = Number(value)
  if (numeric !== 0 && (Math.abs(numeric) >= 10000 || Math.abs(numeric) < 0.001)) {
    return numeric.toExponential(2)
  }
  return numeric.toFixed(4)
}

function nodeMetricLabel(node: MctsNode): string {
  return isPendingNode(node) ? 'N/A' : shortMetric(node.metric)
}

function nodeTitle(node: MctsLayoutNode): string {
  const status = node.status ? `\nstatus: ${node.status}` : ''
  return `${node.stage || 'node'}\nscore: ${nodeMetricLabel(node)}\nuct: ${shortMetric(node.uct)}\nvisits: ${node.visits ?? 0}${status}`
}

function selectNode(nodeId: string): void {
  emit('select', nodeId)
}

function clampZoom(value: number): number {
  return Math.min(maxZoom, Math.max(minZoom, Math.round(value * 100) / 100))
}

function setZoom(nextZoom: number, clientX?: number, clientY?: number): void {
  const normalizedZoom = clampZoom(nextZoom)
  const previousZoom = zoom.value
  if (normalizedZoom === previousZoom) return

  const viewport = treeViewport.value
  const rect = viewport?.getBoundingClientRect()
  const focusX = viewport
    ? clientX === undefined
      ? viewport.clientWidth / 2
      : clientX - (rect?.left ?? 0)
    : 0
  const focusY = viewport
    ? clientY === undefined
      ? viewport.clientHeight / 2
      : clientY - (rect?.top ?? 0)
    : 0
  const contentX = viewport ? (viewport.scrollLeft + focusX) / previousZoom : 0
  const contentY = viewport ? (viewport.scrollTop + focusY) / previousZoom : 0

  zoom.value = normalizedZoom
  void nextTick(() => {
    if (!viewport) return
    viewport.scrollLeft = contentX * normalizedZoom - focusX
    viewport.scrollTop = contentY * normalizedZoom - focusY
  })
}

function zoomIn(): void {
  setZoom(zoom.value + zoomStep)
}

function zoomOut(): void {
  setZoom(zoom.value - zoomStep)
}

function handleTreeWheel(event: WheelEvent): void {
  if (!event.ctrlKey || event.deltaY === 0) return
  event.preventDefault()
  event.stopPropagation()
  setZoom(zoom.value * Math.exp(-event.deltaY * 0.002), event.clientX, event.clientY)
}
</script>

<template>
  <div v-if="graph.nodes.length" class="tree-shell">
    <div class="tree-toolbar" aria-label="搜索树缩放">
      <button
        type="button"
        class="zoom-button"
        :disabled="!canZoomOut"
        aria-label="缩小搜索树"
        title="缩小搜索树（Ctrl + 鼠标滚轮）"
        @click="zoomOut"
      >−</button>
      <output class="zoom-level" aria-live="polite">{{ zoomPercent }}%</output>
      <button
        type="button"
        class="zoom-button"
        :disabled="!canZoomIn"
        aria-label="放大搜索树"
        title="放大搜索树（Ctrl + 鼠标滚轮）"
        @click="zoomIn"
      >+</button>
    </div>
    <div ref="treeViewport" class="tree-viewport" @wheel="handleTreeWheel">
      <svg
        :width="scaledWidth"
        :height="scaledHeight"
        :viewBox="`0 0 ${graph.width} ${graph.height}`"
        aria-label="蒙特卡洛搜索树"
        role="img"
      >
        <g class="tree-edges">
          <path
            v-for="edge in graph.edges"
            :key="`${edge.from}-${edge.to}`"
            :d="edgePath(edge.from, edge.to)"
            class="tree-edge"
            :class="edgeClass(edge.action)"
          />
        </g>
        <g
          v-for="node in graph.nodes"
          :key="node.id"
          class="tree-node"
          role="button"
          tabindex="0"
          :aria-label="nodeTitle(node)"
          @click="selectNode(node.id)"
          @keydown.enter="selectNode(node.id)"
          @keydown.space.prevent="selectNode(node.id)"
        >
          <title>{{ nodeTitle(node) }}</title>
          <circle
            v-if="node.id === selectedNodeId"
            :cx="node.x"
            :cy="node.y"
            :r="nodeRadius + 5"
            class="selection-ring"
          />
          <circle
            :cx="node.x"
            :cy="node.y"
            :r="nodeRadius"
            :class="nodeClass(node)"
          />
          <text :x="node.x" :y="node.y + 0.5" class="node-score">{{ nodeMetricLabel(node) }}</text>
          <text
            v-if="node.id === bestNodeId"
            :x="node.x - nodeRadius - 5"
            :y="node.y - nodeRadius + 1"
            class="best-mark"
          >★</text>
        </g>
      </svg>
    </div>
  </div>
  <div v-else class="empty">暂无 AutoML 节点</div>
</template>

<style scoped>
.tree-shell {
  width: 100%;
  max-width: 100%;
  min-width: 0;
  border: 1px solid #cedcf0;
  border-radius: 8px;
  background: #fff;
  overflow: hidden;
}

.tree-toolbar {
  min-height: 38px;
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 5px;
  padding: 4px 8px;
  border-bottom: 1px solid #e1e9f4;
  background: #fff;
}

.zoom-button {
  width: 28px;
  height: 28px;
  display: inline-grid;
  place-items: center;
  padding: 0;
  border: 1px solid #b9cae0;
  border-radius: 4px;
  background: #fff;
  color: #2f5f9f;
  font-size: 19px;
  line-height: 1;
  cursor: pointer;
}

.zoom-button:hover:not(:disabled) {
  background: #edf4fd;
  border-color: #7fa2ce;
}

.zoom-button:focus-visible {
  outline: 2px solid #2f5f9f;
  outline-offset: 1px;
}

.zoom-button:disabled {
  color: #9aa8b9;
  background: #f3f5f8;
  cursor: default;
}

.zoom-level {
  width: 44px;
  color: #406486;
  font-size: 11px;
  font-variant-numeric: tabular-nums;
  letter-spacing: 0;
  text-align: center;
}

.tree-viewport {
  width: 100%;
  max-width: 100%;
  min-width: 0;
  max-height: 520px;
  overflow: auto;
  overscroll-behavior: contain;
  scrollbar-gutter: stable both-edges;
}

.tree-viewport svg {
  display: block;
  max-width: none;
}

.tree-edge {
  fill: none;
  stroke-width: 1.6;
  stroke-linecap: round;
  opacity: 0.9;
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
  outline: none;
}

.tree-node:focus-visible .selection-ring {
  stroke-width: 2.8;
}

.node-circle {
  stroke-width: 1.5;
  transition: filter 120ms ease, stroke-width 120ms ease;
}

.tree-node:hover .node-circle {
  filter: brightness(0.98);
  stroke-width: 2.2;
}

.node-circle.ok {
  fill: #e7f9ef;
  stroke: #6bb58a;
}

.node-circle.buggy {
  fill: #ffeaea;
  stroke: #d48a8a;
}

.node-circle.unknown {
  fill: #eef2f7;
  stroke: #b8c3d2;
}

.node-circle.pending {
  fill: #f1f3f5;
  stroke: #8d98a7;
  stroke-dasharray: 4 3;
}

.node-circle.best {
  stroke: #cfa53f;
  stroke-width: 2.8;
}

.selection-ring {
  fill: none;
  stroke: #2f5f9f;
  stroke-width: 2;
  opacity: 0.8;
}

.node-score {
  fill: #24466b;
  font-size: 8.5px;
  font-weight: 700;
  letter-spacing: 0;
  text-anchor: middle;
  dominant-baseline: middle;
  pointer-events: none;
}

.best-mark {
  fill: #c28c06;
  font-size: 13px;
  text-anchor: middle;
  pointer-events: none;
}

.empty {
  color: #587aa8;
}
</style>
