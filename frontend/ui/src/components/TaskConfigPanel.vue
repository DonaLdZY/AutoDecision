<script setup lang="ts">
import { computed, reactive, shallowRef, watch } from 'vue'
import type { SnapshotPayload, Task, TaskConfig } from '../types'
import { cloneDeep } from '../utils/clone'
import DirectoryPicker from './DirectoryPicker.vue'
import TaskResourceSettings from './TaskResourceSettings.vue'
import AutoRealizeSettings from './AutoRealizeSettings.vue'
import AutoMLSettings from './AutoMLSettings.vue'
import AutoReportSettings from './AutoReportSettings.vue'
import TaskActionPanel from './TaskActionPanel.vue'
import { api } from '../api'
import { normalizeTaskResources } from '../utils/taskResources'
import { normalizeAutoReportConfig } from '../utils/autoReport'

const props = defineProps<{
  task: Task
  snapshot?: SnapshotPayload
  isDirty?: boolean
}>()

const emit = defineEmits<{
  updateConfig: [taskId: string, config: TaskConfig]
  restoreDefaults: [taskId: string]
  save: [taskId: string]
  runAutoRealize: [taskId: string]
  runAutoML: [taskId: string]
  continueAutoML: [taskId: string]
  runReport: [taskId: string]
  runTask: [taskId: string]
  resumeTask: [taskId: string]
  stop: [taskId: string]
  refresh: [taskId: string]
}>()

const subTab = reactive({ key: 'basic' })
const localConfig = reactive<TaskConfig>(cloneDeep(props.task.config))

function normalizeLocalConfig() {
  localConfig.resources = normalizeTaskResources(localConfig.resources)
  localConfig.output_language = localConfig.output_language === 'en' ? 'en' : 'zh'
  localConfig.auto_ml.engine = 'mlevolve'
  localConfig.auto_ml.enabled = true
  localConfig.auto_report = normalizeAutoReportConfig(localConfig.auto_report)
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
  localConfig.auto_ml.engine = 'mlevolve'
  localConfig.auto_ml.enabled = true
  emit('updateConfig', props.task.id, cloneDeep(localConfig))
}

const canStop = computed(() => props.task.status === 'running')
const canOpenRunDir = computed(() => !!props.task.run_dir)
const hasRequiredBasics = computed(() => (
  localConfig.input_root.trim().length > 0 && localConfig.task_name.trim().length > 0
))
const canRunAutoRealize = computed(() => props.task.status !== 'running' && hasRequiredBasics.value)
const canRunAutoML = computed(() => props.task.status !== 'running' && hasRequiredBasics.value)
const canContinueAutoML = computed(() => (
  props.task.status !== 'running'
  && !!props.task.auto_ml_log_dir
  && !!props.task.auto_ml_workspace_dir
))
const canRunReport = computed(() => (
  props.task.status !== 'running'
  && localConfig.auto_report.enabled
  && !!props.task.auto_ml_log_dir
  && !!props.task.auto_ml_workspace_dir
))
const canRunTask = computed(() => props.task.status !== 'running' && hasRequiredBasics.value)
const isResumableInterruption = computed(() => props.task.status === 'interrupted_resumable')
const canResumeTask = computed(() => (
  hasRequiredBasics.value
  && ['stopped', 'interrupted_resumable', 'interrupted_incomplete'].includes(String(props.task.status))
))
const currentStateStatus = computed(() => {
  const status = props.snapshot?.auto_realize?.current_state?.status
  return typeof status === 'string' ? status : '-'
})

