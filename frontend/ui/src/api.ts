import type { GlobalSettings, PythonEnvironment, SnapshotPayload, Task, TaskConfig } from './types'

const API_BASE = 'http://127.0.0.1:18080/api'

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: {
      'Content-Type': 'application/json',
      ...(init?.headers ?? {}),
    },
    ...init,
  })
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
  deleteTask: (taskId: string) => request<{ status: string }>(`/tasks/${taskId}`, { method: 'DELETE' }),
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
  stopTask: (taskId: string) => request<{ status: string }>('/tasks/stop', { method: 'POST', body: JSON.stringify({ task_id: taskId, confirm: true }) }),
  getSnapshot: (taskId: string) => request<SnapshotPayload>(`/tasks/${taskId}/snapshot`),
  getGlobalSettings: () => request<GlobalSettings>('/settings/global'),
  saveGlobalSettings: (payload: GlobalSettings) => request<{ status: string }>('/settings/global', { method: 'PUT', body: JSON.stringify(payload) }),
  listDir: (path: string) => request<{ path: string; children: { name: string; path: string; is_dir: boolean }[] }>(`/fs/list?path=${encodeURIComponent(path)}`),
  listRoots: () => request<{ roots: string[] }>('/fs/roots'),
  pickDirectory: (initialPath: string, title: string) =>
    request<{ ok: boolean; path: string | null; method: string; reason?: string; raw_path?: string | null }>('/fs/pick-directory', {
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
