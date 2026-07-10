export interface AutoRealizeConfig {
  run_data_cognition: boolean
  run_task_definition: boolean
  run_data_cleaning?: boolean
  enable_question_investigator: boolean
  enable_fewshot: boolean
  generate_sample_submission: boolean
  prefer_original_description: boolean
  direct_automl_from_description: boolean
  no_knowledge: boolean
  no_telemetry: boolean
  no_llm_cache: boolean
  enable_vllm: boolean
  offline?: boolean
  auto_generate_predict_split: boolean
  parallel_cleaning?: boolean
  task_hint: string
  llm_timeout: number
  llm_concurrency: number
  llm_enable_thinking: boolean | null
  llm_reasoning_effort: string | null
  llm_structured_disable_thinking: boolean
  cognition_workers: number
  cleaning_workers?: number
}

export interface AutoMLConfig {
  engine: 'mlevolve' | string
  enabled: boolean
  steps: number
  time_limit_secs: number
  parallel_search_num: number
  k_fold_validation: number
  check_format: boolean
  expose_prediction: boolean
  generate_submission: boolean
  steerable_reasoning: boolean
  search_num_drafts: number
  search_num_bugs: number
  search_num_improves: number
  search_max_debug_depth: number
  search_back_debug_depth: number
  metric_improvement_threshold: number
  invalid_metric_upper_bound: number
  max_improve_failure: number
  decay_type: string
  exploration_constant: number
  lower_bound: number
  goal: string
  eval: string
  initial_drafts: number
  preprocess_data: boolean
  copy_data: boolean
  data_preview: boolean
  use_diff_mode: boolean
  check_data_leakage: boolean
  use_global_memory: boolean
  memory_similarity_threshold: number
  memory_embedding_backend: string
  memory_embedding_model: string
  memory_embedding_device: string
  memory_embedding_model_path: string
  use_coldstart: boolean
  use_grading_server: boolean
  exec_timeout_secs: number
}

export interface AutoReportConfig {
  enabled: boolean
  audience: string
  language: string
  include_raw_logs: boolean
  include_code_excerpt: boolean
  use_llm: boolean
}

export interface TaskConfig {
  task_name: string
  input_root: string
  output_root: string
  auto_realize: AutoRealizeConfig
  auto_ml: AutoMLConfig
  auto_report: AutoReportConfig
}

export interface Task {
  id: string
  task_name: string
  input_root: string
  output_root: string
  created_at: number
  updated_at: number
  status: 'idle' | 'running' | 'completed' | 'failed' | 'stopped' | string
  phase: string
  config: TaskConfig
  run_dir?: string | null
  run_started_at?: number | null
  auto_ml_log_dir?: string | null
  auto_ml_workspace_dir?: string | null
  report_dir?: string | null
  last_error?: string | null
}

export interface GlobalSettings {
  python: {
    executable: string
  }
  resource: {
    cpuLimit: number
    memoryLimitGb: number
  }
  llm: {
    modelLibrary: ModelConfig[]
    roleModels: ModelRoleSelection
    codeModel: {
      model: string
      baseUrl: string
    apiKey: string
    enableThinking: boolean | null
    reasoningEffort: string
    maxTokens?: number
    structuredDisableThinking: boolean
  }
  autoRealizeModel: {
    model: string
    baseUrl: string
    apiKey: string
    enableThinking: boolean | null
    reasoningEffort: string
    maxTokens?: number
    structuredDisableThinking: boolean
  }
  feedbackModel: {
    model: string
    baseUrl: string
    apiKey: string
    enableThinking: boolean | null
    reasoningEffort: string
    maxTokens?: number
  }
    vllm: {
      enabled: boolean
      model: string
      baseUrl: string
      apiKey: string
    }
  }
  coreServices: {
    autoRealizeBaseUrl: string
    mlevolveBaseUrl: string
    autoReportBaseUrl: string
    requestTimeoutSecs: number
  }
  mlevolve: {
    torchHubDir: string
    pretrainModelDir: string
    embeddingBaseUrl: string
    embeddingApiKey: string
    embeddingModel: string
  }
}

export interface ModelConfig {
  id: string
  name: string
  model: string
  baseUrl: string
  apiKey: string
  thinkingMode: 'default' | 'enabled' | 'disabled' | string
  reasoningEffort: 'default' | 'low' | 'medium' | 'high' | 'xhigh' | 'max' | string
  maxTokens: number | '' | null
}

export interface ModelRoleSelection {
  autoRealize: string
  autoRealizeVision: string
  autoMlCode: string
  autoMlFeedback: string
  embedding: string
}

export interface SnapshotPayload {
  task: Task
  auto_realize: {
    report_dir?: string
    current_state?: Record<string, unknown>
    frontend_manifest?: Record<string, unknown>
    run_summary?: Record<string, unknown>
    data_cognition_report?: Record<string, unknown>
    question_investigation_report?: Record<string, unknown>
    task_definition_report?: Record<string, unknown>
    submission_report?: Record<string, unknown>
    evaluation_contract_report?: Record<string, unknown>
    main_task_protocol?: Record<string, unknown>
    automl_context_pack?: Record<string, unknown>
    authoritative_task_memory?: Record<string, unknown>
    agent_context_pack?: Record<string, unknown>
    retrieved_knowledge?: unknown[]
    events?: Record<string, unknown>[]
    directory_tree_text?: string
    output_tree_text?: string
    description_text?: string
    data_description_text?: string
    automl_context_text?: string
    original_requirements_text?: string
    file_cognition_index?: Record<string, { json?: Record<string, unknown>; markdown?: string }>
  }
  auto_ml: {
    engine?: string
    log_dir?: string
    workspace_dir?: string
    events?: Record<string, unknown>[]
    nodes?: MctsNode[]
    pending_nodes?: MctsNode[]
    best_node_id?: string | null
    best_solution_code?: string
    best_metric_text?: string
    ml_log?: string
    verbose_log?: string
    frontend_stdout?: string
    frontend_stderr?: string
    service_stdout?: string
    service_stderr?: string
  }
  auto_report?: {
    output_dir?: string
    current_state?: Record<string, unknown>
    events?: Record<string, unknown>[]
    report?: Record<string, unknown>
    report_markdown?: string
    resolved_config?: Record<string, unknown>
    stdout?: string
    stderr?: string
  }
}

export interface MctsNode {
  id: string
  parent_id?: string | null
  stage?: string
  plan?: string
  code?: string
  result?: string
  insight?: string
  llm_insight?: string | null
  parser_analysis?: string | null
  decision_signals?: Record<string, unknown> | null
  metric?: number | null
  maximize?: boolean | null
  is_buggy?: boolean | null
  is_valid?: boolean | null
  visits?: number
  total_reward?: number
  uct?: number
  finish_time?: string | null
  created_time?: string | null
  exec_time?: number | null
  branch_id?: number | null
  from_topk?: boolean | null
  status?: string | null
  pending_execution?: boolean | null
  label?: string | null
}

export interface DirectoryEntry {
  name: string
  path: string
  is_dir: boolean
}

export interface PythonEnvironment {
  path: string
  version: string
  source: string
  exists: boolean
}

