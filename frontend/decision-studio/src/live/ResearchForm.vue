<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { ui, state, request, run, refresh, selectProject } from './store'
import type { Catalog } from './store'
const props = defineProps<{
  goal?: string
  conversationId?: string
  packageId?: string
  plan?: Record<string, unknown>
}>(),
  emit = defineEmits<{ done: [id: string] }>()
const goal = ref(props.goal || ''),
  name = ref(''),
  metric = ref(''),
  constraints = ref(''),
  polishing = ref(false),
  suggestion = ref<ResearchSuggestion | null>(null),
  useSuggestion = ref({ title: true, goal: true, evaluation: true, constraints: true }),
  steps = ref(128),
  minutes = ref(30),
  cpu = ref(4),
  memory = ref(8),
  report = ref(true),
  reportMinutes = ref(20),
  webResearch = ref(false),
  webResearchQuery = ref('')
const projectId = ref(ui.projectId),
  inputRoot = ref(''),
  preview = ref<Catalog | null>(null),
  dataError = ref(''),
  loading = ref(false)
const selectedProject = computed(() => state.projects.find((p) => p.id === projectId.value))
const webResearchQueryError = computed(() => {
  if (!webResearch.value) return ''
  const query = webResearchQuery.value.trim()
  if (!query) return '请填写适合公开发送的检索词。'
  if (query.length > 128) return '检索词不能超过 128 个字符。'
  return ''
})
interface ResearchSuggestion {
  title: string
  goal: string
  evaluation: string
  constraints: string[]
  changes: string[]
  questions: string[]
  model: string
}
let sequence = 0
let polishSequence = 0
function invalidatePolish() {
  polishSequence++
  polishing.value = false
  suggestion.value = null
}
const draftSnapshot = () => JSON.stringify([
  projectId.value, inputRoot.value, goal.value, name.value, metric.value, constraints.value,
])
watch([goal, name, metric, constraints], () => { if (suggestion.value) suggestion.value = null })
onBeforeUnmount(invalidatePolish)
async function polish() {
  if (!goal.value.trim() || polishing.value || !preview.value || dataError.value || loading.value) return
  const n = ++polishSequence
  const snapshot = draftSnapshot()
  polishing.value = true
  suggestion.value = null
  try {
    const result = await request<ResearchSuggestion>(`/studio/projects/${projectId.value}/research-optimization`, {
      input_root: inputRoot.value,
      title: name.value.trim(),
      goal: goal.value,
      evaluation: metric.value,
      constraints: constraints.value,
    })
    if (n !== polishSequence || snapshot !== draftSnapshot()) return
    suggestion.value = result
    useSuggestion.value = { title: !!result.title, goal: true, evaluation: true, constraints: true }
  } catch (e) {
    if (n === polishSequence) ui.error = e instanceof Error ? e.message : String(e)
  } finally {
    if (n === polishSequence) polishing.value = false
  }
}
function applySuggestion() {
  const result = suggestion.value
  if (!result) return
  if (useSuggestion.value.title && result.title) name.value = result.title
  if (useSuggestion.value.goal) goal.value = result.goal
  if (useSuggestion.value.evaluation) metric.value = result.evaluation
  if (useSuggestion.value.constraints) {
    // Keep every original constraint verbatim; the user can edit additions afterwards.
    const original = constraints.value.split('\n').map((line) => line.trim()).filter(Boolean)
    constraints.value = [...new Set([...original, ...result.constraints.map((line) => line.trim()).filter(Boolean)])].join('\n')
  }
  suggestion.value = null
}
async function loadData() {
  const n = ++sequence
  preview.value = null
  dataError.value = ''
  loading.value = false
  if (!selectedProject.value || !inputRoot.value) return
  loading.value = true
  try {
    const result = await request<Catalog & { input_root: string }>(
      `/studio/projects/${projectId.value}/research-data?input_root=${encodeURIComponent(inputRoot.value)}`,
    )
    if (n === sequence) preview.value = result
  } catch (e) {
    if (n === sequence) dataError.value = e instanceof Error ? e.message : String(e)
  } finally {
    if (n === sequence) loading.value = false
  }
}
watch(
  projectId,
  () => {
    invalidatePolish()
    inputRoot.value = selectedProject.value?.input_root || ''
  },
  { immediate: true, flush: 'sync' },
)
watch(inputRoot, () => { invalidatePolish(); void loadData() }, { immediate: true, flush: 'sync' })
async function pickData() {
  await run('research-data-directory', async () => {
    const result = await request('/fs/pick-directory', {
      initial_path: inputRoot.value,
      title: '选择一个研发数据包目录',
    })
    if (result.ok) inputRoot.value = result.path
  })
}
async function create() {
  if (!preview.value || dataError.value || loading.value || polishing.value) return
  if (webResearchQueryError.value) {
    ui.error = webResearchQueryError.value
    return
  }
  await run('create-task', async () => {
    const t = await request(`/studio/projects/${projectId.value}/tasks`, {
      input_root: inputRoot.value,
      task_name: name.value.trim() + '__' + Date.now().toString(36),
      auto_realize: { task_hint: goal.value },
      auto_ml: {
        goal: goal.value,
        eval: [metric.value, constraints.value].filter(Boolean).join('\n硬约束：\n'),
        steps: steps.value,
        time_limit_secs: minutes.value * 60,
        parallel_search_num: 1,
        memory_embedding_device: 'cpu',
        web_research_enabled: webResearch.value,
        web_research_query: webResearch.value ? webResearchQuery.value.trim() : '',
      },
      auto_report: { enabled: report.value, request_timeout_secs: reportMinutes.value * 60 },
      resources: { cpu_cores: cpu.value, memory_limit_gb: memory.value, accelerator_mode: 'none' },
    })
    await refresh()
    selectProject(projectId.value)
    emit('done', t.id)
  })
}
</script>
<template>
  <form class="live-form" @submit.prevent="create">
    <label
      >所属数据项目<select v-model="projectId" aria-label="所属数据项目" required>
        <option v-for="p in state.projects" :key="p.id" :value="p.id">{{ p.name }}</option>
      </select></label
    >
    <section class="live-panel research-data-panel">
      <h3>本次研发数据包 · 单目录</h3>
      <label>数据包目录<input v-model="inputRoot" required placeholder="所选项目内的一个数据目录" /></label>
      <div class="form-actions">
        <button type="button" class="btn secondary small" :disabled="!!ui.busy" @click="pickData">
          选择数据包目录
        </button>
        <button
          type="button"
          class="btn secondary small"
          @click="inputRoot = selectedProject?.input_root || ''"
        >
          使用整个项目目录
        </button>
      </div>
      <p class="hint">
        仅将所选目录及其子目录作为本次研发输入。其他数据包不会合并；所需说明和辅助文件请一并放入该目录。
      </p>
      <p v-if="loading" role="status">正在读取数据包…</p>
      <p v-if="dataError" class="live-error" role="alert">{{ dataError }}</p>
      <div v-if="preview" class="research-data-preview" aria-label="研发数据包文件预览">
        <span v-for="f in preview.files" :key="f.name" class="tag neutral"
          >{{ f.is_dir ? '目录 / ' : '' }}{{ f.name }}</span
        >
        <p v-if="!preview.files.length" class="hint">该目录没有可预览的文件。</p>
        <p v-if="preview.limited" class="hint">预览已显示前 120 项，任务仍使用整个所选目录。</p>
      </div>
    </section>
    <div class="form-heading-row">
      <span class="eyebrow">研发简报</span>
      <button
        type="button"
        class="btn secondary small"
        :disabled="polishing || !goal.trim() || !preview || !!dataError || loading"
        @click="polish"
      >
        {{ polishing ? '正在优化…' : 'AI 优化研发需求' }}
      </button>
    </div>
    <label
      >任务名称<input v-model="name" required maxlength="80" placeholder="例如：逐门架车流预测改进" /></label
    ><label>研发目标<textarea v-model="goal" required rows="5" /></label
    ><label
      >评价标准<textarea v-model="metric" rows="2" placeholder="指标、时间切分、基线及验收阈值" />
    </label>
    <label>硬约束（每行一条）<textarea v-model="constraints" rows="3" placeholder="例如：只使用当前项目目录；不得泄漏未来数据" /></label>
    <p class="hint">优化时会发送当前填写内容、项目名称、所选目录的文件名与表头给所选模型；不会读取数据行。</p>
    <section v-if="suggestion" class="optimization-review" aria-label="AI 优化建议">
      <div class="optimization-heading"><div><span class="eyebrow">候选稿 · {{ suggestion.model }}</span><h3>核对优化建议</h3></div><button type="button" class="text-btn" @click="suggestion = null">放弃</button></div>
      <p class="hint">选择要应用的内容。原有硬约束会保留；请核对新增内容和待确认事项。</p>
      <div v-for="field in ([['title', '任务名称', name], ['goal', '研发目标', goal], ['evaluation', '评价标准', metric], ['constraints', '硬约束', constraints]] as const)" :key="field[0]" class="optimization-field">
        <label class="optimization-field-title"><input v-model="useSuggestion[field[0]]" type="checkbox" />{{ field[1] }}</label>
        <div class="optimization-compare"><div><span>当前</span><p>{{ field[2] || '未填写' }}</p></div><div><span>建议</span><p>{{ field[0] === 'constraints' ? suggestion.constraints.join('\n') || '无新增建议' : suggestion[field[0]] || '未提供' }}</p></div></div>
      </div>
      <div v-if="suggestion.changes.length" class="optimization-notes"><strong>调整说明</strong><ul><li v-for="item in suggestion.changes" :key="item">{{ item }}</li></ul></div>
      <div v-if="suggestion.questions.length" class="optimization-notes"><strong>待确认</strong><ul><li v-for="item in suggestion.questions" :key="item">{{ item }}</li></ul></div>
      <button type="button" class="btn primary small" @click="applySuggestion">应用所选建议</button>
    </section>
    <label
        >搜索时间上限（分钟）<input
          v-model.number="minutes"
          type="number"
          min="1"
          max="1440"
          required /></label>
    <details class="developer-details">
      <summary>计算资源与高级设置</summary>
      <div class="live-grid two">
        <label>搜索动作上限<input v-model.number="steps" type="number" min="1" max="500" required /></label>
        <label>CPU 核数<input v-model.number="cpu" type="number" min="1" required /></label>
        <label>内存（GiB）<input v-model.number="memory" type="number" min="1" required /></label>
        <label v-if="report">报告单次请求时限（分钟）<input v-model.number="reportMinutes" type="number" min="1" max="60" required /></label>
      </div>
    </details>
    <label class="check-line"><input v-model="report" type="checkbox" />搜索后生成报告与交付包</label>
    <p class="hint">研发结束后，任务页会提示交付与发布的下一步；成果发布后才能由决策对话直接调用。</p>
    <label class="check-line"><input v-model="webResearch" type="checkbox" />检索公开方法资料</label>
    <div v-if="webResearch" class="web-research-fields">
      <label
        >公开检索词<input
          v-model="webResearchQuery"
          type="text"
          maxlength="128"
          required
          placeholder="例如：异构车辆 时间窗 配送优化 MILP 大邻域搜索"
          aria-describedby="web-research-policy"
          :aria-invalid="!!webResearchQueryError"
      /></label>
      <div class="search-query-meta">
        <p id="web-research-policy" class="hint">
          仅此处文字会发送给 DeepSeek Search / Fetch；任务说明、文件路径和本地数据不会自动发送。需在本机配置搜索 API 密钥。
        </p>
        <span>{{ webResearchQuery.trim().length }}/128</span>
      </div>
      <p v-if="webResearchQueryError" class="live-error" role="alert">
        {{ webResearchQueryError }}
      </p>
    </div>
    <p class="hint">
      默认 CPU、单路搜索。时间为搜索阶段上限，包含依赖准备和其他阶段的总耗时可能更长；它不是 API
      费用硬上限。完整配置可在任务草稿里编辑。
    </p>
    <button
      class="btn primary"
      :disabled="!!ui.busy || !selectedProject || !preview || !!dataError || loading || polishing || !!webResearchQueryError"
    >
      保存研发草稿
    </button>
  </form>
