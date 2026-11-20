import type { AutoReportConfig } from '../types'

export function defaultAutoReportConfig(): AutoReportConfig {
  return {
    enabled: true,
    request_timeout_secs: 1200,
    audience: 'technical',
    detail_level: 'detailed',
    comparison_candidate_limit: 6,
    max_retrieval_rounds: 2,
    enable_report_audit: true,
  }
}

export function normalizeAutoReportConfig(value: Partial<AutoReportConfig> | null | undefined): AutoReportConfig {
  const defaults = defaultAutoReportConfig()
  const candidateLimit = Number(value?.comparison_candidate_limit ?? defaults.comparison_candidate_limit)
  const retrievalRounds = Number(value?.max_retrieval_rounds ?? defaults.max_retrieval_rounds)
  const timeout = Number(value?.request_timeout_secs ?? defaults.request_timeout_secs)
  const audience = value?.audience
  const detailLevel = value?.detail_level
  return {
    enabled: value?.enabled !== false,
    request_timeout_secs: Math.min(3600, Math.max(30, Number.isFinite(timeout) ? timeout : defaults.request_timeout_secs)),
    audience: audience === 'executive' || audience === 'delivery' ? audience : 'technical',
    detail_level: detailLevel === 'concise' || detailLevel === 'standard' ? detailLevel : 'detailed',
    comparison_candidate_limit: Math.min(12, Math.max(2, Number.isFinite(candidateLimit) ? Math.round(candidateLimit) : 6)),
    max_retrieval_rounds: Math.min(4, Math.max(0, Number.isFinite(retrievalRounds) ? Math.round(retrievalRounds) : 2)),
    enable_report_audit: value?.enable_report_audit !== false,
  }
}
