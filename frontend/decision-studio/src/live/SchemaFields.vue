<script setup lang="ts">
import { computed } from 'vue'
import { fieldName, record } from './presentation'
const props = defineProps<{
  schema?: Record<string, unknown>
  dataframes?: { pointer: string; columns: string[] }[]
}>()
const schemaValue = computed(() => record(props.schema))
const rowSchema = computed(() => schemaValue.value.type === 'array' ? record(schemaValue.value.items) : schemaValue.value)
const rootTable = computed(() => props.dataframes?.find(frame => frame.pointer === ''))
type SchemaDefinition = {
  title?: string
  type?: string
  description?: string
  enum?: unknown[]
  properties?: Record<string, unknown>
  items?: SchemaDefinition
}
type SchemaField = SchemaDefinition & { key: string }
const fields = computed<SchemaField[]>(() => Object.entries(record(rowSchema.value.properties)).map(([key, value]) => {
  const definition = record(value)
  return {
    key,
    title: typeof definition.title === 'string' ? definition.title : undefined,
    type: typeof definition.type === 'string' ? definition.type : undefined,
    description: typeof definition.description === 'string' ? definition.description : undefined,
    enum: Array.isArray(definition.enum) ? definition.enum : undefined,
    properties: Object.keys(record(definition.properties)).length ? record(definition.properties) : undefined,
    items: Object.keys(record(definition.items)).length ? record(definition.items) as SchemaDefinition : undefined,
  }
}))
const requiredFields = computed(() => Array.isArray(rowSchema.value.required) ? rowSchema.value.required.map(String) : [])
const types: Record<string, string> = { number: '数值', integer: '整数', string: '文本', boolean: '是 / 否', object: '字段集合', array: '多条记录' }
</script>
<template>
  <div v-if="rootTable" class="table-input-fields">
    <strong>表格数据 · {{ rootTable.columns.length }} 个字段</strong>
    <details><summary>查看所需字段</summary><ul><li v-for="column in rootTable.columns" :key="column">{{ fieldName(column) }}</li></ul></details>
  </div>
  <div v-else-if="fields.length" class="schema-fields">
    <div v-for="field in fields" :key="field.key" class="schema-field">
      <div><strong>{{ field.title || fieldName(field.key) }}</strong><span class="tag neutral">{{ field.type ? types[field.type] || '数据' : '数据' }}</span><span v-if="requiredFields.includes(field.key)" class="field-required">必填</span></div>
      <p v-if="field.description">{{ field.description }}</p>
      <small v-if="field.title && field.title !== field.key" class="hint">{{ field.key }}</small>
      <p v-if="field.enum?.length" class="hint">可选值：{{ field.enum.join('、') }}</p>
      <details v-if="field.properties || field.items?.properties"><summary>查看记录字段</summary><SchemaFields :schema="field.items || field" /></details>
    </div>
  </div>
  <p v-else class="hint">{{ schemaValue.description || '尚未登记输入字段，请先核对交付说明。' }}</p>
</template>
<style scoped>
.schema-fields { display: grid; gap: 16px; }.schema-field { padding: 16px 0; border-bottom: 1px solid var(--line); }.schema-field > div { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }.schema-field p { margin-top: 8px; }.field-required { color: var(--secondary); font-size: 11px; }
.table-input-fields { padding-block: 10px; color: var(--secondary); font-size: 13px; }
.table-input-fields > strong { font-weight: 500; }
.table-input-fields summary { cursor: pointer; margin-block: 8px; }
.table-input-fields ul { display: flex; flex-wrap: wrap; gap: 6px 14px; list-style: none; padding: 0; margin-block: 12px; max-height: 200px; overflow: auto; }
</style>
