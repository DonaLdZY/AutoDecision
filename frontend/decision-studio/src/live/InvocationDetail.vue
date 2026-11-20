<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { request, date, download, state, selectProject } from './store'
import type { Invocation } from './store'
import DecisionResult from './DecisionResult.vue'
import InvokeForm from './InvokeForm.vue'
import MarkdownView from './MarkdownView.vue'
import { humanTaskStatus, inputSummary, record } from './presentation'
const props = defineProps<{ id: string }>()
const emit = defineEmits<{ open: [kind: string, id: string]; navigate: [page: string] }>()
const retrying = ref(false)
const canRetry = computed(() => !!data.value?.package_ids.length && data.value.package_ids.every(id => state.packages.some(p => p.id === id && p.project_id === data.value?.project_id)))
function retry() {
  if (!data.value || !canRetry.value) return
  selectProject(data.value.project_id)
  retrying.value = true
}
const data = ref<Invocation>(), full = ref<Invocation>(), error = ref(''), technicalError = ref('')
let timer: ReturnType<typeof setTimeout> | undefined, sequence = 0, disposed = false, loading = false
async function load(n: number, id: string) {
  if (loading || disposed || document.hidden) return
  loading = true
  try {
    const result = await request<Invocation>(`/studio/invocations/${id}?view=summary`)
    if (disposed || n !== sequence) return
    data.value = result; error.value = ''
    if (result.status === 'running' && !document.hidden) timer = setTimeout(() => load(n, id), 3000)
  } catch (e) { if (!disposed && n === sequence) error.value = String(e) }
  finally { loading = false }
}
watch(() => props.id, id => {
  clearTimeout(timer); const n = ++sequence
  retrying.value = false; data.value = undefined; full.value = undefined; error.value = ''; technicalError.value = ''
  void load(n, id)
}, { immediate: true })
function onVisibilityChange() {
  clearTimeout(timer)
  if (!document.hidden && (!data.value || data.value.status === 'running')) void load(sequence, props.id)
}
onMounted(() => document.addEventListener('visibilitychange', onVisibilityChange))
onUnmounted(() => { disposed = true; sequence++; clearTimeout(timer); document.removeEventListener('visibilitychange', onVisibilityChange) })
async function completeRecord() {
  const n = sequence, result = await request<Invocation>(`/studio/invocations/${props.id}`)
  if (!disposed && n === sequence) full.value = result
  return result
}
async function exportRecord() {
  try { const result = await completeRecord(); download(`invocation-${result.id}.json`, result) }
  catch (e) { error.value = String(e) }
}
async function showTechnical(event: Event) {
  if (!(event.target as HTMLDetailsElement).open || full.value) return
  try { await completeRecord() } catch (e) { technicalError.value = String(e) }
}
function packageName(id: unknown) {
  const pkg = state.packages.find(p => p.id === id)
  return pkg?.name || '算法包'
}
function resultCount(value: unknown): string {
  if (Array.isArray(value)) return `${value.length} 项结果`
  const object = record(value)
  return Object.keys(object).length ? `${Object.keys(object).length} 项结果` : '已返回结果'
}
</script>
<template>
  <div v-if="data" class="live-detail">
    <div class="detail-hero"><div><div class="eyebrow">{{ humanTaskStatus(data.status) }}</div><h2>{{ data.title }}</h2><p>{{ date(data.created_at) }} · {{ data.duration_seconds == null ? '执行中' : `耗时 ${data.duration_seconds.toFixed(1)} 秒` }}</p></div><button class="btn secondary small" @click="exportRecord">导出记录</button></div>
    <div v-if="data.error_summary" class="live-error" role="alert">{{ data.error_summary }}</div>
    <section v-if="data.status === 'failed'" class="live-panel" aria-label="调用失败后续操作">
      <h3>调整输入后重新调用</h3>
      <p>本次失败记录会保留。重新选择输入并确认后，将创建新的调用记录。</p>
      <div class="form-actions">
        <button v-if="canRetry && !retrying" class="btn primary small" @click="retry">重新核对输入并调用</button>
        <button class="btn secondary small" @click="emit('navigate', 'packages')">查看算法包与使用要求</button>
        <button class="btn secondary small" @click="emit('navigate', 'settings')">检查运行设置</button>
      </div>
      <p v-if="!canRetry" class="hint">原调用中的算法包已不可用，请在算法包目录选择可用版本。</p>
      <InvokeForm v-if="retrying && canRetry" :package-ids="data.package_ids" @done="id => emit('open', 'invocation', id)" />
    </section>
    <section class="live-panel">
      <div class="panel-heading"><h3>{{ data.answer ? '决策答案' : '计算结果' }}</h3></div>
      <MarkdownView v-if="data.answer" :text="data.answer" />
      <DecisionResult v-else-if="data.result != null" :result="data.result" />
      <p v-else>{{ data.status === 'running' ? '正在计算…' : '没有成功输出' }}</p>
      <details v-if="data.answer && data.result != null"><summary>查看计算结果</summary><DecisionResult :result="data.result" /></details>
    </section>
    <section class="live-panel"><h3>本次使用</h3>
      <div v-for="(step, index) in data.steps" :key="index" class="input-receipt">
        <div><span class="step-index">{{ index + 1 }}</span><strong>{{ packageName(step.package_id) }}</strong></div>
        <p v-for="line in inputSummary(step)" :key="line">{{ line }}</p>
      </div>
    </section>
    <details class="live-panel" @toggle="showTechnical">
      <summary>技术详情</summary>
      <p v-if="technicalError" class="live-error">{{ technicalError }}</p>
      <template v-if="full">
        <p v-if="full.error" class="live-error">{{ full.error }}</p>
        <section v-if="full.decision_program">
          <h3>决策代码</h3>
          <p>{{ full.decision_program.model }} · 生成耗时 {{ full.decision_program.duration_seconds }} 秒</p>
          <pre><code>{{ full.decision_program.code }}</code></pre>
          <details><summary>模型用量</summary><pre>{{ JSON.stringify(full.decision_program.usage, null, 2) }}</pre></details>
        </section>
        <section v-for="(step, index) in full.steps" :key="index">
          <details><summary>步骤 {{ index + 1 }} · 原始记录</summary><pre>{{ JSON.stringify(step, null, 2) }}</pre></details>
        </section>
      </template>
      <p v-else>正在读取…</p>
    </details>
  </div>
  <div v-else-if="error" class="live-error" role="alert">{{ error }}<button class="btn secondary small" @click="load(sequence, id)">重试读取记录</button></div><p v-else class="hint" role="status">正在读取调用记录…</p>
</template>
