import { computed, reactive, watch } from 'vue'
import { seedState } from './data'
import type {
  Conversation,
  Invocation,
  Message,
  ModelPackage,
  Page,
  Project,
  ResearchTask,
  Scenario,
  StudioState,
} from './types'

const KEY = 'autodecision.studio.demo.v1'
const pages: Page[] = ['chat', 'projects', 'packages', 'tasks', 'invocations', 'settings']
function restore(): StudioState {
  try {
    const raw = JSON.parse(localStorage.getItem(KEY) || 'null')
    if (
      raw?.schema === 1 &&
      ['projects', 'packages', 'tasks', 'invocations', 'conversations'].every((k) => Array.isArray(raw[k])) &&
      raw.projects.some((p: Project) => p.id === raw.projectId) &&
      raw.settings &&
      raw.conversations.some(
        (c: Conversation) => c.id === raw.conversationId && c.projectId === raw.projectId,
      )
    )
      return raw
  } catch {
    /* Invalid local demo state is replaced by the versioned seed. */
  }
  return seedState()
}
export const state = reactive<StudioState>(restore())
function hashPage(): Page {
  const name = location.hash.slice(1) as Page
  return pages.includes(name) ? name : 'chat'
}
export const ui = reactive({
  page: hashPage(),
  mobileNav: false,
  dialog: '' as '' | 'package' | 'invocation' | 'task' | 'create-project' | 'help' | 'data' | 'reset',
  detailId: '',
  toast: '',
  busyId: '',
  pinnedPackageId: '',
})
let toastTimer: ReturnType<typeof setTimeout>
let generation = 0
export function toast(message: string) {
  ui.toast = message
  clearTimeout(toastTimer)
  toastTimer = setTimeout(() => {
    ui.toast = ''
  }, 3800)
}
watch(
  state,
  () => {
    try {
      localStorage.setItem(KEY, JSON.stringify(state))
    } catch {
      toast('浏览器未能保存更改；当前会话仍可使用。')
    }
  },
  { deep: true },
)
window.addEventListener('hashchange', () => {
  ui.page = hashPage()
  ui.mobileNav = false
  closeDialog()
})
export const project = computed(() => state.projects.find((p) => p.id === state.projectId)!)
export const packages = computed(() => state.packages.filter((p) => p.projectId === state.projectId))
export const tasks = computed(() => state.tasks.filter((t) => t.projectId === state.projectId))
export const invocations = computed(() => state.invocations.filter((i) => i.projectId === state.projectId))
export const conversations = computed(() =>
  state.conversations.filter((c) => c.projectId === state.projectId),
)
export const conversation = computed(() => state.conversations.find((c) => c.id === state.conversationId)!)
export const runningCount = computed(
  () => tasks.value.filter((t) => t.status === 'running' || t.status === 'queued').length,
)
export function navigate(page: Page) {
  ui.page = page
  location.hash = page
  ui.mobileNav = false
  closeDialog()
}
export function openDialog(kind: typeof ui.dialog, id = '') {
  ui.dialog = kind
  ui.detailId = id
  ui.mobileNav = false
}
export function closeDialog() {
  ui.dialog = ''
  ui.detailId = ''
}
const id = (prefix: string) => `${prefix}-${crypto.randomUUID().slice(0, 8)}`
export const now = () => new Date().toLocaleString('sv-SE', { timeZone: 'Asia/Shanghai' }).slice(0, 16)
export function newConversation() {
  const c: Conversation = {
    id: id('conv'),
    projectId: state.projectId,
    title: '新的决策对话',
    messages: [],
    created: now(),
  }
  state.conversations.unshift(c)
  state.conversationId = c.id
  ui.pinnedPackageId = ''
  navigate('chat')
}
export function selectConversation(conversationId: string) {
  const c = state.conversations.find((c) => c.id === conversationId && c.projectId === state.projectId)
  if (c) {
    state.conversationId = c.id
    ui.pinnedPackageId = ''
    navigate('chat')
  }
}
export function selectProject(projectId: string) {
  if (!state.projects.some((p) => p.id === projectId)) return
  state.projectId = projectId
  ui.pinnedPackageId = ''
  closeDialog()
  const c = conversations.value[0]
  if (c) state.conversationId = c.id
  else newConversation()
}
export function createProject(name: string, industry: string) {
  if (!name.trim()) return
  const p: Project = {
    id: id('project'),
    name: name.trim(),
    short: name.trim(),
    industry,
    description: '新建的数据工作空间。先添加演示数据，再尝试提出需求。',
    icon: 'database',
    color: 'blue',
    snapshot: 'empty',
    tables: [],
  }
  state.projects.push(p)
  selectProject(p.id)
  navigate('projects')
  toast('已创建本地演示项目')
}
export function importDemoData() {
  if (project.value.tables.length) {
    toast('此项目已有演示数据，可在表详情中查看字段。')
    return
  }
  project.value.tables = structuredClone(seedState().projects[0].tables)
  project.value.snapshot = `demo-${Date.now()}`
  toast('已添加 3 张合成能源示例表；没有读取本机数据库')
}
export function usePackage(pkg: ModelPackage) {
  selectProject(pkg.projectId)
  newConversation()
  ui.pinnedPackageId = pkg.id
  closeDialog()
  toast(`已选择 ${pkg.name}，可以在对话中提出需求`)
}
export function getPackage(packageId: string) {
  return state.packages.find((p) => p.id === packageId)
}
export function getInvocation(invocationId?: string) {
  return state.invocations.find((i) => i.id === invocationId)
}

