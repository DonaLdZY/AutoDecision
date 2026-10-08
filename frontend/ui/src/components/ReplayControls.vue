<script setup lang="ts">
import { Pause, Play, SkipBack, SkipForward, RotateCcw, Repeat2, X, Scan } from 'lucide-vue-next'
import type { ReplayRecording } from '../types'
import type { PlaybackMode } from '../utils/replay'
defineProps<{ recording: ReplayRecording; playing: boolean; position: number; duration: number; index: number; label?: string }>()
const mode = defineModel<PlaybackMode>('mode', { required: true })
const interval = defineModel<number>('interval', { required: true })
const speed = defineModel<number>('speed', { required: true })
const loop = defineModel<boolean>('loop', { required: true })
const followStage = defineModel<boolean>('followStage', { required: true })
const emit = defineEmits<{ play: []; pause: []; seek: [ms: number]; step: [direction: number]; close: []; present: [] }>()
const time = (ms: number) => `${Math.floor(ms / 60000).toString().padStart(2, '0')}:${Math.floor(ms / 1000 % 60).toString().padStart(2, '0')}`
</script>

<template>
  <section class="replay-dock" aria-label="任务重放控制">
    <div class="replay-heading">
      <span class="replay-badge"><span class="status-dot" />任务重放</span>
      <span class="replay-evidence" :title="recording.fidelity_notes.join('\n')">{{ recording.fidelity === 'recorded' ? '运行记录' : recording.fidelity === 'mixed' ? '记录与历史重建' : '历史重建' }}</span>
      <span class="replay-event">{{ label || '准备就绪' }}</span>
      <span class="replay-count">{{ Math.max(0, index + 1) }} / {{ recording.events.length }}</span>
      <button class="icon-button" title="全屏演示" aria-label="全屏演示" @click="emit('present')"><Scan :size="16" /></button>
      <button class="icon-button" title="退出重放" aria-label="退出重放" @click="emit('close')"><X :size="16" /></button>
    </div>
    <div class="replay-track-row">
      <span class="mono">{{ time(position) }}</span>
      <input class="replay-track" type="range" aria-label="重放进度" min="0" :max="Math.max(1, duration)" step="1" :value="position" @input="emit('seek', Number(($event.target as HTMLInputElement).value))" />
      <span class="mono">{{ time(duration) }}</span>
    </div>
    <div class="replay-actions">
      <div class="playback-buttons">
        <button class="icon-button" title="回到开始" aria-label="回到开始" @click="emit('seek', 0)"><RotateCcw :size="16" /></button>
        <button class="icon-button" title="上一事件" aria-label="上一事件" :disabled="index < 0" @click="emit('step', -1)"><SkipBack :size="17" /></button>
        <button class="play-button" :title="playing ? '暂停重放' : '播放重放'" :aria-label="playing ? '暂停重放' : '播放重放'" :disabled="!recording.events.length" @click="playing ? emit('pause') : emit('play')"><Pause v-if="playing" :size="19" /><Play v-else :size="19" /></button>
        <button class="icon-button" title="下一事件" aria-label="下一事件" :disabled="index >= recording.events.length - 1" @click="emit('step', 1)"><SkipForward :size="17" /></button>
        <button class="icon-button" title="循环播放" aria-label="循环播放" :aria-pressed="loop" :class="{ active: loop }" @click="loop = !loop"><Repeat2 :size="17" /></button>
      </div>
      <div class="segmented compact" aria-label="重放节奏">
        <button :class="{ active: mode === 'nodes' }" @click="mode = 'nodes'">节点节奏</button>
        <button :class="{ active: mode === 'original' }" @click="mode = 'original'">原始时间</button>
      </div>
      <label v-if="mode === 'nodes'" class="inline-field"><input v-model.number="interval" aria-label="节点间隔（毫秒）" type="number" min="100" max="60000" step="100" /><span>ms / 节点</span></label>
      <select v-model.number="speed" aria-label="播放倍速"><option v-for="value in [0.25, 0.5, 1, 2, 4, 8, 16, 60]" :key="value" :value="value">{{ value }}×</option></select>
      <label class="follow-stage"><input v-model="followStage" type="checkbox" />跟随阶段</label>
    </div>
  </section>
</template>
