<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from 'vue'
import { project, request } from './store'
import type { Catalog } from './store'
const props = defineProps<{ modelValue: string; inputRoot?: string }>()
const emit = defineEmits<{ 'update:modelValue': [value: string] }>()
const catalog = ref<Catalog>(), error = ref(''), loading = ref(false), manual = ref(false)
let sequence = 0
const root = computed(() => props.inputRoot || project.value?.input_root || '')
const files = computed(() => (catalog.value?.files || []).filter(file => !file.is_dir && /\.csv$/i.test(file.name)))
const filePath = (name: string) => root.value.replace(/[\\/]$/, '') + (root.value.includes('\\') ? '\\' : '/') + name
async function load() {
  const n = ++sequence
  catalog.value = undefined
  loading.value = false
  if (!project.value || !root.value) return
  loading.value = true
  error.value = ''
  try {
    const result = await request<Catalog>(`/studio/projects/${project.value.id}/research-data?input_root=${encodeURIComponent(root.value)}`,
      undefined, 'GET', { timeoutMs: 15000 })
    if (n === sequence) {
      catalog.value = result
      error.value = result.error || ''
    }
  } catch (e) { if (n === sequence) error.value = e instanceof Error ? e.message : String(e) }
  finally { if (n === sequence) loading.value = false }
}
watch([root, () => project.value?.id], load, { immediate: true })
onUnmounted(() => sequence++)
</script>
<template>
  <div class="project-csv-input">
    <label>数据文件
      <select v-if="files.length && !manual" :value="modelValue" required aria-label="选择项目数据文件"
        @change="emit('update:modelValue', ($event.target as HTMLSelectElement).value)">
        <option value="" disabled>选择 CSV 文件</option>
        <option v-for="file in files" :key="file.name" :value="filePath(file.name)">{{ file.name }}</option>
      </select>
      <input v-else :value="modelValue" required placeholder="项目内的 CSV 文件路径" aria-label="数据文件路径"
        @input="emit('update:modelValue', ($event.target as HTMLInputElement).value)" />
    </label>
    <span v-if="loading" role="status" class="hint">正在读取文件…</span>
    <p v-if="error" class="hint">{{ error }} <button type="button" class="text-btn" @click="load">重试</button></p>
    <button v-if="files.length" type="button" class="text-btn csv-manual" @click="manual = !manual">{{ manual ? '从项目选择' : '填写其他路径' }}</button>
  </div>
</template>
