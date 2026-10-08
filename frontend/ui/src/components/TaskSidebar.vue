<script setup lang="ts">
import { computed, ref } from 'vue'
import { Plus, Search, Trash2, Folder, CircleCheck, LoaderCircle } from 'lucide-vue-next'
import type { Task } from '../types'
import { displayTaskName } from '../utils/taskName'
const props = defineProps<{ tasks: Task[]; activeTaskId: string; dirtyTaskIds?: Record<string, boolean> }>()
const emit = defineEmits<{ select: [id: string]; create: []; remove: [id: string]; removeBlocked: [id: string] }>()
const query = ref('')
const filtered = computed(() => props.tasks.filter(t => displayTaskName(t.config.task_name || t.task_name).toLocaleLowerCase().includes(query.value.toLocaleLowerCase())))
const labels: Record<string, string> = { idle: '待运行', running: '运行中', completed: '已完成', failed: '失败', stopped: '已停止', interrupted_resumable: '可恢复', interrupted_incomplete: '中断' }
</script>
<template>
  <div class="task-sidebar-content">
    <div class="sidebar-section-label"><span>任务空间</span><button class="icon-button" title="新建任务" aria-label="新建任务" @click="emit('create')"><Plus :size="17" /></button></div>
    <label class="task-search"><Search :size="14" /><input v-model="query" aria-label="搜索任务" placeholder="搜索任务" /></label>
    <nav class="task-list" aria-label="任务列表">
      <div v-for="task in filtered" :key="task.id" class="task-item" :class="{ selected: activeTaskId === task.id }">
        <button class="task-select" :title="displayTaskName(task.config.task_name || task.task_name)" @click="emit('select', task.id)">
          <LoaderCircle v-if="task.status === 'running'" :size="16" class="spin" /><CircleCheck v-else-if="task.status === 'completed'" :size="16" /><Folder v-else :size="16" />
          <span class="task-name"><strong>{{ displayTaskName(task.config.task_name || task.task_name) }}</strong><small>{{ labels[task.status] || task.status }}<span v-if="dirtyTaskIds?.[task.id]"> · 未保存</span></small></span>
        </button>
        <button v-if="activeTaskId === task.id" class="task-remove icon-button" title="删除任务" aria-label="删除当前任务" @click="task.status === 'running' ? emit('removeBlocked', task.id) : emit('remove', task.id)"><Trash2 :size="13" /></button>
      </div>
      <span v-if="!filtered.length" class="sidebar-empty">{{ query ? '没有匹配的任务' : '暂无任务' }}</span>
    </nav>
  </div>
</template>
