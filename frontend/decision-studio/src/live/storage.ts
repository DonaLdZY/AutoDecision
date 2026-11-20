import { reactive, ref } from 'vue'
import { request } from './store'

export type ResourceKind = 'projects' | 'datasets' | 'tasks' | 'packages' | 'runs'
export type StorageAction = 'archive' | 'restore' | 'delete'
export interface ResourceRef { kind: ResourceKind; id: string }
export interface Resource extends ResourceRef {
  name: string
  project_id: string
  data_id: string
  data_name: string
  data_path: string
  task_id: string
  task_name: string
  can_delete: boolean
  status: string
  archived: boolean
  archived_direct: boolean
  inherited_archive: boolean
  paths: string[]
}
export interface StoragePath {
  path: string
  exists: boolean
  bytes: number
  files: number
  directories: number
  links: number
  errors: string[]
}
export interface StorageDetails extends Omit<Resource, 'paths'> {
  paths: StoragePath[]
  bytes: number
  files: number
  complete: boolean
}
export interface StoragePreview {
  action: StorageAction
  resources: Resource[]
  paths: StoragePath[]
  counts: Record<string, number>
  bytes: number
  files: number
  blockers: string[]
  confirmation_token: string
}
export const kindLabel: Record<ResourceKind, string> = {
  projects: '数据文件夹', datasets: '数据文件夹', tasks: '开发目录', packages: '代码包', runs: '开发目录',
}
export const actionLabel: Record<StorageAction, string> = { archive: '归档', restore: '还原', delete: '删除' }
export const storageRevision = ref(0)
export const storageDialog = reactive<{ action: StorageAction; resources: ResourceRef[] }>(
  { action: 'archive', resources: [] },
)
export function resourceKey(resource: ResourceRef) { return `${resource.kind}:${resource.id}` }
export function manageStorage(action: StorageAction, resources: ResourceRef[]) {
  storageDialog.action = action
  storageDialog.resources = resources.map(({ kind, id }) => ({ kind, id }))
}
export function formatBytes(bytes: number) {
  if (!Number.isFinite(bytes) || bytes < 0) return '—'
  if (bytes < 1024) return `${bytes} B`
  const units = ['KiB', 'MiB', 'GiB', 'TiB']
  let value = bytes / 1024, index = 0
  while (value >= 1024 && index < units.length - 1) { value /= 1024; index++ }
  return `${value.toFixed(value >= 100 ? 0 : 1)} ${units[index]}`
}

// Bound concurrent directory walks when a page contains many historical runs.
let running = 0
const queue: (() => void)[] = []
const pending = new Map<string, Promise<StorageDetails>>()
export function readStorage(resource: ResourceRef) {
  const key = `${storageRevision.value}:${resourceKey(resource)}`
  if (pending.has(key)) return pending.get(key)!
  const promise = new Promise<StorageDetails>((resolve, reject) => {
    const execute = () => {
      running++
      request<StorageDetails>(`/studio/storage/${resource.kind}/${encodeURIComponent(resource.id)}${storageRevision.value ? '?refresh=true' : ''}`)
        .then(resolve, reject).finally(() => {
          running--
          pending.delete(key)
          queue.shift()?.()
        })
    }
    if (running < 4) execute()
    else queue.push(execute)
  })
  pending.set(key, promise)
  return promise
}
