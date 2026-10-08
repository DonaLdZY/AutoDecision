<script setup lang="ts">
import { computed, nextTick, shallowRef, useTemplateRef, watch } from 'vue'
import { Activity, ArrowDown, ArrowUp, Check, ChevronLeft, ChevronRight, Code2, Copy, Download, GitBranch, ListFilter, Terminal, Trophy } from 'lucide-vue-next'
import type { SnapshotPayload } from '../types'
import { formatGraphMetric, graphAction, graphNodeState, type GraphInputNode } from '../utils/mctsGraph'
import DependencyInstallPanel from './DependencyInstallPanel.vue'
import AlgoEvolveSummary from './AlgoEvolveSummary.vue'
import MctsSearchTree from './MctsSearchTree.vue'

const props = defineProps<{ snapshot?: SnapshotPayload; replay?: boolean }>()
const graphView = useTemplateRef<InstanceType<typeof MctsSearchTree>>('graphView')
const selectedId = shallowRef('')
const inspectorTab = shallowRef('overview')
const lowerTab = shallowRef('candidates')
const copied = shallowRef(false)
const copyError = shallowRef('')
const followLatest = shallowRef(true)
const page = shallowRef(0)
const pageSize = 12
const ml = computed(() => props.snapshot?.auto_ml ?? {})
const searchActive = computed(() => props.snapshot?.task?.status === 'running' && props.snapshot?.task?.phase === 'automl')
const nodes = computed<GraphInputNode[]>(() => {
  const complete = ml.value.nodes ?? []
  const ids = new Set(complete.map(node => node.id))
  return [...complete, ...(ml.value.pending_nodes ?? []).filter(node => !ids.has(node.id))]
})
const nodeIds = computed(() => nodes.value.map(node => node.id).join('|'))
const candidateNodes = computed(() => nodes.value.filter(node => node.stage !== 'root'))
const replayNodeSignature = computed(() => nodes.value.map(node => `${node.id}:${node.status ?? ''}:${node.metric ?? ''}`).join('|'))
const bestId = computed(() => ml.value.best_node_id ?? null)
const bestNode = computed(() => nodes.value.find(node => node.id === bestId.value))
const selectedNode = computed(() => nodes.value.find(node => node.id === selectedId.value))
const validNodes = computed(() => nodes.value.filter(node => graphNodeState(node) === 'success'))
const pendingCount = computed(() => nodes.value.filter(node => graphNodeState(node) === 'pending').length)
const rankingMaximize = computed(() => typeof bestNode.value?.maximize === 'boolean' ? bestNode.value.maximize : nodes.value.find(node => typeof node.maximize === 'boolean')?.maximize ?? true)
const metricName = computed(() => {
  const protocol = selectedNode.value?.evaluation_protocol
  if (protocol && typeof protocol === 'object' && typeof (protocol as Record<string, unknown>).metric_name === 'string') {
    return String((protocol as Record<string, unknown>).metric_name)
  }
  return ''
})
const actionLabels = { draft: '初始方案', improve: '方案优化', debug: '异常修复', evolution: '方案演化', fusion: '分支融合' }
const stateLabels = { success: '评审通过', pending: '进行中', bug: '异常', unreviewed: '未评审' }
const tabs = [{ id: 'overview', label: '概览' }, { id: 'plan', label: '方案' }, { id: 'code', label: '代码' }, { id: 'result', label: '结果' }, { id: 'insight', label: '洞察' }, { id: 'diagnostics', label: '诊断' }]
const parents = computed(() => [...new Set([selectedNode.value?.parent_id, ...(selectedNode.value?.parent_ids ?? []), ...(selectedNode.value?.fusion_sources ?? [])].filter((id): id is string => Boolean(id)))])
const evidenceFlags = computed(() => {
  const node = selectedNode.value
  return [{ label: '执行成功', value: node?.runtime_ok }, { label: '合同合规', value: node?.contract_valid }, { label: '结果有效', value: node?.is_valid }, { label: '参与搜索', value: node?.search_eligible }, { label: '产物就绪', value: node?.artifact_ready }, { label: '可交付', value: node?.delivery_ready }, { label: '交付认证', value: node?.delivery_certified }, { label: '分数复算', value: node?.score_recomputed }]
})
const rankedNodes = computed(() => [...candidateNodes.value].sort((a, b) => {
  const aMetric = typeof a.metric === 'number' && Number.isFinite(a.metric) && graphNodeState(a) !== 'pending'
  const bMetric = typeof b.metric === 'number' && Number.isFinite(b.metric) && graphNodeState(b) !== 'pending'
  if (aMetric !== bMetric) return aMetric ? -1 : 1
  if (a.id === bestId.value) return -1
  if (b.id === bestId.value) return 1
  const aSuccess = graphNodeState(a) === 'success', bSuccess = graphNodeState(b) === 'success'
  if (aSuccess !== bSuccess) return aSuccess ? -1 : 1
  if (aMetric && bMetric) {
    const aComparable = typeof a.maximize !== 'boolean' || a.maximize === rankingMaximize.value
    const bComparable = typeof b.maximize !== 'boolean' || b.maximize === rankingMaximize.value
    if (aComparable !== bComparable) return aComparable ? -1 : 1
    if (aComparable) return rankingMaximize.value ? b.metric! - a.metric! : a.metric! - b.metric!
  }
  return a.id.localeCompare(b.id)
}))
const pageCount = computed(() => Math.max(1, Math.ceil(rankedNodes.value.length / pageSize)))
const pagedNodes = computed(() => rankedNodes.value.slice(page.value * pageSize, (page.value + 1) * pageSize))
const terminalText = computed(() => {
  const source = ml.value
  const channels = [source.service_stderr, source.frontend_stderr, source.service_stdout, source.frontend_stdout, source.ml_log, source.verbose_log].filter(value => value?.trim())
  if (channels.length) return [...new Set(channels)].join('\n\n')
  return (source.events ?? []).map(event => [event.ts ?? event.timestamp ?? '', event.component ?? '', event.event ?? '', event.message ?? ''].join(' ')).join('\n')
})
const inspectorText = computed(() => {
  const node = selectedNode.value
  if (!node) return ''
  if (inspectorTab.value === 'plan') return node.plan ?? ''
  if (inspectorTab.value === 'code') return node.code ?? ''
  if (inspectorTab.value === 'result') return node.result ?? ''
  if (inspectorTab.value === 'insight') return node.llm_insight || node.insight || ''
  return ''
})
watch(nodeIds, () => {
  if (selectedId.value && nodes.value.some(node => node.id === selectedId.value)) return
  selectedId.value = bestId.value || nodes.value[nodes.value.length - 1]?.id || ''
}, { immediate: true })
watch(() => props.replay, () => { followLatest.value = true })
watch(replayNodeSignature, async (_current, previous) => {
  if (!props.replay || !followLatest.value || !nodes.value.length) return
  const previousStates = new Set((previous ?? '').split('|'))
  const changed = nodes.value.filter(node => !previousStates.has(`${node.id}:${node.status ?? ''}:${node.metric ?? ''}`))
  const node = changed[changed.length - 1] ?? nodes.value[nodes.value.length - 1]
  if (!node) return
  await nextTick()
  selectedId.value = node.id
  graphView.value?.focusNode(node.id)
}, { flush: 'post' })
watch(pageCount, count => { page.value = Math.min(page.value, count - 1) })
watch([selectedId, inspectorTab], () => { copied.value = false; copyError.value = '' })
function selectNode(id: string, focus = false) { if (props.replay) followLatest.value = false; selectedId.value = id; if (focus) graphView.value?.focusNode(id) }
function manualCamera() { if (props.replay) followLatest.value = false }
function toggleFollow() {
  if (!followLatest.value) return
  const node = nodes.value[nodes.value.length - 1]
  if (node) { selectedId.value = node.id; graphView.value?.focusNode(node.id) }
}
function formatTime(value: unknown) {
  if (!value) return '--'
  const date = new Date(typeof value === 'number' ? value * 1000 : String(value))
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString('zh-CN', { hour12: false })
}
function jsonText(value: unknown) { return value ? JSON.stringify(value, null, 2) : '' }
function downloadCode() {
  const node = selectedNode.value
  if (!node?.code) return
  const link = document.createElement('a')
  const url = URL.createObjectURL(new Blob([node.code], { type: 'text/x-python;charset=utf-8' }))
  link.href = url
  link.download = `solution_${node.id.replace(/[^a-zA-Z0-9_-]/g, '_')}.py`
  link.click()
  window.setTimeout(() => URL.revokeObjectURL(url), 1000)
}
async function copyText() {
  try { await navigator.clipboard.writeText(inspectorText.value); copied.value = true }
  catch { copyError.value = '剪贴板不可用，请下载代码文件' }
}
</script>

