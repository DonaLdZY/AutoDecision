import type { AutoMLReadiness, GlobalSettings, PythonEnvironment, ReplayRecording, ResourceInventory, SnapshotPayload, Task, TaskConfig } from './types'

// Keep browser requests same-origin by default. Vite proxies /api to the local
// Gateway during development, which also works when Vite selects a port other
// than 5173 or the page is opened through localhost instead of 127.0.0.1.
const API_BASE = (import.meta.env.VITE_AUTODECISION_API_BASE || '/api').replace(/\/$/, '')
const API_TOKEN = import.meta.env.VITE_AUTODECISION_API_TOKEN || ''

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response
  try {
    res = await fetch(`${API_BASE}${path}`, {
      headers: {
        'Content-Type': 'application/json',
        ...(API_TOKEN ? { Authorization: `Bearer ${API_TOKEN}` } : {}),
        ...(init?.headers ?? {}),
      },
      ...init,
    })
  } catch (error) {
    const detail = error instanceof Error ? error.message : String(error)
    throw new Error(`无法连接本地服务（${API_BASE}）：${detail}。请确认已运行项目根目录的统一启动脚本。`)
  }
  if (!res.ok) {
    const text = await res.text()
    let message = text
    try {
      const payload = JSON.parse(text) as { detail?: unknown }
      if (typeof payload.detail === 'string') message = payload.detail
      else if (payload.detail !== undefined) message = JSON.stringify(payload.detail)
    } catch {
      // Keep the raw response text when it is not JSON.
    }
    throw new Error(message || `Request failed: ${res.status}`)
  }
  return (await res.json()) as T
}

