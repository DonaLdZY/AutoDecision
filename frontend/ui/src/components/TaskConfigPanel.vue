<script setup lang="ts">
import { computed, reactive, watch } from 'vue'
import type { SnapshotPayload, Task, TaskConfig } from '../types'
import { cloneDeep } from '../utils/clone'
import DirectoryPicker from './DirectoryPicker.vue'
import { api } from '../api'

const props = defineProps<{
  task: Task
  snapshot?: SnapshotPayload
  isDirty?: boolean
}>()

const emit = defineEmits<{
  updateConfig: [taskId: string, config: TaskConfig]
  save: [taskId: string]
  start: [taskId: string]
  rerunAutoRealize: [taskId: string]
  rerunAutoML: [taskId: string]
  startAutoML: [taskId: string]
  rerunAutoReport: [taskId: string]
  rerunFull: [taskId: string]
  resume: [taskId: string]
  stop: [taskId: string]
  remove: [taskId: string]
  refresh: [taskId: string]
}>()

const subTab = reactive({ key: 'basic' })
const localConfig = reactive<TaskConfig>(cloneDeep(props.task.config))

function normalizeLocalConfig() {
  localConfig.auto_realize.run_data_cognition = true
  localConfig.auto_realize.run_task_definition = true
  localConfig.auto_realize.enable_question_investigator = localConfig.auto_realize.enable_question_investigator !== false
  localConfig.auto_realize.prefer_original_description = true
  localConfig.auto_realize.direct_automl_from_description = false
  localConfig.auto_realize.auto_generate_predict_split = false
  localConfig.auto_realize.cognition_workers = localConfig.auto_realize.llm_concurrency
  localConfig.auto_ml.enabled = true
  localConfig.auto_ml.preprocess_data = true
  localConfig.auto_ml.data_preview = true
}

normalizeLocalConfig()

watch(
  () => props.task.id,
  () => {
    Object.assign(localConfig, cloneDeep(props.task.config))
    normalizeLocalConfig()
    subTab.key = 'basic'
  },
)

watch(
  () => props.task.config,
  (cfg) => {
    Object.assign(localConfig, cloneDeep(cfg))
    normalizeLocalConfig()
  },
  { deep: true },
)

function propagateConfig() {
  localConfig.auto_report.use_llm = true
  localConfig.auto_realize.run_data_cognition = true
  localConfig.auto_realize.run_task_definition = true
  localConfig.auto_realize.run_data_cleaning = false
  localConfig.auto_realize.offline = false
  localConfig.auto_realize.enable_question_investigator = localConfig.auto_realize.enable_question_investigator !== false
  localConfig.auto_realize.prefer_original_description = true
  localConfig.auto_realize.direct_automl_from_description = false
  localConfig.auto_realize.auto_generate_predict_split = false
  localConfig.auto_realize.cognition_workers = localConfig.auto_realize.llm_concurrency
  localConfig.auto_realize.no_knowledge = false
  localConfig.auto_realize.no_telemetry = false
  localConfig.auto_realize.no_llm_cache = false
  localConfig.auto_ml.enabled = true
  localConfig.auto_ml.preprocess_data = true
  localConfig.auto_ml.data_preview = true
  emit('updateConfig', props.task.id, cloneDeep(localConfig))
}

