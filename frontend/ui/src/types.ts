export interface AutoRealizeConfig {
  enable_question_investigator: boolean
  enable_fewshot: boolean
  generate_sample_submission: boolean
  direct_automl_from_description: boolean
  enable_vllm: boolean
  task_hint: string
  llm_timeout: number
  llm_concurrency: number
  optimize_llm_cost: boolean
  llm_file_cognition_mode: 'all' | 'documents_only' | 'none'
  table_profile_sample_rows: number
  investigation_max_questions: number
  investigation_max_rounds_per_question: number
  investigation_max_scripts_per_question: number
  investigation_script_timeout_secs: number
  prompt_token_budget: number
  artifact_consistency_enabled: boolean
  artifact_consistency_max_rounds: number
  cross_stage_memory_enabled: boolean
  cross_stage_headroom_ratio: number
  cross_stage_retrieval_enabled: boolean
}

export interface AutoMLConfig {
  engine: 'mlevolve' | string
  enabled: boolean
  goal: string
  eval: string
  steps: number
  time_limit_secs: number
  parallel_search_num: number
  generate_submission: boolean
  search_num_drafts: number
  search_num_bugs: number
  search_num_improves: number
  search_max_debug_depth: number
  search_back_debug_depth: number
  metric_improvement_threshold: number
  max_improve_failure: number
  exploration_constant: number
  lower_bound: number
  initial_drafts: number
  copy_data: boolean
  use_diff_mode: boolean
  check_data_leakage: boolean
  use_global_memory: boolean
  memory_similarity_threshold: number
  memory_embedding_backend: string
  memory_embedding_device: string
  memory_embedding_model_path: string
  use_coldstart: boolean
  exec_timeout_secs: number
  auto_install_missing_dependencies: boolean
  dependency_install_timeout_secs: number
  dependency_install_max_packages: number
  code_temperature: number
  feedback_temperature: number
  code_request_timeout_secs: number
  feedback_request_timeout_secs: number
  code_generation_max_retries: number
  feedback_generation_max_retries: number
  code_continuation_max_rounds: number
  feedback_continuation_max_rounds: number
  code_review_max_attempts: number
  preflight_regeneration_max_attempts: number
  code_review_escalate_to_code: boolean
  code_generation_extract_max_attempts: number
  metric_direction_max_attempts: number
  result_review_max_attempts: number
  refine_plan_max_attempts: number
  result_adjudicator_on_anomaly: boolean
  fast_first_draft: boolean
  fast_first_draft_skip_pre_review: boolean
  use_stepwise_after_first: boolean
  stepwise_context_max_tokens: number
  stepwise_compaction_keep_recent_steps: number
  stepwise_compaction_max_tokens: number
  stepwise_context_headroom_ratio: number
  search_topk_max_improves: number
  search_debug_prob: number
  search_branch_stagnation_threshold: number
  search_topk_stagnation_threshold: number
  search_stagnation_window: number
  search_top_candidates_size: number
  search_explore_switch_start: number
  search_explore_switch_end: number
  search_min_exploration_weight: number
  search_root_new_draft_probability: number
  fusion_vs_evolution_prob: number
  branch_fusion_trigger_prob: number
  max_fusion_drafts: number
  search_fusion_min_remaining_seconds: number
  search_fusion_min_successful_nodes: number
  search_fusion_min_branches: number
  use_optimization_experience_library: boolean
  optimization_experience_max_cards: number
  optimization_experience_min_score: number
  optimization_experience_max_chars: number
}

export interface AutoReportConfig {
  enabled: boolean
  audience: 'technical' | 'executive' | 'delivery'
  detail_level: 'concise' | 'standard' | 'detailed'
  comparison_candidate_limit: number
  max_retrieval_rounds: number
  enable_report_audit: boolean
}

export type AcceleratorMode = 'all' | 'selected' | 'none'

export interface TaskResourceConfig {
  cpu_cores: number
  memory_limit_gb: number
  accelerator_mode: AcceleratorMode
  accelerator_device_ids: string[]
  monitor_interval_seconds: number
}

export interface TaskConfig {
  task_name: string
  input_root: string
  output_root: string
  output_language: 'zh' | 'en'
  auto_realize: AutoRealizeConfig
  auto_ml: AutoMLConfig
  auto_report: AutoReportConfig
  resources: TaskResourceConfig
}

