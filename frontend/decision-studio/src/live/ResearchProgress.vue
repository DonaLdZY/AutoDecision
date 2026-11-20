<script setup lang="ts">
import { computed } from 'vue'
import type { Task } from './store'
import { status, state } from './store'
import { taskWorkflow } from './taskWorkflow'
import Icon from '../components/Icon.vue'
const props = defineProps<{ task: Task; nodes: any[]; bestId?: string }>()
const stages = [
  { name: '数据与评价', engine: 'AutoRealize' },
  { name: '方案搜索', engine: 'AlgoEvolve' },
  { name: '报告与交付说明', engine: 'AutoReport' },
  { name: '交付与发布', engine: '能力目录' },
]
const delivery = computed(() => taskWorkflow(props.task, state.task_deliveries?.[props.task.id]))
const active = computed(() => {
  const p = props.task.phase.toLowerCase()
  if (props.task.status === 'completed') return 3
  if (/report|delivery/.test(p)) return 2
  if (/automl|auto_ml|search|final|evaluat/.test(p)) return 1
  return 0
})
function stageDone(i: number) {
  if (i === 3) return delivery.value.stage === 'published'
  if (i === 2 && !props.task.config.auto_report.enabled) return false
  if (i === 1 && !props.task.config.auto_ml.enabled) return false
  return i < active.value
}
const best = computed(() => props.nodes.find(n => n.id === props.bestId))
const comparable = computed(() => props.nodes.filter(n => n.search_eligible && !n.is_buggy).length)
</script>
<template>
  <section class="research-progress" aria-label="研究进度">
    <ol class="research-stages">
      <li v-for="(stage, i) in stages" :key="stage.name" :class="{ current: i === active && !stageDone(i), done: stageDone(i) }" :aria-current="i === active && !stageDone(i) ? 'step' : undefined">
        <Icon :name="stageDone(i) ? 'checkCircle' : i === active && task.status === 'running' ? 'loader' : 'circle'" :size="16" /><div>{{ stage.name }}<small>{{ i === 3 ? delivery.label : (i === 2 && !task.config.auto_report.enabled) || (i === 1 && !task.config.auto_ml.enabled) ? '未启用' : stage.engine }}</small></div>
      </li>
    </ol>
    <dl class="research-stats">
      <div><dt>任务状态</dt><dd>{{ task.status === 'completed' ? delivery.label : status(task.status) }}</dd></div>
      <div><dt>已生成方案</dt><dd>{{ nodes.length }}</dd></div>
      <div><dt>可比较方案</dt><dd>{{ comparable }}</dd></div>
      <div v-if="best?.metric != null"><dt>当前最佳开发指标</dt><dd>{{ Number(best.metric).toPrecision(5) }}</dd></div>
    </dl>
  </section>
</template>
