<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import Icon from '../components/Icon.vue'
import ResourceStorage from './ResourceStorage.vue'
import { storageRevision } from './storage'
import { taskWorkflow } from './taskWorkflow'
import { packages, usePackage, ui, state, request, status, phase, date } from './store'
import { inspectionReads } from './readCache'
const emit = defineEmits<{ open: [kind: string, id: string]; navigate: [page: string] }>(),
  query = ref('')
const filtered = computed(() =>
  packages.value.filter((p) => (p.name + p.description).toLowerCase().includes(query.value.toLowerCase())),
)
interface Candidate {
  task_id: string
  task_name: string
  status: string
  phase: string
  created_at: number
  updated_at: number
  inspection: 'not_checked' | 'checked'
  published_ids: string[]
}
const groupedPackages = computed(() => {
  const groups = new Map<string, { id: string; name: string; packages: typeof filtered.value }>()
  for (const item of filtered.value) {
    const id = item.task_id || 'unlinked'
    if (!groups.has(id)) groups.set(id, { id, name: item.task_name || state.tasks.find(t => t.id === id)?.task_name || '未关联任务', packages: [] })
    groups.get(id)!.packages.push(item)
  }
  return [...groups.values()]
})
const pending = computed(() => state.tasks.filter(t => state.links.some(l => l.id === t.id && l.project_id === ui.projectId) && taskWorkflow(t, state.task_deliveries?.[t.id]).pendingDelivery))
function nextStep(c: Candidate) { return taskWorkflow({ id: c.task_id, status: c.status, phase: c.phase }, state.task_deliveries?.[c.task_id]) }
const candidates = ref<Candidate[]>([]),
  candidateError = ref(''),
  candidatesLoading = ref(false),
  candidatesChecked = ref(false)
let sequence = 0,
  disposed = false
async function loadCandidates(force = false) {
  const n = ++sequence,
    id = ui.projectId
  candidateError.value = ''
  candidatesChecked.value = true
  if (!id) {
    candidates.value = []
    candidatesLoading.value = false
    return
  }
  candidatesLoading.value = true
  try {
    const linked = new Set(state.links.filter(link => link.project_id === id).map(link => link.id))
    const revision = state.tasks.filter(task => linked.has(task.id))
      .map(task => `${task.id}:${task.status}:${task.phase}:${task.updated_at}`).sort().join('|')
    const published = packages.value.map(item => `${item.id}:${item.version}`).sort().join('|')
    const result = await inspectionReads.read(`candidates:${id}:${revision}:${published}`,
      () => request<Candidate[]>(`/studio/projects/${id}/package-candidates`, undefined, 'GET', { timeoutMs: 20000 }), 20000, force)
    if (!disposed && n === sequence) candidates.value = result
  } catch (e) {
    if (!disposed && n === sequence) candidateError.value = e instanceof Error ? e.message : String(e)
  } finally {
    if (!disposed && n === sequence) candidatesLoading.value = false
  }
}
watch(
  () => ui.projectId,
  (id, previous) => {
    if (id === previous) return
    sequence += 1
    candidates.value = []
    candidateError.value = ''
    candidatesChecked.value = false
    candidatesLoading.value = false
    void loadCandidates()
  },
)
onMounted(() => void loadCandidates())
watch(storageRevision, () => void loadCandidates(true))
watch(() => state.tasks.map(t => `${t.id}:${t.updated_at}:${t.status}`).join('|') + packages.value.map(p => p.id).join('|'), () => { if (ui.online) void loadCandidates() })
onUnmounted(() => {
  disposed = true
  sequence += 1
})
</script>
<template>
  <section class="live-page">
    <div class="page-heading">
      <div>
        <h1>算法模型包</h1>
      </div>
    </div>
    <label class="live-search"
      ><Icon name="search" /><input
        v-model="query"
        placeholder="搜索当前项目的模型包"
        aria-label="搜索模型包"
    /></label>
    <section v-for="group in groupedPackages" :key="group.id" class="package-task-group" :data-task="group.id">
      <h2>{{ group.name }}</h2>
    <div class="live-grid three">
      <article v-for="p in group.packages" :key="p.id" class="live-panel package-tile">
        <div class="panel-heading">
          <span class="square-icon"><Icon name="package" :size="24" /></span
          ><span class="tag neutral">v{{ p.version }}</span>
        </div>
        <h2>{{ p.name }}</h2>
        <p>{{ p.description }}</p>
        <div class="package-meta">
          <span>{{ p.file_count ?? p.files?.length ?? 0 }} 个文件</span>
          <span>{{ p.input_binding ? '支持项目数据直接调用' : '填写输入调用' }}</span>
        </div>
        <footer>
          <button class="btn secondary small" @click="emit('open', 'package', p.id)">查看详情</button
          ><button class="btn primary small" :disabled="!!ui.busy" @click="usePackage(p)">
            在对话中使用<Icon name="arrow" :size="14" />
          </button>
        </footer>
        <ResourceStorage kind="packages" :id="p.id" />
      </article>
    </div>
    </section>
    <div v-if="!filtered.length" class="live-empty">
      <Icon name="package" :size="32" />
      <template v-if="query.trim()">
        <h2>没有匹配“{{ query }}”的模型包</h2>
        <button class="btn secondary small" @click="query = ''">清除搜索，查看全部模型包</button>
      </template>
      <template v-else-if="!ui.projectId">
        <h2>先选择或创建数据项目</h2>
        <button class="btn primary small" @click="emit('navigate', 'projects')">打开项目数据</button>
      </template>
      <template v-else-if="pending.length">
        <h2>已有 {{ pending.length }} 项研发成果待交付或发布</h2>
        <p>先检查已有成果，发布后即可在决策对话中使用。</p>
        <button class="btn primary small" @click="emit('open', 'delivery', pending[0]!.id)">检查已有成果并发布</button>
      </template>
      <template v-else>
        <h2>当前项目还没有已发布模型包</h2>
        <p v-if="candidates.some(c => c.status === 'running')">已有任务正在研发，可在下方查看进度。</p>
        <button class="btn secondary small" :disabled="!ui.online" @click="emit('open', 'research', '')">新建研发任务</button>
      </template>
    </div>
    <section class="live-panel results-section">
      <div class="panel-heading">
        <div>
          <h2>已有研发成果</h2>
        </div>
        <button
          class="btn secondary small"
          :disabled="candidatesLoading || !ui.projectId"
          @click="loadCandidates(true)"
        >
          {{ candidatesLoading ? '读取中…' : '刷新列表' }}
        </button>
      </div>
      <p v-if="!candidatesChecked && !ui.projectId" class="hint">先选择一个数据项目。</p>
      <p v-else-if="candidatesLoading" role="status" aria-live="polite">正在读取任务列表…</p>
      <p v-if="candidateError" class="live-error">{{ candidateError }}</p>
      <div v-for="c in candidates" :key="c.task_id" class="candidate-row">
        <div class="candidate-copy">
          <h3>{{ c.task_name }}</h3>
          <p>{{ status(c.status) }} · {{ phase(c.phase) }} · 更新于 {{ date(c.updated_at) }}</p>
        </div>
        <span class="tag" :class="nextStep(c).tone">{{ nextStep(c).label }}</span>
        <button class="btn secondary small" @click="emit('open', nextStep(c).kind, nextStep(c).packageId || c.task_id)">
          {{ nextStep(c).action }}
        </button>
      </div>
      <p v-if="candidatesChecked && !candidatesLoading && !candidateError && !candidates.length" class="hint">
        当前项目没有可查看的研发任务。
      </p>
    </section>
  </section>
</template>
