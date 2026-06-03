<script setup lang="ts">
import { computed, onMounted, onUnmounted, reactive, shallowRef } from 'vue'
import { api } from './api'
import AutoMLView from './components/AutoMLView.vue'
import DataCognitionView from './components/DataCognitionView.vue'
import GlobalSettingsDrawer from './components/GlobalSettingsDrawer.vue'
import TaskConfigPanel from './components/TaskConfigPanel.vue'
import TaskDefinitionView from './components/TaskDefinitionView.vue'
import TaskTabs from './components/TaskTabs.vue'
import WorkflowStepper, { type StepKey } from './components/WorkflowStepper.vue'
import { useTasks } from './composables/useTasks'
import type { GlobalSettings, Task, TaskConfig } from './types'
import { cloneDeep } from './utils/clone'

const {
  tasks,
  activeTaskId,
  activeTask,
  snapshots,
  error,
  refreshTasks,
  createTask,
  saveTask,
  deleteTask,
  startTask,
  rerunAutoML,
  rerunFull,
  resumeTask,
  stopTask,
  refreshSnapshot,
} = useTasks()

const settingsVisible = shallowRef(false)
const globalSettings = shallowRef<GlobalSettings | null>(null)
const message = shallowRef('')
const pollingTimer = shallowRef<number | null>(null)
const workingCopies = reactive<Record<string, Task>>({})
const dirtyTaskIds = reactive<Record<string, boolean>>({})
const activeStep = shallowRef<StepKey>('data_cognition')

const activeSnapshot = computed(() => {
  if (!activeTaskId.value) return undefined
  return snapshots[activeTaskId.value]
})

const activeWorkingTask = computed(() => {
  const task = activeTask.value
  if (!task) return null
  if (!workingCopies[task.id]) workingCopies[task.id] = cloneDeep(task)
  return workingCopies[task.id]
})

function syncWorkingCopies() {
  for (const task of tasks.value) {
    if (!workingCopies[task.id]) {
      workingCopies[task.id] = cloneDeep(task)
      dirtyTaskIds[task.id] = false
      continue
    }
    const target = workingCopies[task.id]
    target.id = task.id
    target.task_name = task.task_name
    target.input_root = task.input_root
    target.output_root = task.output_root
    target.created_at = task.created_at
    target.updated_at = task.updated_at
    target.status = task.status
    target.phase = task.phase
    target.run_dir = task.run_dir
    target.run_started_at = task.run_started_at
    target.auto_ml_log_dir = task.auto_ml_log_dir
    target.auto_ml_workspace_dir = task.auto_ml_workspace_dir
    target.last_error = task.last_error
    if (!dirtyTaskIds[task.id]) target.config = cloneDeep(task.config)
  }

  const ids = new Set(tasks.value.map((task) => task.id))
  for (const key of Object.keys(workingCopies)) {
    if (!ids.has(key)) {
      delete workingCopies[key]
      delete dirtyTaskIds[key]
    }
  }
}

async function loadGlobalSettings() {
  globalSettings.value = await api.getGlobalSettings()
}

async function openSettings() {
  try {
    await loadGlobalSettings()
    settingsVisible.value = true
  } catch (e) {
    message.value = `加载全局设置失败: ${(e as Error).message}`
    settingsVisible.value = false
  }
}

async function saveSettings(payload: GlobalSettings) {
  await api.saveGlobalSettings(payload)
  globalSettings.value = payload
  settingsVisible.value = false
  message.value = '全局设置已保存'
}

function onUpdateConfig(taskId: string, config: TaskConfig) {
  const target = workingCopies[taskId]
  if (!target) return
  target.config = cloneDeep(config)
  dirtyTaskIds[taskId] = true
}

async function onSaveTask(taskId: string) {
  const task = workingCopies[taskId]
  if (!task) return
  await saveTask(task)
  dirtyTaskIds[taskId] = false
  await refreshTasks()
  syncWorkingCopies()
  message.value = `任务 ${task.config.task_name} 已保存`
}

