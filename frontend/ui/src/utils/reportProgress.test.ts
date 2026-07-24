import { describe, expect, it } from 'vitest'
import { deriveReportProgress } from './reportProgress'

describe('deriveReportProgress', () => {
  it('maps stage events to a stable five-step progress view', () => {
    const events = [
      { component: 'autoreport.collector', event: 'ACTIVATED' },
      { component: 'autoreport.collector', event: 'COMPLETED' },
      { component: 'autoreport.generator', event: 'ACTIVATED' },
      { component: 'autoreport.analyzer', event: 'ACTIVATED' },
      { component: 'autoreport.analyzer', event: 'SOURCE_RETRIEVED' },
    ]
    const result = deriveReportProgress({ status: 'running' }, events)

    expect(result.status).toBe('running')
    expect(result.percent).toBe(30)
    expect(result.stages.map((stage) => stage.status)).toEqual([
      'completed',
      'running',
      'pending',
      'pending',
      'pending',
    ])
    expect(result.activityLabel).toContain('补读')
  })

  it('marks every stage complete when the pipeline completes', () => {
    const result = deriveReportProgress(
      { status: 'completed' },
      [{ component: 'autoreport.generator', event: 'COMPLETED' }],
    )

    expect(result.percent).toBe(100)
    expect(result.stages.every((stage) => stage.status === 'completed')).toBe(true)
  })
})
