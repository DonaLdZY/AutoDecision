<script setup lang="ts">
import { computed } from 'vue'
import ResultValue from './ResultValue.vue'
import { resultLabel } from './resultLabels'
const props = defineProps<{ result: unknown }>()
const names: Record<string, string> = {
  prediction_cutoff: '观测截止时间',
  prediction_time: '预测时间',
  predicted_al_n: '预测压滤液 Al(N)',
  unit: '单位',
  steam_advice: '蒸汽进气流量参考',
  recommended_flow_kg_h: '参考流量（kg/h）',
  recommended_steam_flow: '参考蒸汽流量',
  current_flow_kg_h: '当前流量（kg/h）',
  support_count: '支持样本数',
  support_sample_count: '支持样本数',
  interval_kg_h: '参考区间（kg/h）',
  basis: '参考依据',
  caveats: '需复核事项',
  status: '状态',
  reason: '依据',
  limitations: '适用限制',
}
const entries = computed(() =>
  props.result && typeof props.result === 'object' && !Array.isArray(props.result)
    ? Object.entries(props.result)
    : [],
)
const metadata = new Set(['model', 'contract', 'diagnostics', 'execution_evidence', 'version'])
const mainEntries = computed(() => entries.value.filter(([key]) => !metadata.has(key)))
const technicalEntries = computed(() => entries.value.filter(([key]) => metadata.has(key)))
function object(value: unknown): Record<string, any> {
  return value && typeof value === 'object' && !Array.isArray(value) ? (value as Record<string, any>) : {}
}
function steamStatus(value: unknown): string {
  const advice = object(value)
  if (advice.status === 'ok') return advice.caveats?.length ? '有历史参考 · 需核查附带条件' : '有历史参考'
  return (
    ({ review_required: '需要人工复核', unavailable: '当前无法提供参考' } as Record<string, string>)[
      advice.status
    ] || String(advice.status || '未提供')
  )
}
function display(value: unknown): string {
  return typeof value === 'number'
    ? String(Number(value.toPrecision(8)))
    : value == null
      ? '未提供'
      : String(value)
}
</script>
<template>
  <div v-if="entries.length" class="decision-result">
    <div v-for="[key, value] in mainEntries" :key="key" class="result-field">
      <strong>{{ names[key] || resultLabel(key) }}</strong>
      <template v-if="key === 'steam_advice' && value && typeof value === 'object'">
        <span>{{ steamStatus(value) }}</span>
        <dl class="steam-values">
          <template
            v-for="field in [
              'recommended_flow_kg_h',
              'interval_kg_h',
              'current_flow_kg_h',
              'support_sample_count',
            ]"
            :key="field"
          >
            <dt>{{ names[field] }}</dt>
            <dd>
              {{
                Array.isArray(object(value)[field])
                  ? object(value)[field].map(display).join(' – ')
                  : display(object(value)[field])
              }}
            </dd>
          </template>
        </dl>
        <p v-if="object(value).reason">{{ object(value).reason }}</p>
        <p v-for="note in object(value).caveats || []" :key="note" class="steam-caveat">{{ note }}</p>
        <details v-if="object(value).basis">
          <summary>查看参考依据</summary>
          <ResultValue :value="object(value).basis" />
        </details>
        <details>
          <summary>查看完整蒸汽输出</summary>
          <pre>{{ JSON.stringify(value, null, 2) }}</pre>
        </details>
      </template>
      <ResultValue v-else :value="value" />
    </div>
    <details v-if="technicalEntries.length" class="result-field">
      <summary>技术详情</summary>
      <div v-for="[key, value] in technicalEntries" :key="key">
        <strong>{{ names[key] || key }}</strong>
        <pre>{{ JSON.stringify(value, null, 2) }}</pre>
      </div>
    </details>
  </div>
  <ResultValue v-else-if="result != null" :value="result" />
  <p v-else class="result-unavailable">没有可展示的结果</p>
</template>
<style scoped>
.decision-result {
  display: grid;
  gap: 12px;
  margin: 14px 0;
}
.result-field {
  display: grid;
  gap: 6px;
  padding: 12px 16px;
  border: 1px solid var(--line, #dbe5e3);
  border-radius: 10px;
  background: var(--surface, #fff);
}
.result-field strong {
  font-size: 12px;
  color: #58706b;
}
.result-field span {
  font-size: 17px;
  overflow-wrap: anywhere;
}
.result-field pre {
  margin: 0;
  max-height: 260px;
  overflow: auto;
  white-space: pre-wrap;
  font-size: 12px;
}
.steam-values {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  gap: 8px;
  margin: 6px 0;
}
.steam-values dt {
  color: #58706b;
  font-size: 12px;
}
.steam-values dd {
  margin: 0;
  overflow-wrap: anywhere;
}
.result-field p,
.result-field li {
  font-size: 13px;
  line-height: 1.7;
  overflow-wrap: anywhere;
}
.result-field ul {
  margin: 0;
  padding-left: 20px;
}
.result-list {
  line-height: 1.8;
}
.result-unavailable {
  color: #6c7e86;
}
.steam-caveat {
  padding: 10px;
  background: #fff7e7;
  border-left: 3px solid #c88728;
}
.result-field summary {
  cursor: pointer;
  font-size: 12px;
}
</style>
