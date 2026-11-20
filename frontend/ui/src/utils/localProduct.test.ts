import { describe, expect, it } from 'vitest'
import { applyResourcePreset, executionStage, primaryAction } from './localProduct'
import { defaultTaskConfig } from '../composables/useTasks'
import type { Task } from '../types'

describe('local product lifecycle', () => {
  it('selects safe actions for each runtime state', () => {
    for (const [status, expected] of [['idle', 'start'], ['completed', 'solution'], ['failed', 'resume'], ['interrupted_resumable', 'resume'], ['running', 'stop']]) {
      expect(primaryAction({ status, phase: 'automl' } as Task)).toBe(expected)
    }
    expect(primaryAction({ status: 'running', phase: 'automl_stopping' } as Task)).toBe('stopping')
  })
  it('derives execution stage from evidence rather than the selected page', () => {
    expect(executionStage({ status: 'running', phase: 'automl' } as Task, 'task_definition')).toBe('方案搜索')
    expect(executionStage({ status: 'idle', phase: 'config' } as Task)).toBe('未开始')
  })
  it('preserves computer headroom and separates API concurrency from local workers', () => {
    const config = defaultTaskConfig(1)
    applyResourcePreset(config, 'full', 2, 4)
    expect(config.resources.cpu_cores).toBe(1)
    expect(config.resources.memory_limit_gb).toBe(3)
    expect(config.auto_ml.parallel_search_num).toBe(1)
    expect(config.auto_realize.llm_concurrency).toBe(16)
    expect(config.resources.accelerator_mode).toBe('none')
  })
})
