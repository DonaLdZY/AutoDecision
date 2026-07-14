import type { Task } from '../types'

function timestamp(value: unknown) {
  const number = Number(value)
  return Number.isFinite(number) ? number : 0
}

export function latestCreatedTaskId(tasks: Task[]) {
  let latest: Task | undefined
  for (const task of tasks) {
    if (!latest) {
      latest = task
      continue
    }
    const createdDelta = timestamp(task.created_at) - timestamp(latest.created_at)
    const updatedDelta = timestamp(task.updated_at) - timestamp(latest.updated_at)
    if (createdDelta > 0 || (createdDelta === 0 && updatedDelta > 0)) latest = task
  }
  return latest?.id ?? ''
}
