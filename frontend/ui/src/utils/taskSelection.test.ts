import { describe, expect, it } from 'vitest'
import type { Task } from '../types'
import { latestCreatedTaskId } from './taskSelection'

function task(id: string, createdAt: number, updatedAt = createdAt): Task {
  return {
    id,
    task_name: id,
    input_root: '',
    output_root: '',
    created_at: createdAt,
    updated_at: updatedAt,
    status: 'idle',
    phase: '',
    config: {} as Task['config'],
  }
}

describe('latestCreatedTaskId', () => {
  it('selects by creation time instead of API order', () => {
    expect(latestCreatedTaskId([
      task('older', 10),
      task('latest', 30),
      task('middle', 20),
    ])).toBe('latest')
  })

  it('uses update time only to break equal creation timestamps', () => {
    expect(latestCreatedTaskId([
      task('first', 30, 31),
      task('second', 30, 35),
    ])).toBe('second')
    expect(latestCreatedTaskId([])).toBe('')
  })
})