<template>
  <section class="search-view">
    <header class="search-heading">
      <div class="search-title"><GitBranch :size="18" :stroke-width="1.6" /><h2>方案搜索</h2><span class="search-engine">MCTS + Fusion</span><label v-if="replay" class="search-follow"><input v-model="followLatest" type="checkbox" @change="toggleFollow" />跟随新节点</label></div>
      <div class="search-counters"><span>候选 <b class="mono">{{ candidateNodes.length }}</b></span><span>通过 <b class="mono">{{ validNodes.length }}</b></span><span v-if="pendingCount" class="search-pending"><Activity :size="12" />{{ pendingCount }} 进行中</span><span v-if="bestNode" class="search-best"><Trophy :size="13" /><b class="mono">{{ formatGraphMetric(bestNode.metric) }}</b><ArrowDown v-if="bestNode.maximize === false" :size="12" /><ArrowUp v-else :size="12" /></span></div>
    </header>
    <div class="search-workspace">
      <MctsSearchTree ref="graphView" :nodes="nodes" :best-node-id="bestId" :selected-node-id="selectedId" :empty-label="searchActive ? '正在生成首个候选' : undefined" @select="selectNode($event)" @camera-interaction="manualCamera" />
      <aside class="inspector">
        <header class="inspector-header"><div><span class="inspector-eyebrow">节点检查器</span><h3>{{ selectedNode ? actionLabels[graphAction(selectedNode.stage)] : '未选择节点' }}</h3></div><span v-if="selectedNode" class="inspector-status" :class="`state-${graphNodeState(selectedNode)}`">{{ stateLabels[graphNodeState(selectedNode)] }}</span></header>
        <div v-if="selectedNode" class="inspector-identity mono">{{ selectedNode.id }}<Trophy v-if="selectedId === bestId" :size="13" /></div>
        <nav class="inspector-tabs" aria-label="节点详情视图"><button v-for="tab in tabs" :key="tab.id" :class="{ active: inspectorTab === tab.id }" :aria-pressed="inspectorTab === tab.id" @click="inspectorTab = tab.id">{{ tab.label }}</button></nav>
        <div v-if="!selectedNode" class="inspector-empty"><GitBranch :size="25" :stroke-width="1.4" /><span>暂无节点详情</span></div>
        <div v-else class="inspector-body">
          <template v-if="inspectorTab === 'overview'">
            <div class="inspector-score"><span>目标指标 <ArrowDown v-if="selectedNode.maximize === false" :size="12" /><ArrowUp v-else-if="selectedNode.maximize === true" :size="12" /></span><strong class="mono">{{ graphNodeState(selectedNode) === 'pending' ? '--' : formatGraphMetric(selectedNode.metric) }}</strong><small v-if="metricName">{{ metricName }}</small><small v-if="selectedId === bestId">{{ ml.best_node_kind === 'provisional' ? '当前搜索最优，待交付验证' : '当前最佳交付方案' }}</small></div>
            <dl class="inspector-metadata"><div><dt>UCT</dt><dd class="mono">{{ formatGraphMetric(selectedNode.uct) }}</dd></div><div><dt>访问次数</dt><dd class="mono">{{ selectedNode.visits ?? '--' }}</dd></div><div><dt>累计奖励</dt><dd class="mono">{{ formatGraphMetric(selectedNode.total_reward) }}</dd></div><div><dt>执行耗时</dt><dd class="mono">{{ selectedNode.exec_time == null ? '--' : `${formatGraphMetric(selectedNode.exec_time)} s` }}</dd></div><div><dt>所属分支</dt><dd class="mono">{{ selectedNode.branch_id ?? '--' }}</dd></div><div><dt>方法类型</dt><dd>{{ selectedNode.method_mode || '--' }}</dd></div></dl>
            <section class="inspector-section"><h4>验证证据</h4><div class="inspector-flags"><div v-for="flag in evidenceFlags" :key="flag.label"><span>{{ flag.label }}</span><span :class="{ passed: flag.value === true, rejected: flag.value === false }">{{ flag.value == null ? '未记录' : flag.value ? '通过' : '未通过' }}</span></div></div></section>
            <section class="inspector-section"><h4>{{ graphAction(selectedNode.stage) === 'fusion' ? '融合来源' : '父节点' }}</h4><div v-if="parents.length" class="inspector-parents"><button v-for="parent in parents" :key="parent" :disabled="!nodes.some(node => node.id === parent)" @click="selectNode(parent, true)"><GitBranch :size="12" /><span class="mono">{{ parent }}</span><ChevronRight :size="12" /></button></div><p v-else class="inspector-muted">独立初始分支</p></section>
            <dl class="inspector-times"><div><dt>创建时间</dt><dd>{{ formatTime(selectedNode.created_time) }}</dd></div><div><dt>完成时间</dt><dd>{{ formatTime(selectedNode.finish_time) }}</dd></div></dl>
          </template>
          <template v-else-if="inspectorTab === 'diagnostics'"><section class="inspector-section"><h4>解析摘要</h4><pre class="inspector-prose">{{ selectedNode.parser_analysis || '暂无解析摘要' }}</pre></section><section class="inspector-section"><h4>决策信号</h4><pre class="inspector-json">{{ jsonText(selectedNode.decision_signals) || '暂无决策信号' }}</pre></section><section class="inspector-section"><h4>评估协议</h4><pre class="inspector-json">{{ jsonText(selectedNode.evaluation_protocol) || '暂无协议记录' }}</pre></section><section v-if="selectedNode.certification_notes?.length" class="inspector-section"><h4>认证记录</h4><pre class="inspector-prose">{{ selectedNode.certification_notes.join('\n') }}</pre></section></template>
          <template v-else><div class="inspector-text-toolbar"><span>{{ inspectorTab === 'code' ? 'solution.py' : tabs.find(tab => tab.id === inspectorTab)?.label }}</span><div><button class="icon-button" :disabled="!inspectorText" :title="copied ? '已复制' : '复制内容'" aria-label="复制节点内容" @click="copyText"><Check v-if="copied" :size="14" /><Copy v-else :size="14" /></button><button v-if="inspectorTab === 'code'" class="icon-button" :disabled="!selectedNode.code" title="下载 Python 代码" aria-label="下载节点代码" @click="downloadCode"><Download :size="14" /></button></div></div><p v-if="copyError" class="inspector-copy-error">{{ copyError }}</p><pre v-if="inspectorText" :class="inspectorTab === 'code' ? 'inspector-code' : 'inspector-prose'">{{ inspectorText }}</pre><div v-else class="inspector-empty"><Code2 :size="23" :stroke-width="1.4" /><span>当前节点暂无{{ tabs.find(tab => tab.id === inspectorTab)?.label }}</span></div></template>
        </div>
      </aside>
    </div>
    <section class="search-evidence">
      <header class="search-evidence-header"><nav aria-label="搜索证据视图"><button :class="{ active: lowerTab === 'candidates' }" @click="lowerTab = 'candidates'"><ListFilter :size="14" />候选对比<span class="mono">{{ candidateNodes.length }}</span></button><button :class="{ active: lowerTab === 'logs' }" @click="lowerTab = 'logs'"><Terminal :size="14" />执行日志</button></nav><div v-if="lowerTab === 'candidates' && candidateNodes.length" class="search-pagination"><span class="mono">{{ page + 1 }} / {{ pageCount }}</span><button class="icon-button" :disabled="page === 0" title="上一页候选" aria-label="上一页候选" @click="page--"><ChevronLeft :size="15" /></button><button class="icon-button" :disabled="page >= pageCount - 1" title="下一页候选" aria-label="下一页候选" @click="page++"><ChevronRight :size="15" /></button></div></header>
      <div v-if="lowerTab === 'candidates'" class="search-table-scroll"><table class="search-table"><thead><tr><th>#</th><th>节点</th><th>方法 / 动作</th><th>指标</th><th>评审状态</th><th>执行耗时</th><th>交付</th></tr></thead><tbody><tr v-for="(node, index) in pagedNodes" :key="node.id" :class="{ selected: node.id === selectedId, best: node.id === bestId }"><td class="mono">{{ page * pageSize + index + 1 }}</td><td><button class="search-node-link mono" :title="node.id" @click="selectNode(node.id, true)"><Trophy v-if="node.id === bestId" :size="12" /><span>{{ node.id.slice(0, 12) }}</span></button></td><td>{{ node.method_mode || actionLabels[graphAction(node.stage)] }}</td><td class="mono">{{ graphNodeState(node) === 'pending' ? '--' : formatGraphMetric(node.metric) }}</td><td><span class="search-table-status" :class="`state-${graphNodeState(node)}`">{{ stateLabels[graphNodeState(node)] }}</span></td><td class="mono">{{ node.exec_time == null ? '--' : `${formatGraphMetric(node.exec_time)} s` }}</td><td>{{ node.delivery_ready === true ? '就绪' : node.delivery_ready === false ? '待验证' : '--' }}</td></tr><tr v-if="!nodes.length"><td colspan="7" class="search-table-empty">暂无候选方案</td></tr></tbody></table></div>
      <pre v-else class="search-log">{{ terminalText || '暂无执行日志' }}</pre>
    </section>
    <details class="search-runtime-details"><summary>运行资源与交付记录</summary><DependencyInstallPanel :summary="ml.dependency_installation_summary" :detail-text="ml.dependency_installations" /><AlgoEvolveSummary :snapshot="snapshot" /></details>
  </section>
