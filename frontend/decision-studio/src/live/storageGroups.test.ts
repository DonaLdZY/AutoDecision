import { describe, expect, it } from 'vitest'
import { groupStorage } from './storageGroups'
import type { Resource } from './storage'

function resource(kind: Resource['kind'], id: string, data: string, task = ''): Resource {
  return { kind, id, name: id, project_id: data, data_id: data, data_name: data, data_path: '/data/' + data,
    task_id: task, task_name: task ? '同名任务' : '', archived: false, archived_direct: false,
    inherited_archive: false, status: '', can_delete: kind !== 'projects', paths: ['/output/' + id] }
}
describe('storage data and task grouping', () => {
  it('keeps same-named tasks in different datasets separate, with their own packages', () => {
    const groups = groupStorage([
      resource('projects', 'p1', 'data-1'), resource('projects', 'p2', 'data-2'),
      resource('tasks', 't1', 'data-1', 't1'), resource('tasks', 't2', 'data-2', 't2'),
      resource('packages', 'pkg1', 'data-1', 't1'), resource('packages', 'pkg2', 'data-2', 't2'),
    ])
    expect(groups).toHaveLength(2)
    expect(groups[0]!.folders.map(r => r.id)).toEqual(['p1'])
    expect(groups[0]!.tasks[0]!.resources.map(r => r.id)).toEqual(['t1', 'pkg1'])
    expect(groups[1]!.tasks[0]!.resources.map(r => r.id)).toEqual(['t2', 'pkg2'])
  })
  it('preserves parent context when a filter only shows packages', () => {
    const [group] = groupStorage([resource('packages', 'pkg', 'dataset', 'task')])
    expect(group!.name).toBe('dataset')
    expect(group!.tasks[0]!.name).toBe('同名任务')
    expect(group!.folders).toEqual([])
  })
  it('separates unlinked development without pretending it belongs to a task', () => {
    const groups = groupStorage([resource('runs', 'old', ''), resource('projects', 'p', 'dataset')])
    expect(groups[1]!.id).toBe('unlinked')
    expect(groups[1]!.tasks[0]!.id).toBe('unlinked')
    expect(groups[1]!.resources.map(r => r.id)).toEqual(['old'])
  })
})
