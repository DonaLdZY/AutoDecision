import type { GlobalSettings, PythonEnvironment, ResourceInventory, SnapshotPayload, Task, TaskConfig } from './types'

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
    throw new Error(`无法连接 AutoDecision Gateway（${API_BASE}）：${detail}。请确认已运行项目根目录的统一启动脚本。`)
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
  getAutoMLReadiness: (taskId: string) => request<{
    ready: boolean
    source: string
    detail: string
    autorealize_description: string
    input_description: string
    configured_goal: boolean
    configured_eval: boolean
  }>(`/tasks/${taskId}/automl-readiness`),
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