export const api = {
  getReadiness: (taskId?: string) => request<Readiness>(`/system/readiness${taskId ? `?task_id=${encodeURIComponent(taskId)}` : ''}`),
  probeModel: (role: string) => request('/system/probe-model', { method: 'POST', body: JSON.stringify({ role }) }),
  getDiagnostics: () => request<Record<string, unknown>>('/system/diagnostics'),
  newExperiment: (taskId: string) => request<Task>(`/tasks/${taskId}/experiments`, { method: 'POST' }),
  getExperiments: (taskId: string) => request<Task[]>(`/tasks/${taskId}/experiments`),
  getSolution: (taskId: string) => request<Solution>(`/tasks/${taskId}/solution`),
  trialSolution: (taskId: string, payload: { input_mode: string; data_json: string; csv_path: string; timeout_seconds: number }) => request<Record<string, unknown>>(`/tasks/${taskId}/solution/trial`, { method: 'POST', body: JSON.stringify(payload) }),
  getTrials: (taskId: string) => request<{ trial_id: string; created_at: number; node_id: string }[]>(`/tasks/${taskId}/solution/trials`),
  getTrial: (taskId: string, trialId: string) => request<Record<string, unknown>>(`/tasks/${taskId}/solution/trials/${trialId}`),
  downloadSolution: async (taskId: string) => {
    const response = await fetch(`${API_BASE}/tasks/${taskId}/solution/bundle`, { headers: API_TOKEN ? { Authorization: `Bearer ${API_TOKEN}` } : {} })
    if (!response.ok) {
      const detail = await response.json().catch(() => ({ detail: '方案导出失败' }))
      throw new Error(detail.detail || '方案导出失败')
    }
    saveBlob(await response.blob(), `solution-${taskId.slice(0, 12)}.zip`)
  },
  listTasks: () => request<Task[]>('/tasks'),
  createTask: (payload: TaskConfig) => request<Task>('/tasks', { method: 'POST', body: JSON.stringify(payload) }),
  updateTask: (taskId: string, payload: TaskConfig) => request<Task>(`/tasks/${taskId}`, { method: 'PUT', body: JSON.stringify(payload) }),
  deleteTask: async (taskId: string, deleteFiles = false) => {
    if (deleteFiles) {
      // A legacy Gateway silently ignores the query flag and would delete only
      // the task record. Probe a new action endpoint before destructive cleanup.
      await request(`/tasks/${taskId}/automl-readiness`)
    }
    return request<{ status: string; deleted_files: string[] }>(
      `/tasks/${taskId}?delete_files=${deleteFiles ? 'true' : 'false'}`,
      { method: 'DELETE' },
    )
  },
  startTask: (taskId: string) => request<{ status: string; task_id: string }>('/tasks/start', { method: 'POST', body: JSON.stringify({ task_id: taskId }) }),
  rerunAutoRealize: (taskId: string) =>
    request<{ status: string; task_id: string; mode: string }>('/tasks/rerun-autorealize', {
      method: 'POST',
      body: JSON.stringify({ task_id: taskId, confirm: true }),
    }),
  getReviewRepairPlan: (taskId: string) => request<{
    plan_token: string; replace_paths: string[]; delete_paths: string[]; archive_root: string;
    preserve_paths: string[]; files: { path: string; size: number }[]
  }>(`/tasks/${taskId}/review-repair-plan`),
  repairReviewAndResume: (taskId: string, planToken: string) =>
    request<{ status: string; task_id: string; mode: string; repair_required: boolean; review_gate_policy: string }>('/tasks/repair-review-and-resume', {
      method: 'POST',
      body: JSON.stringify({ task_id: taskId, confirm: true, plan_token: planToken }),
    }),
  rerunAutoML: (taskId: string) =>
    request<{ status: string; task_id: string; mode: string }>('/tasks/rerun-automl', {
      method: 'POST',
      body: JSON.stringify({ task_id: taskId, confirm: true }),
    }),
  startAutoML: (taskId: string) =>
    request<{ status: string; task_id: string; mode: string }>('/tasks/start-automl', {
      method: 'POST',
      body: JSON.stringify({ task_id: taskId, confirm: true }),
    }),
  getAutoMLReadiness: (taskId: string) => request<AutoMLReadiness>(`/tasks/${taskId}/automl-readiness`),
  continueAutoML: (taskId: string) =>
    request<{ status: string; task_id: string; mode: string }>('/tasks/continue-automl', {
      method: 'POST',
      body: JSON.stringify({ task_id: taskId }),
    }),
  rerunAutoReport: (taskId: string) =>
    request<{ status: string; task_id: string; mode: string }>('/tasks/rerun-autoreport', {
      method: 'POST',
      body: JSON.stringify({ task_id: taskId, confirm: true }),
    }),
  rerunFull: (taskId: string) =>
    request<{ status: string; task_id: string; mode: string }>('/tasks/rerun-full', {
      method: 'POST',
      body: JSON.stringify({ task_id: taskId, confirm: true }),
    }),
  resumeTask: (taskId: string) =>
    request<{ status: string; task_id: string; mode: string }>('/tasks/resume', {
      method: 'POST',
      body: JSON.stringify({ task_id: taskId }),
    }),
  stopTask: (taskId: string) => request<{ status: string; checkpoint_ready?: boolean; resumable?: boolean }>('/tasks/stop', { method: 'POST', body: JSON.stringify({ task_id: taskId, confirm: true }) }),
  getSnapshot: (taskId: string) => request<SnapshotPayload>(`/tasks/${taskId}/snapshot`),
  getReplay: (taskId: string) => request<ReplayRecording>(`/tasks/${taskId}/replay`),
  getGlobalSettings: () => request<GlobalSettings>('/settings/global'),
  saveGlobalSettings: (payload: GlobalSettings) => request<{ status: string }>('/settings/global', { method: 'PUT', body: JSON.stringify(payload) }),
  getResourceInventory: () => request<ResourceInventory>('/resources/inventory'),
  listDir: (path: string) => request<{ path: string; children: { name: string; path: string; is_dir: boolean }[] }>(`/fs/list?path=${encodeURIComponent(path)}`),
  listRoots: () => request<{ roots: string[] }>('/fs/roots'),
  pickDirectory: (initialPath: string, title: string) =>
    request<{ ok: boolean; path: string | null; method: string; reason?: string; raw_path?: string | null; platform?: string }>('/fs/pick-directory', {
      method: 'POST',
      body: JSON.stringify({ initial_path: initialPath, title }),
    }),
  openDirectory: (path: string) =>
    request<{ ok: boolean; path: string }>(`/fs/open-directory?path=${encodeURIComponent(path)}`, {
      method: 'POST',
    }),
  listPythonEnvs: (current: string) =>
    request<PythonEnvironment[]>(`/python/environments?current=${encodeURIComponent(current || '')}`),
}

export function saveBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url; link.download = filename; link.click()
  window.setTimeout(() => URL.revokeObjectURL(url), 30000)
}

export interface Readiness {
  version: string; checked_at: number; ready: boolean; output_root: string
  lifecycle: string; data_policy: string
  checks: { key: string; label: string; status: 'pass' | 'warn' | 'fail'; detail: string }[]
  providers: { role: string; model: string; host: string; local: boolean }[]
}
export interface Solution {
  trial_ready?: boolean
  available: boolean; exportable: boolean; issues: string[]; node_id?: string
  manifest?: Record<string, unknown>; model_path?: string; directory?: string
  files: { path: string; size: number }[]; size_bytes?: number; usage?: string
  verification?: Record<string, unknown>; portability?: string; notice?: string
}