const canStart = computed(() => props.task.status !== 'running' && localConfig.input_root.trim().length > 0 && localConfig.task_name.trim().length > 0)
const canStop = computed(() => props.task.status === 'running')
const canOpenRunDir = computed(() => !!props.task.run_dir)
const canFullRerun = computed(() => props.task.status !== 'running' && localConfig.input_root.trim().length > 0 && localConfig.task_name.trim().length > 0)
const canRerunAutoRealize = computed(() => props.task.status !== 'running' && localConfig.input_root.trim().length > 0 && localConfig.task_name.trim().length > 0)
const canRerunAutoML = computed(() => {
  if (props.task.status === 'running') return false
  if (!props.task.run_dir) return false
  return true
})
const canStartAutoML = computed(() => {
  if (props.task.status === 'running') return false
  return localConfig.input_root.trim().length > 0 && localConfig.task_name.trim().length > 0
})
const canRerunAutoReport = computed(() => props.task.status !== 'running' && localConfig.auto_report.enabled && !!props.task.run_dir)
const canResume = computed(() => {
  if (props.task.status === 'running') return false
  if (!localConfig.input_root.trim() || !localConfig.task_name.trim()) return false
  return ['failed', 'stopped'].includes(String(props.task.status))
})
const autoMlEngine = computed(() => String(localConfig.auto_ml.engine || 'mlevolve').toLowerCase())
const embeddingEnabled = computed(() => !!localConfig.auto_ml.use_global_memory)
const embeddingMode = computed({
  get: () => (String(localConfig.auto_ml.memory_embedding_backend || '').toLowerCase() === 'local' ? 'local' : 'remote'),
  set: (mode: 'local' | 'remote') => {
    localConfig.auto_ml.memory_embedding_backend = mode === 'local' ? 'local' : 'openai'
    propagateConfig()
  },
})

const currentStateStatus = computed(() => {
  const status = props.snapshot?.auto_realize?.current_state?.status
  return typeof status === 'string' ? status : '-'
})

function joinPath(base: string, sub: string) {
  if (!base) return ''
  if (base.endsWith('/') || base.endsWith('\\')) return `${base}${sub}`
  if (base.includes('\\') && !base.includes('/')) return `${base}\\${sub}`
  return `${base}/${sub}`
}

const autoRealizeDirPath = computed(() => (props.task.run_dir ? joinPath(props.task.run_dir, 'autorealize') : ''))
const autoMlDirPath = computed(() => (props.task.run_dir ? joinPath(props.task.run_dir, 'automl') : ''))

const dirPicker = reactive({
  visible: false,
  mode: 'input' as 'input' | 'output',
})
const pickerMessage = reactive({
  text: '',
})

const pickerInitialPath = computed(() => {
  if (dirPicker.mode === 'input') return localConfig.input_root
  return localConfig.output_root
})

const pickerTitle = computed(() => (dirPicker.mode === 'input' ? '选择输入文件夹' : '选择输出文件夹'))

function openDirPicker(mode: 'input' | 'output') {
  void openDirPickerAsync(mode)
}

async function openDirPickerAsync(mode: 'input' | 'output') {
  dirPicker.mode = mode
  pickerMessage.text = ''
  const initial = mode === 'input' ? localConfig.input_root : localConfig.output_root
  const title = mode === 'input' ? '选择输入文件夹' : '选择输出文件夹'
  try {
    const res = await api.pickDirectory(initial, title)
    if (res.ok && res.path) {
      onDirSelected(res.path)
      return
    }
    if (res.reason === 'cancelled') {
      return
    }
    const detail = [res.method, res.reason, res.raw_path || ''].filter(Boolean).join(' | ')
    pickerMessage.text = `系统目录选择器不可用，已切换内置选择器（${detail}）`
  } catch {
    pickerMessage.text = '系统目录选择器调用失败，已切换内置选择器'
  }
  dirPicker.visible = true
}

function onDirSelected(path: string) {
  if (dirPicker.mode === 'input') {
    localConfig.input_root = path
  } else {
    localConfig.output_root = path
  }
  propagateConfig()
  dirPicker.visible = false
  pickerMessage.text = ''
}

async function openRunDirectory() {
  if (!props.task.run_dir) return
  await api.openDirectory(props.task.run_dir)
}

function onToggleEmbedding() {
  if (localConfig.auto_ml.use_global_memory && !localConfig.auto_ml.memory_embedding_backend) {
    localConfig.auto_ml.memory_embedding_backend = 'openai'
  }
  propagateConfig()
}

</script>

