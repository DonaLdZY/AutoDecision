<script setup lang="ts">
import { computed, onMounted, onUnmounted, reactive, shallowRef, watch } from 'vue'
import { api } from './api'
import AutoMLView from './components/AutoMLView.vue'
import DataCognitionView from './components/DataCognitionView.vue'
import GlobalSettingsDrawer from './components/GlobalSettingsDrawer.vue'
import ReportView from './components/ReportView.vue'
import TaskConfirmDialog from './components/TaskConfirmDialog.vue'
import TaskConfigPanel from './components/TaskConfigPanel.vue'
import TaskDefinitionView from './components/TaskDefinitionView.vue'
import TaskTabs from './components/TaskTabs.vue'
import WorkflowStepper, { type StepKey } from './components/WorkflowStepper.vue'
import { defaultTaskConfig, useTasks } from './composables/useTasks'
import type { GlobalSettings, SnapshotPayload, Task, TaskConfig } from './types'
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
  rerunAutoRealize,
  startAutoML,
  continueAutoML,
  rerunAutoReport,
  rerunFull,
  resumeTask,
  stopTask,
  refreshSnapshot,
} = useTasks()

const settingsVisible = shallowRef(false)
const globalSettings = shallowRef<GlobalSettings | null>(null)
const message = shallowRef('')
const pollingTimer = shallowRef<number | null>(null)
const autoStepTimer = shallowRef<number | null>(null)
const autoStepPendingTarget = shallowRef<StepKey | null>(null)
const notificationAudioContext = shallowRef<AudioContext | null>(null)
const workingCopies = reactive<Record<string, Task>>({})
const dirtyTaskIds = reactive<Record<string, boolean>>({})
const taskStatusMemory = reactive<Record<string, string>>({})
const activeStep = shallowRef<StepKey>('data_cognition')
const AUTO_STEP_DELAY_MS = 10_000

interface ActionDialogOptions {
  title: string
  message: string
  confirmLabel?: string
  cancelLabel?: string
  confirmTone?: 'positive' | 'danger' | 'primary'
  cancelTone?: 'neutral' | 'danger'
  checkboxLabel?: string
  showCancel?: boolean
}

const actionDialog = reactive({
  open: false,
  title: '',
  message: '',
  confirmLabel: '确认',
  cancelLabel: '取消',
  confirmTone: 'primary' as 'positive' | 'danger' | 'primary',
  cancelTone: 'neutral' as 'neutral' | 'danger',
  checkboxLabel: '',
  showCancel: true,
})
const actionDialogChecked = shallowRef(false)
const pendingDialogAction = shallowRef<((checked: boolean) => Promise<void> | void) | null>(null)

function openActionDialog(
  options: ActionDialogOptions,
  action: (checked: boolean) => Promise<void> | void,
) {
  Object.assign(actionDialog, {
    open: true,
    title: options.title,
    message: options.message,
    confirmLabel: options.confirmLabel ?? '确认',
    cancelLabel: options.cancelLabel ?? '取消',
    confirmTone: options.confirmTone ?? 'primary',
    cancelTone: options.cancelTone ?? 'neutral',
    checkboxLabel: options.checkboxLabel ?? '',
    showCancel: options.showCancel ?? true,
  })
  actionDialogChecked.value = false
  pendingDialogAction.value = action
}

function openActionAlert(title: string, detail: string) {
  openActionDialog(
    {
      title,
      message: detail,
      confirmLabel: '知道了',
      showCancel: false,
    },
    () => undefined,
  )
}

function closeActionDialog() {
  actionDialog.open = false
  pendingDialogAction.value = null
  actionDialogChecked.value = false
}

async function confirmActionDialog() {
  const action = pendingDialogAction.value
  const checked = actionDialogChecked.value
  closeActionDialog()
  if (!action) return
  try {
    await action(checked)
  } catch (e) {
    message.value = formatActionError('操作', e)
  }
}

const stepLabels: Record<StepKey, string> = {
  data_cognition: '数据理解',
  task_definition: '任务定义',
  automl: '自动机器学习',
  report: '报告生成',
}

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

