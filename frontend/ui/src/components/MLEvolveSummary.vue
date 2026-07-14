<script setup lang="ts">
import { computed } from 'vue'
import type { SnapshotPayload } from '../types'

const props = defineProps<{
  snapshot?: SnapshotPayload
}>()

const autoMl = computed(() => props.snapshot?.auto_ml ?? {})
const isMLEvolve = computed(() => String(autoMl.value.engine ?? '') === 'mlevolve')
const nodes = computed(() => autoMl.value.nodes ?? [])
const pendingNodes = computed(() => autoMl.value.pending_nodes ?? [])
const visiblePendingNodes = computed(() => {
  const seen = new Set(nodes.value.map((node) => node.id))
  return pendingNodes.value.filter((node) => node.id && !seen.has(node.id))
})
const displayNodes = computed(() => [...nodes.value, ...visiblePendingNodes.value])
const bestNodeId = computed(() => String(autoMl.value.best_node_id ?? ''))
const bestNode = computed(() => nodes.value.find((node) => node.id === bestNodeId.value) ?? null)
const goodNodes = computed(() => nodes.value.filter((node) => node.is_buggy === false))
const buggyNodes = computed(() => nodes.value.filter((node) => node.is_buggy === true))
const finishedNodes = computed(() => nodes.value.filter((node) => !!node.finish_time))
const branchCount = computed(() => {
  const set = new Set<number>()
  for (const node of displayNodes.value) {
    if (typeof node.branch_id === 'number') set.add(node.branch_id)
  }
  return set.size
})
const stageSummary = computed(() => {
  const map = new Map<string, number>()
  for (const node of displayNodes.value) {
    const key = String(node.stage || 'unknown')
    map.set(key, (map.get(key) ?? 0) + 1)
  }
  return [...map.entries()].sort((a, b) => a[0].localeCompare(b[0]))
})
const bestMetricText = computed(() => String(autoMl.value.best_metric_text ?? '').trim())
const bestSolutionCode = computed(() => String(autoMl.value.best_solution_code ?? '').trim())
const logDir = computed(() => String(autoMl.value.log_dir ?? ''))
const workspaceDir = computed(() => String(autoMl.value.workspace_dir ?? ''))
</script>

<template>
  <section v-if="isMLEvolve" class="summary-panel">
    <header class="summary-header">
      <div>
        <h4>MLEvolve 摘要</h4>
        <p>面向 MLEvolve 的分支演化监控摘要，不影响原有搜索逻辑。</p>
      </div>
    </header>

    <div class="stats-grid">
      <article class="stat-card">
        <span class="label">总节点数</span>
        <strong>{{ displayNodes.length }}</strong>
      </article>
      <article class="stat-card pending-stat">
        <span class="label">待执行草稿</span>
        <strong>{{ visiblePendingNodes.length }}</strong>
      </article>
      <article class="stat-card">
        <span class="label">已完成节点</span>
        <strong>{{ finishedNodes.length }}</strong>
      </article>
      <article class="stat-card">
        <span class="label">成功节点</span>
        <strong>{{ goodNodes.length }}</strong>
      </article>
      <article class="stat-card">
        <span class="label">Bug 节点</span>
        <strong>{{ buggyNodes.length }}</strong>
      </article>
      <article class="stat-card">
        <span class="label">分支数</span>
        <strong>{{ branchCount }}</strong>
      </article>
      <article class="stat-card">
        <span class="label">最优节点</span>
        <strong>{{ bestNodeId || '-' }}</strong>
      </article>
    </div>

    <div class="meta-grid">
      <article class="meta-card">
        <h5>运行目录</h5>
        <p><strong>log_dir</strong></p>
        <pre>{{ logDir || '-' }}</pre>
        <p><strong>workspace_dir</strong></p>
        <pre>{{ workspaceDir || '-' }}</pre>
      </article>

      <article class="meta-card">
        <h5>阶段分布</h5>
        <ul class="stage-list">
          <li v-for="item in stageSummary" :key="item[0]">
            <span>{{ item[0] }}</span>
            <strong>{{ item[1] }}</strong>
          </li>
        </ul>
      </article>
    </div>

    <div class="detail-grid">
      <article class="detail-card">
        <h5>最优节点摘要</h5>
        <div v-if="bestNode" class="best-node-meta">
          <span>stage: {{ bestNode.stage || '-' }}</span>
          <span>metric: {{ bestNode.metric ?? '-' }}</span>
          <span>branch: {{ bestNode.branch_id ?? '-' }}</span>
          <span>uct: {{ bestNode.uct ?? '-' }}</span>
          <span>visits: {{ bestNode.visits ?? 0 }}</span>
        </div>
        <pre>{{ bestMetricText || '暂无 best_solution/metric.txt' }}</pre>
      </article>

      <article class="detail-card">
        <h5>最优方案代码</h5>
        <pre>{{ bestSolutionCode || '暂无 best_solution/solution.py' }}</pre>
      </article>
    </div>
  </section>
</template>

<style scoped>
.summary-panel {
  margin-top: 10px;
  border: 1px solid #d7e2f2;
  border-radius: 12px;
  background: #fcfdff;
  padding: 12px;
}

.summary-header h4 {
  margin: 0;
  color: #234a76;
}

.summary-header p {
  margin: 4px 0 0;
  color: #55749a;
  font-size: 12px;
}

.stats-grid {
  margin-top: 10px;
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(112px, 1fr));
  gap: 8px;
}

.stat-card {
  border: 1px solid #d7e2f2;
  border-radius: 10px;
  background: #fff;
  padding: 10px;
}

.stat-card .label {
  display: block;
  font-size: 12px;
  color: #5f7da2;
}

.stat-card strong {
  display: block;
  margin-top: 6px;
  color: #234a76;
  font-size: 18px;
}

.pending-stat {
  background: #f6f7f9;
  border-color: #c9d0d9;
}

.pending-stat strong {
  color: #5f6875;
}

.meta-grid,
.detail-grid {
  margin-top: 10px;
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}

.meta-card,
.detail-card {
  border: 1px solid #d7e2f2;
  border-radius: 10px;
  background: #fff;
  padding: 10px;
}

.meta-card h5,
.detail-card h5 {
  margin: 0 0 8px;
  color: #254a76;
}

.meta-card p {
  margin: 8px 0 4px;
  color: #496a92;
  font-size: 12px;
}

.stage-list {
  margin: 0;
  padding: 0;
  list-style: none;
  display: grid;
  gap: 6px;
}

.stage-list li,
.best-node-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  font-size: 12px;
  color: #496a92;
}

pre {
  margin: 0;
  background: #f7fbff;
  border: 1px solid #d5e2f2;
  border-radius: 8px;
  padding: 10px;
  overflow: auto;
  max-height: 260px;
  white-space: pre-wrap;
  font-size: 12px;
}

@media (max-width: 900px) {
  .stats-grid,
  .meta-grid,
  .detail-grid {
    grid-template-columns: 1fr;
  }
}
</style>