<template>
  <section class="task-panel">
    <div class="panel-header">
      <div>
        <h2>任务配置</h2>
        <p>配置完成后启动：数据认知 → 任务定义 → AutoML → AutoReport</p>
      </div>
      <div class="status-block">
        <span v-if="props.isDirty" class="draft-pill">未保存草稿</span>
        <span class="status-pill" :class="task.status">{{ task.status }}</span>
        <span class="phase-pill">phase: {{ task.phase }}</span>
      </div>
    </div>

    <div class="sub-tabs">
      <button :class="{ active: subTab.key === 'basic' }" @click="subTab.key = 'basic'">基础配置</button>
      <button :class="{ active: subTab.key === 'autorealize' }" @click="subTab.key = 'autorealize'">AutoRealize</button>
      <button :class="{ active: subTab.key === 'automl' }" @click="subTab.key = 'automl'">AutoML</button>
      <button :class="{ active: subTab.key === 'report' }" @click="subTab.key = 'report'">AutoReport</button>
    </div>

    <div class="sub-body" v-if="subTab.key === 'basic'">
      <label>
        <span>任务名</span>
        <input v-model="localConfig.task_name" @input="propagateConfig" placeholder="例如 sale_forecast_apr" />
      </label>
      <label>
        <span>输入文件夹</span>
        <div class="path-input-row">
          <input v-model="localConfig.input_root" @input="propagateConfig" placeholder="数据文件夹路径" />
          <button type="button" class="path-btn" @click="openDirPicker('input')">浏览...</button>
        </div>
      </label>
      <label>
        <span>输出文件夹</span>
        <div class="path-input-row">
          <input v-model="localConfig.output_root" @input="propagateConfig" placeholder="默认 AutoDecision/runs" />
          <button type="button" class="path-btn" @click="openDirPicker('output')">浏览...</button>
        </div>
      </label>
      <label>
        <span>任务自然语言需求</span>
        <textarea v-model="localConfig.auto_realize.task_hint" @input="propagateConfig" rows="4" placeholder="一句话任务需求或文档摘要" />
      </label>
    </div>

    <div class="sub-body" v-else-if="subTab.key === 'autorealize'">
      <div class="grid2">
        <label><span>LLM超时(秒)</span><input type="number" v-model.number="localConfig.auto_realize.llm_timeout" @input="propagateConfig" /></label>
        <label><span>LLM并发</span><input type="number" v-model.number="localConfig.auto_realize.llm_concurrency" @input="propagateConfig" /></label>
      </div>
      <div class="switches">
        <label><input type="checkbox" v-model="localConfig.auto_realize.enable_question_investigator" @change="propagateConfig" /> 启用 Question-Driven Investigator</label>
        <label><input type="checkbox" v-model="localConfig.auto_realize.enable_fewshot" @change="propagateConfig" /> 启用 few-shot 示例</label>
        <label><input type="checkbox" v-model="localConfig.auto_realize.generate_sample_submission" @change="propagateConfig" /> 生成 sample_submission.csv</label>
        <label><input type="checkbox" v-model="localConfig.auto_realize.enable_vllm" @change="propagateConfig" /> 启用 VLLM 视觉模型</label>
      </div>
    </div>

    <div class="sub-body" v-else-if="subTab.key === 'automl'">
      <label>
        <span>AutoML 引擎</span>
        <select v-model="localConfig.auto_ml.engine" @change="propagateConfig">
          <option value="ml_master">ML-Master</option>
          <option value="mlevolve">MLEvolve</option>
        </select>
      </label>
      <div class="grid2">
        <label><span>搜索步数</span><input type="number" v-model.number="localConfig.auto_ml.steps" @input="propagateConfig" /></label>
        <label><span>总时限(秒)</span><input type="number" v-model.number="localConfig.auto_ml.time_limit_secs" @input="propagateConfig" /></label>
        <label><span>并行搜索数</span><input type="number" v-model.number="localConfig.auto_ml.parallel_search_num" @input="propagateConfig" /></label>
        <label><span>K折验证</span><input type="number" v-model.number="localConfig.auto_ml.k_fold_validation" @input="propagateConfig" /></label>
        <label v-if="autoMlEngine === 'mlevolve'"><span>初始草稿数</span><input type="number" v-model.number="localConfig.auto_ml.initial_drafts" @input="propagateConfig" /></label>
        <label v-if="autoMlEngine === 'mlevolve'"><span>执行超时(秒)</span><input type="number" v-model.number="localConfig.auto_ml.exec_timeout_secs" @input="propagateConfig" /></label>
        <label><span>最大草稿数</span><input type="number" v-model.number="localConfig.auto_ml.search_num_drafts" @input="propagateConfig" /></label>
        <label><span>num_bugs</span><input type="number" v-model.number="localConfig.auto_ml.search_num_bugs" @input="propagateConfig" /></label>
        <label><span>num_improves</span><input type="number" v-model.number="localConfig.auto_ml.search_num_improves" @input="propagateConfig" /></label>
        <label><span>探索常数C</span><input type="number" step="0.001" v-model.number="localConfig.auto_ml.exploration_constant" @input="propagateConfig" /></label>
      </div>
      <label>
        <span>AutoML Goal(可选)</span>
        <input v-model="localConfig.auto_ml.goal" @input="propagateConfig" placeholder="补充目标说明，可空" />
      </label>
      <label>
        <span>AutoML Eval(可选)</span>
        <input v-model="localConfig.auto_ml.eval" @input="propagateConfig" placeholder="补充评估约束，可空" />
      </label>
      <div class="switches">
        <label v-if="autoMlEngine !== 'mlevolve'"><input type="checkbox" v-model="localConfig.auto_ml.check_format" @change="propagateConfig" /> 检查submission格式</label>
        <label v-if="autoMlEngine !== 'mlevolve'"><input type="checkbox" v-model="localConfig.auto_ml.expose_prediction" @change="propagateConfig" /> 暴露predict函数</label>
        <label v-if="autoMlEngine === 'mlevolve'"><input type="checkbox" v-model="localConfig.auto_ml.generate_submission" @change="propagateConfig" /> 生成最终 submission.csv</label>
        <label v-if="autoMlEngine !== 'mlevolve'"><input type="checkbox" v-model="localConfig.auto_ml.steerable_reasoning" @change="propagateConfig" /> steerable reasoning</label>
        <label v-if="autoMlEngine === 'mlevolve'"><input type="checkbox" v-model="localConfig.auto_ml.copy_data" @change="propagateConfig" /> 复制数据到工作区</label>
        <label v-if="autoMlEngine === 'mlevolve'"><input type="checkbox" v-model="localConfig.auto_ml.use_diff_mode" @change="propagateConfig" /> 使用 diff patch 模式</label>
        <label v-if="autoMlEngine === 'mlevolve'"><input type="checkbox" v-model="localConfig.auto_ml.check_data_leakage" @change="propagateConfig" /> 检查数据泄漏</label>
        <label v-if="autoMlEngine === 'mlevolve'"><input type="checkbox" v-model="localConfig.auto_ml.use_global_memory" @change="onToggleEmbedding" /> 启用 Embedding 记忆</label>
        <label v-if="autoMlEngine === 'mlevolve'"><input type="checkbox" v-model="localConfig.auto_ml.use_coldstart" @change="propagateConfig" /> 启用 cold-start</label>
        <label v-if="autoMlEngine === 'mlevolve'"><input type="checkbox" v-model="localConfig.auto_ml.use_grading_server" @change="propagateConfig" /> 启用 grading server</label>
      </div>
      <div v-if="autoMlEngine === 'mlevolve' && embeddingEnabled" class="grid2">
        <label><span>Memory 相似度阈值</span><input type="number" step="0.01" v-model.number="localConfig.auto_ml.memory_similarity_threshold" @input="propagateConfig" /></label>
        <label>
          <span>Embedding 类型</span>
          <select v-model="embeddingMode">
            <option value="remote">远程 API</option>
            <option value="local">本地模型</option>
          </select>
        </label>
        <label v-if="embeddingMode === 'local'"><span>Embedding Device</span><input v-model="localConfig.auto_ml.memory_embedding_device" @input="propagateConfig" placeholder="cpu / cuda" /></label>
        <label v-if="embeddingMode === 'local'"><span>Embedding Model Path</span><input v-model="localConfig.auto_ml.memory_embedding_model_path" @input="propagateConfig" placeholder="例如 BAAI/bge-base-en-v1.5 或本地路径" /></label>
      </div>
    </div>

    <div class="sub-body" v-else>
      <div class="switches">
        <label><input type="checkbox" v-model="localConfig.auto_report.enabled" @change="propagateConfig" /> 启用 AutoReport 报告生成</label>
        <label><input type="checkbox" v-model="localConfig.auto_report.include_raw_logs" @change="propagateConfig" /> 报告包含原始日志摘录</label>
        <label><input type="checkbox" v-model="localConfig.auto_report.include_code_excerpt" @change="propagateConfig" /> 报告包含最优代码摘录</label>
        <label class="disabled-hint"><input type="checkbox" checked disabled /> LLM 文章生成(必需，未配置全局反馈/编码模型会启动失败)</label>
      </div>
      <div class="grid2">
        <label>
          <span>报告受众</span>
          <select v-model="localConfig.auto_report.audience" @change="propagateConfig">
            <option value="technical">technical 技术复现</option>
            <option value="executive">executive 管理摘要</option>
            <option value="delivery">delivery 交付验收</option>
          </select>
        </label>
        <label>
          <span>报告语言</span>
          <select v-model="localConfig.auto_report.language" @change="propagateConfig">
            <option value="zh-CN">中文</option>
            <option value="en-US">English</option>
          </select>
        </label>
      </div>
    </div>

    <div class="footer-actions">
      <button @click="emit('save', task.id)">保存配置</button>
      <button @click="emit('refresh', task.id)">刷新状态</button>
      <button @click="openRunDirectory" :disabled="!canOpenRunDir">打开任务目录</button>
      <button class="danger-soft" @click="emit('rerunFull', task.id)" :disabled="!canFullRerun">完全重跑</button>
      <button class="primary-soft" @click="emit('rerunAutoRealize', task.id)" :disabled="!canRerunAutoRealize">仅重跑AutoRealize</button>
      <button class="primary-soft direct" @click="emit('startAutoML', task.id)" :disabled="!canStartAutoML">直接跑AutoML</button>
      <button class="primary-soft" @click="emit('rerunAutoML', task.id)" :disabled="!canRerunAutoML">仅重跑AutoML</button>
      <button class="primary-soft" @click="emit('rerunAutoReport', task.id)" :disabled="!canRerunAutoReport">仅重跑AutoReport</button>
      <button class="primary-soft" @click="emit('resume', task.id)" :disabled="!canResume">继续任务</button>
      <button class="danger" @click="emit('remove', task.id)" :disabled="task.status === 'running'">删除任务</button>
      <button class="primary" @click="emit('start', task.id)" :disabled="!canStart">启动任务</button>
      <button class="warn" @click="emit('stop', task.id)" :disabled="!canStop">终止任务</button>
    </div>

    <div class="meta-row">
      <span>AutoRealize current_state: {{ currentStateStatus }}</span>
      <span v-if="task.run_dir">run_dir: {{ task.run_dir }}</span>
      <span v-if="autoRealizeDirPath">step1-3_dir: {{ autoRealizeDirPath }}</span>
      <span v-if="autoMlDirPath">automl_dir: {{ autoMlDirPath }}</span>
      <span v-if="task.report_dir">report_dir: {{ task.report_dir }}</span>
      <span v-if="task.auto_ml_log_dir">automl_log_dir: {{ task.auto_ml_log_dir }}</span>
      <span v-if="task.auto_ml_workspace_dir">automl_workspace_dir: {{ task.auto_ml_workspace_dir }}</span>
      <span v-if="task.last_error" class="error">error: {{ task.last_error }}</span>
    </div>

    <DirectoryPicker
      :visible="dirPicker.visible"
      :initial-path="pickerInitialPath"
      :title="pickerTitle"
      @close="dirPicker.visible = false"
      @select="onDirSelected"
    />
    <div v-if="pickerMessage.text" class="picker-msg">{{ pickerMessage.text }}</div>
  </section>