const autoStepTarget = computed<StepKey | null>(() => inferRunningAutoStepTarget(activeWorkingTask.value, activeSnapshot.value))

function formatActionError(action: string, error: unknown) {
  return `${action}失败: ${(error as Error).message || String(error)}`
}

function stepFromComponentName(component: string): StepKey | null {
  const text = component.toLowerCase()
  if (text.includes('task_definition') || text.includes('stage.p2')) return 'task_definition'
  if (text.includes('data_cognition') || text.includes('file_cognition') || text.includes('cognition_probe') || text.includes('stage.p1')) return 'data_cognition'
  return null
}

function stepFromAutoRealizeState(snapshot?: SnapshotPayload): StepKey | null {
  const state = snapshot?.auto_realize?.current_state ?? {}
  const active = state.active_components
  if (Array.isArray(active) && active.length > 0) {
    const first = active[0] as Record<string, unknown>
    const step = stepFromComponentName(String(first.component ?? ''))
    if (step) return step
  }
  const events = snapshot?.auto_realize?.events ?? []
  for (let i = events.length - 1; i >= 0; i -= 1) {
    const step = stepFromComponentName(String(events[i]?.component ?? ''))
    if (step) return step
  }
  return null
}

function inferRunningAutoStepTarget(task: Task | null, snapshot?: SnapshotPayload): StepKey | null {
  if (!task) return null
  const phase = String(task.phase ?? '').toLowerCase()

  if (task.status !== 'running') return null
  if (phase.includes('automl')) return 'automl'
  if (phase.includes('report')) return 'report'
  if (phase.includes('autorealize')) return stepFromAutoRealizeState(snapshot) ?? 'data_cognition'

  return null
}

function clearAutoStepTimer() {
  if (autoStepTimer.value !== null) {
    window.clearTimeout(autoStepTimer.value)
    autoStepTimer.value = null
  }
  autoStepPendingTarget.value = null
}

function scheduleAutoStep(target: StepKey | null) {
  if (!target || target === activeStep.value) {
    clearAutoStepTimer()
    return
  }
  if (autoStepPendingTarget.value === target) return
  clearAutoStepTimer()
  autoStepPendingTarget.value = target
  autoStepTimer.value = window.setTimeout(() => {
    activeStep.value = target
    autoStepTimer.value = null
    autoStepPendingTarget.value = null
    message.value = `已自动切换到${stepLabels[target]}`
  }, AUTO_STEP_DELAY_MS)
}

function getNotificationAudioContext() {
  if (notificationAudioContext.value) return notificationAudioContext.value
  const AudioContextCtor = window.AudioContext ?? (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext
  if (!AudioContextCtor) return null
  notificationAudioContext.value = new AudioContextCtor()
  return notificationAudioContext.value
}

function unlockNotificationAudio() {
  const ctx = getNotificationAudioContext()
  if (ctx?.state === 'suspended') void ctx.resume().catch(() => undefined)
}

function playTaskCompletedSound() {
  const ctx = getNotificationAudioContext()
  if (!ctx) return
  void ctx.resume().then(() => {
    const now = ctx.currentTime
    const gain = ctx.createGain()
    const first = ctx.createOscillator()
    const second = ctx.createOscillator()

    first.type = 'sine'
    first.frequency.setValueAtTime(660, now)
    second.type = 'sine'
    second.frequency.setValueAtTime(880, now + 0.09)
    gain.gain.setValueAtTime(0.0001, now)
    gain.gain.exponentialRampToValueAtTime(0.06, now + 0.015)
    gain.gain.exponentialRampToValueAtTime(0.0001, now + 0.32)

    first.connect(gain)
    second.connect(gain)
    gain.connect(ctx.destination)
    first.start(now)
    first.stop(now + 0.16)
    second.start(now + 0.09)
    second.stop(now + 0.32)
  }).catch(() => undefined)
}

function syncTaskCompletionNotifications() {
  const liveIds = new Set<string>()
  for (const task of tasks.value) {
    liveIds.add(task.id)
    const previous = taskStatusMemory[task.id]
    const current = String(task.status ?? '')
    if (previous === 'running' && current === 'completed') {
      playTaskCompletedSound()
      message.value = `任务 ${task.task_name || task.config.task_name} 已完成`
    }
    taskStatusMemory[task.id] = current
  }
  for (const id of Object.keys(taskStatusMemory)) {
    if (!liveIds.has(id)) delete taskStatusMemory[id]
  }
}

function onSelectWorkflowStep(step: StepKey) {
  clearAutoStepTimer()
  activeStep.value = step
}

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
    target.report_dir = task.report_dir
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
  await loadGlobalSettings()
  settingsVisible.value = false
  message.value = '全局设置已保存'
}