export interface Task {
  id: string
  task_name: string
  input_root: string
  output_root: string
  created_at: number
  updated_at: number
  status: 'idle' | 'running' | 'completed' | 'failed' | 'stopped' | 'interrupted_resumable' | 'interrupted_incomplete' | string
  phase: string
  config: TaskConfig
  run_dir?: string | null
  run_started_at?: number | null
  auto_ml_log_dir?: string | null
  auto_ml_workspace_dir?: string | null
  auto_ml_service_job_id?: string | null
  report_dir?: string | null
  last_error?: string | null
}

export interface GlobalSettings {
  python: {
    executable: string
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
    embeddingApiKeyConfigured?: boolean
    embeddingModel: string
  }
}

export interface ModelConfig {
  id: string
  name: string
  model: string
  baseUrl: string
  apiKey: string
  apiKeyConfigured?: boolean
  thinkingMode: 'default' | 'enabled' | 'disabled' | string
  reasoningEffort: 'default' | 'low' | 'medium' | 'high' | 'xhigh' | 'max' | string
  maxTokens: number | '' | null
  contextWindowTokens: number | '' | null
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
    best_node_kind?: 'delivery' | 'provisional' | null
    best_solution_code?: string
    best_metric_text?: string
    ml_log?: string
    verbose_log?: string
    frontend_stdout?: string
    frontend_stderr?: string
    service_stdout?: string
    service_stderr?: string
    resource_usage?: Record<string, unknown>
    dependency_installations?: string
    dependency_installation_summary?: DependencyInstallationSummary
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

export interface DependencyInstallationRecord {
  timestamp?: string
  run_log_dir?: string
  node_id?: string
  missing_module?: string
  distribution?: string
  requirement?: string
  selection_source?: string
  status?: string
  success?: boolean
  exit_code?: number | null
  duration_seconds?: number
  python_executable?: string
  install_target?: string
  installed_version?: string
  resolved_requirement?: string
  stdout_tail?: string
  stderr_tail?: string
}

export interface DependencyInstallationSummary {
  schema_version?: string
  updated_at?: string
  python_executable?: string
  install_target?: string
  attempt_count?: number
  installed_count?: number
  failed_count?: number
  rejected_count?: number
  installed_requirements?: string[]
  requirements_candidates?: string[]
  records?: DependencyInstallationRecord[]
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
  runtime_ok?: boolean | null
  search_eligible?: boolean | null
  score_recomputed?: boolean | null
  contract_valid?: boolean | null
  artifact_ready?: boolean | null
  delivery_ready?: boolean | null
  delivery_certified?: boolean | null
  certification_source?: string | null
  certification_notes?: string[] | null
  method_mode?: string | null
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

export interface AcceleratorDevice {
  id: string
  backend: string
  index: number
  name: string
  vendor: string
  uuid: string
  memory_mb: number
  visibility_env: string
  visibility_supported: boolean
  runtime_available: boolean
  source: string
}

export interface ResourceInventory {
  platform?: {
    system: string
    release: string
    machine: string
    python_platform: string
  }
  cpu: {
    logical_count: number
    physical_count: number
    available_ids: number[]
    affinity_supported: boolean
    enforcement?: {
      backend: string
      hard_limit: boolean
      total_process_tree: boolean
      exact_core_set: boolean
    }
  }
  memory: {
    total_bytes: number
    total_gb: number
    enforcement?: {
      backend: string
      hard_limit_supported: boolean
      total_process_tree: boolean
      over_limit_behavior: string
      whole_task_termination: boolean
    }
  }
  devices: AcceleratorDevice[]
  accelerator?: {
    backend: string
    isolatable_device_ids: string[]
    non_isolatable_device_ids: string[]
    mode_none_fully_enforced: boolean
    exclusive_reservation: boolean
    vram_quota: boolean
  }
  torch: {
    version: string
    python_executable?: string
    probe_source?: string
    cuda_available: boolean
    cuda_count: number
    hip_version: string
    xpu_available: boolean
    xpu_count: number
    mps_available: boolean
    error?: string
  }
}

