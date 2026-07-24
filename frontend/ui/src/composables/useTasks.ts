import { computed, reactive, shallowRef } from 'vue'
import { api } from '../api'
import type { AutoMLConfig, AutoRealizeConfig, AutoReportConfig, SnapshotPayload, Task, TaskConfig } from '../types'
import { defaultTaskResources } from '../utils/taskResources'
import { latestCreatedTaskId, latestStartedTask } from '../utils/taskSelection'
import { defaultAutoReportConfig } from '../utils/autoReport'
import { cloneDeep } from '../utils/clone'

export function defaultAutoRealize(): AutoRealizeConfig {
  return {
    enable_question_investigator: true,
    enable_fewshot: false,
    generate_sample_submission: true,
    direct_automl_from_description: false,
    enable_vllm: true,
    task_hint: '',
    llm_timeout: 180,
    llm_concurrency: 100,
    optimize_llm_cost: true,
    llm_file_cognition_mode: 'all',
    table_profile_sample_rows: 20000,
    investigation_max_questions: 20,
    investigation_max_rounds_per_question: 10,
    investigation_max_scripts_per_question: 3,
    investigation_script_timeout_secs: 30,
    prompt_token_budget: 12000,
    artifact_consistency_enabled: true,
    artifact_consistency_max_rounds: 2,
    cross_stage_memory_enabled: true,
    cross_stage_headroom_ratio: 0.72,
    cross_stage_retrieval_enabled: true,
  }
}

export function defaultAutoML(): AutoMLConfig {
  return {
    engine: 'mlevolve',
    enabled: true,
    goal: '',
    eval: '',
    steps: 50,
    time_limit_secs: 10800,
    parallel_search_num: 4,
    generate_submission: true,
    search_num_drafts: 8,
    search_num_bugs: 1,
    search_num_improves: 5,
    search_max_debug_depth: 20,
    search_back_debug_depth: 3,
    metric_improvement_threshold: 0.0001,
    max_improve_failure: 3,
    exploration_constant: 1.414,
    lower_bound: 0.5,
    initial_drafts: 3,
    copy_data: false,
    use_diff_mode: true,
    check_data_leakage: true,
    use_global_memory: true,
    memory_similarity_threshold: 0.7,
    memory_embedding_backend: 'openai',
    memory_embedding_device: 'cuda',
    memory_embedding_model_path: 'BAAI/bge-base-en-v1.5',
    use_coldstart: true,
    exec_timeout_secs: 1800,
    auto_install_missing_dependencies: true,
    dependency_install_timeout_secs: 600,
    dependency_install_max_packages: 3,
    code_temperature: 0.5,
    feedback_temperature: 0.5,
    code_request_timeout_secs: 1200,
    feedback_request_timeout_secs: 1200,
    code_generation_max_retries: 5,
    feedback_generation_max_retries: 5,
    code_continuation_max_rounds: 2,
    feedback_continuation_max_rounds: 2,
    code_review_max_attempts: 2,
    preflight_regeneration_max_attempts: 2,
    code_review_escalate_to_code: true,
    code_generation_extract_max_attempts: 2,
    metric_direction_max_attempts: 3,
    result_review_max_attempts: 3,
    refine_plan_max_attempts: 3,
    result_adjudicator_on_anomaly: true,
    fast_first_draft: true,
    fast_first_draft_skip_pre_review: true,
    use_stepwise_after_first: true,
    stepwise_context_max_tokens: 90000,
    stepwise_compaction_keep_recent_steps: 2,
    stepwise_compaction_max_tokens: 8192,
    stepwise_context_headroom_ratio: 0.15,
    search_topk_max_improves: 10,
    search_debug_prob: 1,
    search_branch_stagnation_threshold: 3,
    search_topk_stagnation_threshold: 6,
    search_stagnation_window: 4,
    search_top_candidates_size: 20,
    search_explore_switch_start: 0.5,
    search_explore_switch_end: 0.7,
    search_min_exploration_weight: 0.2,
    search_root_new_draft_probability: 0.25,
    fusion_vs_evolution_prob: 0.3,
    branch_fusion_trigger_prob: 1,
    max_fusion_drafts: 2,
    search_fusion_min_remaining_seconds: 300,
    search_fusion_min_successful_nodes: 2,
    search_fusion_min_branches: 2,
    use_optimization_experience_library: true,
    optimization_experience_max_cards: 2,
    optimization_experience_min_score: 3,
    optimization_experience_max_chars: 6000,
  }
}

export function defaultAutoReport(): AutoReportConfig {
  return defaultAutoReportConfig()
}

export function defaultTaskConfig(index: number): TaskConfig {
  return {
    task_name: `task_${index}`,
    input_root: '',
    output_root: '',
    output_language: 'zh',
    auto_realize: defaultAutoRealize(),
    auto_ml: defaultAutoML(),
    auto_report: defaultAutoReport(),
    resources: defaultTaskResources(),
  }
}

