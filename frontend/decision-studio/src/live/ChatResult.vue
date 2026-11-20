<script setup lang="ts">
import { onUnmounted, ref, watch } from 'vue'
import { request, status } from './store'
import type { Invocation } from './store'
import DecisionResult from './DecisionResult.vue'
const props = defineProps<{ id: string }>()
const emit = defineEmits<{ open: [kind: string, id: string] }>()
const data = ref<Invocation>(), error = ref('')
let timer: ReturnType<typeof setTimeout> | undefined, sequence = 0, loading = false, disposed = false
function clear() { if (timer) clearTimeout(timer); timer = undefined }
async function load(n: number, id: string) {
  if (loading || disposed || document.hidden || n !== sequence) return
  loading = true
  try {
    const result = await request<Invocation>(`/studio/invocations/${id}?view=summary`)
    if (disposed || n !== sequence) return
    data.value = result; error.value = ''
    if (result.status === 'running' && !document.hidden) timer = setTimeout(() => load(n, id), 3000)
  } catch (e) {
    if (!disposed && n === sequence) error.value = e instanceof Error ? e.message : String(e)
  } finally { loading = false }
}
watch(() => props.id, id => {
  clear(); const n = ++sequence; data.value = undefined; error.value = ''; void load(n, id)
}, { immediate: true })
function onVisibilityChange() {
  clear()
  if (!document.hidden) void load(sequence, props.id)
}
document.addEventListener('visibilitychange', onVisibilityChange)
onUnmounted(() => { disposed = true; sequence++; clear(); document.removeEventListener('visibilitychange', onVisibilityChange) })
</script>
<template>
  <div v-if="data?.status === 'completed'">
    <DecisionResult v-if="!data.answer" :result="data.result" />
    <details v-else class="answer-data"><summary>查看计算结果</summary><DecisionResult :result="data.decision_facts ?? data.result" /></details>
  </div>
  <div v-else-if="data?.status === 'running'" class="chat-result-status" role="status">
    <span class="tag info">{{ status(data.status) }}</span><span>正在计算，结果会自动更新。</span>
    <button class="text-btn" @click="emit('open', 'invocation', props.id)">查看调用详情</button>
  </div>
  <div v-else-if="data?.error || data?.error_summary || error" class="chat-result-error live-error" role="alert">
    <span>{{ data?.error_summary || data?.error || error }}</span>
    <button class="btn secondary small" @click="emit('open', 'invocation', props.id)">查看失败原因并重试</button>
  </div>
</template>
