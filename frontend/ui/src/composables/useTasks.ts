import { computed, reactive, shallowRef } from 'vue'
import { api } from '../api'
import type { AutoMLConfig, AutoRealizeConfig, AutoReportConfig, SnapshotPayload, Task, TaskConfig } from '../types'

function defaultAutoRealize(): AutoRealizeConfig {
  return {
    run_data_cognition: true,
    run_task_definition: true,
    enable_question_investigator: true,
    enable_fewshot: false,
    generate_sample_submission: true,
    prefer_original_description: true,
    direct_automl_from_description: false,
    no_knowledge: false,
    no_telemetry: false,
    no_llm_cache: false,
    enable_vllm: true,
    auto_generate_predict_split: false,
    task_hint: '',
    llm_timeout: 180,
    llm_concurrency: 4,
    llm_enable_thinking: null,
    llm_reasoning_effort: null,
    llm_structured_disable_thinking: true,
    cognition_workers: 4,
  }
}

function defaultAutoML(): AutoMLConfig {
  return {
    engine: 'mlevolve',
    enabled: true,
    steps: 50,
    time_limit_secs: 3600,
    parallel_search_num: 1,
    k_fold_validation: 1,
    check_format: false,
    expose_prediction: true,
    generate_submission: true,
    steerable_reasoning: false,
    search_num_drafts: 5,
    search_num_bugs: 1,
    search_num_improves: 3,
    search_max_debug_depth: 20,
    search_back_debug_depth: 3,
    metric_improvement_threshold: 0.0001,
    invalid_metric_upper_bound: 100,
    max_improve_failure: 3,
    decay_type: 'piecewise',
    exploration_constant: 1.414,
    lower_bound: 0.5,
    goal: '',
    eval: '',
    initial_drafts: 3,
    preprocess_data: true,
    copy_data: false,
    data_preview: true,
    use_diff_mode: true,
    check_data_leakage: true,
    use_global_memory: true,
    memory_similarity_threshold: 0.7,
    memory_embedding_backend: 'openai',
    memory_embedding_model: '',
    memory_embedding_device: 'cuda',
    memory_embedding_model_path: 'BAAI/bge-base-en-v1.5',
    use_coldstart: true,
    use_grading_server: false,
    exec_timeout_secs: 32400,
  }
}

function defaultAutoReport(): AutoReportConfig {
  return {
    enabled: true,
    audience: 'technical',
    language: 'zh-CN',
    include_raw_logs: true,
    include_code_excerpt: true,
    use_llm: true,
  }
}

function defaultTaskConfig(index: number): TaskConfig {
  return {
    task_name: `task_${index}`,
    input_root: '',
    output_root: '',
    auto_realize: defaultAutoRealize(),
    auto_ml: defaultAutoML(),
    auto_report: defaultAutoReport(),
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
      const list = await api.listTasks()
      tasks.value = list
      if (silent && isConnectivityError(error.value)) error.value = ''
      if (!silent) error.value = ''
      if (!activeTaskId.value && list.length > 0) {
        activeTaskId.value = list[0].id
      }
      if (activeTaskId.value && !list.some((x) => x.id === activeTaskId.value) && list.length > 0) {
        activeTaskId.value = list[0].id
      }
    } catch (e) {
      if (!silent) error.value = (e as Error).message
    } finally {
      if (!silent) loading.value = false
    }
  }

  async function createTask() {
    const next = tasks.value.length + 1
    const payload = defaultTaskConfig(next)
    try {
      const task = await api.createTask(payload)
      tasks.value = [...tasks.value, task]
      activeTaskId.value = task.id
      error.value = ''
    } catch (e) {
      error.value = (e as Error).message
      throw e
    }
  }

  async function saveTask(task: Task) {
    const saved = await api.updateTask(task.id, task.config)
    tasks.value = tasks.value.map((t) => (t.id === saved.id ? saved : t))
  }

  async function deleteTask(taskId: string) {
    await api.deleteTask(taskId)
    tasks.value = tasks.value.filter((t) => t.id !== taskId)
    if (activeTaskId.value === taskId) {
      activeTaskId.value = tasks.value[0]?.id ?? ''
    }
    delete snapshots[taskId]
  }

  async function startTask(taskId: string) {
    await api.startTask(taskId)
    await refreshTasks()
  }

  async function stopTask(taskId: string) {
    await api.stopTask(taskId)
    await refreshTasks()
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
    snapshots[taskId] = data
    const updated = data.task
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
    rerunAutoReport,
    rerunFull,
    resumeTask,
    stopTask,
    refreshSnapshot,
  }
}

