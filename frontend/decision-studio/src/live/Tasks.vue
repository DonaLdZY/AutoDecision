<script setup lang="ts">
import { computed, ref } from 'vue'
import Icon from '../components/Icon.vue'
import Modal from './Modal.vue'
import ResearchForm from './ResearchForm.vue'
import { taskWorkflow } from './taskWorkflow'
import { tasks, state, ui, status, phase, date, taskProjectId } from './store'
import { summarizeGoal } from './presentation'
const emit = defineEmits<{ open: [kind: string, id: string]; navigate: [page: string] }>(),
  create = ref(false),
  filter = ref('all'),
  projectFilter = ref('')
const projectOf = (taskId: string) => state.projects.find((p) => p.id === taskProjectId(taskId))
const filtered = computed(() =>
  [...tasks.value]
    .sort((a, b) => b.updated_at - a.updated_at)
    .filter((t) => !projectFilter.value || taskProjectId(t.id) === projectFilter.value)
    .filter(
      (t) =>
        filter.value === 'all' ||
        (filter.value === 'running'
          ? t.status === 'running'
          : filter.value === 'done'
            ? t.status === 'completed'
            : t.status !== 'running' && t.status !== 'completed'),
    ),
)
function tag(t: (typeof tasks.value)[number]) {
  if (t.status !== 'completed')
    return { tone: t.status === 'running' ? 'info' : 'neutral', label: status(t.status) }
  return taskWorkflow(t, state.task_deliveries?.[t.id]).stage === 'published'
    ? { tone: 'success', label: '已发布算法包' }
    : { tone: 'success', label: '已完成' }
}
</script>
<template>
  <section class="live-page">
    <div class="page-heading">
      <div>
        <h1>研究计划</h1>
      </div>
      <button class="btn primary" :disabled="!state.projects.length || !ui.online" @click="create = true">
        <Icon name="plus" />新建研究计划
      </button>
    </div>
    <div class="plan-toolbar">
      <div class="live-tabs">
        <button
          v-for="f in [
            { id: 'all', name: '全部' },
            { id: 'running', name: '进行中' },
            { id: 'done', name: '已完成' },
            { id: 'other', name: '草稿与中断' },
          ]"
          :key="f.id"
          :class="{ active: filter === f.id }"
          @click="filter = f.id"
        >
          {{ f.name }}
        </button>
      </div>
      <select v-if="state.projects.length > 1" v-model="projectFilter" aria-label="按项目数据筛选">
        <option value="">全部数据</option>
        <option v-for="p in state.projects" :key="p.id" :value="p.id">{{ p.name }}</option>
      </select>
    </div>
    <div v-if="!filtered.length" class="live-empty">
      <Icon name="branch" :size="32" />
      <h2>
        {{
          !state.projects.length
            ? '先导入项目数据'
            : tasks.length
              ? '这个筛选下没有研究计划'
              : '还没有研究计划'
        }}
      </h2>
      <button v-if="!state.projects.length" class="btn primary small" @click="emit('navigate', 'projects')">
        打开项目数据
      </button>
      <button
        v-else-if="!tasks.length"
        class="btn primary small"
        :disabled="!ui.online"
        @click="create = true"
      >
        新建研究计划
      </button>
    </div>
    <article v-for="t in filtered" :key="t.id" class="live-panel plan-row">
      <button class="plan-main" @click="emit('open', 'task', t.id)">
        <div class="plan-title">
          <h3>{{ t.task_name }}</h3>
          <span class="tag" :class="tag(t).tone">{{ tag(t).label }}</span>
        </div>
        <p v-if="t.status === 'completed' && state.research_briefs?.[t.id]" class="plan-headline">
          {{ state.research_briefs[t.id]!.headline }}
        </p>
        <p v-else class="plan-goal">
          {{ summarizeGoal(t.config.auto_ml.goal || t.config.auto_realize.task_hint, 90) }}
        </p>
        <small>
          <span v-if="projectOf(t.id)" class="plan-data"
            ><i :style="{ background: projectOf(t.id)!.color }"></i>{{ projectOf(t.id)!.name }}</span
          >
          {{ t.status === 'running' ? phase(t.phase) : date(t.updated_at) }}
        </small>
      </button>
      <button v-if="t.status === 'completed'" class="btn primary small" @click="emit('open', 'report', t.id)">
        查看详细报告
      </button>
      <button v-else class="btn secondary small" @click="emit('open', 'task', t.id)">
        {{ t.status === 'running' ? '查看进度' : '打开' }}
      </button>
    </article>
    <Modal v-if="create" title="新建研究计划" @close="create = false"
      ><ResearchForm
        @done="
          (id) => {
            create = false
            emit('open', 'task', id)
          }
        "
    /></Modal>
  </section>
</template>
<style scoped>
.plan-toolbar {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 16px;
}
.plan-toolbar .live-tabs {
  margin: 0;
}
.plan-toolbar select {
  min-width: 160px;
  padding: 8px 10px;
  border: 1px solid var(--line);
  border-radius: 7px;
  background: #fff;
  color: var(--ink);
  font: inherit;
  font-size: 13px;
}
.plan-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 16px;
  align-items: center;
  margin: 0 0 12px;
}
.plan-main {
  min-width: 0;
  padding: 0;
  border: 0;
  background: none;
  color: inherit;
  text-align: left;
  cursor: pointer;
}
.plan-title {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  align-items: center;
}
.plan-title h3 {
  margin: 0;
  font-size: 16px;
}
.plan-headline {
  margin: 8px 0 6px;
  color: var(--ink);
  font-size: 15px;
  font-weight: 600;
}
.plan-goal {
  display: -webkit-box;
  margin: 8px 0 6px;
  overflow: hidden;
  color: var(--secondary);
  font-size: 13px;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
}
.plan-row small {
  color: var(--muted);
  font-size: 12px;
}
.plan-data {
  margin-right: 10px;
}
.plan-data i {
  display: inline-block;
  width: 8px;
  height: 8px;
  margin-right: 5px;
  border-radius: 50%;
  vertical-align: 0;
}
@media (max-width: 760px) {
  .plan-row {
    grid-template-columns: 1fr;
  }
}
</style>
