<script setup lang="ts">
import { computed } from 'vue'
import { fieldName, record } from './presentation'
import { emptySchemaValue } from './schemaInput'
const props = defineProps<{ schema: any; modelValue: any; label?: string; required?: boolean }>()
const emit = defineEmits<{ 'update:modelValue': [value: any] }>()
const fields = computed(() => Object.entries(record(props.schema.properties)))
const requiredFields = computed(() => Array.isArray(props.schema.required) ? props.schema.required : [])
const rows = computed<any[]>(() => Array.isArray(props.modelValue) ? props.modelValue : [])
function updateField(key: string, value: unknown) {
  emit('update:modelValue', { ...record(props.modelValue), [key]: value })
}
function updateRow(index: number, value: unknown) {
  const next = [...rows.value]
  next[index] = value
  emit('update:modelValue', next)
}
function numberValue(event: Event) {
  const input = event.target as HTMLInputElement
  emit('update:modelValue', input.value === '' ? undefined : input.valueAsNumber)
}
</script>
<template>
  <fieldset v-if="fields.length" class="schema-input-group">
    <legend v-if="label">{{ label }}</legend>
    <SchemaValueInput
      v-for="[key, field] in fields" :key="key"
      :schema="field" :label="String(field.title || fieldName(key))"
      :required="requiredFields.includes(key)" :model-value="record(modelValue)[key]"
      @update:model-value="updateField(key, $event)"
    />
  </fieldset>
  <fieldset v-else-if="schema.type === 'array'" class="schema-input-group">
    <legend>{{ label || '数据记录' }}<span v-if="required"> *</span></legend>
    <p v-if="schema.description" class="hint">{{ schema.description }}</p>
    <div v-for="(row, i) in rows" :key="i" class="schema-input-row">
      <div class="panel-heading">
        <strong>记录 {{ i + 1 }}</strong>
        <button type="button" class="text-btn" @click="emit('update:modelValue', rows.filter((_, n) => n !== i))">移除</button>
      </div>
      <SchemaValueInput :schema="schema.items" :model-value="row" :required="true" @update:model-value="updateRow(i, $event)" />
    </div>
    <button type="button" class="btn secondary small" @click="emit('update:modelValue', [...rows, emptySchemaValue(schema.items)])">添加记录</button>
    <input v-if="required && !rows.length" class="schema-array-required" aria-label="请添加至少一条记录" required value="" tabindex="-1" />
  </fieldset>
  <label v-else-if="schema.enum" class="schema-input-field">
    <span>{{ label || '值' }}<span v-if="required"> *</span></span>
    <select :value="modelValue === undefined ? '' : String(schema.enum.indexOf(modelValue))" :required="required" @change="emit('update:modelValue', schema.enum[Number(($event.target as HTMLSelectElement).value)])">
      <option value="" disabled>请选择</option>
      <option v-for="(option, i) in schema.enum" :key="i" :value="String(i)">{{ typeof option === 'boolean' ? (option ? '是' : '否') : option }}</option>
    </select>
    <small v-if="schema.description" class="hint">{{ schema.description }}</small>
  </label>
  <label v-else-if="schema.type === 'boolean'" class="schema-input-field">
    <span>{{ label || '值' }}<span v-if="required"> *</span></span>
    <select :value="modelValue === undefined ? '' : String(modelValue)" :required="required" @change="emit('update:modelValue', ($event.target as HTMLSelectElement).value === 'true')">
      <option value="" disabled>请选择</option><option value="true">是</option><option value="false">否</option>
    </select>
    <small v-if="schema.description" class="hint">{{ schema.description }}</small>
  </label>
  <label v-else class="schema-input-field">
    <span>{{ label || '值' }}<span v-if="required"> *</span></span>
    <input v-if="['number', 'integer'].includes(schema.type)" :type="'number'" :step="schema.type === 'integer' ? 1 : 'any'" :min="schema.minimum" :max="schema.maximum" :value="modelValue" :required="required" @input="numberValue" />
    <input v-else type="text" :value="modelValue" :required="required" :minlength="schema.minLength" :maxlength="schema.maxLength" @input="emit('update:modelValue', ($event.target as HTMLInputElement).value)" />
    <small v-if="schema.description" class="hint">{{ schema.description }}</small>
  </label>
</template>
<style scoped>
.schema-input-group { position: relative; display: grid; gap: 14px; min-width: 0; padding: 16px; border: 1px solid var(--line); border-radius: 10px; }
.schema-input-group > legend { padding: 0 6px; font-size: 13px; font-weight: 600; }
.schema-input-field { display: grid; gap: 6px; min-width: 0; }
.schema-input-row { padding-bottom: 14px; border-bottom: 1px solid var(--line); }
.schema-array-required { position: absolute; bottom: 12px; width: 1px; height: 1px; opacity: 0; }
</style>
