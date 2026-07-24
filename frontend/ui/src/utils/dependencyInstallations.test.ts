import { describe, expect, it } from 'vitest'
import {
  dependencyInstallCount,
  dependencyRequirementCandidates,
  parseDependencyInstallationRecords,
} from './dependencyInstallations'

describe('dependency installation presentation', () => {
  it('parses valid JSONL records and ignores malformed lines', () => {
    const records = parseDependencyInstallationRecords([
      '{"distribution":"ortools","status":"installed","success":true}',
      'not-json',
      '',
      '{"distribution":"pulp","status":"failed","success":false}',
    ].join('\n'))

    expect(records).toHaveLength(2)
    expect(records[0].distribution).toBe('ortools')
    expect(records[1].status).toBe('failed')
  })

  it('normalizes counters and requirement candidates', () => {
    const summary = {
      attempt_count: 2.9,
      installed_count: -1,
      requirements_candidates: ['pulp>=2.8,<3', 'ortools>=9.9,<10', 'pulp>=2.8,<3'],
    }

    expect(dependencyInstallCount(summary, 'attempt_count')).toBe(2)
    expect(dependencyInstallCount(summary, 'installed_count')).toBe(0)
    expect(dependencyRequirementCandidates(summary)).toEqual([
      'ortools>=9.9,<10',
      'pulp>=2.8,<3',
    ])
  })
})
