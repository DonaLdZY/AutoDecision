import { graphlib, layout } from '@dagrejs/dagre'
import type { MctsNode } from '../types'

export type GraphAction = 'draft' | 'improve' | 'debug' | 'evolution' | 'fusion'
export type GraphNodeState = 'success' | 'pending' | 'bug' | 'unreviewed'
export type GraphInputNode = MctsNode & { fusion_sources?: string[]; parent_ids?: string[]; evaluation_protocol?: Record<string, unknown> }
export interface GraphPosition { id: string; x: number; y: number }
export interface GraphEdge { id: string; from: string; to: string; fusion: boolean; action: GraphAction; points: Array<{ x: number; y: number }> }
export interface SearchGraph { nodes: GraphPosition[]; edges: GraphEdge[]; width: number; height: number }
export interface Camera { x: number; y: number; scale: number }
export const NODE_WIDTH = 140
export const NODE_HEIGHT = 64
export const MIN_ZOOM = 0.12
export const MAX_ZOOM = 3

export function graphAction(stage?: string | null): GraphAction {
  const value = String(stage ?? '').toLowerCase()
  if (value.includes('fusion')) return 'fusion'
  if (value.includes('debug') || value.includes('bug')) return 'debug'
  if (value.includes('evolution')) return 'evolution'
  if (value.includes('improve')) return 'improve'
  return 'draft'
}

export function graphNodeState(node: MctsNode): GraphNodeState {
  if (node.status === 'failed' || node.is_buggy === true) return 'bug'
  if (node.pending_execution || ['generating', 'pending_execution', 'executing', 'reviewing', 'cancelled'].includes(String(node.status))) return 'pending'
  return node.is_buggy === false ? 'success' : 'unreviewed'
}

function sources(node: GraphInputNode): string[] {
  return [...new Set([node.parent_id, ...(node.parent_ids ?? []), ...(node.fusion_sources ?? [])].filter((id): id is string => Boolean(id) && id !== node.id))]
}

export function topologyKey(nodes: GraphInputNode[]): string {
  return JSON.stringify(nodes.map(node => [node.id, node.parent_id, sources(node).sort(), graphAction(node.stage)]).sort((a, b) => String(a[0]).localeCompare(String(b[0]))))
}

export function buildSearchGraph(input: GraphInputNode[]): SearchGraph {
  const nodes = [...new Map(input.filter(node => node.id).map(node => [node.id, node])).values()].sort((a, b) => String(a.id).localeCompare(String(b.id)))
  if (!nodes.length) return { nodes: [], edges: [], width: 400, height: 280 }
  const ids = new Set(nodes.map(node => node.id))
  const graph = new graphlib.Graph({ multigraph: true }).setGraph({ rankdir: 'TB', nodesep: 30, ranksep: 68, edgesep: 16, marginx: 40, marginy: 40, acyclicer: 'greedy' }).setDefaultEdgeLabel(() => ({}))
  for (const node of nodes) graph.setNode(node.id, { width: NODE_WIDTH, height: NODE_HEIGHT })
  const edges: Array<Omit<GraphEdge, 'points'>> = []
  for (const node of nodes) {
    for (const parent of sources(node)) {
      if (!ids.has(parent)) continue
      const id = `${parent}:${node.id}`
      const fusion = parent !== node.parent_id || graphAction(node.stage) === 'fusion'
      graph.setEdge(parent, node.id, { weight: parent === node.parent_id ? 3 : 1 }, id)
      edges.push({ id, from: parent, to: node.id, fusion, action: graphAction(node.stage) })
    }
  }
  layout(graph)
  return {
    nodes: nodes.map(node => ({ id: node.id, x: graph.node(node.id).x, y: graph.node(node.id).y })),
    edges: edges.map(edge => ({ ...edge, points: graph.edge({ v: edge.from, w: edge.to, name: edge.id }).points })),
    width: Math.max(220, graph.graph().width ?? 400),
    height: Math.max(160, graph.graph().height ?? 280),
  }
}

export function zoomAt(camera: Camera, scale: number, focus: { x: number; y: number }): Camera {
  const next = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, scale))
  return { x: focus.x - (focus.x - camera.x) * next / camera.scale, y: focus.y - (focus.y - camera.y) * next / camera.scale, scale: next }
}

export function fitGraph(graph: Pick<SearchGraph, 'width' | 'height'>, width: number, height: number): Camera {
  const scale = Math.min(1.25, Math.max(MIN_ZOOM, Math.min((width - 48) / graph.width, (height - 48) / graph.height)))
  return { x: (width - graph.width * scale) / 2, y: (height - graph.height * scale) / 2, scale }
}

export function formatGraphMetric(value: unknown): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) return '--'
  if (value !== 0 && (Math.abs(value) >= 100000 || Math.abs(value) < 0.001)) return value.toExponential(2)
  return new Intl.NumberFormat('en', { maximumFractionDigits: 4 }).format(value)
}
