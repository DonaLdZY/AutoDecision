import { afterEach, describe, expect, it, vi } from 'vitest'
import { effectScope, nextTick } from 'vue'
import { useReplay } from '../composables/useReplay'
import type { MctsNode, ReplayEvent, ReplayRecording, Task } from '../types'
import { applyReplayEvent, emptyReplaySnapshot, indexAtTime, playbackOffsets, projectReplay, replayFocusTimeline, selectVisibleBest } from './replay'

vi.mock('vue', async (original) => ({
  ...await original<typeof import('vue')>(),
  onUnmounted: vi.fn(),
}))

const task = { id: 'replay-test', task_name: 'Monthly sales', status: 'completed', phase: 'completed' } as Task
const cleanups: Array<() => void> = []

function event(sequence: number, offset: number, payload: ReplayEvent['payload'], stage: ReplayEvent['stage'] = 'automl'): ReplayEvent {
  return { sequence, timestamp: 1000 + offset / 1000, offset_ms: offset, stage, kind: payload.node ? 'node' : payload.event ? 'event' : payload.snapshot ? 'artifact' : 'stage', label: `event-${sequence}`, payload }
}

function recording(events: ReplayEvent[]): ReplayRecording {
  return { schema_version: 1, task_id: task.id, task_name: task.task_name, fidelity: 'recorded', fidelity_notes: [], started_at: 1000, ended_at: 1000 + (events.at(-1)?.offset_ms ?? 0) / 1000, duration_ms: events.at(-1)?.offset_ms ?? 0, events }
}

function accepted(id: string, metric: number, extras: Partial<MctsNode> = {}): MctsNode {
  return { id, metric, maximize: false, is_buggy: false, is_valid: true, search_eligible: true, ...extras }
}

function rig() {
  const callbacks = new Map<number, FrameRequestCallback>()
  let id = 0
  vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => { callbacks.set(++id, callback); return id })
  vi.stubGlobal('cancelAnimationFrame', (frame: number) => callbacks.delete(frame))
  const scope = effectScope()
  const replay = scope.run(() => useReplay())!
  cleanups.push(() => { replay.pause(); scope.stop() })
  function frame(time: number) {
    const current = [...callbacks.values()]
    callbacks.clear()
    current.forEach(callback => callback(time))
  }
  return { replay, frame, callbacks }
}

afterEach(() => {
  cleanups.splice(0).forEach(cleanup => cleanup())
  vi.unstubAllGlobals()
})

describe('recorded history projection', () => {
  const history = recording([
    event(1, 0, { task: { status: 'running', phase: 'automl' } }),
    event(2, 1000, { node: { id: 'a', status: 'generating', pending_execution: true } }),
    event(3, 2000, { node: accepted('a', 8, { status: 'completed', code: 'final code', visits: 5 }) }),
    event(4, 3000, { node: accepted('b', 6, { fusion_sources: ['a'], delivery_ready: true }) }),
    event(5, 4000, { snapshot: { auto_report: { report_markdown: '# Measured result' } }, task: { status: 'completed' } }, 'report'),
  ])

  it('does not reveal final code, metric, report or best node before its event', () => {
    const early = projectReplay(history, 1, task)
    expect(early.auto_ml.nodes).toEqual([])
    expect(early.auto_ml.pending_nodes).toEqual([{ id: 'a', status: 'generating', pending_execution: true }])
    expect(early.auto_ml.best_node_id).toBeNull()
    expect(early.auto_report?.report_markdown).toBeUndefined()
    expect(early.task.status).toBe('running')
    const complete = projectReplay(history, 4, task)
    expect(complete.auto_ml.best_node_id).toBe('b')
    expect(complete.auto_report?.report_markdown).toBe('# Measured result')
  })

  it('replaces candidate state without mutating an earlier snapshot or recording', () => {
    const before = projectReplay(history, 1, task)
    const serialized = JSON.stringify(history)
    const after = applyReplayEvent(before, history.events[2]!)
    expect(after.auto_ml.pending_nodes).toEqual([])
    expect(after.auto_ml.nodes?.[0]?.code).toBe('final code')
    expect(before.auto_ml.pending_nodes?.[0]?.code).toBeUndefined()
    expect(before.auto_ml.nodes).toEqual([])
    expect(JSON.stringify(history)).toBe(serialized)
    expect(projectReplay(history, -1, task)).toEqual(emptyReplaySnapshot(task))
  })

  it('clears the graph and best marker at a backend search_reset snapshot', () => {
    const final = projectReplay(history, 3, task)
    const reset = applyReplayEvent(final, event(6, 5000, { snapshot: { auto_ml: { nodes: [], pending_nodes: [], events: [], best_node_id: null, best_node_kind: null } } }))
    expect(reset.auto_ml.nodes).toEqual([])
    expect(reset.auto_ml.best_node_id).toBeNull()
    expect(final.auto_ml.nodes).toHaveLength(2)
  })

  it('rejects explicitly invalid and nonfinite candidates despite stale delivery flags', () => {
    expect(selectVisibleBest([accepted('invalid', 0, { is_valid: false, delivery_ready: true }), accepted('nan', NaN), accepted('valid', 8)])?.id).toBe('valid')
  })

  it('retains backend legacy delivery eligibility for valid reviewed historical nodes', () => {
    const legacy: MctsNode[] = [{ id: 'old', metric: 8, maximize: false, is_buggy: false, is_valid: true }]
    expect(selectVisibleBest(legacy)?.id).toBe('old')
  })

  it('matches backend default direction when legacy maximize is not recorded', () => {
    expect(selectVisibleBest([accepted('low', 1, { maximize: undefined }), accepted('high', 2, { maximize: undefined })])?.id).toBe('high')
  })
})

