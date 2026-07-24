<script setup lang="ts">
import { computed } from 'vue'
import { deriveReportProgress } from '../utils/reportProgress'

const props = defineProps<{
  currentState?: Record<string, unknown>
  events: Record<string, unknown>[]
}>()

const progress = computed(() => deriveReportProgress(props.currentState, props.events))
</script>

<template>
  <section class="report-progress" :class="progress.status">
    <div class="progress-heading">
      <div>
        <p class="eyebrow">AutoReport</p>
        <div class="title-row">
          <h3>最终方案报告</h3>
          <span class="status" :class="progress.status">{{ progress.statusLabel }}</span>
        </div>
        <p class="activity">
          <span v-if="progress.status === 'running'" class="pulse" aria-hidden="true"></span>
          {{ progress.activityLabel }}
        </p>
      </div>
      <strong class="percent">{{ progress.percent }}%</strong>
    </div>

    <div class="track" aria-label="AutoReport 生成进度">
      <span :style="{ width: `${progress.percent}%` }"></span>
    </div>

    <div class="stages">
      <article v-for="(stage, index) in progress.stages" :key="stage.key" :class="stage.status">
        <span class="stage-index">{{ String(index + 1).padStart(2, '0') }}</span>
        <div>
          <strong>{{ stage.label }}</strong>
          <small>{{ stage.detail }}</small>
        </div>
        <span class="stage-dot" aria-hidden="true"></span>
      </article>
    </div>

    <p v-if="progress.error" class="error">{{ progress.error }}</p>
  </section>
</template>

<style scoped>
.report-progress {
  border: 1px solid #c8d9dc;
  border-radius: 8px;
  padding: 20px 22px;
  background: #f6faf9;
}

.report-progress.completed {
  border-color: #b9d9ca;
  background: #f3faf6;
}

.report-progress.failed {
  border-color: #e7bdb6;
  background: #fff7f5;
}

.progress-heading,
.title-row,
.activity,
.stages article {
  display: flex;
  align-items: center;
}

.progress-heading {
  justify-content: space-between;
  gap: 18px;
}

.eyebrow {
  margin: 0 0 3px;
  color: #668087;
  font-size: 11px;
  font-weight: 700;
  text-transform: uppercase;
}

.title-row {
  flex-wrap: wrap;
  gap: 10px;
}

.title-row h3 {
  margin: 0;
  color: #173f49;
  font-size: 21px;
}

.status {
  border-radius: 6px;
  padding: 4px 8px;
  background: #e5ecee;
  color: #536b71;
  font-size: 11px;
  font-weight: 800;
}

.status.running {
  background: #dff2ef;
  color: #087269;
}

.status.completed {
  background: #ddefe3;
  color: #286c4d;
}

.status.failed {
  background: #f8dfdb;
  color: #9b4037;
}

.activity {
  gap: 8px;
  margin: 8px 0 0;
  color: #536f77;
  font-size: 13px;
}

.pulse {
  width: 8px;
  height: 8px;
  flex: 0 0 auto;
  border-radius: 50%;
  background: #13877c;
  animation: report-pulse 1.8s infinite;
}

.percent {
  color: #1b5f63;
  font-size: 28px;
}

.track {
  height: 7px;
  margin-top: 16px;
  overflow: hidden;
  border-radius: 4px;
  background: #dbe6e7;
}

.track span {
  display: block;
  height: 100%;
  background: #247b77;
  transition: width 450ms ease;
}

.stages {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 8px;
  margin-top: 14px;
}

.stages article {
  position: relative;
  min-width: 0;
  gap: 8px;
  border: 1px solid #d6e0e2;
  border-radius: 7px;
  padding: 10px 24px 10px 9px;
  background: #fff;
}

.stages article.running {
  border-color: #79b9b3;
  background: #edf8f6;
}

.stages article.completed {
  border-color: #bddbc9;
  background: #f3faf5;
}

.stages article.failed {
  border-color: #e9b9b1;
  background: #fff2ef;
}

.stage-index {
  color: #80969b;
  font-family: Consolas, monospace;
  font-size: 10px;
  font-weight: 800;
}

.stages article > div {
  display: grid;
  min-width: 0;
  gap: 2px;
}

.stages strong {
  overflow: hidden;
  color: #31545d;
  font-size: 12px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.stages small {
  overflow: hidden;
  color: #74898e;
  font-size: 10px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.stage-dot {
  position: absolute;
  top: 12px;
  right: 9px;
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #b7c4c7;
}

.running .stage-dot {
  background: #13877c;
}

.completed .stage-dot {
  background: #3e9666;
}

.failed .stage-dot {
  background: #bd5044;
}

.error {
  margin: 12px 0 0;
  color: #983b32;
  font-size: 12px;
}

@keyframes report-pulse {
  70% { box-shadow: 0 0 0 7px rgba(19, 135, 124, 0); }
  100% { box-shadow: 0 0 0 0 rgba(19, 135, 124, 0); }
}

@media (max-width: 980px) {
  .stages {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
}

@media (max-width: 640px) {
  .stages {
    grid-template-columns: 1fr;
  }
}
</style>
