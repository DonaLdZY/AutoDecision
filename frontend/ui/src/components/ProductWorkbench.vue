<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { Task, SnapshotPayload } from '../types'
import { api, saveBlob, type Solution } from '../api'
import LocalReadiness from './LocalReadiness.vue'
const props = defineProps<{ task: Task; snapshot?: SnapshotPayload; view: string }>()
defineEmits<{ settings: []; configure: []; newExperiment: []; select: [id: string]; report: [] }>()
const experiments = ref<Task[]>([])
const solution = ref<Solution | null>(null)
const busy = ref(false)
const error = ref('')
const trialMode = ref('json')
const trialJson = ref('{}')
const trialCsv = ref('')
const trialTimeout = ref(30)
const trialBusy = ref(false)
const trialResult = ref<Record<string, unknown> | null>(null)
const trials = ref<{ trial_id: string; created_at: number; node_id: string }[]>([])
const trialRows = computed(() => {
  const result = trialResult.value?.result
  if (result === null || result === undefined) return []
  if (typeof result !== 'object' || Array.isArray(result)) {
    return [{ label: '结果', value: readableValue(result) }]
  }
  return Object.entries(result as Record<string, unknown>).map(([key, value]) => ({
    label: resultLabels[key] ?? key.replaceAll('_', ' '),
    value: readableValue(value),
  }))
})
const selectedNodeLabel = computed(() => {
  const nodeId = solution.value?.node_id
  if (!nodeId) return '未记录'
  const nodes = props.snapshot?.auto_ml?.nodes ?? []
  const index = nodes.findIndex(node => node.id === nodeId)
  return index >= 0 ? `候选方案 ${index + 1}` : '已选方案'
})

const resultLabels: Record<string, string> = {
  answer: '结果',
  actual: '实际值',
  accuracy: '准确率',
  basis: '参考依据',
  caveats: '需复核事项',
  interval: '参考区间',
  prediction: '预测值',
  predictions: '预测结果',
  reason: '说明',
  recommended_flow_kg_h: '建议流量',
  status: '状态',
  support_count: '参考样本数',
  support_sample_count: '参考样本数',
  unit: '单位',
  value: '数值',
}

function readableValue(value: unknown): string {
  if (value === null || value === undefined || value === '') return '未提供'
  if (typeof value === 'boolean') return value ? '是' : '否'
  if (typeof value === 'string' || typeof value === 'number') return String(value)
  if (Array.isArray(value)) return `${value.length} 项结果`
  return `${Object.keys(value as Record<string, unknown>).length} 项信息`
}

function taskStatusLabel(status: string) {
  return ({ completed: '已完成', failed: '失败', idle: '待运行', running: '运行中', stopped: '已停止' } as Record<string, string>)[status] ?? '状态未知'
}

function trialTitle(trial: { created_at: number; node_id: string }, index: number) {
  const nodes = props.snapshot?.auto_ml?.nodes ?? []
  const node = nodes.find(item => item.id === trial.node_id)
  const nodeIndex = nodes.findIndex(item => item.id === trial.node_id)
  const candidate = node?.label || (nodeIndex >= 0 ? `候选方案 ${nodeIndex + 1}` : `试算 ${index + 1}`)
  return `${new Date(trial.created_at * 1000).toLocaleString()} · ${candidate}`
}

