import type { MctsNode } from '../types'

export type MctsEdgeAction = 'draft' | 'improve' | 'debug' | 'other'

export type MctsLayoutNode = MctsNode & {
  x: number
  y: number
  depth: number
  order: number
}

export interface MctsLayoutEdge {
  from: string
  to: string
  action: MctsEdgeAction
}

export interface MctsTreeLayout {
  nodes: MctsLayoutNode[]
  edges: MctsLayoutEdge[]
  width: number
  height: number
}

interface MctsTreeLayoutOptions {
  horizontalStep?: number
  verticalStep?: number
  paddingX?: number
  paddingTop?: number
  paddingBottom?: number
  forestGap?: number
  minWidth?: number
  minHeight?: number
}

function nodeTime(node: MctsNode): string {
  return String(node.created_time ?? node.finish_time ?? '')
}

function compareNodes(a: MctsNode, b: MctsNode): number {
  const timeOrder = nodeTime(a).localeCompare(nodeTime(b))
  return timeOrder || String(a.id).localeCompare(String(b.id))
}

function actionOf(stage?: string | null): MctsEdgeAction {
  const normalized = String(stage ?? '').toLowerCase()
  if (normalized.includes('draft')) return 'draft'
  if (normalized.includes('improve') || normalized.includes('evolution') || normalized.includes('fusion')) {
    return 'improve'
  }
  if (normalized.includes('debug') || normalized.includes('bug')) return 'debug'
  return 'other'
}

export function buildMctsTreeLayout(
  nodes: MctsNode[],
  options: MctsTreeLayoutOptions = {},
): MctsTreeLayout {
  const horizontalStep = options.horizontalStep ?? 64
  const verticalStep = options.verticalStep ?? 76
  const paddingX = options.paddingX ?? 36
  const paddingTop = options.paddingTop ?? 30
  const paddingBottom = options.paddingBottom ?? 30
  const forestGap = options.forestGap ?? 1
  const minWidth = options.minWidth ?? 560
  const minHeight = options.minHeight ?? 320

  if (!nodes.length) return { nodes: [], edges: [], width: minWidth, height: minHeight }

  const nodeMap = new Map(nodes.map((node) => [node.id, node]))
  const childrenMap = new Map<string, MctsNode[]>()
  const edges: MctsLayoutEdge[] = []

  for (const node of nodes) {
    if (!node.parent_id || node.parent_id === node.id || !nodeMap.has(node.parent_id)) continue
    const children = childrenMap.get(node.parent_id) ?? []
    children.push(node)
    childrenMap.set(node.parent_id, children)
    edges.push({ from: node.parent_id, to: node.id, action: actionOf(node.stage) })
  }
  for (const children of childrenMap.values()) children.sort(compareNodes)

  const roots = nodes
    .filter((node) => !node.parent_id || node.parent_id === node.id || !nodeMap.has(node.parent_id))
    .sort(compareNodes)
  const visited = new Set<string>()
  const positioned = new Map<string, { xSlot: number; depth: number; order: number }>()
  let nextLeafSlot = 0
  let order = 0

  function positionSubtree(node: MctsNode, depth: number, ancestors: Set<string>): number {
    if (positioned.has(node.id)) return positioned.get(node.id)?.xSlot ?? nextLeafSlot

    visited.add(node.id)
    const nextAncestors = new Set(ancestors)
    nextAncestors.add(node.id)
    const children = (childrenMap.get(node.id) ?? []).filter(
      (child) => !visited.has(child.id) && !nextAncestors.has(child.id),
    )
    const childSlots = children.map((child) => positionSubtree(child, depth + 1, nextAncestors))
    const xSlot = childSlots.length
      ? (childSlots[0] + childSlots[childSlots.length - 1]) / 2
      : nextLeafSlot++
    positioned.set(node.id, { xSlot, depth, order: order++ })
    return xSlot
  }

  const layoutRoots = [...roots]
  for (const node of [...nodes].sort(compareNodes)) {
    if (!layoutRoots.some((root) => root.id === node.id) && !visited.has(node.id)) layoutRoots.push(node)
  }
  for (const root of layoutRoots) {
    if (visited.has(root.id)) continue
    positionSubtree(root, 0, new Set())
    nextLeafSlot += forestGap
  }

  // Malformed cyclic input may have no natural root. Keep every node visible as
  // a separate root instead of allowing a bad snapshot to break the whole view.
  for (const node of [...nodes].sort(compareNodes)) {
    if (!positioned.has(node.id)) {
      positioned.set(node.id, { xSlot: nextLeafSlot++, depth: 0, order: order++ })
    }
  }

  const positions = [...positioned.values()]
  const maxDepth = Math.max(...positions.map((item) => item.depth), 0)
  const maxSlot = Math.max(...positions.map((item) => item.xSlot), 0)
  const layoutNodes = nodes.map<MctsLayoutNode>((node) => {
    const position = positioned.get(node.id) ?? { xSlot: 0, depth: 0, order: 0 }
    return {
      ...node,
      x: paddingX + position.xSlot * horizontalStep,
      y: paddingTop + position.depth * verticalStep,
      depth: position.depth,
      order: position.order,
    }
  })

  return {
    nodes: layoutNodes,
    edges,
    width: Math.max(minWidth, paddingX * 2 + maxSlot * horizontalStep),
    height: Math.max(minHeight, paddingTop + maxDepth * verticalStep + paddingBottom),
  }
}
