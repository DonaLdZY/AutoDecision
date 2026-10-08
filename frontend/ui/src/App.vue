<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, reactive, shallowRef, watch } from 'vue'
import './workspace.css'
import { Activity, ArrowUpRight, Check, ChevronRight, FolderOpen, Layers3, Menu, Play, Plus, Presentation, RefreshCw, Settings2, SlidersHorizontal, Square, X } from 'lucide-vue-next'
import { api } from './api'
import AutoMLView from './components/AutoMLView.vue'
import DataCognitionView from './components/DataCognitionView.vue'
import GlobalSettingsDrawer from './components/GlobalSettingsDrawer.vue'
import ReportView from './components/ReportView.vue'
import TaskConfirmDialog from './components/TaskConfirmDialog.vue'
import TaskConfigPanel from './components/TaskConfigPanel.vue'
import TaskDefinitionView from './components/TaskDefinitionView.vue'
import TaskTabs from './components/TaskSidebar.vue'
import ReplayControls from './components/ReplayControls.vue'
import WorkflowStepper, { type StepKey } from './components/WorkflowStepper.vue'
import { defaultTaskConfig, useTasks } from './composables/useTasks'
import type { GlobalSettings, SnapshotPayload, Task, TaskConfig } from './types'
import { cloneDeep } from './utils/clone'
import { displayTaskName } from './utils/taskName'
import { useReplay } from './composables/useReplay'
import { demoRecording, demoSnapshot, demoTask } from './utils/demoRecording'

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
  repairReviewAndResume,
  startAutoML,
  continueAutoML,
  rerunAutoReport,
  rerunFull,
  resumeTask,
  stopTask,
  refreshSnapshot,
} = useTasks()

const settingsVisible = shallowRef(false)
const configVisible = shallowRef(false)
const sidebarVisible = shallowRef(false)
const demoSelected = shallowRef(new URLSearchParams(window.location.search).has('demo'))
const replayLoading = shallowRef(false)
const followLive = shallowRef(false)
const presentation = shallowRef(false)
let previousFocus: HTMLElement | null = null
const replay = useReplay()
const { recording, playing, position, duration, index: replayIndex, mode: replayMode, interval: replayInterval, speed: replaySpeed, loop: replayLoop, followStage } = replay
const globalSettings = shallowRef<GlobalSettings | null>(null)
const message = shallowRef('')
const pollingTimer = shallowRef<number | null>(null)
const autoStepTimer = shallowRef<number | null>(null)
const autoStepPendingTarget = shallowRef<StepKey | null>(null)
const notificationAudioContext = shallowRef<AudioContext | null>(null)
const workingCopies = reactive<Record<string, Task>>({})
const dirtyTaskIds = reactive<Record<string, boolean>>({})
const taskStatusMemory = reactive<Record<string, string>>({})
const activeStep = shallowRef<StepKey>(demoSelected.value ? 'automl' : 'data_cognition')
const AUTO_STEP_DELAY_MS = 0

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
  if (recording.value) return replay.snapshot.value
  if (demoSelected.value) return demoSnapshot
  if (!activeTaskId.value) return undefined
  return snapshots[activeTaskId.value]
})

const activeWorkingTask = computed(() => {
  if (demoSelected.value) return demoTask
  const task = activeTask.value
  if (!task) return null
  if (!workingCopies[task.id]) workingCopies[task.id] = cloneDeep(task)
  return workingCopies[task.id]
})

const viewedTask = computed(() => activeSnapshot.value?.task ?? activeWorkingTask.value)
const completedNodes = computed(() => activeSnapshot.value?.auto_ml?.nodes ?? [])
const allNodeCount = computed(() => new Set([
  ...completedNodes.value, ...(activeSnapshot.value?.auto_ml?.pending_nodes ?? []),
].filter(node => node.stage !== 'root').map(node => node.id)).size)
const bestNode = computed(() => completedNodes.value.find(n => n.id === activeSnapshot.value?.auto_ml.best_node_id))
const validCount = computed(() => completedNodes.value.filter(n => n.is_valid && !n.is_buggy).length)
const statusNames: Record<string, string> = { idle: '待运行', running: '运行中', completed: '已完成', failed: '运行失败', stopped: '已停止', interrupted_resumable: '已中断 · 可恢复', interrupted_incomplete: '已中断' }
const statusName = computed(() => statusNames[viewedTask.value?.status ?? 'idle'] ?? viewedTask.value?.status)