async function onStartTask(taskId: string) {
  const task = workingCopies[taskId]
  if (!task) return
  await onSaveTask(taskId)
  await startTask(taskId)
  await refreshSnapshot(taskId)
  message.value = '任务已启动'
}

async function onStopTask(taskId: string) {
  if (!window.confirm('确认终止任务吗？终止后如需继续，需要重新启动或重跑。')) return
  await stopTask(taskId)
  await refreshSnapshot(taskId)
  message.value = '任务已终止'
}

async function onRerunAutoML(taskId: string) {
  if (!window.confirm('确认仅重跑 AutoML 吗？这会复用 AutoRealize 已生成的输出。')) return
  const task = workingCopies[taskId]
  if (!task) return
  await onSaveTask(taskId)
  await rerunAutoML(taskId)
  await refreshSnapshot(taskId)
  message.value = '已启动仅重跑 AutoML'
}

async function onRerunFull(taskId: string) {
  if (!window.confirm('确认完全重跑该任务吗？这会清理当前任务目录下的已有结果，并按当前配置从头开始。')) return
  const task = workingCopies[taskId]
  if (!task) return
  await onSaveTask(taskId)
  await rerunFull(taskId)
  await refreshTasks()
  syncWorkingCopies()
  try {
    await refreshSnapshot(taskId)
  } catch {
    // cleanup + restart interval
  }
  message.value = '已按当前配置完全重跑任务'
}

async function onResumeTask(taskId: string) {
  const task = workingCopies[taskId]
  if (!task) return
  await onSaveTask(taskId)
  await resumeTask(taskId)
  await refreshTasks()
  syncWorkingCopies()
  try {
    await refreshSnapshot(taskId)
  } catch {
    // poll will retry
  }
  message.value = '已启动继续任务'
}

async function onDeleteTask(taskId: string) {
  if (!window.confirm('确认删除这个任务标签页吗？')) return
  await deleteTask(taskId)
  delete dirtyTaskIds[taskId]
  message.value = '任务已删除'
}

async function onRefreshTask(taskId: string) {
  await refreshSnapshot(taskId)
}

async function onCreateTask() {
  try {
    await createTask()
    await refreshTasks()
    syncWorkingCopies()
    message.value = '已新建任务标签页'
  } catch (e) {
    message.value = `新建任务失败: ${(e as Error).message}`
  }
}

function onSelectTask(id: string) {
  activeTaskId.value = id
}

async function refreshActiveSnapshot() {
  if (!activeTaskId.value) return
  try {
    await refreshSnapshot(activeTaskId.value)
  } catch {
    // transient poll errors are expected when services restart
  }
}

function startPolling() {
  stopPolling()
  pollingTimer.value = window.setInterval(() => {
    refreshTasks().then(syncWorkingCopies)
    void refreshActiveSnapshot()
  }, 3000)
}

function stopPolling() {
  if (pollingTimer.value !== null) {
    window.clearInterval(pollingTimer.value)
    pollingTimer.value = null
  }
}

onMounted(async () => {
  await refreshTasks()
  syncWorkingCopies()
  if (activeTaskId.value) await refreshSnapshot(activeTaskId.value)
  startPolling()
})

onUnmounted(() => {
  stopPolling()
})
</script>

