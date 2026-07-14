import { describe, expect, it } from 'vitest'
import { deriveCognitionProgress } from './cognitionProgress'

describe('deriveCognitionProgress', () => {
  it('shows QDI as the active cognition stage while investigation is running', () => {
    const progress = deriveCognitionProgress([
      { component: 'module.data_cognition', event: 'FILES_SELECTED', fields: { selected: 28 } },
      { component: 'module.data_cognition.parallel', event: 'COMPLETED' },
      { component: 'module.data_cognition.relations', event: 'COMPLETED' },
      { component: 'module.data_cognition.investigator', event: 'ACTIVATED', ts: '2026-07-14T06:00:00Z' },
      {
        component: 'llm.client',
        event: 'REQUEST_STARTED',
        fields: { prompt: 'question_investigator_action' },
        ts: '2026-07-14T06:01:00Z',
      },
    ], { totalFiles: 28, completedFiles: 28, failedFiles: 0 })

    expect(progress.status).toBe('running')
    expect(progress.activityLabel).toContain('QDI')
    expect(progress.stages.find((stage) => stage.key === 'qdi')?.status).toBe('running')
    expect(progress.activeLlmCalls).toBe(1)
  })

  it('treats a persisted cognition report as completed even if early events were trimmed', () => {
    const progress = deriveCognitionProgress([], {
      totalFiles: 28,
      completedFiles: 28,
      failedFiles: 0,
      reportAvailable: true,
    })

    expect(progress.status).toBe('completed')
    expect(progress.percent).toBe(100)
  })
})
