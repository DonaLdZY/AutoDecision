import { computed, reactive } from 'vue'
import type { Task, GlobalSettings, SnapshotPayload } from '../../../ui/src/types'
import { formatDate, humanApiError } from './presentation'
import type { DeliveryOverview } from './taskWorkflow'
export type { Task, GlobalSettings, SnapshotPayload }
export interface Project {
  id: string
  name: string
  input_root: string
  description: string
  created_at: number
  color: string
  archived_at?: number
}
export interface Plan {
  action: 'clarify' | 'reuse' | 'research'
  reply: string
  goal: string
  steps: {
    package_id: string
    reason: string
    mappings?: { source: string; target: string; source_unit: string; target_unit: string }[]
    output_pointer?: string
  }[]
  missing_inputs: string[]
}
export interface Message {
  id: string
  role: string
  text: string
  plan?: Plan
  model?: string
  usage?: Record<string, unknown>
  invocation_id?: string
  context_scope?: string
  created_at?: number
  publication_candidates?: { task_id: string; task_name: string; delivery_id: string; verification_status: string }[]
}
export interface Conversation {
  id: string
  project_id: string
  task_ids?: string[]
  title: string
  messages: Message[]
  created_at?: number
  updated_at?: number
  archived_at?: number
}
export interface Package {
  id: string
  project_id: string
  task_id: string
  task_name?: string
  name: string
  version: string
  description: string
  created_at: number
  entrypoint: string
  input_schema: Record<string, unknown>
  dataframes?: { pointer: string; columns: string[] }[]
  input_binding?: {
    kind: 'time_window'
    include_cutoff?: boolean
    forecast?: { source_field: string; target_field: string } | null
    cutoff_field: string
    timezone: string
    sources: {
      path: string
      field: string
      time_column: string
      window_seconds: number
      lower_bound?: 'exclusive' | 'inclusive'
      aggregation?: { entity_column: string; distinct_column: string; entity_field: string; time_field: string; count_field: string; rows_field: string } | null
      columns: string[]
    }[]
  } | null
  output_description: string
  output_view?: { kind: string; fields: string[] }
  fingerprint: string
  verification_summary: string
  manifest: Record<string, unknown>
  files: { path: string; size: number }[]
  file_count?: number
  validation?: {
    trial_status: string
    trial_error?: string
    quality_status: string
    metrics?: Record<string, unknown>
    notes?: string[]
  }
  verification: Record<string, unknown>
  contracts?: Record<string, string>
  model_path?: string
}
export interface Invocation {
  id: string
  project_id: string
  conversation_id: string
  title: string
  status: string
  package_ids: string[]
  created_at: number
  duration_seconds?: number
  error?: string
  error_summary?: string
  result?: unknown
  answer?: string
  decision_facts?: unknown
  decision_program?: {
    code: string
    model: string
    usage: Record<string, unknown>
    duration_seconds: number
    thinking_requested?: string
  }
  steps?: {
    index?: number
    package_id?: string
    input_mode?: string
    input_summary?: {
      source_count?: number
      row_count?: number | null
      first_observation?: string | null
      last_observation?: string | null
      cutoff?: string | null
      timezone?: string | null
    }
  }[]
}
export interface Catalog {
  files: {
    name: string
    is_dir: boolean
    size: number | null
    modified_at: number
    columns: string[]
    header_error?: string
  }[]
  error: string
  limited: boolean
}
export interface Workspace {
  version: string
  capabilities?: string[]
  projects: Project[]
  archived_projects: Project[]
  conversations: Conversation[]
  packages: Package[]
  invocations: Invocation[]
  tasks: Task[]
  links: { id: string; project_id: string; conversation_id?: string }[]
  task_deliveries?: Record<string, DeliveryOverview>
  research_briefs?: Record<string, { headline: string }>
}
export const state = reactive<Workspace>({
  version: '0.2.6',
  projects: [],
  archived_projects: [],
  conversations: [],
  packages: [],
  invocations: [],
  tasks: [],
  links: [],
})
const pages = ['notices', 'chat', 'projects', 'packages', 'tasks', 'invocations', 'storage', 'settings']
export const ui = reactive({
  page: pages.includes(location.hash.slice(1)) ? location.hash.slice(1) : 'projects',
  projectId: localStorage.getItem('studio.project') || '',
  conversationId: '',
  busy: '',
  error: '',
  toast: '',
  online: false,
  loaded: false,
  mobile: false,
  packageId: '',
  newChat: false,
  newChatProjectId: '',
  chatMode: 'llm' as 'llm' | 'catalog',
  token: sessionStorage.getItem('studio.token') || '',
})
export const chatDrafts = reactive<Record<string, string>>({})
// 项目数据只是数据库；当前对话所属的项目记在 ui.projectId，供对话和调用使用，不作为全局筛选。
export const project = computed(() => state.projects.find((p) => p.id === ui.projectId))
export const taskProjectId = (taskId: string) =>
  state.links.find((l) => l.id === taskId && state.projects.some((p) => p.id === l.project_id))?.project_id || ''