function resultFor(scenario: Scenario, p: Project, capability?: string): Invocation['result'] {
  if (scenario === 'compose')
    return [
      { label: '预计用电成本', value: '19,340', unit: '元', change: '较原计划 −12.8%' },
      { label: '预计节省', value: '2,840', unit: '元 / 日', change: '保持原定产量' },
      { label: '调度后峰值', value: '38.6', unit: 'MW', change: '原计划 44.3 MW' },
    ]
  if (scenario === 'anomaly')
    return [
      { label: '疑似异常时段', value: '3', unit: '处' },
      { label: '覆盖设备', value: '2', unit: '台' },
      { label: '最高异常分数', value: '0.92', unit: '/ 1.00' },
    ]
  if (scenario === 'research')
    return [
      {
        label: capability?.includes('寿命') ? '预计剩余寿命' : '模型输出样例',
        value: capability?.includes('寿命') ? '182' : '0.87',
        unit: capability?.includes('寿命') ? '小时' : '示例值',
      },
      { label: '输入检查', value: '通过', unit: '演示' },
      { label: '本次新增训练', value: '0', unit: '次' },
    ]
  return p.id === 'water'
    ? [
        { label: '预计供水总量', value: '12,640', unit: 'm³ / 日' },
        { label: '峰时需求', value: '684', unit: 'm³/h' },
        { label: '预测范围', value: '24', unit: '小时' },
      ]
    : [
        { label: '预计用电总量', value: '682.4', unit: 'MWh' },
        { label: '峰值负荷', value: '44.3', unit: 'MW' },
        { label: '预测范围', value: '24', unit: '小时' },
      ]
}
export function createInvocation(
  c: Conversation,
  scenario: Scenario,
  selected: ModelPackage[],
  aligned = false,
) {
  const p = state.projects.find((p) => p.id === c.projectId)!
  const inv: Invocation = {
    id: id('RUN').toUpperCase(),
    projectId: p.id,
    conversationId: c.id,
    title: scenario === 'compose' ? '明日负荷预测与错峰排产' : selected[0].name,
    packageIds: selected.map((p) => p.id),
    scenario,
    created: now(),
    duration: scenario === 'compose' ? '2.4 s' : '0.8 s',
    snapshot: p.snapshot,
    aligned,
    result: resultFor(scenario, p, selected[0].name),
    mapping: selected[0].input.map((f) => ({
      from:
        aligned && f.field === 'load_mw'
          ? 'new_readings.power_kw'
          : `${p.tables[0]?.name || 'input'}.${f.field}`,
      to: `${selected[0].entry.split('(')[0]}.${f.field}`,
      rule: aligned && f.field === 'load_mw' ? '÷ 1000 · kW → MW（已确认）' : '字段与合同对齐（模拟）',
    })),
  }
  if (scenario === 'compose')
    inv.mapping.push({
      from: 'forecast.predicted_load_mw',
      to: 'scheduler.load_forecast',
      rule: '上游输出 → 下游输入',
    })
  state.invocations.unshift(inv)
  selected.forEach((p) => p.calls++)
  c.messages.push({
    id: id('msg'),
    role: 'assistant',
    kind: 'result',
    text:
      scenario === 'compose'
        ? '可以复用当前项目的两个模型包。我已把负荷预测结果作为用能优化的输入，生成下面的方案。模型版本保持冻结，结果供业务审核。'
        : `已复用「${selected[0].name}」生成演示结果。输入对齐与包版本已记录，本次无需启动研发任务。`,
    invocationId: inv.id,
  })
  return inv
}
export async function sendMessage(text: string) {
  if (!text.trim() || ui.busyId) return
  const c = conversation.value
  const p = project.value
  const epoch = generation
  const pinned = getPackage(ui.pinnedPackageId)
  c.messages.push({ id: id('msg'), role: 'user', text: text.trim() })
  if (c.messages.length === 1) c.title = text.trim().slice(0, 24)
  ui.busyId = c.id
  await new Promise((resolve) => setTimeout(resolve, 650))
  if (epoch !== generation) return
  const available = state.packages.filter((pkg) => pkg.projectId === c.projectId)
  const reply = (m: Omit<Message, 'id' | 'role'>) =>
    c.messages.push({ id: id('msg'), role: 'assistant', ...m })
  if (!p.tables.length)
    reply({
      text: '这个项目还没有数据。请先在「数据项目」中添加演示数据，再定义要预测或优化的目标。',
      kind: 'clarify',
    })
  else if (pinned && pinned.projectId === c.projectId) {
    const chain =
      pinned.scenario === 'compose'
        ? available
            .filter((pkg) => pkg.scenario === 'forecast')
            .slice(0, 1)
            .concat(pinned)
        : [pinned]
    if (pinned.scenario === 'compose' && chain.length < 2)
      reply({
        text: '这个优化包需要上游预测结果，当前项目还缺少对应能力。',
        kind: 'research',
        capability: '生产负荷预测',
      })
    else createInvocation(c, pinned.scenario, chain)
  } else if (/字段|对齐|kW|kw|新表|单位|上传|缺失/.test(text)) {
    if (available.some((pkg) => pkg.id === 'pkg-load'))
      reply({
        text: '新表中的功率字段与模型输入合同不同。可以把 power_kw 转为 MW 后调用现有模型；请先确认单位。换算不会修改模型权重或训练特征。',
        kind: 'mapping',
      })
    else
      reply({
        text: '当前项目没有适用的单位对齐演示。可以先查看模型包的输入合同，或体验预测、组合、研发三个示例。',
        kind: 'clarify',
      })
  } else {
    let scenario: Scenario | undefined = /寿命|故障|泄漏|研发|新任务|新能力|冷轧/.test(text)
      ? 'research'
      : /排产|优化|电价|节省|错峰|调度/.test(text)
        ? 'compose'
        : /异常|监测/.test(text)
          ? 'anomaly'
          : /预测|负荷|用水|用电/.test(text)
            ? 'forecast'
            : undefined
    if (!scenario)
      reply({
        text: '此原型使用预设场景演示需求路由。你可以体验「预测下一日需求」「组合优化」「研发新能力」，或查看右侧现有能力。接入后端后，这一步才会由模型结合输入合同判断。',
        kind: 'clarify',
      })
    else {
      const selected =
        scenario === 'compose'
          ? ([
              available.find((pkg) => pkg.scenario === 'forecast'),
              available.find((pkg) => pkg.scenario === 'compose'),
            ].filter(Boolean) as ModelPackage[])
          : available.filter((pkg) => pkg.scenario === scenario).slice(0, 1)
      if (scenario === 'research' || selected.length < (scenario === 'compose' ? 2 : 1)) {
        const capability = /寿命/.test(text)
          ? '设备剩余寿命预测'
          : /泄漏/.test(text)
            ? '管网泄漏定位'
            : /冷轧/.test(text)
              ? '冷轧负荷预测'
              : scenario === 'compose' && p.id === 'water'
                ? '供水调度优化'
                : scenario === 'forecast'
                  ? '生产负荷预测'
                  : '新场景决策模型'
        const reusable = available.find((pkg) => pkg.name === capability)
        const existing = state.tasks.find(
          (t) => t.projectId === p.id && t.capability === capability && t.status !== 'completed',
        )
        if (reusable) createInvocation(c, reusable.scenario, [reusable])
        else
          reply({
            text: existing
              ? '这项能力已经在研发中，可以查看现有任务的进度，无需重复创建。'
              : '现有模型包的适用范围没有覆盖这项需求。建议发起一次研发任务，先确认目标与数据，再搜索和验证候选算法；通过审核后沉淀为可复用模型包。',
            kind: 'research',
            capability,
            taskId: existing?.id,
            resolved: !!existing,
          })
      } else createInvocation(c, scenario, selected)
    }
  }
  ui.busyId = ''
}
export function startResearch(message: Message) {
  if (message.resolved) return
  const t: ResearchTask = {
    id: id('AD').toUpperCase(),
    projectId: state.projectId,
    title: `${message.capability} · 能力研发`,
    target:
      conversation.value.messages.filter((m) => m.role === 'user').at(-1)?.text || message.capability || '',
    status: 'running',
    progress: 18,
    stage: 0,
    candidates: 0,
    budget: '16 候选 · 30 分钟',
    created: now(),
    capability: message.capability || '新决策模型',
  }
  state.tasks.unshift(t)
  message.taskId = t.id
  message.resolved = true
  toast('已创建演示研发任务，可在任务中心推进流程')
  openDialog('task', t.id)
}
export function confirmMapping(message: Message, unit: string) {
  if (message.resolved) return
  if (unit === 'kWh') {
    toast('kWh 是能量，不能直接映射为功率；需要采样时长与明确换算规则。')
    return
  }
  const pkg = packages.value.find((p) => p.id === 'pkg-load')
  if (!pkg) return
  message.resolved = true
  const inv = createInvocation(conversation.value, 'forecast', [pkg], unit === 'kW')
  if (unit === 'MW')
    inv.mapping[1] = {
      from: 'new_readings.power_kw（用户声明 MW）',
      to: 'predict.load_mw',
      rule: '仅重命名 · 已确认源单位为 MW',
    }
  toast('已确认输入对齐，并生成模拟调用结果')
}
export function advanceTask(task: ResearchTask) {
  if (task.status !== 'running') return
  if (task.stage === 0) {
    task.stage = 1
    task.progress = 36
    task.candidates = 0
  } else if (task.stage === 1) {
    task.stage = 2
    task.progress = 62
    task.candidates = 12
  } else if (task.stage === 2) {
    task.stage = 3
    task.progress = 88
    task.candidates = 16
  } else {
    task.stage = 4
    task.progress = 100
    task.status = 'completed'
  }
  toast(task.status === 'completed' ? '演示研发已完成；审核合同后可发布模型包' : '演示已推进到下一阶段')
}
export function toggleTask(task: ResearchTask) {
  task.status = task.status === 'running' ? 'paused' : 'running'
  toast(task.status === 'paused' ? '演示任务已暂停' : '演示任务已继续')
}
export function publishTask(task: ResearchTask) {
  if (task.status !== 'completed' || task.packageId) return
  const pkg: ModelPackage = {
    id: id('pkg'),
    projectId: task.projectId,
    name: task.capability,
    version: '1.0.0',
    kind: '决策模型',
    icon: 'box',
    description: `来自研发任务 ${task.id} 的可复用演示能力。实际输入合同与验证尚待后端实现。`,
    scenario: 'research',
    input: [
      {
        field: 'observations',
        type: 'table',
        unit: '按字段合同',
        required: true,
        description: '经审核的特征表（演示占位合同）',
      },
    ],
    output: 'prediction · confidence · checks',
    entry: 'predict(input: DecisionInput) → DecisionResult',
    artifact: `packages/${task.id.toLowerCase()}/1.0.0/model/model.pkl`,
    metric: '模拟开发评分',
    metricValue: '0.94',
    validation: '仅演示发布流程，没有真实训练、模型文件或生产验收。',
    taskId: task.id,
    calls: 0,
    tags: ['新能力', '演示发布', 'CPU'],
    runtime: 'Python 3.11（拟定环境）',
    parameters: '以最终冻结合同为准；当前为原型占位。',
    limits: '这个包仅存在浏览器演示状态中。真实发布必须经过训练、独立验证与输入合同审核。',
    created: now().slice(0, 10),
  }
  state.packages.unshift(pkg)
  task.packageId = pkg.id
  toast('新模型包已加入当前项目，可以返回对话复用')
  openDialog('package', pkg.id)
}
export function download(filename: string, data: unknown, type = 'application/json') {
  const blob = new Blob([typeof data === 'string' ? data : JSON.stringify(data, null, 2)], { type })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
  toast('已导出演示文件')
}
export function manifest(pkg: ModelPackage) {
  return {
    schema_version: 'demo-0.1.0',
    demo: true,
    id: pkg.id,
    name: pkg.name,
    version: pkg.version,
    project_id: pkg.projectId,
    entry: pkg.entry,
    artifact: pkg.artifact,
    input: pkg.input,
    output: pkg.output,
    runtime: pkg.runtime,
    parameters: pkg.parameters,
    immutable: ['weights', 'feature_order', 'preprocessor', 'input_semantics'],
    validation: { description: pkg.validation, metric: pkg.metric, value: pkg.metricValue },
    source_task: pkg.taskId,
  }
}
export function resetDemo() {
  generation++
  Object.assign(state, seedState())
  ui.busyId = ''
  ui.pinnedPackageId = ''
  closeDialog()
  navigate('chat')
  toast('演示已恢复到初始状态')
}
export const statusText = (status: ResearchTask['status']) =>
  ({ running: '运行中', paused: '已暂停', queued: '排队中', completed: '已完成' })[status]
export const stageNames = ['需求与意图', '数据与约束', '算法搜索', '独立验证', '报告与发布']
