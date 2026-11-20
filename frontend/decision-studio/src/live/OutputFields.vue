<script setup lang="ts">
import { computed } from 'vue'
import { resultLabel } from './resultLabels'
const props = defineProps<{
  shape?: { kind: string; fields: string[] }
  result?: unknown
}>()
const shape = computed(() => {
  if (props.shape) return props.shape
  const sample = Array.isArray(props.result) ? props.result[0] : props.result
  return {
    kind: Array.isArray(props.result) ? 'table' : sample && typeof sample === 'object' ? 'object' : 'unknown',
    fields: sample && typeof sample === 'object' && !Array.isArray(sample) ? Object.keys(sample).slice(0, 30) : [],
  }
})
</script>
<template>
  <div class="output-fields">
    <p>{{ shape.kind === 'table' ? '结果表' : shape.kind === 'unknown' ? '尚无试算结果' : '计算结果' }}</p>
    <ul v-if="shape.fields.length"><li v-for="field in shape.fields" :key="field">{{ resultLabel(field) }}</li></ul>
  </div>
</template>
<style scoped>
.output-fields p { margin: 0; color: var(--secondary); }
.output-fields ul { display: flex; flex-wrap: wrap; gap: 8px 24px; list-style: none; padding: 0; margin-top: 12px; color: var(--ink); }
</style>
