<script setup lang="ts">
import { nextTick, useTemplateRef, watch } from 'vue'
import type { Task } from '../types'

const props = defineProps<{
  tasks: Task[]
  activeTaskId: string
  dirtyTaskIds?: Record<string, boolean>
}>()

const emit = defineEmits<{
  select: [taskId: string]
  create: []
  remove: [taskId: string]
  removeBlocked: [taskId: string]
}>()

const tabBar = useTemplateRef<HTMLDivElement>('tabBar')

watch(
  () => props.activeTaskId,
  async (taskId) => {
    if (!taskId) return
    await nextTick()
    const activeTab = Array.from(tabBar.value?.querySelectorAll<HTMLElement>('[data-task-id]') ?? [])
      .find((element) => element.dataset.taskId === taskId)
    activeTab?.scrollIntoView({ behavior: 'auto', block: 'nearest', inline: 'center' })
  },
  { immediate: true },
)

function statusLabel(status: string) {
  const labels: Record<string, string> = {
    idle: '等待',
    running: '运行中',
    completed: '已完成',
    failed: '失败',
    stopped: '已停止',
    interrupted_resumable: '已中断，可恢复',
    interrupted_incomplete: '中断未完整',
  }
  return labels[status] ?? status
}

function requestRemove(task: Task) {
  if (task.status === 'running') {
    emit('removeBlocked', task.id)
    return
  }
  emit('remove', task.id)
}
</script>

<template>
  <div ref="tabBar" class="tab-bar">
    <div
      v-for="task in props.tasks"
      :key="task.id"
      class="tab-item"
      :class="{ active: task.id === props.activeTaskId }"
      :data-task-id="task.id"
    >
      <button class="tab-select" type="button" :title="task.task_name" @click="emit('select', task.id)">
        <span class="tab-name">
          {{ task.config.task_name || task.task_name }}
          <span v-if="props.dirtyTaskIds?.[task.id]" class="dirty-dot" title="未保存草稿">●</span>
        </span>
        <span class="tab-status" :class="task.status">{{ statusLabel(task.status) }}</span>
      </button>
      <button
        v-if="task.id === props.activeTaskId"
        type="button"
        class="tab-delete"
        :class="{ blocked: task.status === 'running' }"
        :title="task.status === 'running' ? '运行中的任务不能删除' : '删除当前任务'"
        :aria-label="task.status === 'running' ? '运行中，点击查看不能删除的原因' : '删除当前任务'"
        @click="requestRemove(task)"
      >
        ×
      </button>
    </div>
    <button class="tab-add" @click="emit('create')" title="新建任务">+</button>
  </div>
</template>

<style scoped>
.tab-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 14px;
  background: linear-gradient(180deg, #142239, #0f1a2d);
  border-bottom: 1px solid #2d4368;
  overflow-x: auto;
}

.tab-item {
  min-width: 180px;
  max-width: 280px;
  border: 1px solid #38517c;
  border-radius: 10px;
  color: #d9e8ff;
  background: #11203a;
  display: flex;
  align-items: center;
  overflow: hidden;
}

.tab-item.active {
  border-color: #6ba6ff;
  background: #18325b;
}

.tab-select {
  display: flex;
  flex: 1 1 auto;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  min-width: 0;
  border: 0;
  padding: 8px 10px;
  background: transparent;
  color: inherit;
  font: inherit;
  letter-spacing: 0;
  cursor: pointer;
}

.tab-delete {
  flex: 0 0 30px;
  align-self: stretch;
  border: 0;
  border-left: 1px solid #45658f;
  background: #2b3f5d;
  color: #ffd7d9;
  font-size: 20px;
  line-height: 1;
  cursor: pointer;
}

.tab-delete:hover:not(.blocked) {
  background: #9e343c;
  color: #fff;
}

.tab-delete.blocked {
  cursor: not-allowed;
  opacity: 0.45;
}

.tab-name {
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
}

.dirty-dot {
  margin-left: 6px;
  color: #ffd36f;
  font-size: 11px;
}

.tab-status {
  font-size: 12px;
  text-transform: uppercase;
  padding: 2px 6px;
  border-radius: 6px;
  background: #25395b;
}

.tab-status.running {
  background: #1f6744;
}

.tab-status.failed {
  background: #7b2f2f;
}

.tab-status.completed {
  background: #1d5e73;
}

.tab-status.interrupted_resumable {
  background: #7a5b16;
  color: #fff2bf;
}

.tab-status.interrupted_incomplete {
  background: #7b2f2f;
  color: #ffe1df;
}

.tab-add {
  width: 36px;
  height: 36px;
  border-radius: 18px;
  border: 1px dashed #6ba6ff;
  background: #10203c;
  color: #6ba6ff;
  font-size: 24px;
  line-height: 1;
  cursor: pointer;
}
</style>