<template>
  <div class="app-shell">
    <header class="top-header">
      <div class="brand">
        <h1>AutoDecision Frontend</h1>
        <p>工业场景自动决策训练系统，统一编排 AutoRealize、ML-Master 与 MLEvolve</p>
      </div>
      <div class="actions">
        <button class="settings" @click="openSettings">全局设置</button>
      </div>
    </header>

    <TaskTabs :tasks="tasks" :active-task-id="activeTaskId" :dirty-task-ids="dirtyTaskIds" @select="onSelectTask" @create="onCreateTask" />

    <main v-if="activeWorkingTask" class="main-layout">
      <TaskConfigPanel
        :task="activeWorkingTask"
        :snapshot="activeSnapshot"
        :is-dirty="!!dirtyTaskIds[activeWorkingTask.id]"
        @update-config="onUpdateConfig"
        @save="onSaveTask"
        @start="onStartTask"
        @rerun-full="onRerunFull"
        @rerun-auto-m-l="onRerunAutoML"
        @resume="onResumeTask"
        @stop="onStopTask"
        @remove="onDeleteTask"
        @refresh="onRefreshTask"
      />

      <WorkflowStepper
        :task="activeWorkingTask"
        :active-step="activeStep"
        :auto-realize-state="(activeSnapshot?.auto_realize?.current_state as Record<string, unknown>) || {}"
        :auto-realize-events="(activeSnapshot?.auto_realize?.events as Record<string, unknown>[]) || []"
        :auto-ml-events="(activeSnapshot?.auto_ml?.events as Record<string, unknown>[]) || []"
        @select="activeStep = $event"
      />

      <section class="step-page">
        <DataCognitionView v-if="activeStep === 'data_cognition'" :snapshot="activeSnapshot" />
        <TaskDefinitionView
          v-else-if="activeStep === 'task_definition'"
          :snapshot="activeSnapshot"
          :active-step-running="activeWorkingTask.status === 'running' && activeWorkingTask.phase === 'autorealize'"
        />
        <section v-else-if="activeStep === 'data_cleaning'" class="placeholder">
          <h3>数据清洗</h3>
          <p>该模块仍在开发中，当前保留占位，不允许点击进入运行。</p>
        </section>
        <AutoMLView v-else-if="activeStep === 'automl'" :snapshot="activeSnapshot" />
        <section v-else class="placeholder">
          <h3>报告生成</h3>
          <p>该模块尚未开发，后续可以接入自动报告摘要、关键结论与导出能力。</p>
        </section>
      </section>
    </main>

    <main v-else class="empty">
      <p>暂无任务，点击上方 + 新建一个任务。</p>
    </main>

    <footer class="status-bar">
      <span v-if="message">{{ message }}</span>
      <span v-if="error" class="error">{{ error }}</span>
    </footer>

    <GlobalSettingsDrawer
      v-if="globalSettings"
      :visible="settingsVisible"
      :model-value="globalSettings"
      @close="settingsVisible = false"
      @save="saveSettings"
    />
  </div>
</template>

<style scoped>
.app-shell {
  min-height: 100vh;
  display: grid;
  grid-template-rows: auto auto 1fr auto;
  background: radial-gradient(circle at 20% 0%, #e8f2ff, #cddbf0 45%, #c0d0e8 100%);
}

.top-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 14px;
  border-bottom: 1px solid #abc1e2;
  background: linear-gradient(90deg, #1f3f72, #14506f);
  color: #ecf5ff;
}

.brand h1 {
  margin: 0;
  font-size: 22px;
}

.brand p {
  margin: 4px 0 0;
  font-size: 13px;
  color: #bfdaff;
}

.settings {
  border: 1px solid #9ac7ff;
  color: #ecf5ff;
  background: rgba(255, 255, 255, 0.09);
  border-radius: 10px;
  padding: 8px 12px;
  cursor: pointer;
}

.main-layout {
  padding: 14px;
  display: grid;
  gap: 12px;
}

.step-page {
  min-height: 460px;
}

.placeholder {
  border: 1px dashed #7190b7;
  border-radius: 12px;
  padding: 12px;
  background: #edf4ff;
  color: #33557f;
}

.empty {
  display: grid;
  place-items: center;
  color: #335885;
}

.status-bar {
  border-top: 1px solid #aec2e0;
  background: #dbe8fa;
  min-height: 38px;
  padding: 8px 12px;
  font-size: 13px;
  color: #24446f;
}

.status-bar .error {
  color: #973535;
  margin-left: 10px;
}
</style>
