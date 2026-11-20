<script setup lang="ts">
import { computed, ref } from 'vue'
import Icon from '../components/Icon.vue'
import Modal from './Modal.vue'
import ResearchForm from './ResearchForm.vue'
import ResourceStorage from './ResourceStorage.vue'
import TaskNextStep from './TaskNextStep.vue'
import { taskWorkflow } from './taskWorkflow'
import { tasks, state, ui, project, status, phase, date } from './store'
import { summarizeGoal } from './presentation'
const emit = defineEmits<{ open: [kind: string, id: string]; navigate: [page: string] }>(),
  create = ref(false),
  filter = ref('all')
const pendingDeliveries = computed(() => tasks.value.filter(t => taskWorkflow(t, state.task_deliveries?.[t.id]).pendingDelivery))
const filtered = computed(() =>
  tasks.value.filter(
    (t) =>
      filter.value === 'all' ||
      (filter.value === 'delivery' ? taskWorkflow(t, state.task_deliveries?.[t.id]).pendingDelivery : filter.value === 'running'
        ? t.status === 'running'
        : filter.value === 'done'
          ? t.status === 'completed'
          : t.status !== 'running' && t.status !== 'completed'),
  ),
)
</script>
<template>
  <section class="live-page">
    <div class="page-heading">
      <div>
        <h1>研发任务</h1>
      </div>
      <button class="btn primary" :disabled="!project || !ui.online" @click="create = true">
        <Icon name="plus" />新建研发任务
      </button>
    </div>
    <div class="live-tabs">
      <button
        v-for="f in [
          { id: 'all', name: '全部任务' },
          { id: 'running', name: '执行中' },
          { id: 'delivery', name: `待交付与发布（${pendingDeliveries.length}）` },
          { id: 'done', name: '研发已结束' },
          { id: 'other', name: '草稿与中断' },
        ]"
        :key="f.id"
        :class="{ active: filter === f.id }"
        @click="filter = f.id"
      >
        {{ f.name }}
      </button>
    </div>
    <div v-if="!filtered.length" class="live-empty">
      <Icon name="branch" :size="32" />
      <h2>{{ !project ? '先选择或创建数据项目' : filter === 'delivery' ? '当前没有待交付成果' : tasks.length ? '这个筛选下没有任务' : '这里还没有研发任务' }}</h2>
      <p>{{ !project ? '任务需要关联数据项目，才能读取数据并保存成果。' : filter === 'delivery' ? '研发结束且尚未发布的成果会显示在这里。' : '可以新建任务，或切换筛选查看已有任务。' }}</p>
      <button v-if="!project" class="btn primary small" @click="emit('navigate', 'projects')">打开项目数据</button>
      <button v-else-if="tasks.length" class="btn secondary small" @click="filter = 'all'">查看全部任务</button>
      <button v-else class="btn primary small" :disabled="!ui.online" @click="create = true">新建研发任务</button>
    </div>
    <article v-for="t in filtered" :key="t.id" class="task-storage-row">
    <button class="live-list-row" @click="emit('open', 'task', t.id)">
      <span class="square-icon"><Icon name="branch" /></span>
      <div>
        <h3>{{ t.task_name }}</h3>
        <p>{{ summarizeGoal(t.config.auto_ml.goal || t.config.auto_realize.task_hint, 140) }}</p>
        <small>创建于 {{ date(t.created_at) }}</small>
      </div>
      <span
        class="tag"
        :class="t.status === 'completed' ? taskWorkflow(t, state.task_deliveries?.[t.id]).tone : t.status === 'running' ? 'info' : 'neutral'"
        >{{ t.status === 'completed' ? taskWorkflow(t, state.task_deliveries?.[t.id]).label : status(t.status) }}</span
      ><span>{{ phase(t.phase) }}</span
      ><Icon name="right" /></button
    ><TaskNextStep :task="t" compact @open="(kind, id) => emit('open', kind, id)" /><ResourceStorage kind="tasks" :id="t.id" compact />
    </article><Modal v-if="create" title="创建研发任务" @close="create = false"
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
.live-list-row p {
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
</style>
