<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import Icon from '../components/Icon.vue'
import DeliveryPanel from './DeliveryPanel.vue'
import TaskNextStep from './TaskNextStep.vue'
import { taskWorkflow } from './taskWorkflow'
import ResearchProgress from './ResearchProgress.vue'
import MarkdownView from './MarkdownView.vue'
import EvaluationCriteria from './EvaluationCriteria.vue'
import {
  summarizeGoal,
  candidateSummary,
  candidatePlan,
  taskResourceSummary,
  webResearchSummary as presentWebResearch,
  candidateReadiness,
  humanReportStatus,
  humanArtifactLabel,
  humanSnapshotError,
  formatDuration,
  formatMetric,
} from './presentation'
import { ui, state, request, run, refresh, status, phase, toast, saveBlob } from './store'
import type { Task } from './store'
import ResourceStorage from './ResourceStorage.vue'
import Settings from './Settings.vue'
const props = defineProps<{ id: string; initialTab?: number }>(),
  emit = defineEmits<{ open: [kind: string, id: string]; navigate: [page: string] }>()
const snapshot = ref<any>(),
  detailSnapshot = ref<any>(),
  detailsError = ref(''),
  detailsLoading = ref(false),
  solution = ref<any>(),
  error = ref(''),
  tab = ref(props.initialTab || 0),
  selected = ref(''),
  readiness = ref<any>(),
  inputReadiness = ref<any>(),
  pending = ref(''),
  publishName = ref(''),
  publishDescription = ref(''),
  schema = ref('{}'),
  binding = ref(''),
  output = ref(''),
  reviewed = ref(false),
  repairPlan = ref<any>()
const publishForm = ref<HTMLFormElement>()
function showPublish() {
  publishForm.value?.scrollIntoView({ block: 'start', behavior: 'smooth' })
  publishForm.value?.querySelector<HTMLInputElement>('input')?.focus({ preventScroll: true })
}
const recoveryGate = ref<any>()
const recoveryError = ref('')
let recoveryKey = ''
const inlineSettings = ref(false)
const editingInput = ref(false)
const inputRoot = ref('')
const deliveryId = ref('')
const reportReady = ref(false)
const deliveryFrames = ref<any[]>([])
const solutionLoading = ref(false),
  solutionChecked = ref(false),
  solutionError = ref('')
const deliveryVisited = ref(tab.value === 3)
watch(tab, (value) => { if (value === 3) deliveryVisited.value = true })
watch(
  () => props.initialTab,
  (value) => {
    tab.value = value || 0
  },
)
async function acceptDelivery(data: any) {
  const changed = deliveryId.value !== (data.delivery_id || '')
  if (changed || !data.report_ready) reviewed.value = false
  deliveryId.value = data.delivery_id || ''
  reportReady.value = !!data.report_ready
  if (changed && data.report_ready && data.draft) {
    publishName.value = data.draft.name || task.value?.task_name || ''
    publishDescription.value = data.draft.description || ''
    output.value = data.draft.output_description || ''
    schema.value = JSON.stringify(data.draft.input_schema || {}, null, 2)
    binding.value = data.draft.input_binding ? JSON.stringify(data.draft.input_binding, null, 2) : ''
    deliveryFrames.value = data.draft.dataframes || []
  }
}
const tabs = ['任务', '数据与指标', '搜索树', '交付与发布', '报告']
function downloadReport() {
  saveBlob(new Blob([snapshot.value?.auto_report?.report_markdown || ''], {
    type: 'text/markdown;charset=utf-8',
  }), `report-${props.id}.md`)
}
const stageLabels: Record<string, string> = {
  root: '搜索起点',
  draft: '初始方案',
  improve: '改进方案',
  debug: '修复方案',
  evolution: '方向演化',
  fusion_draft: '组合方案',
  fusion: '组合改进',
}
function stageName(value: unknown): string {
  const key = String(value || '').trim()
  return stageLabels[key] || (key ? '候选方案' : '待生成')
}
const task = computed<Task | undefined>(
  () => snapshot.value?.task || state.tasks.find((t) => t.id === props.id),
)
const workflow = computed(() => task.value ? taskWorkflow(task.value, state.task_deliveries?.[props.id]) : undefined)
const hasConfigBlockers = computed(() =>
  readiness.value?.checks?.some((c: any) =>
    ['python', 'autorealize', 'automl', 'report', 'autoRealize', 'autoMlCode', 'autoMlFeedback'].includes(c.key),
  ),
)
const hasOptionalReadinessChecks = computed(() =>
  readiness.value?.checks?.some((c: any) => c.status === 'warn'),
)
const taskGoal = computed(() => summarizeGoal(task.value?.config.auto_ml.goal || task.value?.config.auto_realize.task_hint))
const nodes = computed<any[]>(() => (snapshot.value?.auto_ml?.nodes || []).filter((n: any) => n.stage !== 'root'))
const splitSeedCheck = computed(() => snapshot.value?.auto_ml?.split_seed_check || { status: 'unverified' })
const webResearchItems = computed(() => {
  const config = task.value?.execution_config || task.value?.config
  return presentWebResearch(
    Boolean(config?.auto_ml?.web_research_enabled),
    snapshot.value?.auto_ml?.web_research_metrics,
  )
})
const node = computed(() => nodes.value.find((n) => n.id === selected.value) || nodes.value[0])
const nodeDetails = computed(() => detailSnapshot.value?.auto_ml?.nodes?.find((n: any) => n.id === node.value?.id))
const ar = computed(() => snapshot.value?.auto_realize || {})
const solutionPresentation = computed(() => {
  if (!solutionChecked.value) return { label: '尚未检查', tone: 'neutral', detail: '点击“检查成果”读取当前选定方案。' }
  if (solutionError.value && !solution.value) return { label: '检查失败', tone: 'warning', detail: solutionError.value }
  if (!solution.value?.available) {
    return {
      label: '暂时没有可交付方案',
      tone: 'warning',
      detail: solution.value?.issues?.[0] || '当前任务没有通过交付检查的方案。',
    }
  }
  if (solution.value.trial_ready && reportReady.value) {
    return { label: '可试算并发布', tone: 'success', detail: '结构检查和报告交付均已就绪，确认信息后即可发布模型包。' }
  }
  if (solution.value.trial_ready) {
    return { label: '可本地试算', tone: 'success', detail: '方案结构检查通过；报告交付完成后才能发布模型包。' }
  }
  return {
    label: '需要处理',
    tone: 'warning',
    detail: solution.value.issues?.[0] || '方案尚未满足本地试算条件。',
  }
})
const selectedNodePresentation = computed(() => {
  const selectedNode = solution.value?.node_id
    ? nodes.value.find((candidate) => candidate.id === solution.value.node_id)
    : undefined
  if (!selectedNode) return null
  const readiness = candidateReadiness(selectedNode)
  return {
    label: selectedNode.label || `候选方案 ${nodes.value.indexOf(selectedNode) + 1}`,
    metric: selectedNode.metric,
    readiness,
  }
})
const graph = computed(() => {
  const byId = new Map(nodes.value.map((n) => [n.id, n])),
    depths = new Map<string, number>()
  function depth(id: string, seen = new Set<string>()): number {
    if (depths.has(id)) return depths.get(id)!
    if (seen.has(id)) return 0
    seen.add(id)
    const n = byId.get(id)
    const d = n?.parent_id && byId.has(n.parent_id) ? Math.min(depth(n.parent_id, seen) + 1, 30) : 0
    depths.set(id, d)
    return d
  }
  const counts: Record<number, number> = {}
  const result = nodes.value.map((n) => {
    const d = depth(n.id)
    const row = counts[d] || 0
    counts[d] = row + 1
    return { ...n, x: 50 + d * 180, y: 45 + row * 88 }
  })
  return {
    nodes: result,
    width: Math.max(700, ...result.map((n) => n.x + 165)),
    height: Math.max(220, ...result.map((n) => n.y + 65)),
    edges: result
      .flatMap((n) =>
        (n.parent_ids || [n.parent_id])
          .filter(Boolean)
          .map((id: string) => ({ from: result.find((p) => p.id === id), to: n })),
      )
      .filter((e) => e.from),
  }
})
let timer: ReturnType<typeof setTimeout> | undefined,
  disposed = false,
  activeSnapshot = 0,
  activeSolution = 0,
  loadSequence = 0
