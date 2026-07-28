<script setup lang="ts">
import { computed, shallowRef, watch } from 'vue'
import type { MctsNode, SnapshotPayload } from '../types'
import DependencyInstallPanel from './DependencyInstallPanel.vue'
import AlgoEvolveSummary from './AlgoEvolveSummary.vue'
import MctsSearchTree from './MctsSearchTree.vue'

const props = defineProps<{
  snapshot?: SnapshotPayload
}>()

const selectedNodeId = shallowRef('')

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

const selectedNode = computed(() => displayNodes.value.find((node) => node.id === selectedNodeId.value) ?? null)

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
      <MctsSearchTree
        :nodes="displayNodes"
        :best-node-id="bestNodeId"
        :selected-node-id="selectedNodeId"
        @select="selectedNodeId = $event"
      />
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
