<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, shallowRef, useTemplateRef, watch } from 'vue'
import { Check, Crosshair, Eye, EyeOff, Focus, GitBranch, Maximize, Minimize, RotateCcw, Search, Trophy, X, ZoomIn, ZoomOut } from 'lucide-vue-next'
import type { MctsNode } from '../types'
import { buildSearchGraph, fitGraph, formatGraphMetric, graphAction, graphNodeState, topologyKey, zoomAt, NODE_WIDTH, NODE_HEIGHT, type Camera, type GraphEdge, type GraphInputNode, type SearchGraph } from '../utils/mctsGraph'

const props = defineProps<{ nodes: MctsNode[]; bestNodeId?: string | null; selectedNodeId?: string | null; emptyLabel?: string }>()
const emit = defineEmits<{ select: [nodeId: string]; cameraInteraction: [] }>()
const shell = useTemplateRef<HTMLElement>('shell')
const viewport = useTemplateRef<HTMLDivElement>('viewport')
const graph = shallowRef<SearchGraph>(buildSearchGraph([]))
const camera = shallowRef<Camera>({ x: 40, y: 40, scale: 1 })
const search = shallowRef('')
const actionFilter = shallowRef('all')
const stateFilter = shallowRef('all')
const showLabels = shallowRef(true)
const fullscreen = shallowRef(false)
const dragging = shallowRef(false)
const error = shallowRef('')
const layoutPending = shallowRef(false)
const dimensions = shallowRef({ width: 800, height: 520 })
const nodeMap = computed(() => new Map(props.nodes.map(node => [node.id, node as GraphInputNode])))
const topology = computed(() => topologyKey(props.nodes))
const transform = computed(() => `translate(${camera.value.x} ${camera.value.y}) scale(${camera.value.scale})`)
const zoomText = computed(() => `${Math.round(camera.value.scale * 100)}%`)
const filteredIds = computed(() => new Set(props.nodes.filter(node => {
  const query = search.value.trim().toLowerCase()
  return (!query || `${node.id} ${node.label ?? ''} ${node.method_mode ?? ''} ${node.stage ?? ''}`.toLowerCase().includes(query)) && (actionFilter.value === 'all' || graphAction(node.stage) === actionFilter.value) && (stateFilter.value === 'all' || graphNodeState(node) === stateFilter.value)
}).map(node => node.id)))
const visibleNodes = computed(() => graph.value.nodes.filter(node => filteredIds.value.has(node.id)))
const visibleEdges = computed(() => graph.value.edges.filter(edge => filteredIds.value.has(edge.from) && filteredIds.value.has(edge.to)))
const minimapNodes = computed(() => graph.value.nodes.filter(node => nodeMap.value.has(node.id)))
const statusLabels = { success: '评审通过', pending: '进行中', bug: '异常', unreviewed: '未评审' }
const actionLabels = { draft: '初始方案', improve: '优化', debug: '调试', evolution: '演化', fusion: '融合' }
const minimapBox = computed(() => ({ x: -camera.value.x / camera.value.scale, y: -camera.value.y / camera.value.scale, width: dimensions.value.width / camera.value.scale, height: dimensions.value.height / camera.value.scale }))
let observer: ResizeObserver | undefined
let fitted = false
let previousPointer = { x: 0, y: 0 }
const pointers = new Map<number, { x: number; y: number }>()
let pinchDistance = 0
let layoutWorker: Worker | undefined
let layoutRevision = 0
let workerBusy = false
let pendingLayout: { revision: number; nodes: GraphInputNode[] } | undefined
let disposed = false
let requestedFocus: string | null = null

function signalManualCamera() { requestedFocus = null; emit('cameraInteraction') }