function clearPoll() {
  if (timer) clearTimeout(timer)
  timer = undefined
}
async function load() {
  if (activeSnapshot || disposed) return
  const id = props.id
  const section = tab.value === 1 ? 'data' : tab.value === 4 ? 'report' : 'overview'
  const sequence = ++loadSequence
  activeSnapshot = sequence
  try {
    const s = await request(`/tasks/${id}/snapshot?view=summary&section=${section}`, undefined, 'GET', { timeoutMs: 25000 })
    if (disposed || id !== props.id || activeSnapshot !== sequence) return
    const wasRunning = snapshot.value?.task?.status === 'running'
    snapshot.value = s
    error.value = ''
    if (s.task.status === 'failed') {
      const key = `${id}:${s.task.updated_at}:${s.task.phase}`
      if (key !== recoveryKey) {
        recoveryKey = key
        recoveryGate.value = undefined
        recoveryError.value = ''
        try {
          const gate = await request(`/tasks/${id}/automl-readiness`, undefined, 'GET', { timeoutMs: 20000 })
          if (!disposed && id === props.id && recoveryKey === key) recoveryGate.value = gate
        } catch (e) {
          if (!disposed && id === props.id && recoveryKey === key)
            recoveryError.value = e instanceof Error ? e.message : String(e)
        }
      }
    } else {
      recoveryKey = ''
      recoveryGate.value = undefined
      recoveryError.value = ''
    }
    if (disposed || id !== props.id || activeSnapshot !== sequence) return
    if (!publishName.value) publishName.value = s.task.task_name
    if (wasRunning && s.task.status !== 'running') {
      solutionChecked.value = false
      solutionError.value = ''
    }
  } catch (e) {
    if (!disposed && id === props.id && activeSnapshot === sequence)
      error.value = e instanceof Error ? e.message : String(e)
  } finally {
    if (activeSnapshot === sequence) activeSnapshot = 0
    const currentSection = tab.value === 1 ? 'data' : tab.value === 4 ? 'report' : 'overview'
    if (!disposed && id === props.id && currentSection !== section) void load()
  }
}
async function recheckRecovery() {
  recoveryKey = ''
  await load()
}
async function loadDetails(event: Event) {
  if (!(event.target instanceof HTMLDetailsElement) || !event.target.open || detailsLoading.value || disposed) return
  const id = props.id
  detailsLoading.value = true
  detailsError.value = ''
  try {
    const result = await request(`/tasks/${id}/snapshot?view=full`, undefined, 'GET', { timeoutMs: 25000 })
    if (!disposed && props.id === id) detailSnapshot.value = result
  } catch (e) {
    if (!disposed && props.id === id) detailsError.value = e instanceof Error ? e.message : String(e)
  } finally {
    if (props.id === id) detailsLoading.value = false
  }
}
async function inspectSolution() {
  if (activeSolution || disposed || task.value?.status === 'running') return
  const id = props.id,
    sequence = ++loadSequence
  const hadPreviousResult = solutionChecked.value && solution.value !== undefined
  activeSolution = sequence
  solutionLoading.value = true
  if (!hadPreviousResult) solutionChecked.value = false
  solutionError.value = ''
  try {
    const result = await request(
      `/tasks/${id}/solution`,
      undefined,
      'GET',
      {
        timeoutMs: 45000,
        timeoutMessage: '成果检查超时，尚未确认方案状态。可以重试检查；本次读取不会修改任务。',
      },
    )
    if (disposed || id !== props.id || activeSolution !== sequence) return
    solution.value = result
    solutionChecked.value = true
  } catch (e) {
    if (!disposed && id === props.id && activeSolution === sequence) {
      solutionError.value = e instanceof Error ? e.message : String(e)
      solutionChecked.value = hadPreviousResult
    }
  } finally {
    if (activeSolution === sequence) {
      activeSolution = 0
      solutionLoading.value = false
    }
  }
}
async function refreshTask() {
  await load()
}
async function poll() {
  clearPoll()
  if (disposed || document.hidden || task.value?.status !== 'running') return
  timer = setTimeout(async () => {
    await load()
    poll()
  }, 5000)
}
function onVisibilityChange() {
  clearPoll()
  if (!document.hidden) void load().then(poll)
}
onMounted(async () => {
  document.addEventListener('visibilitychange', onVisibilityChange)
  await load()
  if (props.initialTab === 3) void inspectSolution()
  poll()
})
onUnmounted(() => {
  disposed = true
  loadSequence++
  clearPoll()
  document.removeEventListener('visibilitychange', onVisibilityChange)
})
watch(() => task.value?.status, poll)
watch(tab, (value) => { void load(); if (value === 3 && !solutionChecked.value) void inspectSolution() })
watch(
  () => props.id,
  () => {
    clearPoll()
    loadSequence++
    activeSnapshot = 0
    activeSolution = 0
    solutionLoading.value = false
    solutionChecked.value = false
    solutionError.value = ''
    snapshot.value = undefined
    detailSnapshot.value = undefined
    detailsError.value = ''
    detailsLoading.value = false
    solution.value = undefined
    publishName.value = ''
    publishDescription.value = ''
    output.value = ''
    schema.value = '{}'
    binding.value = ''
    reviewed.value = false
    deliveryId.value = ''
    reportReady.value = false
    deliveryFrames.value = []
    pending.value = ''
    selected.value = ''
    void load().then(poll)
  },
)
const actionNames: Record<string, string> = {
  start: '启动研发任务',
  resume: '恢复原实验',
  stop: '停止并保留进度',
  'start-automl': '从已有合同启动搜索',
  'continue-automl': '继续搜索',
  'rerun-autoreport': '生成报告与交付包',
  'recover-report': '修复报告交付',
  'repair-review-and-resume': '修复审查并继续',
}
async function prepare(action: string) {
  await run('check', async () => {
    pending.value = ''
    readiness.value = null
    inputReadiness.value = null
    repairPlan.value = null
    if (action === 'start' || action === 'resume')
      readiness.value = await request(`/system/readiness?task_id=${props.id}`)
    if (action === 'start-automl')
      inputReadiness.value = await request(`/tasks/${props.id}/automl-readiness`)
    if (action === 'repair-review-and-resume')
      repairPlan.value = await request(`/tasks/${props.id}/review-repair-plan`)
    pending.value = action
  })
}
async function recheckReadiness() {
  await run('check', async () => {
    readiness.value = await request(`/system/readiness?task_id=${props.id}`)
  })
}
async function probeReadiness(role: string) {
  await run('probe', async () => {
    await request('/system/probe-model', { role, capability: role === 'autoRealize' ? 'image' : 'text' })
    readiness.value = await request(`/system/readiness?task_id=${props.id}`)
    toast(role === 'autoRealize' ? '图像请求测试通过' : '连接测试通过')
  })
}
async function saveInputRoot() {
  if (!task.value) return
  await run('task-input', async () => {
    await request(`/studio/tasks/${props.id}`, { ...task.value!.config, input_root: inputRoot.value }, 'PUT')
    await refresh()
    await load()
    readiness.value = await request(`/system/readiness?task_id=${props.id}`)
    editingInput.value = false
    toast('数据目录已更新')
  })
}
async function act() {
  await run('task-action', async () => {
    const endpoint: Record<string, string> = {
      start: '/tasks/start',
      resume: '/tasks/resume',
      stop: '/tasks/stop',
      'start-automl': '/tasks/start-automl',
      'continue-automl': '/tasks/continue-automl',
      'rerun-autoreport': '/tasks/rerun-autoreport',
      'recover-report': '/tasks/recover-report',
      'repair-review-and-resume': '/tasks/repair-review-and-resume',
    }
    await request(endpoint[pending.value], {
      task_id: props.id,
      ...(['stop', 'start-automl', 'rerun-autoreport', 'recover-report', 'repair-review-and-resume'].includes(
        pending.value,
      )
        ? { confirm: true }
        : {}),
      ...(repairPlan.value ? { plan_token: repairPlan.value.plan_token } : {}),
    })
    pending.value = ''
    toast('任务操作已提交，状态以后台回报为准')
    await refresh()
    await load()
  })
}
async function experiment() {
  await run('experiment', async () => {
    const t = await request(`/studio/tasks/${props.id}/experiment`, {})
    await refresh()
    emit('open', 'task', t.id)
  })
}
async function publish() {
  await run('publish', async () => {
    const link = state.links.find((l) => l.id === props.id)
    if (!link) throw new Error('请先将任务导入数据项目')
    const p = await request('/studio/packages', {
      project_id: link.project_id,
      task_id: props.id,
      delivery_id: deliveryId.value,
      dataframes: deliveryFrames.value,
      name: publishName.value,
      description: publishDescription.value,
      input_schema: JSON.parse(schema.value),
      input_binding: binding.value.trim() ? JSON.parse(binding.value) : null,
      output_description: output.value,
    })
    await refresh()
    toast('模型包已发布，可以在决策对话中复用')
    emit('open', 'package', p.id)
  })
}
</script>
<template>
  <div class="live-detail" v-if="task">
    <ResourceStorage kind="tasks" :id="id" />
    <div class="detail-hero">
      <span class="hero-icon blue"><Icon name="branch" :size="28" /></span>
      <div>
        <div class="eyebrow">
          <span
            class="tag"
            :class="task.status === 'completed' ? workflow?.tone : task.status === 'running' ? 'info' : 'neutral'"
            >{{ task.status === 'completed' ? workflow?.label : status(task.status) }}</span
          >
        </div>
        <h2>{{ task.task_name }}</h2>
        <p class="task-summary">{{ summarizeGoal(taskGoal, 100) }}</p>
      </div>
    </div>
    <div class="detail-actions">
      <span class="tag neutral">当前阶段：{{ phase(task.phase) }}</span
      ><button
        v-if="task.status === 'idle' && !task.run_dir"
        class="btn primary small"
        :disabled="!!ui.busy"
        @click="prepare('start')"
      >
        检查并启动</button
      ><button
        v-else-if="task.status === 'running'"
        class="btn secondary small"
        :disabled="!!ui.busy || String(task.phase || '').includes('stopping')"
        @click="prepare('stop')"
      >
        {{ String(task.phase || '').includes('stopping') ? '正在停止…' : '停止并保留进度' }}</button
      ><button
        v-else-if="task.status === 'failed' && recoveryGate?.can_repair_review"
        class="btn primary small"
        :disabled="!!ui.busy"
        @click="prepare('repair-review-and-resume')"
      >
        修复审查并继续</button
      ><button
        v-else-if="task.status !== 'completed'"
        class="btn primary small"
        :disabled="!!ui.busy"
        @click="prepare('resume')"
      >
        恢复原实验</button
      ><button class="btn secondary small" :disabled="!!ui.busy" @click="experiment">
        新建实验，保留历史</button
      ><button class="btn secondary small" @click="refreshTask">刷新状态</button>
    </div>
    <TaskNextStep :task="task" @open="(kind, id) => kind === 'delivery' ? (tab = 3) : emit('open', kind, id)" />
    <section v-if="task.status === 'failed'" class="live-panel" aria-label="任务恢复">
      <h3>本次运行需要处理</h3>
      <p>{{ summarizeGoal(task.last_error || '运行未完成，请检查当前阶段后恢复。', 240) }}</p>
      <p v-if="recoveryGate?.can_repair_review">已有任务材料可以就地修复。系统会保留历史记录，重新审查通过后继续研发。</p>
      <p v-else-if="recoveryGate && !recoveryGate.ready">{{ summarizeGoal(recoveryGate.detail, 320) }}</p>
      <p v-if="recoveryError" class="live-error" role="alert">恢复条件读取失败：{{ recoveryError }}</p>
      <div class="form-actions">
        <button v-if="task.phase === 'report_failed'" type="button" class="btn primary small" :disabled="!!ui.busy" @click="prepare('rerun-autoreport')">重新生成报告与交付包</button>
        <button v-else-if="recoveryGate?.can_repair_review" type="button" class="btn primary small"
          :disabled="!!ui.busy" @click="prepare('repair-review-and-resume')">修复审查并继续</button>
        <button v-else type="button" class="btn primary small" :disabled="!!ui.busy" @click="prepare('resume')">检查配置并恢复</button>
        <button type="button" class="btn secondary small" @click="tab = 1">查看数据与指标</button>
        <button v-if="String(task.phase || '').includes('automl') || String(task.phase || '').includes('report')"
          type="button" class="btn secondary small" @click="tab = 3">查看评估与交付问题</button>
        <button type="button" class="btn secondary small" :disabled="!!ui.busy" @click="recheckRecovery">重新检查恢复条件</button>
      </div>
    </section>
    <div v-if="error" class="live-error" role="alert">
      <div>
        <strong>任务详情暂时无法读取</strong>
        <p>{{ error }}</p>
      </div>
      <button class="btn secondary small" @click="refreshTask">重试读取</button>
    </div>
    <details v-if="task.last_error" class="live-panel">
      <summary>查看最近一次运行的问题</summary>
      <p>{{ summarizeGoal(task.last_error, 600) }}</p>
    </details>
    <div v-if="snapshot?.snapshot_errors && Object.keys(snapshot.snapshot_errors).length" class="live-error">
      {{ humanSnapshotError(snapshot.snapshot_errors) }}
      <details>
        <summary>问题详情</summary>
        <pre>{{ JSON.stringify(snapshot.snapshot_errors, null, 2) }}</pre>
      </details>
    </div>
    <section v-if="pending" class="live-panel confirmation-panel">
      <h3>确认{{ actionNames[pending] }}</h3>
      <p>
        {{
          pending === 'stop'
            ? '尝试保留检查点；可恢复性以停止后后端返回为准。'
            : pending === 'rerun-autoreport'
              ? '使用已有研发结果生成报告、交付说明与调用合同，产生模型 API 费用。'
              : '本操作会启动本地计算与已配置模型请求，可能产生 API 费用。恢复使用冻结的原配置。'
        }}
      </p>
      <div v-if="readiness">
        <p v-if="!readiness.ready" class="live-error" role="alert">尚不能启动，请先处理下方标记为“需处理”的项目，再重新检查。</p>
        <p v-if="hasOptionalReadinessChecks" class="hint">标记为“可选”的检查不会阻止启动；只需处理“需处理”项。</p>
        <div v-for="c in readiness.checks" :key="c.key" class="check-row">
          <span
            class="tag"
            :class="c.status === 'fail' ? 'warning' : c.status === 'pass' ? 'success' : 'neutral'"
            >{{ c.status === 'pass' ? '就绪' : c.status === 'fail' ? '需处理' : c.status === 'warn' ? '可选' : '待确认' }}</span
          >
          <div>
            <strong>{{ c.label }}</strong>
            <p>{{ c.detail }}</p>
            <template v-if="c.status !== 'pass'">
              <div class="form-actions">
                <button v-if="['autoRealize', 'autoMlCode', 'autoMlFeedback'].includes(c.key)"
                  type="button" class="btn secondary small" :disabled="!!ui.busy" @click="probeReadiness(c.key)">
                  {{ c.key === 'autoRealize' ? '测试图像输入' : '测试连接' }}
                </button>
                <button v-if="c.key === 'storage'" type="button" class="btn secondary small" @click="emit('navigate', 'storage')">打开本地存储</button>
                <button v-if="c.key === 'input' && !task.run_dir && task.status === 'idle'"
                  type="button" class="btn secondary small" @click="inputRoot = task.input_root; editingInput = !editingInput">修改数据目录</button>
                <button v-if="c.key === 'target'" type="button" class="btn secondary small" :disabled="!!ui.busy" @click="experiment">新建独立实验</button>
              </div>
              <p v-if="c.key === 'autoRealize'" class="hint">测试会向所选模型发送一张系统生成的小图片，可能产生 API 费用，不读取项目文件。</p>
              <p v-else-if="c.key === 'autoMlCode' || c.key === 'autoMlFeedback'" class="hint">连接测试会调用所选模型，可能产生 API 费用，不读取项目文件。</p>
              <p v-else-if="c.key === 'input'">也可在本机恢复上述原目录，然后重新检查。已有运行的任务使用冻结配置，不能直接更改目录。</p>
              <p v-else-if="c.key === 'storage'">请在本地存储中核对并整理不再需要的输出文件，或修复目录写入权限，然后重新检查。删除操作仍需单独核对确认。</p>
              <p v-else-if="['autorealize', 'automl', 'report'].includes(c.key)">请检查本地运行器是否启动，或修改下方服务地址。</p>
              <form v-if="c.key === 'input' && editingInput" class="live-form" @submit.prevent="saveInputRoot">
                <label>项目内的数据目录<input v-model="inputRoot" required /></label>
                <div class="form-actions"><button class="btn primary small" :disabled="!!ui.busy">保存目录并重新检查</button><button type="button" class="btn secondary small" @click="editingInput = false">取消</button></div>
              </form>
            </template>
          </div>
        </div>
        <button v-if="hasConfigBlockers" type="button" class="btn secondary small" @click="inlineSettings = !inlineSettings">{{ inlineSettings ? '收起运行设置' : '打开运行设置' }}</button>
        <button type="button" class="btn secondary small" :disabled="!!ui.busy" @click="recheckReadiness">重新检查启动条件</button>
        <p v-if="readiness && !readiness.ready" class="hint">已列出的“需处理”项都提供了就地处理入口；完成后点击“重新检查启动条件”，系统会重新判定是否可以启动。</p>
        <div v-if="inlineSettings" class="inline-readiness-settings"><Settings /><button type="button" class="btn secondary small" :disabled="!!ui.busy" @click="recheckReadiness">保存设置后重新检查</button></div>
        <p>{{ readiness.data_policy }}</p>
      </div>
      <div v-if="inputReadiness && !inputReadiness.ready" class="live-panel" role="alert">
        <h4>任务材料尚未就绪</h4>
        <p>{{ summarizeGoal(inputReadiness.detail, 480) }}</p>
        <div class="form-actions">
          <button v-if="inputReadiness.can_repair_review" type="button" class="btn primary small"
            :disabled="!!ui.busy" @click="prepare('repair-review-and-resume')">修复审查并继续</button>
          <button type="button" class="btn secondary small" @click="tab = 1">查看数据与指标</button>
          <button v-if="!inputReadiness.can_repair_review" type="button" class="btn secondary small"
            :disabled="!!ui.busy" @click="experiment">新建实验并补充需求</button>
          <button type="button" class="btn secondary small" :disabled="!!ui.busy" @click="prepare('start-automl')">重新检查任务材料</button>
        </div>
      </div>
      <div v-if="repairPlan" class="check-row">
        <span class="tag warning">需确认</span>
        <div>
          <strong>将修复以下任务材料</strong>
          <ul>
            <li v-for="path in repairPlan.replace_paths || []" :key="path">
              {{ path.split(/[\\/]/).slice(-2).join('/') }}
            </li>
          </ul>
          <details>
            <summary>技术详情</summary>
            <pre>{{ JSON.stringify(repairPlan, null, 2) }}</pre>
          </details>
        </div>
      </div>
      <div class="form-actions">
        <button class="btn secondary small" @click="pending = ''">取消</button
        ><button
          class="btn primary small"
          :disabled="!!ui.busy || (readiness && !readiness.ready) || (inputReadiness && !inputReadiness.ready)"
          @click="act"
        >
          确认{{ actionNames[pending] }}
        </button>
      </div>
    </section>
    <ResearchProgress :task="task" :nodes="nodes" :best-id="snapshot?.auto_ml?.best_node_id" />
    <nav class="live-tabs task-detail-tabs">
      <button v-for="(t, i) in tabs" :key="t" :class="{ active: tab === i }" @click="tab = i">
        {{ t }}
      </button>
    </nav>
    <template v-if="tab === 0"
      ><EvaluationCriteria :evaluation="ar.evaluation" :requested="task.config.auto_ml.eval" />
      <div class="live-grid two">
        <section class="live-panel">
          <h3>任务目标与资源</h3>
          <details class="task-requirements">
            <summary>查看完整研发需求</summary>
            <p>{{ task.config.auto_realize.task_hint || task.config.auto_ml.goal || '未填写额外目标' }}</p>
          </details>
          <dl class="live-dl">
            <dt>数据范围</dt>
            <dd>{{ task.input_root.split(/[\\/]/).slice(-2).join('/') }}</dd>
            <dt>搜索上限</dt>
            <dd>
              {{ task.config.auto_ml.steps }} 次尝试 · 最长
              {{ task.config.auto_ml.time_limit_secs / 60 }} 分钟
            </dd>
            <dt>资源</dt>
            <dd>{{ taskResourceSummary(task.config.resources) }}</dd>
            <dt>方案数量</dt>
            <dd>
              {{ nodes.length }} 条候选记录 ·
              {{ nodes.filter((n) => n.search_eligible && !n.is_buggy).length }} 个可比较
            </dd>
          </dl>
        </section>
      </div>
      <details class="live-panel" @toggle="loadDetails">
        <summary>高级操作</summary>
        <div class="form-actions">
          <button
            v-for="action in [
              'start-automl',
              'continue-automl',
              'rerun-autoreport',
              'recover-report',
              'repair-review-and-resume',
            ]"
            :key="action"
            class="btn secondary small"
            :disabled="!!ui.busy || task.status === 'running'"
            @click="prepare(action)"
          >
            {{ actionNames[action] }}
          </button>
        </div>
        <details v-if="detailSnapshot?.automl_readiness">
          <summary>启动检查记录</summary>
          <pre>{{ JSON.stringify(detailSnapshot.automl_readiness, null, 2) }}</pre>
        </details>
        <p class="hint">恢复操作沿用已保存的任务配置。</p>
      </details></template
    >
    <template v-else-if="tab === 1"
      ><EvaluationCriteria :evaluation="ar.evaluation" :requested="task.config.auto_ml.eval" />
      <div class="live-grid two">
        <section class="live-panel">
          <h3>任务说明</h3>
          <MarkdownView v-if="ar.description_text" :text="ar.description_text" />
          <p v-else>任务说明将在数据分析完成后生成。</p>
        </section>
        <section class="live-panel">
          <h3>当前进度</h3>
          <p>{{ phase(task.phase) }} · {{ status(task.status) }}</p>
          <p v-if="task.last_error" class="live-error">{{ summarizeGoal(task.last_error, 240) }}</p>
        </section>
      </div>
      <section class="live-panel">
        <h3>数据概况</h3>
        <MarkdownView v-if="ar.data_description_text" :text="ar.data_description_text" />
        <p v-else>数据概况将在分析完成后生成。</p>
      </section>
      <details class="live-panel developer-details" @toggle="loadDetails">
        <summary>研发记录</summary>
        <p v-if="detailsLoading" role="status">正在读取详情…</p>
        <p v-if="detailsError" class="live-error" role="alert">{{ detailsError }}</p>
        <details
        v-for="key in [
          'data_cognition_report',
          'question_investigation_report',
          'task_definition_report',
          'main_task_protocol',
          'evaluation_contract_report',
          'artifact_consistency_report',
          'automl_context_pack',
        ]"
        :key="key"
        class="live-panel"
      >
        <summary>{{ humanArtifactLabel(key) }}</summary>
        <pre>{{ JSON.stringify(detailSnapshot?.auto_realize?.[key] || {}, null, 2) }}</pre>
      </details>
      </details></template
    >
    <template v-else-if="tab === 2"
      ><section v-if="webResearchItems" class="web-research-summary" aria-label="网页检索结果">
        <h3>公开资料</h3>
        <dl><template v-for="item in webResearchItems" :key="item.label"><dt>{{ item.label }}</dt><dd>{{ item.value }}</dd></template></dl>
      </section>
      <div class="panel-heading">
        <div>
          <h3>方案搜索</h3>
          <p v-if="splitSeedCheck.status === 'mismatch'" class="live-error">
            评价数据的划分与任务要求不一致，暂不比较候选分数。
          </p>
          <p v-else-if="splitSeedCheck.status === 'unverified'" class="hint">
            评价数据的划分尚未核对，候选指标暂供参考。
          </p>
          <p v-else-if="snapshot?.auto_ml?.best_node_id">
            当前最佳方案：第 {{ nodes.findIndex((n) => n.id === snapshot.auto_ml.best_node_id) + 1 }} 个 · 指标
            {{ formatMetric(nodes.find((n) => n.id === snapshot.auto_ml.best_node_id)?.metric) }}
          </p>
        </div>
        <span class="tag neutral">{{ nodes.filter((n) => n.search_eligible && !n.is_buggy).length }} 个可比较</span>
      </div>
      <div v-if="!nodes.length" class="live-empty">搜索尚未产生节点。</div>
      <template v-else
        ><div class="real-tree">
          <svg :width="graph.width" :height="graph.height" role="img" aria-label="实际候选程序搜索树">
            <path
              v-for="(edge, i) in graph.edges"
              :key="i"
              :d="`M${edge.from.x + 140},${edge.from.y + 22} C${edge.from.x + 165},${edge.from.y + 22} ${edge.to.x - 30},${edge.to.y + 22} ${edge.to.x},${edge.to.y + 22}`"
              fill="none"
              stroke="var(--tree-line, #8ba4c7)"
              stroke-width="1.5"
            />
            <g
              v-for="(n, i) in graph.nodes"
              :key="n.id"
              :transform="`translate(${n.x},${n.y})`"
              class="real-node"
              tabindex="0"
              role="button"
              :aria-label="`候选 ${i + 1} ${stageName(n.stage)}`"
              @click="selected = n.id"
              @keydown.enter="selected = n.id"
              @keydown.space.prevent="selected = n.id"
            >
              <rect
                width="140"
                height="48"
                rx="8"
                :fill="node?.id === n.id ? '#203e67' : '#14243d'"
                :stroke="n.is_buggy ? '#a67b61' : node?.id === n.id ? '#66d7ed' : '#3b526d'"
              />
              <text x="10" y="19">候选 {{ i + 1 }} · {{ stageName(n.stage) }}</text>
              <text x="10" y="36" class="node-score">
                {{
                  n.is_buggy || n.runtime_ok === false
                    ? candidateReadiness(n).label
                    : splitSeedCheck.status === 'mismatch'
                      ? '合同不匹配'
              : formatMetric(n.metric)
                }}
              </text>
            </g>
          </svg>
        </div>
        <section v-if="node" class="live-panel">
          <div class="panel-heading">
            <h3>候选方案 {{ nodes.findIndex((n) => n.id === node.id) + 1 }} · {{ stageName(node.stage) }}</h3>
            <span
              v-if="splitSeedCheck.status !== 'mismatch'"
              class="tag"
              :class="candidateReadiness(node).tone"
            >
              {{ candidateReadiness(node).label }}
              <span v-if="node.metric != null"> · {{ formatMetric(node.metric) }}</span>
            </span>
          </div>
          <div class="live-grid two">
            <div>
              <h3>方案说明</h3>
              <MarkdownView :text="candidatePlan(node)" />
            </div>
            <div>
              <h3>运行结果</h3>
              <p>
                {{
                  candidateSummary(node)
                }}
              </p>
              <p v-if="node.exec_time" class="hint">单次运行 {{ formatDuration(node.exec_time) }}</p>
              <details @toggle="loadDetails">
                <summary>查看方案代码</summary>
                <p v-if="detailsLoading" role="status">正在读取详情…</p>
                <p v-else-if="detailsError" class="live-error" role="alert">{{ detailsError }}</p>
                <pre v-else class="code-block">{{ nodeDetails?.code || '尚无代码' }}</pre>
              </details>
              <details class="developer-details" @toggle="loadDetails">
                <summary>方案检查记录</summary>
                <pre>{{
                  JSON.stringify(
                    {
                      evaluation_protocol: nodeDetails?.evaluation_protocol,
                      decision_signals: nodeDetails?.decision_signals,
                      delivery_ready: node.delivery_ready,
                      delivery_certified: node.delivery_certified,
                      certification_source: nodeDetails?.certification_source,
                      fusion_sources: nodeDetails?.fusion_sources,
                    },
                    null,
                    2,
                  )
                }}</pre>
              </details>
            </div>
          </div>
        </section></template
      >
      <details class="live-panel developer-details" @toggle="loadDetails">
        <summary>运行记录</summary>
        <pre>{{
          JSON.stringify(
            { resource_usage: detailSnapshot?.auto_ml?.resource_usage, events: detailSnapshot?.auto_ml?.events },
            null,
            2,
          )
        }}</pre>
      </details></template
    >
    <template v-else-if="tab === 3">
      <section class="live-panel">
        <div class="panel-heading">
          <div>
            <h3>选定方案</h3>
            <p v-if="selectedNodePresentation" class="panel-subtitle">
              {{ selectedNodePresentation.label }}
              <span v-if="selectedNodePresentation.metric != null"> · 开发指标 {{ selectedNodePresentation.metric }}</span>
            </p>
          </div>
          <button
            class="btn secondary small"
            :disabled="solutionLoading || task.status === 'running'"
            @click="inspectSolution"
          >
            {{
              solutionLoading
                ? '检查中…'
                : solutionError
                  ? '重试检查'
                  : solutionChecked
                    ? '重新检查'
                    : '检查成果'
            }}
          </button>
        </div>
        <div v-if="solutionChecked && solution" class="solution-status-card" :class="`tone-${solutionPresentation.tone}`">
          <span class="solution-status-mark">
            <Icon :name="solutionPresentation.tone === 'success' ? 'checkCircle' : solutionPresentation.tone === 'warning' ? 'alert' : 'info'" :size="18" />
          </span>
          <div>
            <strong>{{ solutionPresentation.label }}</strong>
            <p>{{ solutionPresentation.detail }}</p>
          </div>
        </div>
        <p v-if="solutionLoading" role="status">{{ solutionChecked ? '正在复核；下方保留上次结果。' : '正在检查成果…' }}</p>
        <p v-else-if="task.status === 'running'">研发完成后可以检查和试算成果。</p>
        <p v-else-if="solutionError" class="live-error" role="alert">{{ solutionChecked ? `重新检查失败，仍显示上次检查结果：${solutionError}` : solutionError }}</p>
        <p v-else-if="!solutionChecked">尚未检查成果。</p>
        <p v-for="issue in solution?.issues" :key="issue" class="hint">{{ issue }}</p>
        <dl v-if="solution?.available" class="solution-facts">
          <div><dt>当前方案</dt><dd>{{ selectedNodePresentation?.label || '已选方案' }}</dd></div>
          <div><dt>下一步</dt><dd>{{ solution?.trial_ready ? (reportReady ? '核对发布信息' : '等待报告交付') : '处理待办后重新检查' }}</dd></div>
          <div><dt>报告状态</dt><dd>{{ humanReportStatus(reportReady ? 'ready' : 'not_ready') }}</dd></div>
        </dl>
        <details class="developer-details">
          <summary>方案检查记录</summary>
          <pre>{{
            JSON.stringify(
              {
                node_id: solution?.node_id,
                trial_ready: solution?.trial_ready,
                manifest: solution?.manifest,
                verification: solution?.verification,
              },
              null,
              2,
            )
          }}</pre>
        </details>
        <details v-if="solution?.usage" class="developer-details">
          <summary>运行说明原文</summary>
          <pre>{{ solution.usage }}</pre>
        </details>
      </section>
      <form
        v-if="solution?.trial_ready && reportReady"
        ref="publishForm"
        class="live-form live-panel"
        @submit.prevent="publish"
      >
        <h3>发布算法模型包</h3>
        <label>能力名称<input v-model="publishName" required maxlength="120" /></label
        ><label
          >用途与适用范围<textarea
            v-model="publishDescription"
            required
            rows="3"
            placeholder="供规划助手匹配能力；明确输入条件、用途和不能覆盖的场景"
          />
        </label>
        <details>
          <summary>高级输入约束（JSON Schema）</summary>
          <textarea v-model="schema" rows="6" spellcheck="false" />
        </details>
        <details><summary>技术详情 · 输出约定</summary><label>输出结构说明<textarea v-model="output" rows="3" /></label></details>
        <details>
          <summary>绑定项目时间序列数据（可选）</summary>
          <p class="hint">
            登记后，调用时可直接准备项目数据。截止时间、完整字段和窗口必须与该算法的输入合同一致。
          </p>
          <label
            >项目输入绑定 JSON<textarea
              v-model="binding"
              rows="7"
              spellcheck="false"
              placeholder='{"timezone":"Asia/Shanghai","cutoff_field":"prediction_cutoff","sources":[{"path":"设备.csv","field":"history","time_column":"SampleTime","columns":["SampleTime","蒸汽进气流量"],"window_seconds":3600}]}'
            />
          </label>
        </details>
        <label class="check-line"
          ><input
            v-model="reviewed"
            type="checkbox"
          />已核对方案、输入要求和验证结果，同意发布</label
        ><button class="btn primary" :disabled="!reviewed || !!ui.busy">发布模型包</button>
      </form></template
    >
    <template v-else
      ><section class="live-panel">
        <div class="panel-heading">
          <h3>AutoReport 报告</h3>
          <button
            v-if="snapshot?.auto_report?.report_markdown"
            class="btn secondary small"
            @click="downloadReport"
          >
            下载报告
          </button>
        </div>
        <MarkdownView v-if="snapshot?.auto_report?.report_markdown" :text="snapshot.auto_report.report_markdown" />
        <p v-else>尚无报告正文。搜索完成后可生成或恢复报告。</p>
      </section>
      <details class="live-panel developer-details" @toggle="loadDetails">
        <summary>报告记录</summary>
        <pre>{{
          JSON.stringify(
            { state: detailSnapshot?.auto_report?.current_state, report: detailSnapshot?.auto_report?.report },
            null,
            2,
          )
        }}</pre>
      </details></template
    >
    <DeliveryPanel
      v-if="deliveryVisited && task"
      v-show="tab === 3"
      :id="id"
      :running="task.status === 'running'"
      :input-root="task.input_root"
      @prepared="acceptDelivery"
      @report="prepare('rerun-autoreport')"
      @publish="showPublish"
    />
  </div>
  <p v-else-if="error" class="live-error">{{ error }}</p>
  <p v-else>正在读取任务快照…</p>
