import { afterEach, describe, expect, it, vi } from 'vitest'

import { api } from '../api'
import type { AutoMLConfig, SnapshotPayload } from '../types'
import {
  defaultAutoML,
  defaultAutoRealize,
  defaultTaskConfig,
  newTaskConfigFromHistory,
  normalizeTaskConfig,
  useTasks,
} from './useTasks'
import type { Task } from '../types'

afterEach(() => vi.restoreAllMocks())

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>(done => { resolve = done })
  return { promise, resolve }
}

function snapshot(task: Task, code: string): SnapshotPayload {
  return { task, auto_ml: { nodes: [{ id: code, code }] } } as SnapshotPayload
}

describe('task polling races', () => {
  function rig() {
    const state = useTasks()
    const task = { id: 'task', status: 'completed', config: defaultTaskConfig(1) } as Task
    state.tasks.value = [task]
    state.activeTaskId.value = task.id
    return { state, task }
  }

  it('keeps the newest requested snapshot when responses arrive out of order', async () => {
    const { state, task } = rig()
    const old = deferred<SnapshotPayload>()
    vi.spyOn(api, 'getSnapshot').mockReturnValueOnce(old.promise).mockResolvedValueOnce(snapshot(task, 'new'))
    const pending = state.refreshSnapshot(task.id)
    await state.refreshSnapshot(task.id)
    old.resolve(snapshot(task, 'old'))
    await pending
    expect(state.snapshots[task.id]?.auto_ml.nodes?.[0]?.code).toBe('new')
  })

  it('does not restore completed artifacts after a full rerun', async () => {
    const { state, task } = rig()
    const old = deferred<SnapshotPayload>()
    const running = { ...task, status: 'running' }
    vi.spyOn(api, 'getSnapshot').mockReturnValueOnce(old.promise)
    vi.spyOn(api, 'rerunFull').mockResolvedValue({ status: 'running', task_id: task.id, mode: 'full' })
    vi.spyOn(api, 'listTasks').mockResolvedValue([running])
    state.snapshots[task.id] = snapshot(task, 'old')
    const pending = state.refreshSnapshot(task.id)
    await state.rerunFull(task.id)
    old.resolve(snapshot(task, 'old'))
    await pending
    expect(state.snapshots[task.id]).toBeUndefined()
    expect(state.activeTask.value?.status).toBe('running')
  })

  it('does not resurrect a deleted task from either snapshot or list polling', async () => {
    const { state, task } = rig()
    const oldSnapshot = deferred<SnapshotPayload>()
    const oldList = deferred<Task[]>()
    vi.spyOn(api, 'getSnapshot').mockReturnValue(oldSnapshot.promise)
    vi.spyOn(api, 'listTasks').mockReturnValue(oldList.promise)
    vi.spyOn(api, 'deleteTask').mockResolvedValue({ status: 'deleted', deleted_files: [] })
    const snapshotPoll = state.refreshSnapshot(task.id)
    const listPoll = state.refreshTasks({ silent: true })
    await state.deleteTask(task.id)
    oldSnapshot.resolve(snapshot(task, 'old'))
    oldList.resolve([task])
    await Promise.all([snapshotPoll, listPoll])
    expect(state.tasks.value).toEqual([])
    expect(state.snapshots[task.id]).toBeUndefined()
    expect(state.activeTaskId.value).toBe('')
  })

  it('does not overwrite a saved configuration with an earlier snapshot', async () => {
    const { state, task } = rig()
    const old = deferred<SnapshotPayload>()
    vi.spyOn(api, 'getSnapshot').mockReturnValue(old.promise)
    const saved = { ...task, config: { ...task.config, task_name: 'Updated task' } }
    vi.spyOn(api, 'updateTask').mockResolvedValue(saved)
    const pending = state.refreshSnapshot(task.id)
    await state.saveTask(saved)
    old.resolve(snapshot(task, 'old'))
    await pending
    expect(state.activeTask.value?.config.task_name).toBe('Updated task')
  })

  it('does not overwrite fresh snapshot status with an older task list', async () => {
    const { state, task } = rig()
    const old = deferred<Task[]>()
    vi.spyOn(api, 'listTasks').mockReturnValue(old.promise)
    vi.spyOn(api, 'getSnapshot').mockResolvedValue(snapshot({ ...task, status: 'running' }, 'new'))
    const pending = state.refreshTasks({ silent: true })
    await state.refreshSnapshot(task.id)
    old.resolve([task])
    await pending
    expect(state.activeTask.value?.status).toBe('running')
  })
})

