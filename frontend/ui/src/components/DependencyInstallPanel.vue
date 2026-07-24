<script setup lang="ts">
import { computed } from 'vue'
import type { DependencyInstallationSummary } from '../types'
import {
  dependencyInstallCount,
  dependencyRequirementCandidates,
  parseDependencyInstallationRecords,
} from '../utils/dependencyInstallations'

const props = defineProps<{
  summary?: DependencyInstallationSummary
  detailText?: string
}>()

const records = computed(() => parseDependencyInstallationRecords(props.detailText ?? ''))
const attempts = computed(() => dependencyInstallCount(props.summary, 'attempt_count'))
const installed = computed(() => dependencyInstallCount(props.summary, 'installed_count'))
const failed = computed(() => dependencyInstallCount(props.summary, 'failed_count'))
const rejected = computed(() => dependencyInstallCount(props.summary, 'rejected_count'))
const candidates = computed(() => dependencyRequirementCandidates(props.summary))
const hasActivity = computed(() => attempts.value > 0 || rejected.value > 0 || records.value.length > 0)

function recordTitle(index: number): string {
  const record = records.value[index]
  const packageName = record.requirement || record.distribution || record.missing_module || '未知依赖'
  return `${packageName} · ${record.status || 'unknown'}`
}
</script>

<template>
  <section v-if="hasActivity" class="dependency-panel">
    <header class="panel-header">
      <div>
        <h4>环境补库记录</h4>
        <p>记录 MLEvolve 安装到当前任务隔离目录的缺失依赖，可据此补充项目 requirements。</p>
      </div>
      <div class="environment-paths">
        <code v-if="summary?.python_executable">Python: {{ summary.python_executable }}</code>
        <code v-if="summary?.install_target">任务依赖: {{ summary.install_target }}</code>
      </div>
    </header>

    <dl class="stats">
      <div><dt>尝试</dt><dd>{{ attempts }}</dd></div>
      <div class="success"><dt>安装成功</dt><dd>{{ installed }}</dd></div>
      <div :class="{ danger: failed > 0 }"><dt>安装失败</dt><dd>{{ failed }}</dd></div>
      <div :class="{ warning: rejected > 0 }"><dt>声明拒绝</dt><dd>{{ rejected }}</dd></div>
    </dl>

    <div v-if="candidates.length" class="requirements">
      <h5>requirements 候选</h5>
      <pre>{{ candidates.join('\n') }}</pre>
    </div>

    <details v-if="records.length" class="record-details">
      <summary>查看安装明细（{{ records.length }}）</summary>
      <ol>
        <li v-for="(record, index) in records" :key="`${record.timestamp || index}-${record.node_id || ''}`">
          <strong>{{ recordTitle(index) }}</strong>
          <span v-if="record.node_id">node: {{ record.node_id }}</span>
          <span v-if="record.missing_module">missing: {{ record.missing_module }}</span>
          <span v-if="record.duration_seconds !== undefined">{{ record.duration_seconds }}s</span>
          <pre v-if="record.stderr_tail">{{ record.stderr_tail }}</pre>
        </li>
      </ol>
    </details>
  </section>
</template>

<style scoped>
.dependency-panel {
  margin-top: 10px;
  border: 1px solid #cbd8e6;
  border-left: 4px solid #377d62;
  background: #f8fbfa;
  padding: 12px;
}

.panel-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}

.panel-header h4,
.requirements h5 {
  margin: 0;
  color: #244c3e;
}

.panel-header p {
  margin: 4px 0 0;
  color: #557269;
  font-size: 12px;
}

.panel-header code {
  display: block;
  overflow-wrap: anywhere;
  color: #385d52;
  font-size: 11px;
}

.environment-paths {
  display: grid;
  max-width: 45%;
  gap: 4px;
}

.stats {
  display: grid;
  grid-template-columns: repeat(4, minmax(100px, 1fr));
  margin: 12px 0 0;
  border: 1px solid #d6e1dd;
  background: #fff;
}

.stats div {
  min-width: 0;
  padding: 9px 10px;
  border-right: 1px solid #d6e1dd;
}

.stats div:last-child {
  border-right: 0;
}

.stats dt {
  color: #60786f;
  font-size: 11px;
}

.stats dd {
  margin: 3px 0 0;
  color: #284c41;
  font-size: 18px;
  font-weight: 700;
}

.stats .success dd {
  color: #14734f;
}

.stats .danger dd {
  color: #b13d38;
}

.stats .warning dd {
  color: #9a650f;
}

.requirements {
  margin-top: 12px;
}

.requirements pre,
.record-details pre {
  margin: 6px 0 0;
  padding: 8px 10px;
  overflow: auto;
  background: #fff;
  border: 1px solid #d6e1dd;
  color: #2e5146;
  font-size: 12px;
  white-space: pre-wrap;
}

.record-details {
  margin-top: 12px;
  color: #3c6256;
  font-size: 12px;
}

.record-details summary {
  cursor: pointer;
  width: fit-content;
  font-weight: 600;
}

.record-details ol {
  display: grid;
  gap: 8px;
  margin: 10px 0 0;
  padding-left: 24px;
}

.record-details li {
  padding-left: 4px;
}

.record-details li > span {
  margin-left: 10px;
  color: #647c74;
}

@media (max-width: 720px) {
  .panel-header {
    display: block;
  }

  .environment-paths {
    max-width: 100%;
    margin-top: 8px;
  }

  .stats {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .stats div:nth-child(2) {
    border-right: 0;
  }

  .stats div:nth-child(-n + 2) {
    border-bottom: 1px solid #d6e1dd;
  }
}
</style>