export function normalizeTaskConfig(config: TaskConfig): TaskConfig {
  const defaults = defaultTaskConfig(1)
  const autoMLInput = {
    ...(config.auto_ml ?? {}),
  } as Partial<AutoMLConfig> & {
    generation_parallel_num?: unknown
    pending_execution_headroom?: unknown
  }
  Reflect.deleteProperty(autoMLInput, 'generation_parallel_num')
  Reflect.deleteProperty(autoMLInput, 'pending_execution_headroom')
  return {
    ...defaults,
    ...config,
    auto_realize: {
      ...defaults.auto_realize,
      ...(config.auto_realize ?? {}),
    },
    auto_ml: {
      ...defaults.auto_ml,
      ...autoMLInput,
    },
    auto_report: {
      ...defaults.auto_report,
      ...(config.auto_report ?? {}),
    },
    resources: {
      ...defaults.resources,
      ...(config.resources ?? {}),
    },
  }
}

export function newTaskConfigFromHistory(tasks: Task[], index: number): TaskConfig {
  const previous = latestStartedTask(tasks)
  if (!previous) return defaultTaskConfig(index)

  return normalizeTaskConfig(cloneDeep(previous.config))
}

function normalizeTask(task: Task): Task {
  return {
    ...task,
    config: normalizeTaskConfig(task.config),
  }
}

function isConnectivityError(text: string) {
  return /failed to fetch|networkerror|load failed|connection/i.test(text)
}

export function useTasks() {
  const tasks = shallowRef<Task[]>([])
  const activeTaskId = shallowRef<string>('')
  const snapshots = reactive<Record<string, SnapshotPayload>>({})
  const loading = shallowRef(false)
  const error = shallowRef('')

  const activeTask = computed(() => tasks.value.find((t) => t.id === activeTaskId.value) ?? null)

  async function refreshTasks(options: { silent?: boolean } = {}) {
    const silent = options.silent === true
    if (!silent) {
      loading.value = true
      error.value = ''
    }
    try {
      const list = (await api.listTasks()).map(normalizeTask)
      tasks.value = list
      if (silent && isConnectivityError(error.value)) error.value = ''
      if (!silent) error.value = ''
      if (list.length === 0) {
        activeTaskId.value = ''
      } else if (!activeTaskId.value || !list.some((task) => task.id === activeTaskId.value)) {
        activeTaskId.value = latestCreatedTaskId(list)
      }
    } catch (e) {
      if (!silent) error.value = (e as Error).message
    } finally {
      if (!silent) loading.value = false
    }
  }

  async function createTask() {
    const next = tasks.value.length + 1
    const payload = newTaskConfigFromHistory(tasks.value, next)
    try {
      const task = normalizeTask(await api.createTask(payload))
      tasks.value = [...tasks.value, task]
      activeTaskId.value = task.id
      error.value = ''
    } catch (e) {
      error.value = (e as Error).message
      throw e
    }
  }

  async function saveTask(task: Task) {
    const saved = normalizeTask(await api.updateTask(task.id, task.config))
    tasks.value = tasks.value.map((t) => (t.id === saved.id ? saved : t))
  }

  async function deleteTask(taskId: string, deleteFiles = false) {
    const result = await api.deleteTask(taskId, deleteFiles)
    tasks.value = tasks.value.filter((t) => t.id !== taskId)
    if (activeTaskId.value === taskId) {
      activeTaskId.value = latestCreatedTaskId(tasks.value)
    }
    delete snapshots[taskId]
    return result
  }

  async function startTask(taskId: string) {
    await api.startTask(taskId)
    await refreshTasks()
  }

  async function stopTask(taskId: string) {
    const result = await api.stopTask(taskId)
    await refreshTasks()
    return result
  }

  async function rerunAutoRealize(taskId: string) {
    await api.rerunAutoRealize(taskId)
    delete snapshots[taskId]
    await refreshTasks()
  }

  async function rerunAutoML(taskId: string) {
    await api.rerunAutoML(taskId)
    await refreshTasks()
  }

  async function startAutoML(taskId: string) {
    await api.startAutoML(taskId)
    await refreshTasks()
  }

  async function continueAutoML(taskId: string) {
    await api.continueAutoML(taskId)
    await refreshTasks()
  }

  async function rerunAutoReport(taskId: string) {
    await api.rerunAutoReport(taskId)
    await refreshTasks()
  }

  async function rerunFull(taskId: string) {
    await api.rerunFull(taskId)
    delete snapshots[taskId]
    await refreshTasks()
  }

  async function resumeTask(taskId: string) {
    await api.resumeTask(taskId)
    await refreshTasks()
  }

  async function refreshSnapshot(taskId: string) {
    const data = await api.getSnapshot(taskId)
    const updated = normalizeTask(data.task)
    snapshots[taskId] = { ...data, task: updated }
    tasks.value = tasks.value.map((t) => (t.id === updated.id ? updated : t))
  }

  return {
    tasks,
    activeTaskId,
    activeTask,
    snapshots,
    loading,
    error,
    refreshTasks,
    createTask,
    saveTask,
    deleteTask,
    startTask,
    rerunAutoRealize,
    rerunAutoML,
    startAutoML,
    continueAutoML,
    rerunAutoReport,
    rerunFull,
    resumeTask,
    stopTask,
    refreshSnapshot,
  }
}

