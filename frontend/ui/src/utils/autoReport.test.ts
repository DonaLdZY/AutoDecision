import { describe, expect, it } from 'vitest'
import { normalizeAutoReportConfig } from './autoReport'

describe('normalizeAutoReportConfig', () => {
  it('migrates legacy task configs to the current report controls', () => {
    const result = normalizeAutoReportConfig({ enabled: true, audience: 'technical' })

    expect(result.detail_level).toBe('detailed')
    expect(result.comparison_candidate_limit).toBe(6)
    expect(result.max_retrieval_rounds).toBe(2)
    expect(result.enable_report_audit).toBe(true)
  })

  it('clamps cost-sensitive numeric controls', () => {
    const result = normalizeAutoReportConfig({
      comparison_candidate_limit: 99,
      max_retrieval_rounds: -3,
    })

    expect(result.comparison_candidate_limit).toBe(12)
    expect(result.max_retrieval_rounds).toBe(0)
  })
})
