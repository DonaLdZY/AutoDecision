import { describe, expect, it } from 'vitest'
import { buildSearchGraph, fitGraph, graphAction, topologyKey, zoomAt, NODE_HEIGHT, NODE_WIDTH } from './mctsGraph'

describe('search graph geometry', () => {
  it('keeps fusion lineage separate from primary ancestry', () => {
    const graph = buildSearchGraph([{ id: 'a' }, { id: 'b' }, { id: 'f', stage: 'fusion', parent_id: 'a', fusion_sources: ['a', 'b', 'missing', 'f'] }])
    expect(graph.edges.map(edge => [edge.from, edge.to, edge.fusion])).toEqual([['a', 'f', true], ['b', 'f', true]])
    expect(graph.edges.every(edge => edge.points.length >= 2)).toBe(true)
    expect(graphAction('fusion_draft')).toBe('fusion')
  })
  it('does not invalidate geometry when scores, visits or code change', () => {
    const node = { id: 'a', metric: 10, visits: 2, code: 'one' }
    expect(topologyKey([node])).toBe(topologyKey([{ ...node, metric: 2, visits: 30, code: 'two' }]))
    expect(topologyKey([node])).not.toBe(topologyKey([node, { id: 'b', parent_id: 'a' }]))
  })
  it('keeps sibling boxes separate and handles cycles and orphan nodes', () => {
    const graph = buildSearchGraph([{ id: 'a', parent_id: 'b' }, { id: 'b', parent_id: 'a' }, { id: 'c', parent_id: 'missing' }, { id: 'd', parent_id: 'a' }])
    expect(graph.nodes).toHaveLength(4)
    for (const node of graph.nodes) {
      expect(Number.isFinite(node.x) && Number.isFinite(node.y)).toBe(true)
      for (const other of graph.nodes.filter(other => other.id !== node.id)) expect(Math.abs(node.x - other.x) >= NODE_WIDTH || Math.abs(node.y - other.y) >= NODE_HEIGHT).toBe(true)
    }
  })
  it('keeps the world point under the cursor fixed while zooming', () => {
    const camera = { x: 30, y: -80, scale: 0.7 }, focus = { x: 300, y: 180 }
    const next = zoomAt(camera, 1.7, focus)
    expect((focus.x - next.x) / next.scale).toBeCloseTo((focus.x - camera.x) / camera.scale)
    expect((focus.y - next.y) / next.scale).toBeCloseTo((focus.y - camera.y) / camera.scale)
  })
  it('fits the initial graph into narrow and wide workspaces', () => {
    for (const [width, height] of [[360, 480], [1100, 700]]) {
      const camera = fitGraph({ width: 1400, height: 1100 }, width!, height!)
      expect(camera.x).toBeGreaterThanOrEqual(0)
      expect(camera.y).toBeGreaterThanOrEqual(0)
      expect(1400 * camera.scale).toBeLessThanOrEqual(width!)
      expect(1100 * camera.scale).toBeLessThanOrEqual(height!)
    }
  })
})