describe('presentation timing', () => {
  it('compresses long compute gaps to the requested node cadence', () => {
    const events = [event(1, 0, { node: accepted('a', 8) }), event(2, 600000, { node: accepted('b', 7) }), event(3, 1800000, { node: accepted('c', 6) })]
    expect(playbackOffsets(events, 'nodes', 1000)).toEqual([0, 1000, 2000])
    expect(playbackOffsets(events, 'original', 1000)).toEqual([0, 600000, 1800000])
  })

  it('keeps a nonzero presentation interval for a report-only start and final artifact', () => {
    const events = [event(1, 0, { task: { status: 'running' } }, 'report'), event(2, 60000, { task: { status: 'completed' }, snapshot: { auto_report: { report_markdown: '# Final' } } }, 'report')]
    const offsets = playbackOffsets(events, 'nodes', 1000)
    expect(offsets[1]).toBeGreaterThan(offsets[0]!)
  })

  it('resolves equal timestamps and boundaries using the last event at that time', () => {
    const times = [0, 100, 100, 250]
    expect(indexAtTime(times, -1)).toBe(-1)
    expect(indexAtTime(times, 0)).toBe(0)
    expect(indexAtTime(times, 100)).toBe(2)
    expect(indexAtTime(times, 10000)).toBe(3)
    expect(indexAtTime([], 100)).toBe(-1)
  })

  it('looks up a long timeline without changing its recorded offsets', () => {
    const offsets = Array.from({ length: 100000 }, (_, index) => index * 200)
    expect(indexAtTime(offsets, 19800001)).toBe(99000)
    expect(offsets[99000]).toBe(19800000)
  })
})

