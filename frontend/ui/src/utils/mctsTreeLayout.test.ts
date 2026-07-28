import { describe, expect, it } from 'vitest'
import type { MctsNode } from '../types'
import { buildMctsTreeLayout } from './mctsTreeLayout'

function node(id: string, parentId: string | null, created: string): MctsNode {
  return { id, parent_id: parentId, created_time: created, stage: id === 'root' ? 'root' : 'improve' }
}

describe('buildMctsTreeLayout', () => {
  it('lays a tree out from top to bottom and centers parents over child subtrees', () => {
    const layout = buildMctsTreeLayout([
      node('root', null, '0'),
      node('left', 'root', '1'),
      node('right', 'root', '2'),
      node('left-a', 'left', '3'),
      node('left-b', 'left', '4'),
      node('right-a', 'right', '5'),
      node('right-b', 'right', '6'),
    ])
    const byId = new Map(layout.nodes.map((item) => [item.id, item]))

    expect(byId.get('root')?.y).toBeLessThan(byId.get('left')?.y ?? 0)
    expect(byId.get('left')?.y).toBeLessThan(byId.get('left-a')?.y ?? 0)
    expect(byId.get('left')?.x).toBe(
      ((byId.get('left-a')?.x ?? 0) + (byId.get('left-b')?.x ?? 0)) / 2,
    )
    expect(byId.get('right')?.x).toBe(
      ((byId.get('right-a')?.x ?? 0) + (byId.get('right-b')?.x ?? 0)) / 2,
    )
    expect(byId.get('left-b')?.x).toBeLessThan(byId.get('right-a')?.x ?? 0)
    expect((byId.get('left-b')?.x ?? 0) - (byId.get('left-a')?.x ?? 0)).toBe(64)
    expect((byId.get('left')?.y ?? 0) - (byId.get('root')?.y ?? 0)).toBe(76)
  })

  it('keeps orphaned and cyclic snapshot nodes visible', () => {
    const layout = buildMctsTreeLayout([
      node('orphan', 'missing', '0'),
      node('cycle-a', 'cycle-b', '1'),
      node('cycle-b', 'cycle-a', '2'),
    ])

    expect(layout.nodes.map((item) => item.id).sort()).toEqual(['cycle-a', 'cycle-b', 'orphan'])
    expect(layout.nodes.every((item) => Number.isFinite(item.x) && Number.isFinite(item.y))).toBe(true)
  })
})
