<script setup lang="ts">
import { computed, ref } from 'vue'
import { resultLabel, resultText } from './resultLabels'
const props = withDefaults(defineProps<{ value: unknown; depth?: number }>(), { depth: 0 })
const visible = ref(20)
const isObject = computed(
  () => props.value !== null && typeof props.value === 'object' && !Array.isArray(props.value),
)
const entries = computed(() => (isObject.value ? Object.entries(props.value as Record<string, unknown>) : []))
const rows = computed(() => (Array.isArray(props.value) ? props.value : []))
const table = computed(
  () =>
    rows.value.length > 0 &&
    rows.value.every((item) => item && typeof item === 'object' && !Array.isArray(item)),
)
const columns = computed(() =>
  table.value ? [...new Set(rows.value.flatMap((item) => Object.keys(item)))] : [],
)
</script>
<template>
  <div v-if="Array.isArray(value)">
    <p v-if="!rows.length" class="hint">无记录</p>
    <div v-else-if="table" class="result-table-wrap" tabindex="0" aria-label="结果表格">
      <table class="result-table">
        <thead>
          <tr>
            <th v-for="key in columns" :key="key" scope="col">{{ resultLabel(key) }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(row, index) in rows.slice(0, visible)" :key="index">
            <td v-for="key in columns" :key="key"><ResultValue :value="row[key]" :depth="depth + 1" /></td>
          </tr>
        </tbody>
      </table>
    </div>
    <ol v-else class="readable-values">
      <li v-for="(item, index) in rows.slice(0, visible)" :key="index">
        <ResultValue :value="item" :depth="depth + 1" />
      </li>
    </ol>
    <button v-if="rows.length > visible" class="text-btn" @click="visible += 20">
      继续显示（已显示 {{ Math.min(visible, rows.length) }} / {{ rows.length }} 条）
    </button>
  </div>
  <dl v-else-if="isObject && entries.length" class="result-properties">
    <template v-for="[key, item] in entries" :key="key"
      ><dt>{{ resultLabel(key) }}</dt>
      <dd><ResultValue :value="item" :depth="depth + 1" /></dd
    ></template>
  </dl>
  <span v-else class="result-scalar">{{ isObject ? '无记录' : resultText(value) }}</span>
</template>
<style scoped>
.result-properties {
  display: grid;
  grid-template-columns: minmax(90px, 0.7fr) minmax(0, 1.8fr);
  gap: 10px 20px;
  margin: 0;
  align-items: start;
}
dt {
  color: var(--secondary);
  font-size: 12px;
  overflow-wrap: anywhere;
}
dd {
  margin: 0;
  min-width: 0;
}
.result-scalar {
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  line-height: 1.65;
}
.result-table-wrap {
  max-width: 100%;
  overflow: auto;
}
.result-table {
  border-collapse: collapse;
  width: 100%;
  text-align: left;
  font-size: 13px;
}
th {
  color: var(--secondary);
  font-weight: 500;
  white-space: nowrap;
}
th,
td {
  padding: 12px;
  border-bottom: 1px solid var(--line);
  vertical-align: top;
}
.readable-values {
  margin: 0;
  padding-left: 20px;
  display: grid;
  gap: 12px;
}
@media (max-width: 600px) {
  .result-properties {
    grid-template-columns: 1fr;
    gap: 5px;
  }
  dd {
    margin-bottom: 12px;
  }
}
</style>