</template>

<style scoped>
.search-view { min-width: 0; color: var(--ink, #202824); }.search-heading { display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 12px; padding: 17px 20px; border-bottom: 1px solid var(--line, #e4e8e4); background: #fff; }.search-title { display: flex; align-items: center; gap: 9px; }.search-title > svg { color: #50745b; }.search-title h2 { margin: 0; font-size: 15px; font-weight: 650; }.search-engine { padding-left: 8px; font-size: 10px; color: #8c978e; }.search-counters { display: flex; gap: 19px; align-items: center; font-size: 11px; color: #8b948d; }.search-counters > span { display: flex; align-items: center; gap: 6px; }.search-counters b { font-weight: 650; color: #465b4c; }.search-counters .search-best { color: #19845b; }.search-counters .search-best b { color: #19845b; }.search-counters .search-pending { color: #b18f4d; }
.search-workspace { display: grid; grid-template-columns: minmax(0, 1fr) 312px; min-width: 0; border-bottom: 1px solid var(--line, #e4e8e4); }.inspector { display: flex; flex-direction: column; min-width: 0; height: 600px; max-height: 76vh; min-height: 540px; border-left: 1px solid var(--line, #e4e8e4); background: #fff; }.inspector-header { display: flex; align-items: center; justify-content: space-between; padding: 18px 17px 10px; gap: 8px; }.inspector-eyebrow { font-size: 9px; color: #959e97; }.inspector-header h3 { margin: 5px 0 0; font-size: 14px; font-weight: 600; }.inspector-status { flex-shrink: 0; font-size: 10px; padding: 4px 6px; color: #7b877e; background: #f4f6f4; border-radius: 3px; }.inspector-status.state-success { color: #2d8156; background: #f0f8f2; }.inspector-status.state-bug { color: #b36e57; background: #fbf1ed; }.inspector-status.state-pending { color: #a98845; background: #fbf6ea; }.inspector-identity { display: flex; align-items: flex-start; justify-content: space-between; gap: 8px; padding: 0 17px 14px; font-size: 9px; overflow-wrap: anywhere; color: #98a19a; }.inspector-identity svg { color: #19845b; flex-shrink: 0; }
.inspector-tabs { display: flex; border-bottom: 1px solid #e4e8e4; padding: 0 11px; gap: 1px; }.inspector-tabs button { flex: 1; border: 0; border-bottom: 2px solid transparent; border-radius: 0; background: transparent; padding: 9px 3px; color: #969f98; font-size: 11px; cursor: pointer; }.inspector-tabs button.active { border-bottom-color: #19845b; color: #19845b; }.inspector-body { flex: 1; min-height: 0; overflow-y: auto; overflow-x: hidden; padding: 16px 17px 20px; scrollbar-width: thin; }.inspector-score { display: flex; flex-direction: column; padding-bottom: 17px; gap: 5px; border-bottom: 1px solid #edf0ed; }.inspector-score > span { display: flex; gap: 5px; align-items: center; color: #909a92; font-size: 10px; }.inspector-score strong { font-size: 28px; line-height: 1.3; font-weight: 600; color: #2d5039; overflow-wrap: anywhere; }.inspector-score small { color: #72947b; font-size: 9px; }
.inspector-metadata { margin: 14px 0 0; display: grid; grid-template-columns: 1fr 1fr; gap: 15px 10px; }.inspector-metadata div { min-width: 0; }.inspector-metadata dt { font-size: 9px; color: #99a19a; }.inspector-metadata dd { margin: 5px 0 0; font-size: 11px; color: #526557; overflow-wrap: anywhere; }.inspector-section { margin-top: 22px; }.inspector-section:first-child { margin-top: 0; }.inspector-section h4 { margin: 0 0 10px; font-size: 11px; font-weight: 600; color: #687b6d; }.inspector-flags { display: grid; grid-template-columns: 1fr 1fr; gap: 9px 14px; }.inspector-flags > div { display: flex; justify-content: space-between; gap: 6px; font-size: 9px; color: #929d94; }.inspector-flags .passed { color: #4d9567; }.inspector-flags .rejected { color: #b47b5f; }.inspector-parents { display: grid; gap: 6px; }.inspector-parents button { display: flex; align-items: center; gap: 6px; text-align: left; padding: 6px 0; background: transparent; border: 0; color: #697e6f; cursor: pointer; }.inspector-parents button span { min-width: 0; overflow: hidden; text-overflow: ellipsis; font-size: 9px; }.inspector-parents button:disabled { opacity: .5; cursor: default; }.inspector-parents button svg:last-child { margin-left: auto; }.inspector-muted { font-size: 10px; color: #a0aaa2; }.inspector-times { margin: 18px 0 0; padding-top: 12px; border-top: 1px solid #edf0ed; }.inspector-times div { display: flex; justify-content: space-between; gap: 8px; margin-top: 7px; font-size: 9px; color: #929e95; }.inspector-times dd { margin: 0; text-align: right; }
.inspector-text-toolbar { display: flex; justify-content: space-between; align-items: center; gap: 8px; padding-bottom: 10px; font-size: 11px; color: #8a978e; }.inspector-text-toolbar > div { display: flex; }.inspector-text-toolbar .icon-button { width: 28px; height: 28px; }.inspector-prose { white-space: pre-wrap; overflow-wrap: anywhere; margin: 0; font-family: inherit; font-size: 11px; line-height: 1.85; color: #526557; }.inspector-code { margin: 0; padding: 13px; border-radius: 4px; overflow: auto; color: #dce9df; background: #27352d; font-size: 10px; line-height: 1.7; tab-size: 4; min-height: 200px; }.inspector-json { margin: 0; padding: 10px; border-radius: 3px; overflow: auto; background: #f6f8f6; font-size: 10px; line-height: 1.6; color: #7b8b80; }.inspector-empty { display: flex; flex: 1; min-height: 180px; justify-content: center; align-items: center; flex-direction: column; gap: 10px; font-size: 11px; color: #a4b1a7; }.inspector-copy-error { font-size: 10px; color: #ac745b; }
.search-evidence { padding: 0 20px 16px; background: #fff; }.search-evidence-header { display: flex; align-items: center; justify-content: space-between; border-bottom: 1px solid #e7ece8; min-height: 50px; }.search-evidence-header nav { display: flex; align-items: stretch; gap: 20px; align-self: stretch; }.search-evidence-header nav button { display: flex; align-items: center; gap: 7px; padding: 0; border: 0; border-radius: 0; border-bottom: 2px solid transparent; background: transparent; color: #939f96; font-size: 11px; cursor: pointer; }.search-evidence-header nav button.active { color: #3b674b; border-bottom-color: #19845b; }.search-evidence-header nav button span { color: #a6afa8; font-size: 9px; }.search-pagination { display: flex; gap: 4px; align-items: center; color: #9ba79e; font-size: 10px; }.search-pagination .icon-button { width: 26px; height: 26px; }.search-table-scroll { overflow-x: auto; }.search-table { width: 100%; border-collapse: collapse; text-align: left; white-space: nowrap; font-size: 11px; }.search-table th { padding: 12px 12px 10px; border-bottom: 1px solid #edf0ed; color: #99a39b; font-size: 10px; font-weight: 400; }.search-table td { padding: 10px 12px; border-bottom: 1px solid #f0f3f0; color: #728077; }.search-table th:first-child, .search-table td:first-child { padding-left: 0; width: 30px; color: #a3ada6; font-size: 10px; }.search-table tr.selected { background: #f7faf7; }.search-table tr.best td { color: #4c785b; }.search-node-link { display: flex; align-items: center; gap: 6px; background: none; border: 0; padding: 0; color: inherit; font-size: 10px; cursor: pointer; }.search-node-link svg { color: #19845b; }.search-node-link:hover { text-decoration: underline; }.search-table-status { font-size: 10px; }.search-table-status.state-success { color: #5b9470; }.search-table-status.state-bug { color: #b78068; }.search-table-status.state-pending { color: #b09b62; }.search-table-empty { height: 92px; text-align: center; color: #a5afa8; }.search-log { min-height: 150px; max-height: 400px; overflow: auto; white-space: pre-wrap; overflow-wrap: anywhere; color: #586d5f; background: #f7faf7; padding: 16px; margin: 12px 0 0; font-size: 11px; line-height: 1.75; }.search-runtime-details { border-top: 1px solid #e4e8e4; background: #fff; padding: 14px 20px; }.search-runtime-details summary { color: #7f9185; font-size: 11px; cursor: pointer; }.search-runtime-details[open] summary { margin-bottom: 14px; }
.inspector { height: clamp(400px, calc(100dvh - 430px), 560px); min-height: 400px; }
.search-table-scroll { max-height: 310px; overflow: auto; scrollbar-width: thin; }
.search-table:has(.search-table-empty) { min-width: 0; }
.search-table:has(.search-table-empty) thead { display: none; }
.search-table th { position: sticky; top: 0; background: #fff; z-index: 1; }
.search-follow { display: inline-flex; align-items: center; gap: 5px; margin-left: 8px; font-size: 10px; color: #829488; white-space: nowrap; }.search-follow input { margin: 0; accent-color: #19845b; width: 12px; height: 12px; }
@media (max-width: 1100px) { .search-workspace { grid-template-columns: minmax(0, 1fr) 280px; }.search-counters { gap: 12px; }.inspector-header { padding-inline: 12px; }.inspector-body { padding-inline: 12px; } }
@media (max-width: 760px) { .search-heading { padding: 15px 14px; }.search-engine { display: none; }.search-counters { width: 100%; justify-content: space-between; }.search-workspace { grid-template-columns: 1fr; }.inspector { height: 380px; min-height: 360px; max-height: none; border-left: 0; border-top: 1px solid #e4e8e4; }.inspector-header { padding-top: 12px; }.inspector-identity { padding-bottom: 8px; }.inspector-body { padding: 14px 16px; }.search-evidence { padding-inline: 14px; }.search-table { min-width: 670px; }.search-evidence-header nav { gap: 12px; }.search-evidence-header nav button { font-size: 10px; }.search-pagination > span { font-size: 9px; }.inspector-flags { grid-template-columns: 1fr 1fr; } }
</style>