describe('replay page focus', () => {
  const generated = (file: string) => ({ component: 'module.task_definition', event: 'GENERATED_FILE', fields: { file } })
  const events = [
    event(1, 0, { task: { status: 'running', phase: 'autorealize' } }, 'data_cognition'),
    event(2, 1000, { event: { component: 'module.task_definition', event: 'STARTED' } }, 'task_definition'),
    event(3, 2000, { snapshot: { auto_realize: { current_state: { status: 'running' } } } }, 'data_cognition'),
    event(4, 3000, { event: generated('realize_report/automl_context.md') }, 'task_definition'),
    event(5, 4000, { snapshot: { auto_realize: { automl_context_text: '# Context' } } }, 'data_cognition'),
    event(6, 5000, { event: generated('realize_report/main_task_protocol.json') }, 'task_definition'),
    event(7, 6000, { event: generated('C:\\run\\description.md') }, 'task_definition'),
    event(8, 7000, { snapshot: { auto_realize: { description_text: '# Task' } } }, 'data_cognition'),
    event(9, 8000, { event: generated('realize_report/automl_context.md') }, 'task_definition'),
    event(10, 9000, { task: { status: 'running', phase: 'automl' } }),
    event(11, 10000, { snapshot: { auto_realize: { automl_context_text: '# Revised context' } } }, 'data_cognition'),
    event(12, 11000, { task: { status: 'running', phase: 'report' } }, 'report'),
    event(13, 12000, { node: accepted('late', 1) }),
  ]

  it('focuses each generated document once, ignoring interleaved logs and late snapshots', () => {
    const focus = replayFocusTimeline(events)
    expect(focus.map(item => item.artifact ?? item.stage)).toEqual([
      'data_cognition', 'data_cognition', 'data_cognition', 'automl_context', 'automl_context', 'automl_context',
      'description', 'description', 'description', 'automl', 'automl', 'report', 'report',
    ])
    expect(focus[4]).toBe(focus[3])
    expect(focus[8]).toBe(focus[6])
  })

  it('uses nonempty snapshot artifacts for historical recordings without generation events', () => {
    const focus = replayFocusTimeline([
      event(1, 0, { snapshot: { auto_realize: { description_text: '  ' } } }, 'task_definition'),
      event(2, 1000, { snapshot: { auto_realize: { automl_context_text: '# Context' } } }, 'data_cognition'),
      event(3, 2000, { snapshot: { auto_realize: { description_text: '# Task' } } }, 'data_cognition'),
    ])
    expect(focus).toEqual([{ stage: 'data_cognition' }, { stage: 'task_definition', artifact: 'automl_context' }, { stage: 'task_definition', artifact: 'description' }])
  })

  it('does not mistake an input description or empty downstream snapshots for generated output', () => {
    const focus = replayFocusTimeline([
      event(1, 0, { event: { ...generated('description.md'), component: 'module.data_cognition.file_artifact' } }, 'data_cognition'),
      event(2, 1000, { snapshot: { auto_ml: { nodes: [], events: [], best_metric_text: '' } } }),
      event(3, 2000, { snapshot: { auto_report: { current_state: {}, report_markdown: '' } } }, 'report'),
      event(4, 3000, { event: { ...generated('description.md'), event: 'GENERATING_FILE' } }, 'task_definition'),
    ])
    expect(focus.every(item => item.stage === 'data_cognition')).toBe(true)
  })

  it('prefers the task description when a reconstructed snapshot contains both documents', () => {
    expect(replayFocusTimeline([event(1, 0, { snapshot: { auto_realize: { automl_context_text: '# Context', description_text: '# Task' } } }, 'data_cognition')])).toEqual([
      { stage: 'task_definition', artifact: 'description' },
    ])
  })

  it('honors explicit full reruns and search resets without treating telemetry as a restart', () => {
    const focus = replayFocusTimeline([
      ...events,
      { ...event(14, 13000, {}), label: 'search_reset' },
      { ...event(15, 14000, {}, 'data_cognition'), label: 'task_reset' },
      event(16, 15000, { event: generated('description.md') }, 'task_definition'),
    ])
    expect(focus.slice(-3)).toEqual([{ stage: 'automl' }, { stage: 'data_cognition' }, { stage: 'task_definition', artifact: 'description' }])
  })

  it('restores focus on seek, single stepping, stage jumps and playback loops', async () => {
    const { replay, frame } = rig()
    replay.mode.value = 'original'; replay.load(recording(events), task); await nextTick()
    replay.seek(10000)
    expect(replay.currentFocus.value?.stage).toBe('automl')
    replay.seek(7000)
    expect(replay.currentFocus.value?.artifact).toBe('description')
    replay.seek(4000)
    expect(replay.currentFocus.value?.artifact).toBe('automl_context')
    replay.step(-1); replay.step(-1)
    expect(replay.currentFocus.value?.stage).toBe('data_cognition')
    replay.jump('task_definition')
    expect(replay.index.value).toBe(3)
    replay.loop.value = true; replay.play(); frame(100); frame(14000)
    expect(replay.currentFocus.value?.stage).toBe('data_cognition')
  })

  it('does not allocate a node interval to every alternating raw stage', () => {
    const events = Array.from({ length: 21 }, (_, index) => event(index + 1, index * 1000,
      { event: { event: 'PROGRESS' } }, index % 2 ? 'task_definition' : 'data_cognition'))
    expect(playbackOffsets(events, 'nodes', 1000).at(-1)).toBe(1000)
    expect(playbackOffsets(events, 'original', 1000).at(-1)).toBe(20000)
  })
})