describe('task configuration defaults', () => {
  it('uses one output language for the whole task', () => {
    const config = defaultTaskConfig(2)

    expect(config.output_language).toBe('zh')
    expect(config.task_name).toBe('task_2')
    expect('language' in config.auto_report).toBe(false)
  })

  it('exposes current AutoRealize cost and context controls', () => {
    const config = defaultAutoRealize()

    expect(config.llm_file_cognition_mode).toBe('all')
    expect(config.optimize_llm_cost).toBe(true)
    expect(config.cross_stage_memory_enabled).toBe(true)
    expect(config.cross_stage_retrieval_enabled).toBe(true)
    expect('no_llm_cache' in config).toBe(false)
  })

  it('uses the current AlgoEvolve search and Stepwise controls', () => {
    const config = defaultAutoML()

    expect(config.search_root_new_draft_probability).toBe(0.25)
    expect(config.goal).toBe('')
    expect(config.eval).toBe('')
    expect(config.search_fusion_min_remaining_seconds).toBe(300)
    expect(config.stepwise_context_max_tokens).toBe(90000)
    expect(config.result_adjudicator_on_anomaly).toBe(true)
    expect(config.preflight_regeneration_max_attempts).toBe(2)
    expect('search_fusion_min_time_hours' in config).toBe(false)
    expect('k_fold_validation' in config).toBe(false)
  })

  it('fills current controls when loading a task saved by an older backend', () => {
    const legacy = defaultTaskConfig(1)
    const legacyAutoML = legacy.auto_ml as AutoMLConfig & {
      generation_parallel_num?: number
    }
    legacyAutoML.generation_parallel_num = 9
    Reflect.set(legacyAutoML, 'pending_execution_headroom', 9)

    const normalized = normalizeTaskConfig(legacy)

    expect('generation_parallel_num' in normalized.auto_ml).toBe(false)
    expect('pending_execution_headroom' in normalized.auto_ml).toBe(false)
  })

  it('inherits new-task settings from the most recently started task', () => {
    const older = {
      id: 'older',
      created_at: 1,
      updated_at: 2,
      run_started_at: 10,
      config: defaultTaskConfig(1),
    } as Task
    const latest = {
      id: 'latest',
      created_at: 3,
      updated_at: 4,
      run_started_at: 20,
      config: defaultTaskConfig(2),
    } as Task
    latest.config.input_root = 'D:/datasets/latest'
    latest.config.task_name = 'latest-template'
    latest.config.output_language = 'en'
    latest.config.auto_ml.steps = 137

    const inherited = newTaskConfigFromHistory([latest, older], 3)

    expect(inherited.task_name).toBe('latest-template')
    expect(inherited.input_root).toBe('D:/datasets/latest')
    expect(inherited.output_language).toBe('en')
    expect(inherited.auto_ml.steps).toBe(137)
    inherited.auto_ml.steps = 1
    expect(latest.config.auto_ml.steps).toBe(137)
  })

  it('uses system defaults before any task has started', () => {
    const idle = {
      id: 'idle',
      created_at: 1,
      updated_at: 2,
      config: defaultTaskConfig(1),
    } as Task
    idle.config.auto_ml.steps = 999

    expect(newTaskConfigFromHistory([idle], 2)).toEqual(defaultTaskConfig(2))
  })
})
