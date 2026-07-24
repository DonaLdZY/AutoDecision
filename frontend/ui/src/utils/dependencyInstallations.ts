import type { DependencyInstallationRecord, DependencyInstallationSummary } from '../types'

export function parseDependencyInstallationRecords(text: string): DependencyInstallationRecord[] {
  const records: DependencyInstallationRecord[] = []
  for (const line of text.split(/\r?\n/)) {
    const trimmed = line.trim()
    if (!trimmed) continue
    try {
      const value: unknown = JSON.parse(trimmed)
      if (value && typeof value === 'object' && !Array.isArray(value)) {
        records.push(value as DependencyInstallationRecord)
      }
    } catch {
      // A concurrently written or old malformed line must not break task monitoring.
    }
  }
  return records
}

export function dependencyInstallCount(
  summary: DependencyInstallationSummary | undefined,
  key: 'attempt_count' | 'installed_count' | 'failed_count' | 'rejected_count',
): number {
  const value = Number(summary?.[key] ?? 0)
  return Number.isFinite(value) && value >= 0 ? Math.floor(value) : 0
}

export function dependencyRequirementCandidates(
  summary: DependencyInstallationSummary | undefined,
): string[] {
  if (!Array.isArray(summary?.requirements_candidates)) return []
  return [...new Set(summary.requirements_candidates.map(String).filter(Boolean))].sort((a, b) => a.localeCompare(b))
}
