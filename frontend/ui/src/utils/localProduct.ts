import type { Task, TaskConfig } from '../types'

export function primaryAction(task: Task) {
  if (task.status === 'running') return task.phase.includes('stopping') ? 'stopping' : 'stop'
  if (task.status === 'completed') return 'solution'
  if (['interrupted_resumable', 'stopped', 'failed', 'interrupted_incomplete'].includes(task.status)) return 'resume'
  return task.run_dir ? 'solution' : 'start'
}

export function executionStage(task?: Task | null, cognition?: string | null) {
  if (!task) return '未开始'
  const phase = task.phase || task.interrupted_from_phase || ''
  if (phase.includes('automl')) return '方案搜索'
  if (phase.includes('report')) return '报告生成'
  if (phase.includes('review') || cognition === 'task_definition') return '任务定义'
  if (phase.includes('autorealize')) return '数据理解'
  if (phase === 'starting') return '启动中'
  if (phase === 'resuming') return '恢复检查中'
  return task.status === 'idle' ? '未开始' : task.status === 'completed' ? '执行完成' : '已中断 / 待检查'
}

export function applyResourcePreset(config: TaskConfig, preset: 'light' | 'standard' | 'full', cpu = 4, memoryGb = 8) {
  const policy = { light: [2, 4, 1, 4, 1800], standard: [4, 8, 2, 8, 10800], full: [Math.max(1, cpu - 1), Math.max(1, Math.floor(memoryGb * .75)), 4, 16, 21600] }[preset]!
  config.resources.cpu_cores = Math.max(1, Math.min(policy[0]!, cpu - 1 || 1))
  config.resources.memory_limit_gb = Math.max(1, Math.min(policy[1]!, Math.floor(memoryGb * .75)))
  // GPU use is an explicit device choice in resource settings, never implied by a preset.
  config.resources.accelerator_mode = 'none'
  config.resources.accelerator_device_ids = []
  config.auto_ml.parallel_search_num = Math.min(policy[2]!, config.resources.cpu_cores)
  config.auto_realize.llm_concurrency = policy[3]!
  config.auto_ml.time_limit_secs = policy[4]!
}
