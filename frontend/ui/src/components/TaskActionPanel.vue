<script setup lang="ts">
import { BrainCircuit, FileText, FolderOpen, GitBranch, Play, RefreshCw, Save, Square, StepForward } from 'lucide-vue-next'
const props = defineProps<{
  running: boolean
  canOpenDirectory: boolean
  canRunAutoRealize: boolean
  canRunAutoML: boolean
  canContinueAutoML: boolean
  canRepairReview: boolean
  canRunReport: boolean
  canRunTask: boolean
  canResumeTask: boolean
  canStopTask: boolean
}>()

const emit = defineEmits<{
  save: []
  refresh: []
  openDirectory: []
  runAutoRealize: []
  runAutoML: []
  continueAutoML: []
  repairReview: []
  runReport: []
  runTask: []
  resumeTask: []
  stopTask: []
}>()
</script>

<template>
  <div class="task-actions">
    <div class="action-row tool-row" role="group" aria-label="配置操作">
      <button type="button" class="action-icon" title="保存配置" aria-label="保存配置" :disabled="props.running" @click="emit('save')"><Save :size="17" /></button>
      <button type="button" class="action-icon" title="刷新状态" aria-label="刷新状态" @click="emit('refresh')"><RefreshCw :size="17" /></button>
      <button type="button" class="action-icon" title="打开任务目录" aria-label="打开任务目录" :disabled="!props.canOpenDirectory" @click="emit('openDirectory')"><FolderOpen :size="17" /></button>
    </div>

    <div class="action-row stage-row" role="group" aria-label="阶段执行">
      <button type="button" :disabled="!props.canRunAutoRealize" @click="emit('runAutoRealize')"><BrainCircuit :size="15" />执行 AutoRealize</button>
      <button type="button" :disabled="!props.canRunAutoML" @click="emit('runAutoML')"><GitBranch :size="15" />执行 AutoML</button>
      <button type="button" :disabled="!props.canContinueAutoML" @click="emit('continueAutoML')"><StepForward :size="15" />继续执行 AutoML</button>
      <button type="button" class="review-repair" :disabled="!props.canRepairReview" @click="emit('repairReview')"><RefreshCw :size="15" />修复审查并继续</button>
      <button type="button" :disabled="!props.canRunReport" @click="emit('runReport')"><FileText :size="15" />执行报告生成</button>
    </div>

    <div class="action-row workflow-row" role="group" aria-label="整条任务执行">
      <button type="button" class="run-task" :disabled="!props.canRunTask" @click="emit('runTask')"><Play :size="15" />执行任务</button>
      <button type="button" class="resume-task" :disabled="!props.canResumeTask" @click="emit('resumeTask')"><StepForward :size="15" />从中断继续任务</button>
      <button type="button" class="stop-task" :disabled="!props.canStopTask" @click="emit('stopTask')"><Square :size="14" />中断当前任务</button>
    </div>
  </div>
</template>

<style scoped>
.task-actions {
  display: grid;
  gap: 12px;
  margin-top: 16px;
  padding-top: 14px;
  border-top: 1px solid #e1e7de;
  min-width: 0;
}

.action-row {
  display: flex;
  flex-wrap: wrap;
  gap: 7px;
  min-height: 36px;
}

.action-row + .action-row {
  padding-top: 12px;
  border-top: 1px solid #e9ede6;
}

.action-row button {
  min-height: 36px;
  border: 1px solid #dae3d7;
  border-radius: 4px;
  padding: 8px 11px;
  background: #fff;
  color: #5b6b54;
  font: inherit;
  font-size: 11px;
  letter-spacing: 0;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 7px;
  min-width: 0;
  max-width: 100%;
  transition: background-color 100ms ease, border-color 100ms ease, color 100ms ease;
}

.action-row button.review-repair {
  border-color: #e5c58a;
  background: #fff8e8;
  color: #865d16;
}

.action-row button.review-repair:hover:not(:disabled) {
  border-color: #c99a45;
  background: #fff1ce;
}

.action-row button svg { flex-shrink: 0; }
.action-row button.action-icon { width: 36px; height: 36px; padding: 0; background: #f7f9f5; }

.workflow-row .run-task {
  border-color: #26714b;
  background: #26714b;
  color: #fff;
}

.workflow-row .resume-task {
  border-color: #d1dfcc;
  background: #f0f5ed;
  color: #4c7146;
}

.workflow-row .stop-task {
  border-color: #eadbd6;
  background: #fff;
  color: #ad6354;
}

.action-row button:hover:not(:disabled) {
  background: #f1f5ee;
  border-color: #a9c0a3;
}
.workflow-row .run-task:hover:not(:disabled) { color: #fff; background: #1e623f; border-color: #1e623f; }
.workflow-row .stop-task:hover:not(:disabled) { color: #a45447; background: #fff6f3; border-color: #d6b6ad; }

.action-row button:disabled {
  cursor: not-allowed;
  opacity: 0.48;
}

@media (max-width: 480px) {
  .stage-row, .workflow-row {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .action-row button { padding-inline: 8px; font-size: 10px; gap: 5px; }
  .tool-row { display: flex; }
  .workflow-row .stop-task { grid-column: 1 / -1; }
}
@media (prefers-reduced-motion: reduce) {
  .action-row button { transition: none; }
}
</style>
