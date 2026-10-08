import type { MctsNode, ReplayEvent, ReplayRecording, ReplayStage, SnapshotPayload, Task } from '../types'

export type PlaybackMode = 'nodes' | 'original'
export type ReplayArtifact = 'automl_context' | 'description'
export interface ReplayFocus { stage: ReplayStage; artifact?: ReplayArtifact }

// Raw log stages interleave with snapshots. Follow document milestones instead
// of that telemetry, and only move backwards at an explicit rerun boundary.
export function replayFocusTimeline(events: ReplayEvent[]): ReplayFocus[] {
  let focus: ReplayFocus = { stage: 'data_cognition' }
  const seen = new Set<ReplayArtifact>()
  return events.map(event => {
    if (event.label === 'task_reset') {
      seen.clear()
      focus = { stage: 'data_cognition' }
      return focus
    }
    if (event.label === 'search_reset') {
      focus = { stage: 'automl' }
      return focus
    }
    const { snapshot, event: raw } = event.payload
    const fields = raw?.fields as Record<string, unknown> | undefined
    const file = raw?.event === 'GENERATED_FILE' && /(?:task_definition|stage\.p2)/.test(String(raw.component))
      ? String(fields?.file ?? '').replace(/\\/g, '/').split('/').at(-1) : undefined
    for (const artifact of ['automl_context', 'description'] as const) {
      const text = snapshot?.auto_realize?.[`${artifact}_text`]
      if (!seen.has(artifact) && (text?.trim() || file === `${artifact}.md`)) {
        seen.add(artifact)
        if (focus.stage === 'data_cognition' || focus.stage === 'task_definition') {
          focus = { stage: 'task_definition', artifact }
        }
      }
    }
    const ml = snapshot?.auto_ml
    const report = snapshot?.auto_report
    const hasSearch = ml && (ml.nodes?.length || ml.pending_nodes?.length || ml.best_solution_code || ml.best_metric_text)
    const hasReport = report && (report.report_markdown || Object.keys(report.current_state ?? {}).length || Object.keys(report.report ?? {}).length)
    if (event.stage === 'report' && (event.kind !== 'artifact' || hasReport)) {
      if (focus.stage !== 'report') focus = { stage: 'report' }
    } else if (event.stage === 'automl' && focus.stage !== 'report' && (event.kind !== 'artifact' || hasSearch)) {
      if (focus.stage !== 'automl') focus = { stage: 'automl' }
    }
    return focus
  })
}

export function emptyReplaySnapshot(task: Task): SnapshotPayload {
  return { task: { ...task, status: 'idle', phase: 'idle' }, auto_realize: { events: [] },
    auto_ml: { nodes: [], pending_nodes: [], events: [] }, auto_report: { events: [] } }
}

export function selectVisibleBest(nodes: MctsNode[]): MctsNode | undefined {
  const isDelivered = (n: MctsNode) => n.delivery_ready === true
    || (n.delivery_ready == null && n.is_valid === true && n.is_buggy === false)
  const eligible = nodes.filter(n => Number.isFinite(n.metric) && !n.is_buggy && n.is_valid !== false
    && (isDelivered(n) || n.search_eligible === true))
  const delivered = eligible.filter(isDelivered)
  const pool = delivered.length ? delivered : eligible
  const maximize = pool.find(n => typeof n.maximize === 'boolean')?.maximize ?? true
  return pool.reduce<MctsNode | undefined>((best, n) => {
    if (typeof n.maximize === 'boolean' && n.maximize !== maximize) return best
    if (!best) return n
    return (maximize ? Number(n.metric) > Number(best.metric) : Number(n.metric) < Number(best.metric)) ? n : best
  }, undefined)
}

// Node events are replacements: a final score must never survive a backward seek.
export function applyReplayEvent(previous: SnapshotPayload, event: ReplayEvent): SnapshotPayload {
  const patch = event.payload.snapshot ?? {}
  const next: SnapshotPayload = { ...previous, ...patch,
    task: { ...previous.task, ...patch.task, ...event.payload.task },
    auto_realize: { ...previous.auto_realize, ...patch.auto_realize },
    auto_ml: { ...previous.auto_ml, ...patch.auto_ml },
    auto_report: { ...previous.auto_report, ...patch.auto_report } }
  const node = event.payload.node
  if (node) {
    const pending = node.pending_execution || ['generating', 'pending_execution', 'executing', 'reviewing'].includes(node.status ?? '')
    next.auto_ml.nodes = (next.auto_ml.nodes ?? []).filter(n => n.id !== node.id)
    next.auto_ml.pending_nodes = (next.auto_ml.pending_nodes ?? []).filter(n => n.id !== node.id)
    ;(pending ? next.auto_ml.pending_nodes : next.auto_ml.nodes).push({ ...node })
  }
  if (node || patch.auto_ml) {
    const best = selectVisibleBest(next.auto_ml.nodes ?? [])
    next.auto_ml.best_node_id = best?.id ?? null
    next.auto_ml.best_node_kind = best ? best.delivery_ready || (best.delivery_ready == null && best.is_valid && best.is_buggy === false) ? 'delivery' : 'provisional' : null
  }
  if (event.payload.event) {
    const stage = event.stage === 'automl' ? next.auto_ml : event.stage === 'report' ? next.auto_report! : next.auto_realize
    stage.events = [...(stage.events ?? []), event.payload.event]
  }
  return next
}

export function projectReplay(recording: ReplayRecording, index: number, task: Task): SnapshotPayload {
  let snapshot = emptyReplaySnapshot(task)
  for (let i = 0; i <= Math.min(index, recording.events.length - 1); i++) {
    snapshot = applyReplayEvent(snapshot, recording.events[i]!)
  }
  return snapshot
}

// First appearance of each candidate gets one interval; intervening telemetry
// shares that interval so a busy log cannot slow down a client presentation.
export function playbackOffsets(events: ReplayEvent[], mode: PlaybackMode, nodeIntervalMs: number, focus = replayFocusTimeline(events)): number[] {
  if (mode === 'original') return events.map(e => Math.max(0, e.offset_ms))
  const interval = Number.isFinite(nodeIntervalMs) ? Math.max(100, Math.min(60000, nodeIntervalMs)) : 1000
  const seen = new Set<string>()
  const anchors: number[] = []
  events.forEach((e, index) => {
    const id = e.payload.node?.id
    const newNode = !!id && !seen.has(id)
    if (index === 0 || newNode || focus[index] !== focus[index - 1]
      || (e.stage !== 'automl' && e.kind === 'artifact') || index === events.length - 1) anchors.push(index)
    if (id) seen.add(id)
  })
  const offsets = events.map(() => 0)
  for (let a = 0; a < anchors.length; a++) {
    const begin = anchors[a]!, end = anchors[a + 1] ?? begin
    offsets[begin] = a * interval
    for (let i = begin + 1; i < end; i++) offsets[i] = a * interval + interval * (i - begin) / (end - begin)
  }
  return offsets
}

export function indexAtTime(offsets: number[], time: number): number {
  let lo = 0, hi = offsets.length
  while (lo < hi) {
    const mid = (lo + hi) >>> 1
    if (offsets[mid]! <= time) lo = mid + 1
    else hi = mid
  }
  return lo - 1
}