function fit() {
  if (!viewport.value) return
  signalManualCamera()
  camera.value = fitGraph(graph.value, viewport.value.clientWidth, viewport.value.clientHeight - 48)
}
function initialFrame() {
  if (!viewport.value) return
  const width = viewport.value.clientWidth, height = viewport.value.clientHeight
  const fittedCamera = fitGraph(graph.value, width, height - 48)
  if (fittedCamera.scale >= 0.72) { camera.value = fittedCamera; return }
  const target = graph.value.nodes.find(node => node.id === props.selectedNodeId || node.id === props.bestNodeId) ?? graph.value.nodes[0]
  if (!target) return
  const scale = width < 500 ? 0.9 : 0.85
  camera.value = { scale, x: width / 2 - target.x * scale, y: height * 0.63 - target.y * scale }
}
function reset() { signalManualCamera(); camera.value = { x: 40, y: 40, scale: 1 } }
function zoom(factor: number) { signalManualCamera(); camera.value = zoomAt(camera.value, camera.value.scale * factor, { x: dimensions.value.width / 2, y: dimensions.value.height / 2 }) }
function focusNode(nodeId?: string | null) {
  requestedFocus = nodeId ?? null
  const node = graph.value.nodes.find(node => node.id === nodeId)
  if (!node) return
  requestedFocus = null
  clearFilters()
  const scale = Math.max(0.8, camera.value.scale)
  camera.value = { scale, x: dimensions.value.width / 2 - node.x * scale, y: dimensions.value.height / 2 - node.y * scale }
}
function clearFilters() { search.value = ''; actionFilter.value = 'all'; stateFilter.value = 'all' }
function focusBest() { if (props.bestNodeId) { clearFilters(); emit('select', props.bestNodeId); focusNode(props.bestNodeId) } }
function onWheel(event: WheelEvent) {
  event.preventDefault()
  signalManualCamera()
  const rect = viewport.value!.getBoundingClientRect()
  camera.value = zoomAt(camera.value, camera.value.scale * Math.exp(-event.deltaY * 0.0015), { x: event.clientX - rect.left, y: event.clientY - rect.top })
}
function pointerDown(event: PointerEvent) {
  if ((event.target as Element).closest('button') || (event.pointerType === 'mouse' && event.button !== 0)) return
  signalManualCamera()
  pointers.set(event.pointerId, { x: event.clientX, y: event.clientY })
  viewport.value?.setPointerCapture(event.pointerId)
  previousPointer = { x: event.clientX, y: event.clientY }
  dragging.value = true
  if (pointers.size === 2) { const [a, b] = [...pointers.values()]; pinchDistance = Math.hypot(a!.x - b!.x, a!.y - b!.y) }
}
function pointerMove(event: PointerEvent) {
  if (!pointers.has(event.pointerId)) return
  pointers.set(event.pointerId, { x: event.clientX, y: event.clientY })
  if (pointers.size === 2) {
    const [a, b] = [...pointers.values()]
    const distance = Math.hypot(a!.x - b!.x, a!.y - b!.y)
    const rect = viewport.value!.getBoundingClientRect()
    if (pinchDistance > 0) camera.value = zoomAt(camera.value, camera.value.scale * distance / pinchDistance, { x: (a!.x + b!.x) / 2 - rect.left, y: (a!.y + b!.y) / 2 - rect.top })
    pinchDistance = distance
  } else camera.value = { ...camera.value, x: camera.value.x + event.clientX - previousPointer.x, y: camera.value.y + event.clientY - previousPointer.y }
  previousPointer = { x: event.clientX, y: event.clientY }
}
function pointerUp(event: PointerEvent) {
  pointers.delete(event.pointerId)
  if (viewport.value?.hasPointerCapture(event.pointerId)) viewport.value.releasePointerCapture(event.pointerId)
  dragging.value = pointers.size > 0
  if (pointers.size === 1) previousPointer = [...pointers.values()][0]!
  pinchDistance = 0
}
function keyboard(event: KeyboardEvent) {
  if ((event.target as Element).closest('button,input,select')) return
  if (['+', '=', '-', '0', 'f', 'F', 'ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'].includes(event.key)) { event.preventDefault(); signalManualCamera() }
  if (event.key === '+' || event.key === '=') zoom(1.2)
  else if (event.key === '-') zoom(1 / 1.2)
  else if (event.key === '0' || event.key.toLowerCase() === 'f') fit()
  else if (event.key.startsWith('Arrow')) camera.value = { ...camera.value, x: camera.value.x + (event.key === 'ArrowRight' ? -48 : event.key === 'ArrowLeft' ? 48 : 0), y: camera.value.y + (event.key === 'ArrowDown' ? -48 : event.key === 'ArrowUp' ? 48 : 0) }
}
function edgePath(edge: GraphEdge) {
  const points = edge.points
  if (!points.length) return ''
  if (points.length === 2) return `M${points[0]!.x},${points[0]!.y} L${points[1]!.x},${points[1]!.y}`
  let path = `M${points[0]!.x},${points[0]!.y}`
  for (let index = 1; index < points.length - 1; index++) { const point = points[index]!, next = points[index + 1]!; path += ` Q${point.x},${point.y} ${(point.x + next.x) / 2},${(point.y + next.y) / 2}` }
  const last = points[points.length - 1]!
  return `${path} L${last.x},${last.y}`
}
async function toggleFullscreen() {
  try { if (document.fullscreenElement) await document.exitFullscreen(); else await shell.value?.requestFullscreen() }
  catch { error.value = '当前浏览器无法进入全屏' }
}
function syncFullscreen() { fullscreen.value = document.fullscreenElement === shell.value }
function navigateMini(event: MouseEvent) {
  signalManualCamera()
  const rect = (event.currentTarget as SVGElement).getBoundingClientRect()
  const scale = Math.min(rect.width / graph.value.width, rect.height / graph.value.height)
  const x = (event.clientX - rect.left - (rect.width - graph.value.width * scale) / 2) / scale
  const y = (event.clientY - rect.top - (rect.height - graph.value.height * scale) / 2) / scale
  camera.value = { ...camera.value, x: dimensions.value.width / 2 - x * camera.value.scale, y: dimensions.value.height / 2 - y * camera.value.scale }
}
async function acceptLayout(result: SearchGraph) {
  graph.value = result
  layoutPending.value = false
  error.value = ''
  if (!fitted && graph.value.nodes.length) { await nextTick(); if (!disposed && viewport.value?.clientWidth) { initialFrame(); fitted = true } }
  if (requestedFocus && props.nodes.some(node => node.id === requestedFocus)) focusNode(requestedFocus)
}
function postPendingLayout() {
  if (!pendingLayout || !layoutWorker || workerBusy) return
  workerBusy = true
  layoutWorker.postMessage(pendingLayout)
  pendingLayout = undefined
}
watch(topology, () => {
  layoutRevision += 1
  if (props.nodes.length <= 100) {
    pendingLayout = undefined
    void acceptLayout(buildSearchGraph(props.nodes))
    return
  }
  layoutPending.value = true
  if (!layoutWorker) {
    layoutWorker = new Worker(new URL('../utils/mctsLayout.worker.ts', import.meta.url), { type: 'module' })
    layoutWorker.onmessage = ({ data }: MessageEvent<{ revision: number; graph?: SearchGraph; error?: string }>) => {
      workerBusy = false
      if (data.revision === layoutRevision && !disposed) {
        if (data.graph) void acceptLayout(data.graph)
        else { error.value = '搜索图布局失败'; layoutPending.value = false }
      }
      postPendingLayout()
    }
    layoutWorker.onerror = () => {
      error.value = '搜索图布局失败'
      layoutPending.value = false
      workerBusy = false
      layoutWorker?.terminate()
      layoutWorker = undefined
    }
  }
  pendingLayout = {
    revision: layoutRevision,
    nodes: props.nodes.map(node => {
      const row = node as GraphInputNode
      return { id: row.id, parent_id: row.parent_id, parent_ids: row.parent_ids, fusion_sources: row.fusion_sources, stage: row.stage }
    }),
  }
  postPendingLayout()
}, { immediate: true })
onMounted(() => {
  if (viewport.value) dimensions.value = { width: viewport.value.clientWidth, height: viewport.value.clientHeight }
  observer = new ResizeObserver(entries => {
    const size = entries[0]?.contentRect
    if (!size || !size.width || !size.height) return
    const previous = dimensions.value
    camera.value = { ...camera.value, x: camera.value.x + (size.width - previous.width) / 2, y: camera.value.y + (size.height - previous.height) / 2 }
    dimensions.value = { width: size.width, height: size.height }
  })
  if (viewport.value) observer.observe(viewport.value)
  if (!fitted && graph.value.nodes.length) { initialFrame(); fitted = true }
  document.addEventListener('fullscreenchange', syncFullscreen)
})
onBeforeUnmount(() => { disposed = true; layoutWorker?.terminate(); observer?.disconnect(); document.removeEventListener('fullscreenchange', syncFullscreen) })
defineExpose({ focusNode, fit })
</script>

