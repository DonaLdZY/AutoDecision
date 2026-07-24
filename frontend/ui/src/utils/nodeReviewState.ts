import type { MctsNode } from '../types'

export type NodeReviewState = 'pending' | 'success' | 'bug' | 'unreviewed'

export function isPendingNode(node: MctsNode): boolean {
  const status = String(node.status ?? '')
  return Boolean(node.pending_execution) || ['generating', 'pending_execution', 'executing', 'cancelled', 'failed'].includes(status)
}

export function nodeReviewState(node: MctsNode): NodeReviewState {
  if (isPendingNode(node)) return 'pending'
  if (node.is_buggy === false) return 'success'
  if (node.is_buggy === true) return 'bug'
  return 'unreviewed'
}