</template>

<style scoped>
.task-panel {
  padding: 18px;
  background: #f5f8ff;
  border-radius: 14px;
  border: 1px solid #d7e2f6;
}

.panel-header {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 12px;
}

.panel-header h2 {
  margin: 0;
  font-size: 20px;
}

.panel-header p {
  margin: 4px 0 0;
  color: #476084;
  font-size: 13px;
}

.status-block {
  display: flex;
  gap: 8px;
  align-items: center;
}

.status-pill,
.phase-pill {
  padding: 4px 8px;
  border-radius: 8px;
  font-size: 12px;
  background: #dde8ff;
  color: #1c3159;
}

.draft-pill {
  padding: 4px 8px;
  border-radius: 8px;
  font-size: 12px;
  background: #ffe6a8;
  color: #6f4c02;
}

.status-pill.running {
  background: #d6ffe9;
  color: #15633f;
}

.status-pill.failed {
  background: #ffdedd;
  color: #8a2020;
}

.status-pill.completed {
  background: #d9f1ff;
  color: #0d5370;
}

.sub-tabs {
  display: flex;
  gap: 8px;
  margin-bottom: 12px;
}

.sub-tabs button {
  border: 1px solid #b9cbed;
  background: #edf3ff;
  color: #183866;
  border-radius: 8px;
  padding: 6px 10px;
  cursor: pointer;
}

