import { describe, expect, it } from 'vitest'

import type { MctsNode } from '../types'
import { nodeReviewState } from './nodeReviewState'

function node(overrides: Partial<MctsNode>): MctsNode {
  return {
    id: 'node-1',
    parent_id: null,
    stage: 'debug',
    metric: null,
    ...overrides,
  }
}

describe('nodeReviewState', () => {
  it('marks an LLM-accepted scored node successful regardless of delivery flags', () => {
    expect(
      nodeReviewState(
        node({
          metric: 619406,
          is_buggy: false,
          is_valid: false,
          search_eligible: true,
          delivery_ready: false,
          delivery_certified: false,
        }),
      ),
    ).toBe('success')
  })

  it('marks the LLM-rejected node as a bug', () => {
    expect(nodeReviewState(node({ is_buggy: true }))).toBe('bug')
  })

  it('keeps generating nodes pending before any review verdict', () => {
    expect(nodeReviewState(node({ status: 'generating', is_buggy: null }))).toBe('pending')
  })
})