async function openReplay() {
  if (!activeWorkingTask.value || replayLoading.value) return
  const selected = activeWorkingTask.value
  replayLoading.value = true
  try {
    const data = demoSelected.value ? demoRecording : await api.getReplay(selected.id)
    if (activeWorkingTask.value?.id !== selected.id) return
    if (!data.events.length) { message.value = '该任务暂无可重放的运行记录'; return }
    replay.load(data, selected)
    activeStep.value = replay.currentFocus.value?.stage ?? 'data_cognition'
    configVisible.value = false
  } catch (e) { message.value = formatActionError('加载重放', e) }
  finally { replayLoading.value = false }
}

function closeReplay() { replay.close(); activeStep.value = 'automl' }
function selectDemo() { replay.close(); demoSelected.value = true; activeStep.value = 'automl'; sidebarVisible.value = false }
async function togglePresentation() {
  try {
    if (document.fullscreenElement) await document.exitFullscreen()
    else await document.documentElement.requestFullscreen()
  } catch { presentation.value = !presentation.value }
}
function onFullscreenChange() { presentation.value = !!document.fullscreenElement }
function onEscape(event: KeyboardEvent) {
  if (event.key === 'Tab' && configVisible.value) {
    const focusable = [...document.querySelectorAll<HTMLElement>('.config-drawer button:not(:disabled), .config-drawer input:not(:disabled), .config-drawer select:not(:disabled), .config-drawer textarea:not(:disabled), .config-drawer a[href]')].filter(element => element.getClientRects().length)
    const first = focusable[0], last = focusable.at(-1)
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus() }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus() }
  }
  if (event.key !== 'Escape') return
  configVisible.value = false; sidebarVisible.value = false; settingsVisible.value = false
  if (!document.fullscreenElement) presentation.value = false
}
watch([replay.currentFocus, followStage], ([focus, follow]) => {
  if (focus && follow) activeStep.value = focus.stage
})
watch(configVisible, async visible => {
  if (visible) { previousFocus = document.activeElement as HTMLElement; await nextTick(); document.querySelector<HTMLElement>('.config-drawer button')?.focus() }
  else previousFocus?.focus()
})
let toastTimer: number | undefined
watch(message, value => {
  window.clearTimeout(toastTimer)
  if (value) toastTimer = window.setTimeout(() => { message.value = '' }, 6500)
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
  if (!followLive.value || recording.value) return
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
      message.value = `任务 ${displayTaskName(task.task_name || task.config.task_name)} 已完成`
    }
    taskStatusMemory[task.id] = current
  }
  for (const id of Object.keys(taskStatusMemory)) {
    if (!liveIds.has(id)) delete taskStatusMemory[id]
  }
}

