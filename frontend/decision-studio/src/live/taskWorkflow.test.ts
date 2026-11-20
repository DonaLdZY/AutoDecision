import { describe, expect, it } from 'vitest'
import { invocationBlockers, taskWorkflow } from './taskWorkflow'
import type { DeliveryOverview } from './taskWorkflow'
const task = { id: 'task', status: 'completed', phase: 'completed' }
const overview = (state: DeliveryOverview['state']): DeliveryOverview => ({ state, published_ids: [], package_id: '', delivery_id: '', verification_status: 'not_run' })
describe('completed research next steps', () => {
  it('never treats research completion as publication, even against an older API', () => {
    expect(taskWorkflow(task).pendingDelivery).toBe(true)
    expect(taskWorkflow(task).kind).toBe('delivery')
    expect(taskWorkflow(task).label).toContain('待交付')
  })
  it('takes an unverified delivery to review without claiming a passed trial', () => {
    const next = taskWorkflow(task, overview('awaiting_publish'))
    expect(next.detail).toContain('检查使用说明和试算状态')
    expect(next.detail).not.toContain('已通过')
    expect(next.kind).toBe('delivery')
  })
  it('shows actual published models and removes the pending reminder', () => {
    const next = taskWorkflow(task, { ...overview('published'), package_id: 'pkg' })
    expect(next.pendingDelivery).toBe(false)
    expect(next.packageId).toBe('pkg')
    expect(next.kind).toBe('package')
  })
  it('keeps running and failed research out of the completed-delivery queue', () => {
    for (const status of ['running', 'failed', 'idle']) {
      expect(taskWorkflow({ ...task, status }).pendingDelivery).toBe(false)
    }
    expect(taskWorkflow({ ...task, status: 'running' }, overview('published')).stage).toBe('running')
  })
})
const step = () => ({ package_id: 'pkg', input_mode: 'project', csv_path: '', data_json: '{}', cutoff: 'latest', prepared: null as any })
describe('invocation blocking guidance', () => {
  it('explains why preparation is required and invalidates it after model or cutoff changes', () => {
    const input = step()
    expect(invocationBlockers([input], ['pkg'])[0]).toContain('准备项目输入')
    input.prepared = { package_id: 'pkg', requestedCutoff: 'latest' }
    expect(invocationBlockers([input], ['pkg'])).toEqual([])
    input.cutoff = '2025-07-12'
    expect(invocationBlockers([input], ['pkg'])).toHaveLength(1)
    input.cutoff = 'latest'; input.package_id = 'other'
    expect(invocationBlockers([input], ['other'])).toHaveLength(1)
  })
  it('explains unavailable packages, empty CSV input and broken JSON', () => {
    expect(invocationBlockers([{ ...step(), input_mode: 'csv' }], [])[0]).toContain('模型包已不可用')
    expect(invocationBlockers([{ ...step(), input_mode: 'csv' }], ['pkg'])[0]).toContain('CSV')
    expect(invocationBlockers([{ ...step(), input_mode: 'json', data_json: '{broken' }], ['pkg'])[0]).toContain('有效 JSON')
  })
  it('requires new input when the first step of a chain has been deleted', () => {
    expect(invocationBlockers([{ ...step(), input_mode: 'previous' }], ['pkg'])[0]).toContain('首步需要输入')
    expect(invocationBlockers([{ ...step(), input_mode: 'json' }, { ...step(), input_mode: 'previous' }], ['pkg'])).toEqual([])
  })
})
