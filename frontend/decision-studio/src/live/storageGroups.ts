import type { Resource } from './storage'

export interface TaskGroup { id: string; name: string; resources: Resource[] }
export interface DataGroup { id: string; name: string; path: string; folders: Resource[]; tasks: TaskGroup[]; resources: Resource[] }
export function isDataFolder(resource: Resource) { return resource.kind === 'projects' || resource.kind === 'datasets' }

export function groupStorage(resources: Resource[]): DataGroup[] {
  const groups = new Map<string, DataGroup>()
  for (const resource of resources) {
    const id = resource.data_id || 'unlinked'
    let group = groups.get(id)
    if (!group) {
      group = { id, name: resource.data_name || '未关联数据的开发目录', path: resource.data_path, folders: [], tasks: [], resources: [] }
      groups.set(id, group)
    }
    group.resources.push(resource)
    if (isDataFolder(resource)) { group.folders.push(resource); continue }
    const taskId = resource.task_id || 'unlinked'
    let task = group.tasks.find(item => item.id === taskId)
    if (!task) {
      task = { id: taskId, name: resource.task_name || '未关联任务', resources: [] }
      group.tasks.push(task)
    }
    task.resources.push(resource)
  }
  return [...groups.values()].sort((a, b) => a.id === 'unlinked' ? 1 : b.id === 'unlinked' ? -1 : a.name.localeCompare(b.name, 'zh-CN'))
}
