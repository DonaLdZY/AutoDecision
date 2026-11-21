<script setup lang="ts">
import { computed } from 'vue'
import Icon from '../components/Icon.vue'
import { request, refresh, run, toast, ui } from './store'
import type { Task } from './store'
import { degradationChanges } from './taskWorkflow'

// 需求降级清单：等待确认时由生产者决定继续或停止，之后保留为研究记录的一部分。
const props = defineProps<{ task: Task; conversationId?: string; compact?: boolean }>()
const d = computed(() => props.task.degradation)
const waiting = computed(() => d.value?.status === 'proposed' && props.task.status === 'awaiting_input')
const title = computed(() => {
  const n = degradationChanges(d.value)
  return (
    (
      {
        proposed: `有 ${n} 项需求要调整，按此继续？`,
        applying: `已同意调整 ${n} 项需求，正在重新定义任务`,
        applied: `已降级 · ${n} 项需求调整`,
        rejected: '未同意降级，研究已停止',
        infeasible: '现有数据无法完成核心目标',
        planning_failed: '降级规划失败',
        failed_after_degradation: '降级后任务定义未完成',
      } as Record<string, string>
    )[d.value?.status || ''] || '需求降级'
  )
})
const tone = computed(() =>
  waiting.value ? 'ask' : ['applied', 'applying'].includes(d.value?.status || '') ? 'done' : 'stop',
)
// 生产者只需要权衡会改变需求的项；系统内部口径统一的项合成一行。
const changes = computed(() => (d.value?.items || []).filter((i) => i.category !== '审查未收敛'))
const internal = computed(() => (d.value?.items.length || 0) - degradationChanges(d.value))
const decider = computed(() =>
  d.value?.approved_by === 'auto' ? '自动降级' : d.value?.approved_by === 'producer' ? '生产者同意' : '',
)
async function decide(approve: boolean) {
  await run('degradation-decide', async () => {
    await request('/tasks/degradation/decide', {
      task_id: props.task.id,
      approve,
      conversation_id: props.conversationId || '',
    })
    await refresh()
    toast(approve ? '已同意降级，研究继续进行' : '已停止这个研究计划')
  })
}
</script>
<template>
  <section v-if="d" class="live-panel degradation-card" :class="tone">
    <header>
      <span class="deg-icon"
        ><Icon :name="waiting ? 'help' : tone === 'done' ? 'checks' : 'shield'" :size="18"
      /></span>
      <div>
        <h3>{{ title }}</h3>
        <p v-if="!compact" class="deg-plan">
          「{{ task.task_name }}」<template v-if="decider"> · {{ decider }}</template>
        </p>
      </div>
    </header>
    <p v-if="d.core_goal" class="deg-goal"><b>降级后目标</b>{{ d.core_goal }}</p>
    <p v-if="tone === 'stop' && (d.infeasible_reason || d.outcome)" class="deg-goal deg-reason">
      {{ d.infeasible_reason || d.outcome }}
    </p>
    <ul v-if="waiting && changes.length" class="deg-briefs">
      <li v-for="(item, i) in changes" :key="i">{{ item.brief || item.degraded }}</li>
      <li v-if="internal" class="deg-internal">另有 {{ internal }} 项内部口径统一</li>
    </ul>
    <details v-if="d.items.length">
      <summary>{{ waiting ? '查看依据' : `查看 ${d.items.length} 项降级` }}</summary>
      <ol class="deg-items">
        <li v-for="(item, i) in d.items" :key="i">
          <span class="tag">{{ item.category }}</span>
          <div>
            <p v-if="item.brief" class="deg-brief">{{ item.brief }}</p>
            <p class="deg-original">原要求：{{ item.original }}</p>
            <p class="deg-new">改为：{{ item.degraded }}</p>
            <small v-if="item.impact">影响：{{ item.impact }}</small>
          </div>
        </li>
      </ol>
    </details>
    <div v-if="waiting" class="form-actions">
      <button type="button" class="btn primary small" :disabled="!!ui.busy" @click="decide(true)">
        同意降级
      </button>
      <button type="button" class="btn secondary small" :disabled="!!ui.busy" @click="decide(false)">
        不同意，停止
      </button>
    </div>
  </section>
</template>
<style scoped>
.degradation-card {
  display: grid;
  gap: 10px;
  margin: 0 0 12px;
  border-left: 3px solid var(--primary);
}
.degradation-card.ask {
  border-left-color: #d08a1c;
}
.degradation-card.stop {
  border-left-color: #c2410c;
}
header {
  display: flex;
  gap: 10px;
  align-items: center;
}
header h3 {
  margin: 0;
  font-size: 15px;
}
.deg-icon {
  display: grid;
  flex: none;
  place-items: center;
  width: 32px;
  height: 32px;
  border-radius: 8px;
  background: var(--primary-soft, #e8edf6);
  color: var(--primary);
}
.ask .deg-icon {
  background: #fff4e5;
  color: #9a6516;
}
.stop .deg-icon {
  background: #fdeee6;
  color: #c2410c;
}
.deg-plan {
  margin: 2px 0 0;
  color: var(--muted);
  font-size: 12px;
}
.deg-goal {
  margin: 0;
  font-size: 14px;
}
.deg-reason {
  color: #c2410c;
  font-size: 13px;
}
.deg-goal b {
  margin-right: 8px;
}
summary {
  cursor: pointer;
  color: var(--primary);
  font-size: 13px;
}
.deg-items {
  display: grid;
  gap: 10px;
  margin: 10px 0 0;
  padding: 0;
  list-style: none;
}
.deg-items li {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  gap: 10px;
  align-items: start;
}
.deg-items p {
  margin: 0;
  font-size: 13px;
}
.deg-briefs {
  display: grid;
  gap: 6px;
  margin: 0;
  padding-left: 18px;
  font-size: 14px;
}
.deg-internal {
  color: var(--muted);
  list-style: none;
  margin-left: -18px;
  font-size: 13px;
}
.deg-brief {
  font-weight: 600;
}
.deg-original {
  color: var(--muted);
}
.deg-items small {
  color: var(--muted);
  font-size: 12px;
}
.form-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
</style>