</template>
<style scoped>
.web-research-summary {
  padding: 14px 0;
  border-top: 1px solid var(--line);
  border-bottom: 1px solid var(--line);
  margin-bottom: 18px;
}
.web-research-summary h3 {
  margin: 0 0 8px;
  font-size: 13px;
}
.web-research-summary dl {
  display: grid;
  grid-template-columns: max-content minmax(0, 1fr);
  gap: 6px 16px;
  margin: 0;
  font-size: 12px;
}
.web-research-summary dt {
  color: var(--secondary);
}
.web-research-summary dd {
  min-width: 0;
  margin: 0;
  overflow-wrap: anywhere;
}
.task-summary {
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.panel-subtitle {
  margin: 4px 0 0;
  color: var(--secondary);
  font-size: 12px;
  font-weight: 400;
}
.solution-status-card {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  margin: 8px 0 16px;
  padding: 14px 16px;
  border: 1px solid var(--line);
  border-radius: 12px;
  background: #f8fafc;
}
.solution-status-card.tone-success {
  border-color: #b9ddc7;
  background: #f2fbf5;
  color: #1f6b3c;
}
.solution-status-card.tone-warning {
  border-color: #ead0ac;
  background: #fff9ef;
  color: #8a5c1d;
}
.solution-status-card.tone-neutral {
  color: var(--secondary);
}
.solution-status-mark {
  display: grid;
  place-items: center;
  flex: none;
  width: 28px;
  height: 28px;
  border-radius: 50%;
  background: #ffffffb8;
}
.solution-status-card strong {
  display: block;
  font-size: 14px;
}
.solution-status-card p {
  margin: 3px 0 0;
  color: inherit;
  font-size: 12px;
}
.solution-facts {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
  margin: 16px 0;
}
.solution-facts > div {
  min-width: 0;
  padding: 12px;
  border-radius: 10px;
  background: #f6f8fa;
}
.solution-facts dt {
  color: var(--secondary);
  font-size: 11px;
}
.solution-facts dd {
  margin: 4px 0 0;
  color: var(--ink);
  font-size: 13px;
  overflow-wrap: anywhere;
}
@media (max-width: 680px) {
  .solution-facts {
    grid-template-columns: 1fr;
  }
}
.task-requirements p {
  white-space: pre-wrap;
}
</style>