function pathName(path: string) {
  return path.replaceAll('\\', '/').replace(/\/+$/, '').split('/').filter(Boolean).at(-1) || '待选择'
}
async function loadTrial(id: string) {
  try { trialResult.value = await api.getTrial(props.task.id, id) } catch (e) { error.value = String(e) }
}
async function runTrial() {
  if (trialBusy.value) return
  const id = props.task.id
  trialBusy.value = true; error.value = ''; trialResult.value = null
  try {
    const result = await api.trialSolution(id, { input_mode: trialMode.value, data_json: trialJson.value, csv_path: trialCsv.value, timeout_seconds: trialTimeout.value })
    if (props.task.id === id) { trialResult.value = result; trials.value = await api.getTrials(id) }
  } catch (e) { if (props.task.id === id) error.value = String(e) }
  finally { trialBusy.value = false }
}
function saveTrial() { if (trialResult.value) saveBlob(new Blob([JSON.stringify(trialResult.value, null, 2)], { type: 'application/json' }), `trial-${trialResult.value.trial_id}.json`) }
let generation = 0
const protocol = computed(() => solution.value?.manifest?.evaluation_protocol as Record<string, unknown> | undefined)
const selectedNode = computed(() => props.snapshot?.auto_ml?.nodes?.find(node => node.id === solution.value?.node_id))
const frozen = computed(() => props.task.execution_config || props.task.config)
async function refresh() {
  const id = ++generation, taskId = props.task.id, view = props.view
  error.value = ''; solution.value = null; experiments.value = []; busy.value = true
  trialResult.value = null
  try {
    if (view === 'experiments') { const result = await api.getExperiments(taskId); if (id === generation) experiments.value = result }
    if (view === 'solution') {
      const [result, history] = await Promise.all([api.getSolution(taskId), api.getTrials(taskId)])
      if (id === generation) { solution.value = result; trials.value = history }
    }
  } catch (e) { if (id === generation) error.value = String(e) }
  finally { if (id === generation) busy.value = false }
}
async function download() {
  busy.value = true; error.value = ''
  try { await api.downloadSolution(props.task.id) } catch (e) { error.value = String(e) }
  finally { busy.value = false }
}
async function openDirectory() {
  try { if (solution.value?.directory) await api.openDirectory(solution.value.directory) }
  catch (e) { error.value = String(e) }
}
// A task list refresh updates `task.status` while a run is active. That
// snapshot update must not re-run the expensive solution inspection on every
// poll: the solution endpoint scans and fingerprints the selected artifact.
// Read it when the user opens the delivery view, and once when a run actually
// transitions from running to a terminal state.
watch(() => [props.task.id, props.view], refresh, { immediate: true })
watch(
  () => props.task.status,
  (next, previous) => {
    if (props.view === 'solution' && previous && next !== previous) void refresh()
  },
)
</script>
<template>
  <div class="product-workbench">
    <p v-if="error" class="product-error" role="alert">{{ error }}</p>
    <template v-if="view === 'overview'">
      <section class="product-panel">
        <div class="product-panel-heading"><div><h3>目标、数据与预算</h3></div><button class="command" @click="$emit('configure')">{{ task.run_dir || task.execution_config ? '查看冻结配置' : '配置任务' }}</button></div>
        <p class="task-goal">{{ frozen.auto_realize.task_hint || frozen.auto_ml.goal || '还没有描述目标。填写期望输出、评价指标和业务约束。' }}</p>
        <dl class="product-facts"><div><dt>数据目录</dt><dd>{{ pathName(frozen.input_root) }}</dd></div><div><dt>搜索时间上限</dt><dd>{{ Math.round(frozen.auto_ml.time_limit_secs / 60) }} 分钟</dd></div><div><dt>本地计算资源</dt><dd>{{ frozen.resources.cpu_cores }} 核 / {{ frozen.resources.memory_limit_gb }} GiB / {{ frozen.auto_ml.parallel_search_num }} 并行</dd></div><div><dt>模型请求并发</dt><dd>{{ frozen.auto_realize.llm_concurrency }}</dd></div></dl>
        <details v-if="frozen.input_root"><summary>查看完整数据路径</summary><code>{{ frozen.input_root }}</code></details>
        <p class="product-note">搜索时间不包含前置分析、最终评估和报告。API 费用与本地算力分开；本版尚无费用硬上限。开始后按配置自动执行各阶段。</p>
        <p v-if="task.run_dir || task.execution_config" class="product-note">本实验配置已锁定。需要修改目标、数据或预算时，创建新实验；原始数据仍是目录引用，请勿在运行期间修改。</p>
      </section>
      <LocalReadiness :task-id="task.id" @settings="$emit('settings')" />
    </template>
    <section v-else-if="view === 'experiments'" class="product-panel">
      <div class="product-panel-heading"><div><h3>实验历史</h3></div><button class="command primary" @click="$emit('newExperiment')">新建实验</button></div>
      <p v-if="busy">正在读取记录…</p>
      <div class="product-table-wrap"><table class="product-table"><thead><tr><th>实验</th><th>状态</th><th>目标 / 数据</th><th>搜索预算</th><th>创建时间</th></tr></thead><tbody><tr v-for="row in experiments" :key="row.id" :class="{ current: row.id === task.id }"><td><button class="experiment-link" @click="$emit('select', row.id)">{{ row.task_name }}</button></td><td>{{ taskStatusLabel(row.status) }}</td><td>{{ (row.execution_config || row.config).auto_realize.task_hint || '未填写目标' }}<small>{{ pathName((row.execution_config || row.config).input_root) }}</small></td><td>{{ Math.round((row.execution_config || row.config).auto_ml.time_limit_secs / 60) }} 分钟 / {{ (row.execution_config || row.config).auto_ml.parallel_search_num }} 并行</td><td>{{ new Date(row.created_at * 1000).toLocaleString() }}</td></tr></tbody></table></div>
      <p class="product-note">这里比较配置和运行身份。不同数据、合同或评价范围的分数不能直接排名。旧记录没有冻结配置时展示其存量配置，不补造历史。</p>
    </section>
    <section v-else-if="view === 'solution'" class="product-panel">
      <div class="product-panel-heading"><div><h3>选定方案与交付</h3></div><button class="command" :disabled="busy || task.status === 'running'" @click="refresh">{{ busy ? '检查中…' : '重新检查成果' }}</button></div>
      <p v-if="busy" role="status">正在检查成果…</p>
      <p v-else-if="!solution && !error" class="product-note">{{ task.status === 'running' ? '任务运行中，完成后可检查成果。' : '尚未检查成果。' }}</p>
      <ul v-if="solution?.issues.length" class="product-error"><li v-for="issue in solution.issues" :key="issue">{{ issue }}</li></ul>
      <template v-if="solution?.available">
        <dl class="product-facts"><div><dt>方案</dt><dd>{{ selectedNodeLabel }}</dd></div><div><dt>评价指标</dt><dd>{{ protocol?.metric_name || '未记录' }} · {{ protocol?.maximize === true ? '越高越好' : protocol?.maximize === false ? '越低越好' : '方向未记录' }}</dd></div><div><dt>评价范围</dt><dd>{{ protocol?.horizon || protocol?.evaluation_count || '见任务评价标准' }}</dd></div></dl>
        <p class="product-note">{{ solution.notice }}</p><p class="product-note">{{ solution.portability === 'wrapper_present' ? '包含可迁移入口与实现身份；仍需匹配依赖环境。' : '历史方案：未识别到标准迁移入口，移动后需要验证绝对路径与依赖。' }}</p>
        <p>选定节点记录的成绩：<strong>{{ selectedNode?.metric ?? '未在当前快照中找到，请查看报告与包内 metric.txt' }}</strong></p>
        <div class="product-actions"><button class="command primary" :disabled="!solution.exportable || busy" @click="download">导出方案包</button><button class="command" @click="openDirectory">打开方案目录</button><button v-if="task.auto_ml_log_dir && task.status !== 'running'" class="command" @click="$emit('report')">补充 / 更新报告</button></div>
        <details v-if="solution.trial_ready"><summary>试算</summary><p>使用当前方案对一组输入进行本地预测或求解。试算结果单独保存，不会改写搜索成绩。</p><div class="trial-form"><label>输入形式<select v-model="trialMode"><option value="json">业务数据</option><option value="csv">CSV 表格</option></select></label><label v-if="trialMode === 'json'">输入数据<textarea v-model="trialJson" rows="6" spellcheck="false" /></label><label v-else>CSV 文件路径<input v-model="trialCsv" :placeholder="`${pathName(task.input_root)} 内的文件`" /><small>{{ task.input_root }}</small></label><label>执行超时（秒）<input v-model.number="trialTimeout" type="number" min="1" max="120" /></label></div><p class="product-note">JSON 最大 1 MiB，CSV 最大 16 MiB。需要 GPU 或专用文件接口时，请导出方案包后运行。</p><button class="command primary" :disabled="trialBusy || busy" @click="runTrial">{{ trialBusy ? '正在本机试算…' : '运行试算' }}</button><template v-if="trialResult"><p>{{ trialResult.scope }}</p><dl class="trial-result-grid"><div v-for="row in trialRows" :key="row.label"><dt>{{ row.label }}</dt><dd>{{ row.value }}</dd></div></dl><details><summary>查看完整返回数据</summary><pre>{{ JSON.stringify(trialResult.result, null, 2) }}</pre></details><button class="command" @click="saveTrial">保存试算结果</button></template></details>
        <p v-else class="product-note">网页试算暂不可用：需要模型齐全、实现校验通过并带可迁移入口的方案包。历史方案可先导出，按接口说明调用。</p>
        <details v-if="trials.length"><summary>试算记录（{{ trials.length }}）</summary><div class="product-actions"><button v-for="(trial, index) in trials" :key="trial.trial_id" class="command" @click="loadTrial(trial.trial_id)">{{ trialTitle(trial, index) }}</button></div><template v-if="trialResult"><dl class="trial-result-grid"><div v-for="row in trialRows" :key="row.label"><dt>{{ row.label }}</dt><dd>{{ row.value }}</dd></div></dl><details><summary>查看完整返回数据</summary><pre>{{ JSON.stringify(trialResult.result, null, 2) }}</pre></details><button class="command" @click="saveTrial">下载所选记录</button></template></details>
        <details><summary>运行说明与验证记录</summary><p>预测或求解使用当前模型，不会重新训练。输入字段、时间范围和输出格式以任务说明为准。</p><details v-if="solution.usage"><summary>查看调用说明</summary><pre>{{ solution.usage }}</pre></details><details v-if="Object.keys(solution.verification || {}).length"><summary>查看已保存的验证记录</summary><pre>{{ JSON.stringify(solution.verification, null, 2) }}</pre></details><p v-else>没有独立推理或重训验证记录。</p></details>
        <details><summary>技术详情与文件清单</summary><p v-if="solution.manifest?.entrypoint">方案入口：<code>{{ solution.manifest.entrypoint }}</code></p><p v-if="protocol?.contract_id">评价合同编号：<code>{{ protocol.contract_id }}</code></p><ul><li v-for="file in solution.files" :key="file.path"><code>{{ file.path }}</code> · {{ (file.size / 1024).toFixed(1) }} KiB</li></ul></details>
      </template>
    </section>
  </div>
</template>
<style scoped>
.trial-result-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0 24px; margin: 12px 0; }
.trial-result-grid > div { min-width: 0; padding: 9px 0; border-bottom: 1px solid var(--line); }
.trial-result-grid dt { color: #68756d; font-size: 12px; }
.trial-result-grid dd { margin: 4px 0 0; overflow-wrap: anywhere; }
.product-panel details details { border-top: 0; padding: 8px 0; }
@media (max-width: 600px) { .trial-result-grid { grid-template-columns: 1fr; } }
</style>
