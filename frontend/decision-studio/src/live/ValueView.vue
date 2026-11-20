<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { fieldName, scalar } from './presentation'
const props = defineProps<{ value: unknown }>()
const limit = ref(20)
watch(() => props.value, () => limit.value = 20)
const entries = computed(() => props.value && typeof props.value === 'object' && !Array.isArray(props.value) ? Object.entries(props.value) : [])
const array = computed(() => Array.isArray(props.value) ? props.value : null)
const tabular = computed(() => !!array.value?.length && array.value.every(row => row && typeof row === 'object' && !Array.isArray(row) && Object.values(row).every(v => v == null || typeof v !== 'object')))
const columns = computed(() => tabular.value ? [...new Set(array.value!.flatMap(row => Object.keys(row)))] : [])
</script>
<template>
  <div v-if="tabular" class="value-table table-scroll">
    <table class="live-table"><thead><tr><th v-for="key in columns" :key="key">{{ fieldName(key) }}</th></tr></thead>
      <tbody><tr v-for="(row, index) in array!.slice(0, limit)" :key="index"><td v-for="key in columns" :key="key">{{ scalar(row[key]) }}</td></tr></tbody>
    </table>
    <button v-if="array!.length > limit" type="button" class="text-btn" @click="limit += 50">继续查看（共 {{ array!.length }} 条）</button>
  </div>
  <div v-else-if="array" class="value-list">
    <p v-if="!array.length" class="hint">暂无记录</p>
    <div v-for="(item, index) in array.slice(0, limit)" :key="index"><ValueView :value="item" /></div>
    <button v-if="array.length > limit" type="button" class="text-btn" @click="limit += 50">继续查看（共 {{ array.length }} 条）</button>
  </div>
  <dl v-else-if="entries.length" class="value-fields">
    <div v-for="[key, item] in entries" :key="key"><dt>{{ fieldName(key) }}</dt><dd><ValueView :value="item" /></dd></div>
  </dl>
  <span v-else class="value-scalar">{{ scalar(value) }}</span>
</template>
<style scoped>
.value-fields { display: grid; gap: 14px; margin: 0; }
.value-fields > div { display: grid; grid-template-columns: minmax(110px, 30%) minmax(0, 1fr); gap: 16px; padding: 10px 0; border-bottom: 1px solid var(--line); }
dt { color: var(--secondary); font-size: 13px; overflow-wrap: anywhere; }
dd { margin: 0; min-width: 0; overflow-wrap: anywhere; }
.value-scalar { white-space: pre-wrap; line-height: 1.7; overflow-wrap: anywhere; }
.value-list { display: grid; gap: 10px; }
.value-table { max-width: 100%; }
@media(max-width: 600px) { .value-fields > div { grid-template-columns: 1fr; gap: 5px; } }
</style>
