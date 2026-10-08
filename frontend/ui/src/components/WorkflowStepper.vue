<script setup lang="ts">
import { computed } from 'vue'
import { Database, FileCheck2, GitBranch, NotebookText, Check } from 'lucide-vue-next'
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
    if (marker.includes('mcts') || marker.includes('pipeline') || marker.includes('algoevolve') || marker.includes('mlevolve')) return 'automl'
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
        out[key] = 'done'
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
  <nav class="workflow" aria-label="任务阶段">
    <div class="track" role="tablist">
      <button
        v-for="(step, idx) in steps"
        :key="step.key"
        class="node"
        role="tab"
        :aria-selected="activeStep === step.key"
        :class="cls(step)"
        @click="!step.disabled && emit('select', step.key)"
        :title="step.disabled ? '该模块暂未开发完成' : step.label"
        :disabled="!!step.disabled"
      >
        <component :is="[Database, FileCheck2, GitBranch, NotebookText][idx]" :size="15" />
        <span class="label">{{ step.label }}</span>
        <Check v-if="stepStatus[step.key] === 'done'" :size="11" class="step-check" />
      </button>
    </div>
  </nav>
</template>

<style scoped>
.workflow { min-width: 0; }

.track {
  position: relative;
  display: flex;
  gap: 22px;
  align-items: center;
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
  border: none;
  border-bottom: 2px solid transparent;
  background: transparent;
  border-radius: 0;
  padding: 10px 1px 12px;
  display: flex;
  align-items: center;
  color: #98a28d;
  gap: 7px;
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
  font-size: 11px;
  white-space: nowrap;
  color: inherit;
}

.node.active {
  color: #4a7966;
}

.node.active .index {
  background: #2f78cc;
  color: #fff;
}

.node.done {
  color: #7d9070;
}

.node.done .index {
  background: #239255;
  color: #fff;
}

.node.selected {
  border-bottom-color: #357b4c;
  color: #397340;
}
.step-check { color: #73a76b; }
@media(max-width:600px) { .track { gap: 14px; } .node { gap: 5px; } .label { font-size: 10px; } .step-check { display: none; } }

.node.disabled {
  opacity: 0.75;
}
</style>