export const tasks = computed(() => state.tasks.filter((t) => taskProjectId(t.id)))
export const packages = computed(() => state.packages.filter((p) => p.project_id === ui.projectId))
export const conversations = computed(() =>
  [...state.conversations].sort((a, b) => (a.created_at || 0) - (b.created_at || 0) || a.id.localeCompare(b.id)),
)
export const conversation = computed(() => conversations.value.find((c) => c.id === ui.conversationId))
export const invocations = computed(() => state.invocations)
export const unassigned = computed(() => state.tasks.filter((t) => !state.links.some((l) => l.id === t.id)))
export const apiBase = (import.meta.env.VITE_AUTODECISION_API_BASE || '/api').replace(/\/$/, '')
export function headers() {
  return { 'Content-Type': 'application/json', ...(ui.token ? { Authorization: `Bearer ${ui.token}` } : {}) }
}
export async function request<T = any>(
  path: string,
  body?: unknown,
  method = body === undefined ? 'GET' : 'POST',
  options: { timeoutMs?: number; timeoutMessage?: string } = {},
): Promise<T> {
  const controller = options.timeoutMs ? new AbortController() : undefined
  const timer = controller ? setTimeout(() => controller.abort(), options.timeoutMs) : undefined
  try {
    const response = await fetch(apiBase + path, {
      method,
      headers: headers(),
      ...(controller ? { signal: controller.signal } : {}),
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    })
    const data = await response.json().catch((error) => {
      if (controller?.signal.aborted) throw error
      if (!response.ok) return { detail: `HTTP ${response.status}` }
      throw new Error('服务返回的内容无法读取，请重试。')
    })
    if (!response.ok) {
      throw new Error(humanApiError(data.detail, response.status))
    }
    return data as T
  } catch (error) {
    if (controller?.signal.aborted) {
      const message =
        options.timeoutMessage ||
        (method === 'GET'
          ? '读取超时，请重试。'
          : '请求超时，操作结果尚未确认。请先刷新状态，再决定是否重试。')
      throw new Error(message)
    }
    if (error instanceof Error && !(error instanceof TypeError)) throw error
    throw new Error('无法连接本地服务。请运行启动程序，再点击重新连接。')
  } finally {
    if (timer) clearTimeout(timer)
  }
}
export async function run(label: string, work: () => Promise<void>) {
  if (ui.busy) return
  ui.busy = label
  ui.error = ''
  try {
    await work()
  } catch (e) {
    ui.error = e instanceof Error ? e.message : String(e)
  } finally {
    ui.busy = ''
  }
}
export function toast(text: string) {
  ui.toast = text
  setTimeout(() => {
    ui.toast = ''
  }, 4000)
}
let refreshSequence = 0
export async function refresh(silent = false) {
  // A mutation must fetch new state even when an older polling request is pending.
  const sequence = ++refreshSequence
  try {
    const fresh = await request<Workspace>('/studio/state')
    if (sequence !== refreshSequence) return
    Object.assign(state, fresh)
    ui.online = true
    ui.loaded = true
    if (!state.projects.some((p) => p.id === ui.projectId)) ui.projectId = state.projects[0]?.id || ''
    if (!conversations.value.some((c) => c.id === ui.conversationId))
      ui.conversationId = rememberedConversation()
  } catch (e) {
    if (sequence !== refreshSequence) return
    ui.online = false
    ui.loaded = true
    if (!silent) ui.error = e instanceof Error ? e.message : String(e)
  }
}
export function navigate(page: string) {
  ui.page = page
  location.hash = page
  ui.mobile = false
}
window.addEventListener('hashchange', () => {
  const page = location.hash.slice(1)
  if (pages.includes(page)) ui.page = page
})
function rememberedConversation() {
  const remembered = localStorage.getItem('studio.conversation')
  const id = conversations.value.find((item) => item.id === remembered)?.id || conversations.value.at(-1)?.id || ''
  const owner = conversations.value.find((item) => item.id === id)?.project_id
  if (owner) ui.projectId = owner
  return id
}
export function selectConversation(id: string) {
  const item = conversations.value.find((row) => row.id === id)
  if (!item) return
  ui.conversationId = id
  ui.projectId = item.project_id
  ui.packageId = ''
  localStorage.setItem('studio.conversation', id)
}
export function selectProject(id: string) {
  ui.projectId = id
  localStorage.setItem('studio.project', id)
  if (conversation.value?.project_id !== id)
    ui.conversationId = conversations.value.filter((c) => c.project_id === id).at(-1)?.id || ''
  ui.packageId = ''
}
export function openNewConversation(projectId = '') {
  ui.newChatProjectId = projectId
  ui.newChat = true
}
export async function newConversation(projectId = ui.projectId, taskIds: string[] = []) {
  if (!state.projects.some((p) => p.id === projectId)) return
  navigate('chat')
  await run('conversation', async () => {
    const c = await request<Conversation>('/studio/conversations', { project_id: projectId, task_ids: taskIds })
    state.conversations.push(c)
    selectConversation(c.id)
  })
}
export async function usePackage(p: Package) {
  await newConversation(p.project_id, taskProjectId(p.task_id) === p.project_id ? [p.task_id] : [])
  ui.packageId = p.id
}
export function date(value: unknown) {
  return formatDate(value)
}
export function status(value: unknown) {
  const key = String(value ?? '')
    .trim()
    .toLowerCase()
  return (
    (
      {
        idle: '待启动',
        running: '执行中',
        completed: '已完成',
        report_completed: '报告已完成',
        automl_completed: '搜索已完成',
        autorealize_completed: '数据分析已完成',
        failed: '失败',
        stopped: '已停止',
        awaiting_input: '待确认降级',
        interrupted: '已中断',
        interrupted_resumable: '可恢复中断',
        interrupted_incomplete: '不完整中断',
        final_evaluation_completed: '独立评估已完成',
        final_evaluation_failed: '独立评估失败',
        final_evaluation_running: '独立评估中',
      } as Record<string, string>
    )[key] || (key ? '状态更新中' : '状态未知')
  )
}
export function phase(value: unknown) {
  const key = String(value ?? '')
    .trim()
    .toLowerCase()
  if (key.includes('report')) return '报告与交付'
  if (key.includes('automl') || key.includes('search')) return '方案搜索'
  if (key.includes('autorealize') || key.includes('cognition')) return '数据理解'
  return (
    (
      {
        config: '待配置',
        starting: '准备启动',
        resuming: '恢复中',
        completed: '流程完成',
        review_repair: '合同审查与修补',
        review_repair_failed: '合同修补未通过',
        degradation_planning: '规划需求降级',
        degradation_applying: '按降级口径重新定义',
        awaiting_degradation_consent: '待确认降级',
        degradation_rejected: '未同意降级',
        degradation_failed: '降级后继续失败',
      } as Record<string, string>
    )[key] || (key ? '处理中' : '等待开始')
  )
}
export function download(name: string, body: unknown) {
  saveBlob(new Blob([JSON.stringify(body, null, 2)], { type: 'application/json' }), name)
}
export function saveBlob(blob: Blob, name: string) {
  const u = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = u
  a.download = name
  a.click()
  setTimeout(() => URL.revokeObjectURL(u), 10000)
}
export async function bundle(id: string) {
  const res = await fetch(`${apiBase}/studio/packages/${id}/bundle`, { headers: headers() })
  if (!res.ok) throw new Error((await res.json()).detail)
  saveBlob(await res.blob(), `model-package-${id}.zip`)
}