function onUpdateConfig(taskId: string, config: TaskConfig) {
  const target = workingCopies[taskId]
  if (!target) return
  target.config = cloneDeep(config)
  dirtyTaskIds[taskId] = true
}

function onRestoreDefaultConfig(taskId: string) {
  const target = workingCopies[taskId]
  if (!target || target.status === 'running') return
  const taskIndex = Math.max(1, tasks.value.findIndex((task) => task.id === taskId) + 1)
  target.config = defaultTaskConfig(taskIndex)
  dirtyTaskIds[taskId] = true
  message.value = '已还原系统默认配置，保存后生效'
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

function requestStopTask(taskId: string) {
  openActionDialog(
    {
      title: '中断当前任务',
      message: '系统会先保存搜索树、在途动作和 Top-K 方案。检查点保存完成后，可以继续任务或直接生成报告。',
      confirmLabel: '确认中断',
      confirmTone: 'danger',
    },
    () => onStopTask(taskId),
  )
}

async function onStopTask(taskId: string) {
  message.value = '正在保存 AutoML 检查点...'
  const result = await stopTask(taskId)
  await refreshSnapshot(taskId)
  if (result.status === 'interrupted_resumable') {
    message.value = '任务已中断，可继续搜索或生成报告'
  } else if (result.status === 'stopping') {
    message.value = '终止信号已发送，正在保存搜索树与 Top-K 检查点'
  } else {
    message.value = '任务已停止'
  }
}

async function onRunAutoRealize(taskId: string) {
  try {
    const task = workingCopies[taskId]
    if (!task) return
    await onSaveTask(taskId)
    activeStep.value = 'data_cognition'
    await rerunAutoRealize(taskId)
    await refreshTasks()
    syncWorkingCopies()
    try {
      await refreshSnapshot(taskId)
    } catch {
      // AutoRealize may still be recreating its output directory.
    }
    message.value = '已启动 AutoRealize'
  } catch (e) {
    message.value = formatActionError('执行 AutoRealize', e)
  }
}

function requestRunAutoML(taskId: string) {
  openActionDialog(
    {
      title: '执行 AutoML',
      message: 'AutoML 不要求先执行 AutoRealize，但必须满足以下任一条件：\n1. 已执行 AutoRealize；\n2. 输入目录已有 description.md；\n3. AutoML 配置中已同时填写 Goal 和 Eval。\n\n确认后系统会再次检查。',
      confirmLabel: '检查并执行',
      confirmTone: 'positive',
    },
    () => onRunAutoML(taskId),
  )
}

async function onRunAutoML(taskId: string) {
  try {
    const task = workingCopies[taskId]
    if (!task) return
    await onSaveTask(taskId)
    const readiness = await api.getAutoMLReadiness(taskId)
    if (!readiness.ready) {
      openActionAlert('AutoML 输入未就绪', readiness.detail)
      return
    }
    activeStep.value = 'automl'
    await startAutoML(taskId)
    await refreshTasks()
    syncWorkingCopies()
    try {
      await refreshSnapshot(taskId)
    } catch {
      // AutoML output may still be initializing.
    }
    message.value = '已启动 AutoML'
  } catch (e) {
    message.value = formatActionError('执行 AutoML', e)
  }
}

async function onContinueAutoML(taskId: string) {
  try {
    const task = workingCopies[taskId]
    if (!task) return
    await onSaveTask(taskId)
    activeStep.value = 'automl'
    await continueAutoML(taskId)
    await refreshTasks()
    syncWorkingCopies()
    message.value = '已在原搜索树上继续执行 AutoML'
  } catch (e) {
    message.value = formatActionError('继续执行 AutoML', e)
  }
}

async function onRunReport(taskId: string) {
  const task = workingCopies[taskId]
  if (!task) return
  try {
    await onSaveTask(taskId)
    activeStep.value = 'report'
    await rerunAutoReport(taskId)
    await refreshTasks()
    syncWorkingCopies()
    try {
      await refreshSnapshot(taskId)
    } catch {
      // Report directory may be recreated asynchronously.
    }
    message.value = '已启动报告生成'
  } catch (e) {
    message.value = formatActionError('执行报告生成', e)
  }
}

function requestRunTask(taskId: string) {
  openActionDialog(
    {
      title: '执行完整任务',
      message: '这会删除该任务原有的执行过程和阶段产物，然后按当前配置从 AutoRealize 开始完整执行。此操作不可撤销。',
      confirmLabel: '确认执行',
      cancelLabel: '取消任务',
      confirmTone: 'positive',
      cancelTone: 'danger',
    },
    () => onRunTask(taskId),
  )
}

async function onRunTask(taskId: string) {
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
  message.value = '已按当前配置执行完整任务'
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
  message.value = '已从中断处继续任务'
}

function requestDeleteTask(taskId: string) {
  openActionDialog(
    {
      title: '删除任务',
      message: '确认删除当前任务标签吗？默认只删除任务记录，已有运行文件会保留。',
      confirmLabel: '确认删除',
      cancelLabel: '取消删除',
      confirmTone: 'danger',
      cancelTone: 'neutral',
      checkboxLabel: '同时删除该任务的相关运行文件',
    },
    (deleteFiles) => onDeleteTask(taskId, deleteFiles),
  )
}

function explainDeleteBlocked(taskId: string) {
  const task = tasks.value.find((candidate) => candidate.id === taskId)
  const taskName = task?.config.task_name || task?.task_name || '当前任务'
  openActionAlert(
    '无法删除运行中的任务',
    `任务 ${taskName} 仍在运行。请先点击“中断任务”，等待检查点保存完成后再删除。`,
  )
}

async function onDeleteTask(taskId: string, deleteFiles: boolean) {
  try {
    const result = await deleteTask(taskId, deleteFiles)
    delete dirtyTaskIds[taskId]
    const removed = result.deleted_files?.length ?? 0
    message.value = deleteFiles ? `任务已删除，并清理 ${removed} 个任务目录` : '任务已删除，运行文件已保留'
  } catch (e) {
    message.value = formatActionError('删除任务', e)
  }
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
    refreshTasks({ silent: true }).then(() => {
      syncWorkingCopies()
      syncTaskCompletionNotifications()
    })
    void refreshActiveSnapshot()
  }, 3000)
}

