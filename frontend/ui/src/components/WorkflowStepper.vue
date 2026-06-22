<script setup lang="ts">
import { computed } from 'vue'
import type { Task } from '../types'

export type StepKey = 'data_cognition' | 'task_definition' | 'automl' | 'report'

const props = defineProps<{
  task?: Task | null
  autoRealizeState?: Record<string, unknown>
  autoRealizeEvents?: Record<string, unknown>[]
  autoMlEvents?: Record<string, unknown>[]
  activeStep: StepKey
}>()

const emit = defineEmits<{
  select: [step: StepKey]
}>()

type StepMeta = {
  key: StepKey
  label: string
  disabled?: boolean
}

const steps: StepMeta[] = [
  { key: 'data_cognition', label: '数据理解' },
  { key: 'task_definition', label: '任务定义' },
  { key: 'automl', label: '自动机器学习' },
  { key: 'report', label: '报告生成' },
]

const inferredActive = computed<StepKey | null>(() => {
  const phase = String(props.task?.phase ?? '').toLowerCase()
  if (phase.includes('automl')) return 'automl'
  if (phase.includes('report')) return 'report'

  const state = props.autoRealizeState ?? {}
  const active = state.active_components
  if (Array.isArray(active) && active.length > 0) {
    const first = active[0] as Record<string, unknown>
    const comp = String(first.component ?? '').toLowerCase()
    if (comp.includes('task_definition') || comp.includes('stage.p2')) return 'task_definition'
    if (comp.includes('data_cognition') || comp.includes('file_cognition') || comp.includes('cognition_probe') || comp.includes('stage.p1')) return 'data_cognition'
  }

  const mlEvents = props.autoMlEvents ?? []
  if (mlEvents.length > 0) {
    const lastMl = mlEvents[mlEvents.length - 1]
    const marker = `${String(lastMl.component ?? '')}.${String(lastMl.event ?? '')}`.toLowerCase()
    if (marker.includes('mcts') || marker.includes('pipeline') || marker.includes('mlevolve')) return 'automl'
  }

  const arEvents = props.autoRealizeEvents ?? []
  for (let i = arEvents.length - 1; i >= 0; i -= 1) {
    const row = arEvents[i]
    const comp = String(row.component ?? '').toLowerCase()
    if (comp.includes('task_definition') || comp.includes('stage.p2')) return 'task_definition'
    if (comp.includes('data_cognition') || comp.includes('file_cognition') || comp.includes('cognition_probe') || comp.includes('stage.p1')) return 'data_cognition'
  }
  return null
})

const stepStatus = computed(() => {
  const active = inferredActive.value
  const task = props.task
  const completed = task?.status === 'completed'
  const phase = String(task?.phase ?? '').toLowerCase()

  const order: StepKey[] = ['data_cognition', 'task_definition', 'automl', 'report']
  const activeIdx = active ? order.indexOf(active) : -1
  const out: Record<StepKey, 'idle' | 'active' | 'done'> = {
    data_cognition: 'idle',
    task_definition: 'idle',
    automl: 'idle',
    report: 'idle',
  }

  for (let i = 0; i < order.length; i += 1) {
    const key = order[i]
    if (completed) {
      if (phase === 'autorealize_completed') {
        out[key] = key === 'data_cognition' || key === 'task_definition' ? 'done' : 'idle'
        continue
      }
      if (phase === 'automl_completed') {
        out[key] = key === 'data_cognition' || key === 'task_definition' || key === 'automl' ? 'done' : 'idle'
        continue
      }
      if (phase === 'report_completed') {
        if (key === 'automl' && task?.config.auto_ml.enabled === false) out[key] = 'idle'
        else out[key] = 'done'
        continue
      }
      out[key] = 'done'
      continue
    }
    if (activeIdx >= 0) {
      if (i < activeIdx) out[key] = 'done'
      else if (i === activeIdx && task?.status === 'running') out[key] = 'active'
      else out[key] = 'idle'
    }
  }
  return out
})

function cls(step: StepMeta) {
  const status = stepStatus.value[step.key]
  return {
    disabled: !!step.disabled,
    selected: props.activeStep === step.key,
    active: status === 'active',
    done: status === 'done',
  }
}
</script>

<template>
  <section class="workflow">
    <div class="track">
      <div class="track-line"></div>
      <button
        v-for="(step, idx) in steps"
        :key="step.key"
        class="node"
        :class="cls(step)"
        @click="!step.disabled && emit('select', step.key)"
        :title="step.disabled ? '该模块暂未开发完成' : step.label"
        :disabled="!!step.disabled"
      >
        <span class="index">{{ idx + 1 }}</span>
        <span class="label">{{ step.label }}</span>
      </button>
    </div>
  </section>
</template>

<style scoped>
.workflow {
  background: #f6f9ff;
  border: 1px solid #d2ddf2;
  border-radius: 12px;
  padding: 10px 12px 14px;
}

.track {
  position: relative;
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 8px;
  align-items: start;
}

.track-line {
  position: absolute;
  left: 8%;
  right: 8%;
  top: 14px;
  height: 3px;
  background: #c4d1ea;
  z-index: 0;
}

.node {
  position: relative;
  z-index: 1;
  border: 1px solid #b7c9e8;
  background: #eef3ff;
  border-radius: 10px;
  padding: 6px 6px 8px;
  display: grid;
  gap: 4px;
  cursor: pointer;
  text-align: center;
}

.index {
  width: 18px;
  height: 18px;
  line-height: 18px;
  border-radius: 50%;
  margin: 0 auto;
  font-size: 11px;
  background: #d4e0f5;
  color: #2c4f80;
}

.label {
  font-size: 12px;
  color: #2b4872;
}

.node.active {
  background: #dcecff;
  border-color: #67a4e4;
}

.node.active .index {
  background: #2f78cc;
  color: #fff;
}

.node.done {
  background: #d8f9e7;
  border-color: #72c093;
}

.node.done .index {
  background: #239255;
  color: #fff;
}

.node.selected {
  box-shadow: 0 0 0 2px rgba(45, 93, 157, 0.25);
}

.node.disabled {
  opacity: 0.75;
}
</style>
