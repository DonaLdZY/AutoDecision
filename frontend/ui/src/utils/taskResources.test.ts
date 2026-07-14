import { describe, expect, it } from 'vitest'

import { defaultTaskResources, normalizeTaskResources } from './taskResources'

describe('task resource settings', () => {
  it('provides stable defaults', () => {
    expect(defaultTaskResources()).toEqual({
      cpu_cores: 4,
      memory_limit_gb: 8,
      accelerator_mode: 'all',
      accelerator_device_ids: [],
      monitor_interval_seconds: 0.5,
    })
  })

  it('normalizes invalid numbers and duplicate device ids', () => {
    expect(
      normalizeTaskResources({
        cpu_cores: 0,
        memory_limit_gb: -2,
        accelerator_mode: 'selected',
        accelerator_device_ids: [' CUDA:0 ', 'cuda:0', 'XPU:1'],
        monitor_interval_seconds: 0,
      }),
    ).toEqual({
      cpu_cores: 4,
      memory_limit_gb: 0,
      accelerator_mode: 'selected',
      accelerator_device_ids: ['cuda:0', 'xpu:1'],
      monitor_interval_seconds: 0.5,
    })
  })
})