describe('play, seek and step controls', () => {
  const timeline = recording([event(1, 0, { task: { status: 'running' } }), event(2, 1000, { node: accepted('a', 8) }), event(3, 2000, { task: { status: 'completed' }, snapshot: { auto_report: { report_markdown: '# Final' } } }, 'report')])

  it('plays by elapsed animation time and pauses without drift', async () => {
    const { replay, frame, callbacks } = rig()
    replay.mode.value = 'original'; replay.load(timeline, task); await nextTick()
    replay.play(); frame(100); frame(600)
    expect(replay.position.value).toBe(500)
    replay.pause(); frame(1100)
    expect(replay.position.value).toBe(500)
    expect(callbacks.size).toBe(0)
    replay.speed.value = 2; replay.play(); frame(2000); frame(2250)
    expect(replay.position.value).toBe(1000)
    expect(replay.snapshot.value?.auto_ml.nodes).toHaveLength(1)
  })

  it('removes future report and nodes on backward seek and clamps bounds', async () => {
    const { replay } = rig()
    replay.mode.value = 'original'; replay.load(timeline, task); await nextTick()
    replay.seek(99999)
    expect(replay.index.value).toBe(2)
    replay.seek(500)
    expect(replay.snapshot.value?.auto_report?.report_markdown).toBeUndefined()
    expect(replay.snapshot.value?.auto_ml.nodes).toEqual([])
    replay.seek(-1)
    expect(replay.position.value).toBe(0)
    expect(replay.index.value).toBe(0)
  })

  it('steps one event at a time even when events share a timestamp', async () => {
    const { replay } = rig()
    const duplicate = recording([event(1, 0, {}), event(2, 1000, { node: { id: 'a', pending_execution: true } }), event(3, 1000, { node: accepted('a', 8) })])
    replay.mode.value = 'original'; replay.load(duplicate, task); await nextTick()
    replay.step(1)
    expect(replay.index.value).toBe(1)
    expect(replay.snapshot.value?.auto_ml.nodes).toEqual([])
    replay.step(1)
    expect(replay.snapshot.value?.auto_ml.nodes?.[0]?.metric).toBe(8)
    replay.step(-1)
    expect(replay.snapshot.value?.auto_ml.pending_nodes).toHaveLength(1)
    expect(replay.snapshot.value?.auto_ml.nodes).toEqual([])
    replay.step(-999)
    expect(replay.index.value).toBe(-1)
  })

  it('stops at the end and can loop without keeping final artifacts', async () => {
    const { replay, frame } = rig()
    replay.mode.value = 'original'; replay.load(timeline, task); await nextTick()
    replay.play(); frame(100); frame(2200)
    expect(replay.playing.value).toBe(false)
    expect(replay.index.value).toBe(2)
    replay.loop.value = true; replay.play(); frame(3000); frame(5100)
    expect(replay.playing.value).toBe(true)
    expect(replay.position.value).toBe(0)
    expect(replay.snapshot.value?.auto_report?.report_markdown).toBeUndefined()
  })

  it('does not reprocess the entire long history for every backward scrub movement', async () => {
    const { replay } = rig()
    let payloadReads = 0
    const events = Array.from({ length: 2500 }, (_, index) => {
      const row = event(index + 1, index * 100, {})
      Object.defineProperty(row, 'payload', { get: () => { payloadReads++; return {} } })
      return row
    })
    replay.mode.value = 'original'; replay.load(recording(events), task); await nextTick()
    replay.seek(249900)
    payloadReads = 0
    for (let index = 2498; index >= 2483; index--) replay.seek(index * 100)
    expect(replay.index.value).toBe(2483)
    expect(payloadReads).toBeLessThan(15000)
  })
})
