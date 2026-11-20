<script setup lang="ts">
import { computed, ref } from 'vue'
import Icon from './Icon.vue'
import { tasks, openDialog, newConversation, statusText, stageNames } from '../store'
const filter = ref('all')
const query = ref('')
const filtered = computed(() =>
  tasks.value.filter(
    (t) =>
      (filter.value === 'all' || t.status === filter.value) &&
      `${t.title} ${t.id}`.toLowerCase().includes(query.value.toLowerCase()),
  ),
)
</script>
<template>
  <div class="standard-page">
    <div class="page-heading">
      <div>
        <div class="eyebrow">CAPABILITY LAB</div>
        <h1>研发任务</h1>
        <p>当已有能力不足以回答问题，启动一次面向目标的算法研发。</p>
      </div>
      <button class="btn primary" @click="newConversation">
        <Icon name="plus" :size="16" />从对话创建任务
      </button>
    </div>
    <div class="stat-strip">
      <div>
        <span><i class="status-dot" />正在运行</span
        ><strong>{{ tasks.filter((t) => t.status === 'running').length }}<small>个任务</small></strong>
      </div>
      <div>
        <span><Icon name="clock" :size="14" />等待与暂停</span
        ><strong
          >{{ tasks.filter((t) => ['queued', 'paused'].includes(t.status)).length
          }}<small>个任务</small></strong
        >
      </div>
      <div>
        <span><Icon name="checkCircle" :size="14" />研发完成</span
        ><strong>{{ tasks.filter((t) => t.status === 'completed').length }}<small>个任务</small></strong>
      </div>
      <div>
        <span><Icon name="package" :size="14" />已沉淀能力</span
        ><strong>{{ tasks.filter((t) => t.packageId).length }}<small>个模型包</small></strong>
      </div>
    </div>
    <div class="filter-toolbar">
      <div class="pill-tabs">
        <button
          v-for="f in [
            { id: 'all', name: '全部任务' },
            { id: 'running', name: '运行中' },
            { id: 'paused', name: '已暂停' },
            { id: 'completed', name: '已完成' },
          ]"
          :key="f.id"
          :class="{ active: filter === f.id }"
          @click="filter = f.id"
        >
          {{ f.name }}
        </button>
      </div>
      <div class="search-box">
        <Icon name="search" :size="16" /><input
          v-model="query"
          placeholder="搜索任务…"
          aria-label="搜索研发任务"
        />
      </div>
    </div>
    <div class="task-list">
      <button v-for="t in filtered" :key="t.id" class="task-row" @click="openDialog('task', t.id)">
        <span :class="['square-icon', t.status === 'completed' ? '' : 'blue']"
          ><Icon :name="t.status === 'completed' ? 'checks' : 'branch'" :size="23"
        /></span>
        <div class="task-info">
          <div>
            <code>{{ t.id }}</code
            ><span
              :class="[
                'tag',
                t.status === 'running' ? 'info' : t.status === 'completed' ? 'success' : 'neutral',
              ]"
              ><i v-if="t.status === 'running'" class="status-dot" />{{ statusText(t.status) }}</span
            ><span v-if="t.packageId" class="tiny-tag">已发布模型包</span>
          </div>
          <h3>{{ t.title }}</h3>
          <p>{{ t.target }}</p>
        </div>
        <div class="task-progress">
          <div>
            <span>{{ stageNames[t.stage] }}</span
            ><strong>{{ t.progress }}%</strong>
          </div>
          <div class="progress-track"><span :style="{ width: t.progress + '%' }" /></div>
          <small>{{ t.candidates }} 个候选算法</small>
        </div>
        <div class="task-created">
          <span>{{ t.created.slice(0, 10) }}</span
          ><small>{{ t.created.slice(11) }} 创建</small>
        </div>
        <Icon name="right" :size="18" />
      </button>
    </div>
    <div v-if="!filtered.length" class="empty-state">
      <Icon name="branch" :size="36" />
      <h3>这里还没有符合条件的任务</h3>
      <p>从对话提出新的目标，或切换筛选条件。</p>
    </div>
    <div class="bottom-hint">
      <Icon name="cpu" :size="16" />本页任务为模拟。进入任务可手动推进阶段，体验搜索、验证、发布与复用。
    </div>
  </div>
</template>