const taskStatusLabel = computed(() => {
  const labels: Record<string, string> = {
    idle: '等待',
    running: '运行中',
    completed: '已完成',
    failed: '失败',
    stopped: '已停止',
    interrupted_resumable: '已中断，可恢复',
    interrupted_incomplete: '中断未完整',
  }
  return labels[props.task.status] ?? props.task.status
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
const nativePickerPending = shallowRef(false)
const pickerMessage = shallowRef('')
const pickerMessageKind = shallowRef<'info' | 'warning' | 'error'>('info')

const pickerInitialPath = computed(() => {
  if (dirPicker.mode === 'input') return localConfig.input_root
  return localConfig.output_root
})

const pickerTitle = computed(() => (dirPicker.mode === 'input' ? '选择输入文件夹' : '选择输出文件夹'))

function openDirPicker(mode: 'input' | 'output') {
  if (nativePickerPending.value) return
  void openDirPickerAsync(mode)
}

async function openDirPickerAsync(mode: 'input' | 'output') {
  dirPicker.mode = mode
  nativePickerPending.value = true
  pickerMessageKind.value = 'info'
  pickerMessage.value = '正在打开系统目录选择器，请查看任务栏、Dock 或当前桌面...'
  const initial = mode === 'input' ? localConfig.input_root : localConfig.output_root
  const title = mode === 'input' ? '选择输入文件夹' : '选择输出文件夹'
  try {
    const res = await api.pickDirectory(initial, title)
    if (res.ok && res.path) {
      onDirSelected(res.path)
      return
    }
    if (res.reason === 'cancelled') {
      pickerMessageKind.value = 'info'
      pickerMessage.value = '已取消目录选择。'
      return
    }
    const detail = [res.method, res.reason, res.raw_path || ''].filter(Boolean).join(' | ')
    pickerMessageKind.value = 'warning'
    pickerMessage.value = `系统目录选择器不可用，已切换内置选择器（${detail || res.platform || 'unknown'}）`
  } catch (error) {
    pickerMessageKind.value = 'error'
    pickerMessage.value = `系统目录选择器调用失败，已切换内置选择器：${(error as Error).message || String(error)}`
  } finally {
    nativePickerPending.value = false
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
  pickerMessage.value = ''
}

async function openRunDirectory() {
  if (!props.task.run_dir) return
  await api.openDirectory(props.task.run_dir)
}

</script>

<template>
  <section class="task-panel">
    <div class="panel-header">
      <div>
        <h2>任务配置</h2>
        <p>配置完成后启动：数据认知 → 任务定义 → AutoML → AutoReport</p>
      </div>
      <div class="panel-header-actions">
        <button
          type="button"
          class="reset-config-btn"
          :disabled="task.status === 'running'"
          title="将当前表单恢复为系统默认配置"
          @click="emit('restoreDefaults', task.id)"
        >
          <span class="reset-config-icon" aria-hidden="true">↺</span>
          还原默认配置
        </button>
        <div class="status-block">
          <span v-if="props.isDirty" class="draft-pill">未保存草稿</span>
          <span class="status-pill" :class="task.status">{{ taskStatusLabel }}</span>
          <span class="phase-pill">phase: {{ task.phase }}</span>
        </div>
      </div>
    </div>

    <div class="sub-tabs">
      <button :class="{ active: subTab.key === 'basic' }" @click="subTab.key = 'basic'">基础配置</button>
      <button :class="{ active: subTab.key === 'resources' }" @click="subTab.key = 'resources'">任务资源</button>
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
          <button
            type="button"
            class="path-btn"
            :disabled="nativePickerPending"
            :aria-busy="nativePickerPending && dirPicker.mode === 'input'"
            @click="openDirPicker('input')"
          >
            {{ nativePickerPending && dirPicker.mode === 'input' ? '正在打开...' : '浏览...' }}
          </button>
        </div>
      </label>
      <label>
        <span>输出文件夹</span>
        <div class="path-input-row">
          <input v-model="localConfig.output_root" @input="propagateConfig" placeholder="默认 AutoDecision/runs" />
          <button
            type="button"
            class="path-btn"
            :disabled="nativePickerPending"
            :aria-busy="nativePickerPending && dirPicker.mode === 'output'"
            @click="openDirPicker('output')"
          >
            {{ nativePickerPending && dirPicker.mode === 'output' ? '正在打开...' : '浏览...' }}
          </button>
        </div>
      </label>
      <div
        v-if="pickerMessage"
        class="picker-msg"
        :class="pickerMessageKind"
        role="status"
        aria-live="polite"
      >
        {{ pickerMessage }}
      </div>
      <label>
        <span>任务需求</span>
        <textarea v-model="localConfig.auto_realize.task_hint" @input="propagateConfig" rows="4" placeholder="例如：预测下个月销量" />
      </label>
      <label>
        <span>模型输出语言</span>
        <select v-model="localConfig.output_language" @change="propagateConfig">
          <option value="zh">中文</option>
          <option value="en">English</option>
        </select>
        <small>统一约束 AutoRealize、MLEvolve 和 AutoReport 的模型输出。</small>
      </label>
    </div>

    <div class="sub-body" v-else-if="subTab.key === 'resources'">
      <TaskResourceSettings
        v-model="localConfig.resources"
        :disabled="task.status === 'running'"
        @update:model-value="propagateConfig"
      />
    </div>

    <div class="sub-body settings-body" v-else-if="subTab.key === 'autorealize'">
      <AutoRealizeSettings
        v-model="localConfig.auto_realize"
        :disabled="task.status === 'running'"
        @update:model-value="propagateConfig"
      />
    </div>

    <div class="sub-body settings-body" v-else-if="subTab.key === 'automl'">
      <AutoMLSettings
        v-model="localConfig.auto_ml"
        :disabled="task.status === 'running'"
        @update:model-value="propagateConfig"
      />
    </div>

    <div class="sub-body settings-body" v-else>
      <AutoReportSettings
        v-model="localConfig.auto_report"
        :disabled="task.status === 'running'"
        @update:model-value="propagateConfig"
      />
    </div>

    <TaskActionPanel
      :running="task.status === 'running'"
      :can-open-directory="canOpenRunDir"
      :can-run-auto-realize="canRunAutoRealize"
      :can-run-auto-m-l="canRunAutoML"
      :can-continue-auto-m-l="canContinueAutoML"
      :can-run-report="canRunReport"
      :can-run-task="canRunTask"
      :can-resume-task="canResumeTask"
      :can-stop-task="canStop"
      @save="emit('save', task.id)"
      @refresh="emit('refresh', task.id)"
      @open-directory="openRunDirectory"
      @run-auto-realize="emit('runAutoRealize', task.id)"
      @run-auto-m-l="emit('runAutoML', task.id)"
      @continue-auto-m-l="emit('continueAutoML', task.id)"
      @run-report="emit('runReport', task.id)"
      @run-task="emit('runTask', task.id)"
      @resume-task="emit('resumeTask', task.id)"
      @stop-task="emit('stop', task.id)"
    />

    <div class="meta-row">
      <span v-if="isResumableInterruption" class="resume-ready">已中断，搜索树与 Top-K 已保存，可继续搜索或生成报告</span>
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
  </section>
</template>

<style scoped>
.task-panel {
  width: 100%;
  min-width: 0;
  box-sizing: border-box;
  padding: 18px;
  background: #f5f8ff;
  border-radius: 8px;
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
  flex-wrap: wrap;
  justify-content: flex-end;
}

.panel-header-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 10px;
  flex-wrap: wrap;
}

.reset-config-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  min-height: 32px;
  border: 1px solid #b8cdee;
  border-radius: 8px;
  padding: 6px 10px;
  background: #eef4ff;
  color: #234c82;
  cursor: pointer;
  font-size: 13px;
}

.reset-config-btn:hover:not(:disabled) {
  border-color: #7fa5d8;
  background: #e2edfc;
}

.reset-config-btn:disabled {
  cursor: not-allowed;
  opacity: 0.5;
}

.reset-config-icon {
  font-size: 17px;
  line-height: 1;
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

.status-pill.interrupted_resumable {
  background: #fff0bf;
  color: #755300;
}

.status-pill.interrupted_incomplete {
  background: #ffdedd;
  color: #8a2020;
}

.sub-tabs {
  display: flex;
  flex-wrap: wrap;
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

.settings-body {
  display: block;
  min-width: 0;
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

label small {
  color: #647991;
  line-height: 1.4;
}

input,
select,
textarea {
  width: 100%;
  min-width: 0;
  box-sizing: border-box;
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

.path-btn:disabled {
  cursor: wait;
  opacity: 0.72;
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

.picker-msg.info {
  color: #244d78;
  background: #eaf3ff;
  border-color: #b8d3f2;
}

.picker-msg.error {
  color: #8b2525;
  background: #ffeded;
  border-color: #efb5b5;
}

@media (max-width: 900px) {
  .grid2 {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 600px) {
  .task-panel {
    padding: 12px;
  }

  .panel-header {
    align-items: flex-start;
    flex-direction: column;
  }

  .status-block {
    justify-content: flex-start;
  }

  .panel-header-actions {
    justify-content: flex-start;
  }

  .sub-tabs {
    gap: 6px;
  }

  .sub-tabs button {
    flex: 1 1 auto;
  }
}
</style>