function stopPolling() {
  if (pollingTimer.value !== null) {
    window.clearInterval(pollingTimer.value)
    pollingTimer.value = null
  }
}

watch(
  () => [activeTaskId.value, autoStepTarget.value] as const,
  ([, target]) => {
    scheduleAutoStep(target)
  },
)

onMounted(async () => {
  window.addEventListener('pointerdown', unlockNotificationAudio, { once: true })
  window.addEventListener('keydown', unlockNotificationAudio, { once: true })
  await refreshTasks()
  syncWorkingCopies()
  syncTaskCompletionNotifications()
  if (activeTaskId.value) await refreshSnapshot(activeTaskId.value)
  startPolling()
})

onUnmounted(() => {
  window.removeEventListener('pointerdown', unlockNotificationAudio)
  window.removeEventListener('keydown', unlockNotificationAudio)
  stopPolling()
  clearAutoStepTimer()
  void notificationAudioContext.value?.close().catch(() => undefined)
})
</script>

<template>
  <div class="app-shell">
    <header class="top-header">
      <div class="brand">
        <h1>AutoDecision Frontend</h1>
        <p>工业场景自动决策训练系统，统一编排 AutoRealize、MLEvolve 与 AutoReport</p>
      </div>
      <div class="actions">
        <button class="settings" @click="openSettings">全局设置</button>
      </div>
    </header>

    <TaskTabs
      :tasks="tasks"
      :active-task-id="activeTaskId"
      :dirty-task-ids="dirtyTaskIds"
      @select="onSelectTask"
      @create="onCreateTask"
      @remove="requestDeleteTask"
      @remove-blocked="explainDeleteBlocked"
    />

    <main v-if="activeWorkingTask" class="main-layout">
      <TaskConfigPanel
        :task="activeWorkingTask"
        :snapshot="activeSnapshot"
        :is-dirty="!!dirtyTaskIds[activeWorkingTask.id]"
        @update-config="onUpdateConfig"
        @restore-defaults="onRestoreDefaultConfig"
        @save="onSaveTask"
        @run-auto-realize="onRunAutoRealize"
        @run-auto-m-l="requestRunAutoML"
        @continue-auto-m-l="onContinueAutoML"
        @run-report="onRunReport"
        @run-task="requestRunTask"
        @resume-task="onResumeTask"
        @stop="requestStopTask"
        @refresh="onRefreshTask"
      />

      <WorkflowStepper
        :task="activeWorkingTask"
        :active-step="activeStep"
        :auto-realize-state="(activeSnapshot?.auto_realize?.current_state as Record<string, unknown>) || {}"
        :auto-realize-events="(activeSnapshot?.auto_realize?.events as Record<string, unknown>[]) || []"
        :auto-ml-events="(activeSnapshot?.auto_ml?.events as Record<string, unknown>[]) || []"
        @select="onSelectWorkflowStep"
      />

      <section class="step-page">
        <DataCognitionView v-if="activeStep === 'data_cognition'" :snapshot="activeSnapshot" />
        <TaskDefinitionView
          v-else-if="activeStep === 'task_definition'"
          :snapshot="activeSnapshot"
          :active-step-running="activeWorkingTask.status === 'running' && activeWorkingTask.phase === 'autorealize'"
        />
        <AutoMLView v-else-if="activeStep === 'automl'" :snapshot="activeSnapshot" />
        <ReportView v-else :snapshot="activeSnapshot" />
      </section>
    </main>

    <main v-else class="empty">
      <p>暂无任务</p>
    </main>

    <footer class="status-bar">
      <span v-if="message" class="status-message">{{ message }}</span>
      <span v-if="error" class="status-error">错误: {{ error }}</span>
    </footer>

    <GlobalSettingsDrawer
      v-if="globalSettings"
      :visible="settingsVisible"
      :model-value="globalSettings"
      @close="settingsVisible = false"
      @save="saveSettings"
    />

    <TaskConfirmDialog
      v-model:checked="actionDialogChecked"
      :open="actionDialog.open"
      :title="actionDialog.title"
      :message="actionDialog.message"
      :confirm-label="actionDialog.confirmLabel"
      :cancel-label="actionDialog.cancelLabel"
      :confirm-tone="actionDialog.confirmTone"
      :cancel-tone="actionDialog.cancelTone"
      :checkbox-label="actionDialog.checkboxLabel"
      :show-cancel="actionDialog.showCancel"
      @confirm="confirmActionDialog"
      @cancel="closeActionDialog"
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
  min-width: 0;
  max-width: 100%;
  overflow-x: hidden;
}

.step-page {
  min-height: 460px;
  min-width: 0;
  max-width: 100%;
  overflow-x: hidden;
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
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.status-message {
  color: #24446f;
}

.status-error {
  color: #973535;
  border-left: 1px solid rgba(151, 53, 53, 0.35);
  padding-left: 12px;
}
</style>