<template>
  <section ref="shell" class="graph-shell" :class="{ 'is-fullscreen': fullscreen }">
    <div class="graph-filterbar">
      <label class="graph-search"><Search :size="15" /><input v-model="search" placeholder="搜索节点 / 方法" aria-label="搜索节点" @input="signalManualCamera" /><button v-if="search" class="icon-button" title="清除搜索" aria-label="清除搜索" @click="search = ''"><X :size="13" /></button></label>
      <select v-model="actionFilter" aria-label="筛选搜索动作" @change="signalManualCamera"><option value="all">所有动作</option><option v-for="(label, value) in actionLabels" :key="value" :value="value">{{ label }}</option></select>
      <select v-model="stateFilter" aria-label="筛选节点状态" @change="signalManualCamera"><option value="all">所有状态</option><option v-for="(label, value) in statusLabels" :key="value" :value="value">{{ label }}</option></select>
      <span class="graph-node-count mono">{{ visibleNodes.length }} / {{ nodes.length }}</span>
    </div>
    <div ref="viewport" class="graph-viewport" :class="{ dragging }" tabindex="0" role="group" aria-label="蒙特卡洛搜索图工作区" @wheel="onWheel" @pointerdown="pointerDown" @pointermove="pointerMove" @pointerup="pointerUp" @pointercancel="pointerUp" @lostpointercapture="pointerUp" @keydown="keyboard">
      <svg v-if="graph.nodes.length" class="graph-canvas" width="100%" height="100%" aria-label="蒙特卡洛搜索树">
        <g :transform="transform">
          <path v-for="edge in visibleEdges" :key="edge.id" v-memo="[edge, selectedNodeId]" :d="edgePath(edge)" class="graph-edge" :class="[`action-${edge.action}`, { 'fusion-edge': edge.fusion, 'selected-edge': edge.to === selectedNodeId || edge.from === selectedNodeId }]" />
          <g v-for="position in visibleNodes" :key="position.id" v-memo="[position, nodeMap.get(position.id), selectedNodeId, bestNodeId, showLabels]" :transform="`translate(${position.x - NODE_WIDTH / 2} ${position.y - NODE_HEIGHT / 2})`" class="graph-node-position">
            <foreignObject :width="NODE_WIDTH" :height="NODE_HEIGHT" style="overflow: visible">
              <button class="graph-node" :class="[`action-${graphAction(nodeMap.get(position.id)?.stage)}`, `state-${graphNodeState(nodeMap.get(position.id)!)}`, { selected: position.id === selectedNodeId, best: position.id === bestNodeId }]" :title="`${position.id} · ${statusLabels[graphNodeState(nodeMap.get(position.id)!)]}`" :aria-label="`节点 ${position.id}，${actionLabels[graphAction(nodeMap.get(position.id)?.stage)]}，${statusLabels[graphNodeState(nodeMap.get(position.id)!)]}，指标 ${formatGraphMetric(nodeMap.get(position.id)?.metric)}`" :aria-pressed="position.id === selectedNodeId" @click.stop="emit('select', position.id)">
                <span class="graph-node-heading"><span class="graph-action-dot"></span><span>{{ showLabels ? nodeMap.get(position.id)?.label || actionLabels[graphAction(nodeMap.get(position.id)?.stage)] : position.id.slice(0, 7) }}</span><Trophy v-if="position.id === bestNodeId" :size="12" /><Check v-else-if="graphNodeState(nodeMap.get(position.id)!) === 'success'" :size="12" /><span v-else class="graph-state-dot" /></span>
                <span class="graph-node-value mono">{{ graphNodeState(nodeMap.get(position.id)!) === 'pending' ? '进行中' : formatGraphMetric(nodeMap.get(position.id)?.metric) }}</span>
                <span class="graph-node-id mono">{{ showLabels && nodeMap.get(position.id)?.label ? actionLabels[graphAction(nodeMap.get(position.id)?.stage)] : showLabels ? position.id.slice(0, 13) : statusLabels[graphNodeState(nodeMap.get(position.id)!)] }}</span>
              </button>
            </foreignObject>
          </g>
        </g>
      </svg>
      <div v-if="!graph.nodes.length" class="graph-empty"><GitBranch :size="34" :stroke-width="1.3" /><strong>{{ layoutPending ? '正在整理搜索图' : emptyLabel || '暂无搜索节点' }}</strong><span>{{ nodes.length }} 个候选节点</span></div>
      <div v-else-if="!visibleNodes.length" class="graph-empty"><Search :size="28" /><strong>没有匹配的节点</strong><button class="command" @click="clearFilters">清除筛选</button></div>
      <div class="graph-camera-tools" @pointerdown.stop>
        <button class="icon-button" title="缩小" aria-label="缩小搜索图" @click="zoom(1 / 1.2)"><ZoomOut :size="16" /></button><output class="graph-zoom mono">{{ zoomText }}</output><button class="icon-button" title="放大" aria-label="放大搜索图" @click="zoom(1.2)"><ZoomIn :size="16" /></button>
        <i></i><button class="icon-button" title="适应全部节点" aria-label="适应全部节点" :disabled="!nodes.length" @click="fit"><Focus :size="16" /></button><button class="icon-button" title="定位所选节点" aria-label="定位所选节点" :disabled="!selectedNodeId" @click="focusNode(selectedNodeId)"><Crosshair :size="16" /></button><button class="icon-button" title="定位最佳方案" aria-label="定位最佳方案" :disabled="!bestNodeId" @click="focusBest"><Trophy :size="16" /></button><button class="icon-button" title="重置视角" aria-label="重置视角" @click="reset"><RotateCcw :size="16" /></button>
        <i></i><button class="icon-button" :title="showLabels ? '收起节点标签' : '显示节点标签'" aria-label="切换节点标签" :aria-pressed="showLabels" @click="showLabels = !showLabels"><Eye v-if="showLabels" :size="16" /><EyeOff v-else :size="16" /></button><button class="icon-button" :title="fullscreen ? '退出全屏' : '全屏搜索图'" aria-label="切换搜索图全屏" @click="toggleFullscreen"><Minimize v-if="fullscreen" :size="16" /><Maximize v-else :size="16" /></button>
      </div>
      <svg v-if="minimapNodes.length > 6" class="graph-minimap" :viewBox="`0 0 ${graph.width} ${graph.height}`" role="img" aria-label="搜索图缩略图" @pointerdown.stop @click="navigateMini"><rect v-for="node in minimapNodes" :key="node.id" :x="node.x - NODE_WIDTH / 2" :y="node.y - NODE_HEIGHT / 2" :width="NODE_WIDTH" :height="NODE_HEIGHT" :fill="node.id === bestNodeId ? '#19845b' : node.id === selectedNodeId ? '#344b41' : '#b7c5be'" rx="6" /><rect class="graph-minimap-window" v-bind="minimapBox" /></svg>
      <span v-if="error" class="graph-error">{{ error }}</span>
      <span v-else-if="layoutPending && graph.nodes.length" class="graph-layout-pending">布局更新中</span>
    </div>
    <div class="graph-legend"><span v-for="(label, action) in actionLabels" :key="action"><i :class="`action-${action}`"></i>{{ label }}</span><span class="graph-legend-best"><Trophy :size="12" />最佳方案</span></div>
  </section>
