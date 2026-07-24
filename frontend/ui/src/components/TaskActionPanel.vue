<script setup lang="ts">
const props = defineProps<{
  running: boolean
  canOpenDirectory: boolean
  canRunAutoRealize: boolean
  canRunAutoML: boolean
  canContinueAutoML: boolean
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
  runReport: []
  runTask: []
  resumeTask: []
  stopTask: []
}>()
</script>

<template>
  <div class="task-actions">
    <div class="action-row" aria-label="配置操作">
      <button type="button" :disabled="props.running" @click="emit('save')">保存配置</button>
      <button type="button" @click="emit('refresh')">刷新状态</button>
      <button type="button" :disabled="!props.canOpenDirectory" @click="emit('openDirectory')">打开任务目录</button>
    </div>

    <div class="action-row stage-row" aria-label="阶段执行">
      <button type="button" :disabled="!props.canRunAutoRealize" @click="emit('runAutoRealize')">执行 AutoRealize</button>
      <button type="button" :disabled="!props.canRunAutoML" @click="emit('runAutoML')">执行 AutoML</button>
      <button type="button" :disabled="!props.canContinueAutoML" @click="emit('continueAutoML')">继续执行 AutoML</button>
      <button type="button" :disabled="!props.canRunReport" @click="emit('runReport')">执行报告生成</button>
    </div>

    <div class="action-row workflow-row" aria-label="整条任务执行">
      <button type="button" class="run-task" :disabled="!props.canRunTask" @click="emit('runTask')">执行任务</button>
      <button type="button" class="resume-task" :disabled="!props.canResumeTask" @click="emit('resumeTask')">从中断继续任务</button>
      <button type="button" class="stop-task" :disabled="!props.canStopTask" @click="emit('stopTask')">中断当前任务</button>
    </div>
  </div>
</template>

<style scoped>
.task-actions {
  display: grid;
  gap: 8px;
  margin-top: 16px;
  padding-top: 14px;
  border-top: 1px solid #d5dfef;
}

.action-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  min-height: 36px;
}

.action-row + .action-row {
  padding-top: 8px;
  border-top: 1px solid #e2e8f2;
}

.action-row button {
  min-height: 36px;
  border: 1px solid #b8c9df;
  border-radius: 7px;
  padding: 8px 12px;
  background: #f4f7fb;
  color: #24415f;
  font: inherit;
  letter-spacing: 0;
  cursor: pointer;
}

.stage-row button {
  border-color: #8ebbb4;
  background: #e7f2f0;
  color: #155d55;
}

.workflow-row .run-task {
  border-color: #3f876d;
  background: #267257;
  color: #fff;
}

.workflow-row .resume-task {
  border-color: #789bc7;
  background: #e6effa;
  color: #1e4e86;
}

.workflow-row .stop-task {
  border-color: #d4a064;
  background: #fff0dd;
  color: #8a4c0f;
}

.action-row button:hover:not(:disabled) {
  filter: brightness(0.97);
}

.action-row button:disabled {
  cursor: not-allowed;
  opacity: 0.48;
}

@media (max-width: 640px) {
  .action-row {
    display: grid;
    grid-template-columns: 1fr;
  }

  .action-row button {
    min-width: 0;
  }
}
</style>