.sub-tabs .active {
  background: #1f4e8c;
  color: #fff;
  border-color: #1f4e8c;
}

.sub-body {
  display: grid;
  gap: 12px;
}

.grid2 {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}

label {
  display: grid;
  gap: 6px;
  font-size: 13px;
  color: #26416b;
}

input,
select,
textarea {
  border: 1px solid #c4d4ef;
  border-radius: 8px;
  padding: 8px 10px;
  font-size: 14px;
  background: #fff;
}

.path-input-row {
  display: grid;
  grid-template-columns: 1fr auto;
  gap: 8px;
}

.path-btn {
  border: 1px solid #b8cdee;
  border-radius: 8px;
  padding: 8px 10px;
  background: #eef4ff;
  cursor: pointer;
}

.switches {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
}

.switches label {
  display: flex;
  align-items: center;
  gap: 8px;
}

.disabled-hint {
  color: #9f5d1e;
}

.footer-actions {
  margin-top: 14px;
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.footer-actions button {
  border: 1px solid #b8cdee;
  border-radius: 8px;
  padding: 8px 12px;
  background: #f0f5ff;
  cursor: pointer;
}

.footer-actions .primary {
  background: #2464b8;
  color: #fff;
  border-color: #2464b8;
}

.footer-actions .primary-soft {
  background: #e6f0ff;
  color: #1b4f97;
  border-color: #9fbce9;
}

.footer-actions .danger-soft {
  background: #ffe8d9;
  color: #8c4b13;
  border-color: #efbf91;
}

.footer-actions .warn {
  background: #c9721f;
  color: #fff;
  border-color: #c9721f;
}

.footer-actions .danger {
  background: #bf4444;
  color: #fff;
  border-color: #bf4444;
}

.footer-actions button:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.meta-row {
  margin-top: 12px;
  font-size: 12px;
  color: #37517a;
  display: flex;
  gap: 14px;
  flex-wrap: wrap;
}

.meta-row .error {
  color: #9f2f2f;
}

.picker-msg {
  margin-top: 10px;
  font-size: 12px;
  color: #6b4f00;
  background: #fff3c4;
  border: 1px solid #efd681;
  border-radius: 8px;
  padding: 6px 10px;
}

@media (max-width: 900px) {
  .grid2,
  .switches {
    grid-template-columns: 1fr;
  }
}
</style>
