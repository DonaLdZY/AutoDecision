import { computed, onUnmounted, shallowRef, watch } from 'vue'
import type { ReplayRecording, ReplayStage, SnapshotPayload, Task } from '../types'
import { applyReplayEvent, emptyReplaySnapshot, indexAtTime, playbackOffsets, replayFocusTimeline, type PlaybackMode } from '../utils/replay'

export function useReplay() {
  const recording = shallowRef<ReplayRecording | null>(null)
  const replayTask = shallowRef<Task | null>(null)
  const snapshot = shallowRef<SnapshotPayload>()
  const index = shallowRef(-1)
  const playing = shallowRef(false)
  const mode = shallowRef<PlaybackMode>('nodes')
  const interval = shallowRef(1000)
  const speed = shallowRef(1)
  const loop = shallowRef(false)
  const position = shallowRef(0)
  const followStage = shallowRef(true)
  let frame = 0, lastTime = 0
  const checkpoints = new Map<number, SnapshotPayload>()
  const checkpointInterval = 64
  const focusTimeline = computed(() => replayFocusTimeline(recording.value?.events ?? []))
  const offsets = computed(() => playbackOffsets(recording.value?.events ?? [], mode.value, interval.value, focusTimeline.value))
  const duration = computed(() => offsets.value.at(-1) ?? 0)
  const currentEvent = computed(() => recording.value?.events[index.value])
  const currentFocus = computed(() => focusTimeline.value[index.value])

  function pause() { playing.value = false; cancelAnimationFrame(frame); lastTime = 0 }
  function updateIndex(next: number) {
    if (!recording.value || !replayTask.value || next === index.value) return
    let from = -1
    let result = checkpoints.get(-1) ?? emptyReplaySnapshot(replayTask.value)
    if (next > index.value && snapshot.value) { from = index.value; result = snapshot.value }
    for (const [at, saved] of checkpoints) {
      if (at <= next && at > from) { from = at; result = saved }
    }
    for (let i = from + 1; i <= next; i++) {
      result = applyReplayEvent(result, recording.value.events[i]!)
      if (i % checkpointInterval === 0) {
        checkpoints.set(i, result)
        if (checkpoints.size > 128) {
          const oldest = [...checkpoints.keys()].find(key => key !== -1)
          if (oldest !== undefined) checkpoints.delete(oldest)
        }
      }
    }
    snapshot.value = result
    index.value = next
  }
  function seek(time: number) {
    position.value = Math.max(0, Math.min(duration.value, time))
    updateIndex(indexAtTime(offsets.value, position.value))
    lastTime = 0
  }
  function tick(now: number) {
    if (!playing.value) return
    if (lastTime) {
      position.value = Math.min(duration.value, position.value + (now - lastTime) * speed.value)
      updateIndex(indexAtTime(offsets.value, position.value))
    }
    lastTime = now
    if (position.value >= duration.value) {
      if (loop.value) seek(0)
      else { pause(); return }
    }
    frame = requestAnimationFrame(tick)
  }
  function play() {
    if (!recording.value?.events.length || playing.value) return
    if (position.value >= duration.value) seek(0)
    playing.value = true; lastTime = 0; frame = requestAnimationFrame(tick)
  }
  function step(direction: number) {
    pause()
    const next = Math.min((recording.value?.events.length ?? 0) - 1, Math.max(-1, index.value + direction))
    updateIndex(next); position.value = offsets.value[next] ?? 0
  }
  function jump(stage: ReplayStage) {
    const next = focusTimeline.value.findIndex(focus => focus.stage === stage)
    if (next >= 0) { pause(); updateIndex(next); position.value = offsets.value[next] ?? 0 }
  }
  function load(data: ReplayRecording, task: Task) {
    pause(); recording.value = data; replayTask.value = task; index.value = -1; position.value = 0
    snapshot.value = emptyReplaySnapshot(task); checkpoints.clear(); checkpoints.set(-1, snapshot.value); seek(0)
  }
  function close() { pause(); recording.value = null; snapshot.value = undefined; replayTask.value = null; index.value = -1; checkpoints.clear() }
  watch([mode, interval], () => { position.value = offsets.value[index.value] ?? 0; lastTime = 0 })
  onUnmounted(pause)
  return { recording, snapshot, index, playing, mode, interval, speed, loop, position, followStage,
    duration, currentEvent, currentFocus, load, close, seek, play, pause, step, jump }
}