function onSelectWorkflowStep(step: StepKey) {
  clearAutoStepTimer()
  followLive.value = false
  if (recording.value) followStage.value = false
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
  settingsVisible.value = true
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
  message.value = `任务 ${displayTaskName(task.config.task_name)} 已保存`
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

async function onRunAutoRealize(taskId: string, confirmed = false) {
  const existing = workingCopies[taskId]
  if (existing?.run_dir && !confirmed) {
    openActionDialog({
      title: '确认重新生成任务定义',
      message: `本操作会重建数据理解和任务定义。\n\n替换目录及其全部文件：\n${existing.run_dir}/autorealize/\n\n旧文件先归档至：\n${existing.run_dir}/stage-history/\n\n已有 AutoML 搜索结果仍对应旧任务定义。`,
      confirmLabel: '确认重建', confirmTone: 'danger',
    }, () => onRunAutoRealize(taskId, true))
    return
  }
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

async function onRepairReview(taskId: string) {
  try {
    const task = workingCopies[taskId]
    if (!task) return
    await onSaveTask(taskId)
    const plan = await api.getReviewRepairPlan(taskId)
    openActionDialog({
      title: '确认修复范围',
      message: `修复阶段：任务定义。修复成功后继续 AutoML。\n\n成功后替换目录：\n${plan.replace_paths.join('\n')}\n\n旧版本归档至：\n${plan.archive_root}\n\n永久删除：${plan.delete_paths.length ? plan.delete_paths.join('\n') : '无'}\n\n数据理解保持原样：\n${plan.preserve_paths.join('\n')}\n\n目录内现有文件（${plan.files.length} 个）：\n${plan.files.map(file => file.path).join('\n')}\n\n修复失败时保留当前产物。`,
      confirmLabel: '确认范围并修复', confirmTone: 'danger',
    }, async () => {
      await repairReviewAndResume(taskId, plan.plan_token)
      activeStep.value = 'task_definition'
      await refreshTasks()
      syncWorkingCopies()
      message.value = '已启动独立任务定义修复，原产物将在修复成功后归档'
    })
  } catch (e) {
    message.value = formatActionError('修复任务定义审查', e)
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
      if (readiness.can_repair_review) {
        openActionDialog(
          {
            title: 'AutoML 输入审查未通过',
            message: `${readiness.detail}\n\n可以从任务定义检查点继续修复。数据认知和问题调查缓存会保留，修复通过后系统会自动进入 AutoML。`,
            confirmLabel: '修复审查并继续',
            cancelLabel: '稍后处理',
            confirmTone: 'positive',
          },
          () => onRepairReview(taskId),
        )
      } else {
        openActionAlert('AutoML 输入未就绪', readiness.detail)
      }
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

async function onRunReport(taskId: string, confirmed = false) {
  const task = workingCopies[taskId]
  if (!task) return
  if (task.run_dir && !confirmed) {
    openActionDialog({
      title: '确认生成报告',
      message: `使用已有 AutoML 搜索结果及其冻结任务定义。\n\n报告目录中的同名报告、分析与审查文件会更新：\n${task.run_dir}/report/\n\n原报告目录先完整归档至：\n${task.run_dir}/stage-history/\n\n数据理解、任务定义和 AutoML 文件保留。`,
      confirmLabel: '确认生成报告', confirmTone: 'primary',
    }, () => onRunReport(taskId, true))
    return
  }
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
  const taskName = displayTaskName(task?.config.task_name || task?.task_name) || '当前任务'
  openActionAlert(
    '无法删除运行中的任务',
    `任务 ${taskName} 仍在运行。请先点击“中断任务”，等待检查点保存完成后再删除。`,
  )
}

async function onDeleteTask(taskId: string, deleteFiles: boolean) {
  try {
    const result = await deleteTask(taskId, deleteFiles)
    if (recording.value?.task_id === taskId) closeReplay()
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
    replay.close()
    demoSelected.value = false
    await createTask()
    await refreshTasks()
    syncWorkingCopies()
    message.value = '已新建任务标签页'
    configVisible.value = true
    sidebarVisible.value = false
  } catch (e) {
    message.value = `新建任务失败: ${(e as Error).message}`
  }
}

function onSelectTask(id: string) {
  replay.close()
  demoSelected.value = false
  sidebarVisible.value = false
  activeTaskId.value = id
  activeStep.value = tasks.value.find(t => t.id === id)?.status === 'completed' ? 'automl' : 'data_cognition'
  void refreshActiveSnapshot()
}

async function refreshActiveSnapshot() {
  if (!activeTaskId.value || recording.value || demoSelected.value) return
  try {
    await refreshSnapshot(activeTaskId.value)
  } catch {
    // transient poll errors are expected when services restart
  }
}

function startPolling() {
  stopPolling()
  const poll = async () => {
    if (!recording.value) {
      await refreshTasks({ silent: true })
      syncWorkingCopies()
      syncTaskCompletionNotifications()
      await refreshActiveSnapshot()
    }
    pollingTimer.value = window.setTimeout(poll, 2000)
  }
  pollingTimer.value = window.setTimeout(poll, 2000)
}

function stopPolling() {
  if (pollingTimer.value !== null) {
    window.clearTimeout(pollingTimer.value)
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
  document.addEventListener('fullscreenchange', onFullscreenChange)
  window.addEventListener('keydown', onEscape)
  window.addEventListener('pointerdown', unlockNotificationAudio, { once: true })
  window.addEventListener('keydown', unlockNotificationAudio, { once: true })
  await refreshTasks()
  syncWorkingCopies()
  syncTaskCompletionNotifications()
  if (activeTaskId.value && !demoSelected.value) await refreshActiveSnapshot()
  startPolling()
})

onUnmounted(() => {
  window.clearTimeout(toastTimer)
  document.removeEventListener('fullscreenchange', onFullscreenChange)
  window.removeEventListener('keydown', onEscape)
  window.removeEventListener('pointerdown', unlockNotificationAudio)
  window.removeEventListener('keydown', unlockNotificationAudio)
  stopPolling()
  clearAutoStepTimer()
  void notificationAudioContext.value?.close().catch(() => undefined)
})
</script>

<template>
  <div class="decision-app" :class="{ presenting: presentation, 'is-replaying': !!recording }">
    <button v-if="sidebarVisible" class="sidebar-backdrop" aria-label="关闭任务列表" @click="sidebarVisible = false" />
    <aside class="app-sidebar" :class="{ opened: sidebarVisible }">
      <a class="brand" href="#" @click.prevent="sidebarVisible = false"><span class="brand-icon"><Layers3 :size="22" /></span><h1>工智寻优</h1></a>
      <div class="workspace-name"><span class="workspace-avatar">工</span><span>工业决策实验室<small>Industrial Intelligence</small></span></div>
      <TaskTabs :tasks="tasks" :active-task-id="demoSelected ? '' : activeTaskId" :dirty-task-ids="dirtyTaskIds" @select="onSelectTask" @create="onCreateTask" @remove="requestDeleteTask" @remove-blocked="explainDeleteBlocked" />
      <div class="sidebar-bottom">
        <button class="sidebar-link" :class="{ selected: demoSelected }" @click="selectDemo"><Presentation :size="17" /><span>演示任务</span><ArrowUpRight :size="13" /></button>
        <button class="sidebar-link" @click="openSettings"><Settings2 :size="17" /><span>全局设置</span></button>
        <div class="sidebar-footnote"><span class="status-dot" />本地工作空间<span class="mono">v2.0</span></div>
      </div>
    </aside>

    <div class="workspace-main">
      <header class="workspace-topbar">
        <button class="icon-button mobile-menu" title="任务列表" aria-label="任务列表" @click="sidebarVisible = !sidebarVisible"><Menu :size="19" /></button>
        <span class="breadcrumb-root">任务空间</span><ChevronRight :size="13" /><span class="breadcrumb-task">{{ displayTaskName(activeWorkingTask?.config.task_name) || '决策工作台' }}</span>
        <span v-if="demoSelected" class="demo-badge">示例数据</span>
        <div class="topbar-end"><span v-if="recording" class="mode-chip">重放模式</span><button class="icon-button" title="全局设置" aria-label="全局设置" @click="openSettings"><Settings2 :size="17" /></button><span class="user-avatar" aria-label="工智寻优">工智</span></div>
      </header>

      <main v-if="activeWorkingTask" class="workspace-content">
        <div class="workspace-heading">
          <div><div class="eyebrow">工智寻优 · 决策工作台</div><h2>{{ displayTaskName(activeWorkingTask.config.task_name) }}</h2><div class="task-subtitle"><span class="status-dot" :class="viewedTask?.status" /><span>{{ statusName }}</span><span class="subtle-divider">/</span><span>{{ demoSelected ? '门店经营与销售规划' : activeWorkingTask.config.auto_realize.task_hint || '工业大数据决策任务' }}</span></div></div>
          <div class="workspace-commands">
            <button v-if="!recording" class="command" :disabled="replayLoading || (!demoSelected && activeWorkingTask.status === 'idle')" @click="openReplay"><Presentation :size="16" />{{ replayLoading ? '加载中' : '任务重放' }}</button>
            <button v-if="!demoSelected && !recording" class="command" @click="configVisible = true"><SlidersHorizontal :size="16" />任务配置<span v-if="dirtyTaskIds[activeWorkingTask.id]" class="unsaved-dot" /></button>
            <button v-if="!demoSelected && !recording && activeWorkingTask.status === 'running'" class="command danger" @click="requestStopTask(activeWorkingTask.id)"><Square :size="14" />中断</button>
            <button v-else-if="!demoSelected && !recording" class="command primary" :disabled="!activeWorkingTask.config.input_root" @click="requestRunTask(activeWorkingTask.id)"><Play :size="15" />执行任务</button>
            <button v-if="recording" class="command" @click="togglePresentation"><Presentation :size="16" />{{ presentation ? '退出全屏' : '全屏演示' }}</button>
          </div>
        </div>

        <div class="metrics-band">
          <div class="metric-item"><span class="metric-label">搜索候选 <Activity :size="13" /></span><strong>{{ allNodeCount.toString().padStart(2, '0') }}<small v-if="!recording">/ {{ activeWorkingTask.config.auto_ml.steps }}</small></strong><span class="metric-note">蒙特卡洛树搜索</span></div>
          <div class="metric-item"><span class="metric-label">有效方案 <Check :size="13" /></span><strong>{{ validCount.toString().padStart(2, '0') }}<small>个</small></strong><span class="metric-note">通过候选评估</span></div>
          <div class="metric-item"><span class="metric-label">当前最优指标</span><strong class="accent-value">{{ bestNode?.metric != null ? Number(bestNode.metric).toLocaleString(undefined, { maximumFractionDigits: 4 }) : '—' }}<small v-if="bestNode">{{ bestNode.maximize ? '↑' : '↓' }}</small></strong><span class="metric-note">{{ bestNode?.label || bestNode?.method_mode || (bestNode ? bestNode.id.slice(0, 18) : '等待评估结果') }}</span></div>
          <div class="metric-item"><span class="metric-label">任务阶段</span><strong class="stage-metric">{{ stepLabels[activeStep] }}</strong><span class="metric-note">{{ recording ? '历史运行回放' : 'AutoRealize → AlgoEvolve → AutoReport' }}</span></div>
        </div>

        <div class="workflow-bar">
          <WorkflowStepper :task="viewedTask" :active-step="activeStep" :auto-realize-state="activeSnapshot?.auto_realize?.current_state || {}" :auto-realize-events="activeSnapshot?.auto_realize?.events || []" :auto-ml-events="activeSnapshot?.auto_ml?.events || []" @select="onSelectWorkflowStep" />
          <label v-if="!recording" class="follow-live"><input v-model="followLive" type="checkbox" @change="scheduleAutoStep(autoStepTarget)" />跟随运行</label>
        </div>

        <section class="stage-content" :key="activeWorkingTask.id" :class="{ 'legacy-stage': activeStep !== 'automl' }">
          <DataCognitionView v-if="activeStep === 'data_cognition'" :snapshot="activeSnapshot" />
          <TaskDefinitionView v-else-if="activeStep === 'task_definition'" :snapshot="activeSnapshot" :active-step-running="viewedTask?.status === 'running' && viewedTask?.phase === 'autorealize'" :replay-artifact="recording && followStage ? replay.currentFocus.value?.artifact : undefined" />
          <AutoMLView v-else-if="activeStep === 'automl'" :snapshot="activeSnapshot" :replay="!!recording" />
          <ReportView v-else :snapshot="activeSnapshot" />
        </section>
      </main>

      <main v-else class="workspace-empty">
        <span class="empty-brand"><Layers3 :size="42" /></span><span class="eyebrow">工智寻优</span><h2>决策工作台</h2>
        <div class="empty-state-title">暂无任务</div>
        <div class="workspace-commands"><button class="command primary" @click="onCreateTask"><Plus :size="16" />新建任务</button><button class="command" @click="selectDemo"><Presentation :size="16" />打开演示任务</button></div>
      </main>

      <ReplayControls v-if="recording" :recording="recording" :playing="playing" :position="position" :duration="duration" :index="replayIndex" :label="replay.currentEvent.value?.label" v-model:mode="replayMode" v-model:interval="replayInterval" v-model:speed="replaySpeed" v-model:loop="replayLoop" v-model:follow-stage="followStage" @play="replay.play" @pause="replay.pause" @seek="replay.seek" @step="replay.step" @close="closeReplay" @present="togglePresentation" />
      <footer class="workspace-footer"><span><span class="status-dot" />{{ recording ? '历史记录 · 只读' : '工智寻优引擎' }}</span><span class="footer-path">{{ activeWorkingTask?.input_root || 'LOCAL WORKSPACE' }}</span><button v-if="activeWorkingTask && !demoSelected && !recording" class="icon-button" title="刷新任务状态" aria-label="刷新任务状态" @click="onRefreshTask(activeWorkingTask.id)"><RefreshCw :size="13" /></button></footer>
    </div>

    <div v-if="message || error" class="app-toast" :class="{ 'toast-error': !!error }" role="status"><span>{{ error || message }}</span><button class="icon-button" title="关闭提示" aria-label="关闭提示" @click="message = ''; error = ''"><X :size="16" /></button></div>

    <Teleport to="body">
      <Transition name="drawer">
        <div v-if="configVisible && activeWorkingTask && !demoSelected && !recording" class="config-overlay" @click.self="configVisible = false">
          <section class="config-drawer" role="dialog" aria-modal="true" aria-label="任务配置">
            <header class="config-drawer-header"><span><SlidersHorizontal :size="18" />任务配置</span><div><button v-if="activeWorkingTask.run_dir" class="icon-button" title="打开任务目录" aria-label="打开任务目录" @click="api.openDirectory(activeWorkingTask.run_dir)"><FolderOpen :size="17" /></button><button class="icon-button" title="关闭任务配置" aria-label="关闭任务配置" @click="configVisible = false"><X :size="19" /></button></div></header>
            <TaskConfigPanel :task="activeWorkingTask" :snapshot="activeSnapshot" :is-dirty="!!dirtyTaskIds[activeWorkingTask.id]" @update-config="onUpdateConfig" @restore-defaults="onRestoreDefaultConfig" @save="onSaveTask" @run-auto-realize="onRunAutoRealize" @run-auto-m-l="requestRunAutoML" @continue-auto-m-l="onContinueAutoML" @repair-review="onRepairReview" @run-report="onRunReport" @run-task="requestRunTask" @resume-task="onResumeTask" @stop="requestStopTask" @refresh="onRefreshTask" />
          </section>
        </div>
      </Transition>
    </Teleport>

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
