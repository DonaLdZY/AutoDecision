import { describe, expect, it } from 'vitest'
import type { Task } from '../types'
import { latestCreatedTaskId, latestStartedTask } from './taskSelection'

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

describe('latestStartedTask', () => {
  it('selects the task with the most recent actual start time', () => {
    const neverStarted = task('edited-later', 40, 100)
    const olderStart = { ...task('older-start', 10, 80), run_started_at: 50 }
    const latestStart = { ...task('latest-start', 20, 60), run_started_at: 70 }

    expect(latestStartedTask([neverStarted, latestStart, olderStart])?.id).toBe('latest-start')
  })

  it('returns undefined when no task has ever started', () => {
    expect(latestStartedTask([task('idle', 10)])).toBeUndefined()
  })
})