</template>

<style scoped>
.graph-shell { display: flex; flex-direction: column; min-width: 0; min-height: 400px; height: 100%; background: var(--surface, #fff); }
.graph-filterbar { display: flex; gap: 8px; align-items: center; padding: 12px 14px; border-bottom: 1px solid var(--line, #e4e8e4); }
.graph-search { display: flex; align-items: center; gap: 7px; flex: 1; min-width: 100px; color: #7b827c; }.graph-search input { border: 0; background: transparent; outline: none; min-width: 0; width: 100%; font-size: 12px; color: #202824; }
.graph-filterbar select { max-width: 108px; min-width: 78px; padding: 5px 6px; border: 1px solid var(--line, #e4e8e4); border-radius: 4px; background: #fff; color: #515a53; font-size: 11px; }.graph-node-count { font-size: 11px; white-space: nowrap; color: #899189; }
.graph-viewport { position: relative; flex: 1; min-height: 300px; overflow: hidden; touch-action: none; cursor: grab; background-color: #f9fbf9; background-image: linear-gradient(#eaf0eb 1px, transparent 1px), linear-gradient(90deg, #eaf0eb 1px, transparent 1px); background-size: 28px 28px; outline: none; }.graph-viewport:focus-visible { box-shadow: inset 0 0 0 2px #19845b; }.graph-viewport.dragging { cursor: grabbing; }.graph-canvas { position: absolute; inset: 0; overflow: visible; }
.graph-edge { fill: none; stroke: #aab9b0; stroke-width: 1.5; opacity: .65; }.graph-edge.action-improve { stroke: #5690ce; }.graph-edge.action-debug { stroke: #ca9442; }.graph-edge.action-evolution { stroke: #318f89; }.graph-edge.action-fusion { stroke: #9973b9; }.graph-edge.fusion-edge { stroke-dasharray: 5 5; }.graph-edge.selected-edge { stroke-width: 2.4; opacity: 1; }
.graph-node { width: 140px; height: 64px; padding: 7px 10px 6px; border: 1px solid #cdd7cf; border-radius: 5px; background: #fff; color: #303d33; display: flex; flex-direction: column; text-align: left; cursor: pointer; box-shadow: 0 2px 4px #21362809; transition: border-color 100ms, box-shadow 100ms; letter-spacing: 0; }.graph-node:hover { border-color: #819a89; box-shadow: 0 3px 10px #21362816; }.graph-node.selected { border-color: #263f30; outline: 2px solid #344b4133; outline-offset: 2px; }.graph-node.best { border-color: #19845b; background: #f0faf4; }.graph-node.state-pending { border-style: dashed; }.graph-node.state-bug { border-color: #d5a794; background: #fffaf8; }
.graph-node-heading { display: flex; align-items: center; gap: 5px; font-size: 10px; line-height: 13px; width: 100%; color: #6d796f; }.graph-node-heading > span:nth-child(2) { flex: 1; overflow: hidden; white-space: nowrap; text-overflow: ellipsis; }.graph-node-heading svg { color: #19845b; }.graph-action-dot { flex: none; width: 5px; height: 5px; border-radius: 50%; background: #738579; }.action-improve .graph-action-dot { background: #4e88ca; }.action-debug .graph-action-dot { background: #c7943b; }.action-fusion .graph-action-dot { background: #9973b9; }.action-evolution .graph-action-dot { background: #328e88; }.graph-state-dot { width: 5px; height: 5px; border-radius: 50%; background: #aab4ac; }.state-pending .graph-state-dot { background: #c49f56; }.state-bug .graph-state-dot { background: #bf725d; }
.graph-node-value { display: block; font-size: 16px; font-weight: 650; line-height: 23px; overflow: hidden; white-space: nowrap; width: 100%; text-overflow: ellipsis; }.graph-node-id { font-size: 8px; line-height: 10px; color: #8c968e; }
.graph-camera-tools { position: absolute; left: 14px; bottom: 14px; display: flex; align-items: center; gap: 2px; padding: 4px; border: 1px solid #dee6df; border-radius: 6px; background: #fffffff5; box-shadow: 0 3px 14px #203e2a0b; cursor: default; }.graph-camera-tools .icon-button { width: 30px; height: 30px; padding: 5px; }.graph-camera-tools i { height: 15px; width: 1px; margin: 0 3px; background: #e4e8e4; }.graph-zoom { min-width: 38px; font-size: 10px; text-align: center; color: #5e6b61; }
.graph-minimap { position: absolute; right: 12px; bottom: 14px; width: 112px; height: 78px; border: 1px solid #dee6df; border-radius: 4px; background: #ffffffeb; cursor: crosshair; padding: 3px; }.graph-minimap-window { fill: #19845b10; stroke: #61866d; stroke-width: 2; vector-effect: non-scaling-stroke; }
.graph-legend { display: flex; flex-wrap: wrap; align-items: center; gap: 16px; min-height: 38px; padding: 8px 14px; border-top: 1px solid #e4e8e4; font-size: 10px; color: #818b83; }.graph-legend span { display: inline-flex; gap: 5px; align-items: center; }.graph-legend i { width: 14px; height: 2px; background: #99a79e; }.graph-legend i.action-improve { background: #5690ce; }.graph-legend i.action-debug { background: #ca9442; }.graph-legend i.action-evolution { background: #318f89; }.graph-legend i.action-fusion { background: repeating-linear-gradient(90deg, #9973b9 0 4px, transparent 4px 6px); }.graph-legend-best { margin-left: auto; color: #19845b; }
.graph-empty { height: 100%; min-height: 300px; display: flex; flex-direction: column; gap: 11px; align-items: center; justify-content: center; color: #9ca99f; }.graph-empty strong { font-weight: 500; font-size: 14px; color: #657769; }.graph-empty > span { font-size: 11px; }.graph-error { position: absolute; top: 12px; left: 12px; color: #ae654f; background: #fff; font-size: 12px; padding: 6px; }
.graph-shell:fullscreen { width: 100vw; height: 100vh; }.graph-shell:fullscreen .graph-viewport { flex: 1; }
.graph-layout-pending { position: absolute; right: 12px; top: 12px; color: #8d9f92; background: #ffffffdc; padding: 5px 7px; border-radius: 3px; font-size: 10px; pointer-events: none; }
.graph-node { animation: graph-node-enter 140ms ease-out; }
@keyframes graph-node-enter { from { opacity: 0; } to { opacity: 1; } }
@media (prefers-reduced-motion: reduce) { .graph-node { transition: none; animation: none; } }
@media (max-width: 900px) { .graph-minimap { display: none; }.graph-filterbar { flex-wrap: wrap; }.graph-search { flex-basis: 100%; }.graph-node-count { margin-left: auto; }.graph-shell { min-height: 510px; }.graph-viewport { min-height: 390px; }.graph-camera-tools { left: 8px; bottom: 9px; gap: 0; }.graph-camera-tools .icon-button { width: 27px; height: 28px; }.graph-camera-tools i { margin: 0 2px; }.graph-zoom { min-width: 33px; }.graph-legend { gap: 9px; } }
</style>
