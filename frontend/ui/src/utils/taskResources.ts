import type { TaskResourceConfig } from '../types'

export function defaultTaskResources(): TaskResourceConfig {
  return {
    cpu_cores: 4,
    memory_limit_gb: 8,
    accelerator_mode: 'all',
    accelerator_device_ids: [],
    monitor_interval_seconds: 0.5,
  }
}

export function normalizeTaskResources(value?: Partial<TaskResourceConfig> | null): TaskResourceConfig {
  const defaults = defaultTaskResources()
  const mode = value?.accelerator_mode
  return {
    cpu_cores: Math.max(1, Number(value?.cpu_cores || defaults.cpu_cores)),
    memory_limit_gb: Math.max(0, Number(value?.memory_limit_gb ?? defaults.memory_limit_gb)),
    accelerator_mode: mode === 'selected' || mode === 'none' ? mode : 'all',
    accelerator_device_ids: Array.isArray(value?.accelerator_device_ids)
      ? [...new Set(value.accelerator_device_ids.map((item) => String(item).trim().toLowerCase()).filter(Boolean))]
      : [],
    monitor_interval_seconds: Math.max(0.1, Number(value?.monitor_interval_seconds || defaults.monitor_interval_seconds)),
  }
}