</template>
<style scoped>
.form-heading-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}
.optimization-review { display: grid; gap: 14px; padding: 18px; border: 1px solid var(--line); border-left: 3px solid var(--accent, #557bd8); border-radius: 8px; background: var(--surface, #fff); }
.optimization-heading { display: flex; justify-content: space-between; gap: 12px; align-items: start; }
.optimization-heading h3 { margin: 4px 0 0; }
.optimization-field { display: grid; gap: 8px; padding-top: 10px; border-top: 1px solid var(--line); }
.optimization-field-title { display: flex; align-items: center; gap: 8px; font-weight: 600; }
.optimization-field-title input { width: auto; }
.optimization-compare { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
.optimization-compare > div { min-width: 0; padding: 10px; border-radius: 6px; background: var(--bg, #f6f8fb); }
.optimization-compare span { color: var(--muted); font-size: 12px; }
.optimization-compare p { white-space: pre-wrap; overflow-wrap: anywhere; margin: 5px 0 0; }
.optimization-notes ul { margin: 6px 0 0; padding-left: 20px; }
@media (max-width: 600px) { .optimization-compare { grid-template-columns: 1fr; } }
.web-research-fields {
  display: grid;
  gap: 8px;
  padding-left: 24px;
  border-left: 2px solid var(--line);
}
.search-query-meta {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 16px;
}
.search-query-meta .hint {
  margin: 0;
}
.search-query-meta > span {
  flex: none;
  color: var(--muted);
  font-size: 12px;
  font-variant-numeric: tabular-nums;
}
</style>
