<script setup lang="ts">
import { computed, ref } from 'vue'
import { canEditSchema, isBulkInput } from './schemaInput'
import SchemaValueInput from './SchemaValueInput.vue'
const props = defineProps<{ schema?: any; modelValue: string }>()
const emit = defineEmits<{ 'update:modelValue': [value: string] }>()
const advanced = ref(false), error = ref(''), fileName = ref('')
const editable = computed(() => canEditSchema(props.schema))
const value = computed(() => {
  try { return JSON.parse(props.modelValue || '{}') } catch { return {} }
})
const bulkInput = computed(() => isBulkInput(value.value))
const recordCounts = computed(() => {
  const data = value.value
  if (Array.isArray(data)) return [{ name: '数据记录', count: data.length }]
  return Object.entries(data || {}).filter(([, rows]) => Array.isArray(rows)).map(([key, rows]) => ({
    name: props.schema?.properties?.[key]?.title || key, count: (rows as unknown[]).length,
  }))
})
function update(value: unknown) {
  emit('update:modelValue', JSON.stringify(value))
}
async function importFile(event: Event) {
  const file = (event.target as HTMLInputElement).files?.[0]
  if (!file) return
  try {
    if (file.size > 16 * 1024 * 1024) throw new Error('输入文件超过 16 MiB，请缩小本次输入后重新导入。')
    const text = (await file.text()).replace(/^\uFEFF/, '')
    const parsed = JSON.parse(text)
    if (!parsed || typeof parsed !== 'object') throw new Error('输入文件需包含一组字段或多条记录。')
    update(parsed)
    fileName.value = file.name
    error.value = ''
  } catch (e) {
    error.value = e instanceof SyntaxError ? '无法读取输入文件，请检查文件格式。' : (e as Error).message
  }
}
</script>
<template>
  <div class="schema-input">
    <SchemaValueInput v-if="editable && !advanced && !bulkInput" :schema="schema" :model-value="value" @update:model-value="update" />
    <div v-if="bulkInput && !advanced" class="bulk-input-summary" role="status" aria-label="批量输入已就绪">
      <p>批量输入已就绪，可直接运行试算。</p>
      <p v-for="row in recordCounts" :key="row.name" class="hint">{{ row.name }}：{{ row.count }} 条</p>
      <p class="hint">可重新导入文件替换本次输入，或展开下方高级输入编辑原文。</p>
    </div>
    <label class="input-file-label">导入输入文件<input type="file" accept=".json,application/json" @change="importFile" /></label>
    <p v-if="fileName" class="hint" role="status">已读取 {{ fileName }}</p>
    <p v-if="!editable && !fileName && !advanced" class="hint">请选择已有输入文件，或切换为本地 CSV。输入要求见交付说明。</p>
    <p v-if="error" class="live-error" role="alert">{{ error }}</p>
    <details @toggle="advanced = ($event.target as HTMLDetailsElement).open">
      <summary>高级输入 · 编辑原文</summary>
      <textarea :value="modelValue" rows="6" aria-label="输入 JSON 原文" spellcheck="false" @input="emit('update:modelValue', ($event.target as HTMLTextAreaElement).value)" />
    </details>
  </div>
</template>
<style scoped>
.schema-input { display: grid; gap: 14px; }.input-file-label { display: grid; gap: 8px; }
</style>
