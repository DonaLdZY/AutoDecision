<script setup lang="ts">
import type { Task } from '../types'

const props = defineProps<{
  tasks: Task[]
  activeTaskId: string
  dirtyTaskIds?: Record<string, boolean>
}>()

const emit = defineEmits<{
  select: [taskId: string]
  create: []
}>()
</script>

<template>
  <div class="tab-bar">
    <button
      v-for="task in props.tasks"
      :key="task.id"
      class="tab-item"
      :class="{ active: task.id === props.activeTaskId }"
      @click="emit('select', task.id)"
      :title="task.task_name"
    >
      <span class="tab-name">
        {{ task.config.task_name || task.task_name }}
        <span v-if="props.dirtyTaskIds?.[task.id]" class="dirty-dot" title="未保存草稿">●</span>
      </span>
      <span class="tab-status" :class="task.status">{{ task.status }}</span>
    </button>
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
  justify-content: space-between;
  align-items: center;
  gap: 10px;
  padding: 8px 10px;
  cursor: pointer;
}

.tab-item.active {
  border-color: #6ba6ff;
  background: #18325b;
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
