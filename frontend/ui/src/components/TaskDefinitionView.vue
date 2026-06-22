<script setup lang="ts">
import { computed } from 'vue'
import type { SnapshotPayload } from '../types'
import TaskDefinitionProcessView from './TaskDefinitionProcessView.vue'

const props = defineProps<{
  snapshot?: SnapshotPayload
  activeStepRunning?: boolean
}>()

const ar = computed(() => props.snapshot?.auto_realize ?? {})
const descriptionText = computed(() => String(ar.value.description_text ?? ''))
</script>

<template>
  <section class="page">
    <TaskDefinitionProcessView
      :snapshot="snapshot"
      :active-step-running="activeStepRunning"
    />

    <section class="preview-card">
      <h4>description.md 预览</h4>
      <pre class="desc">{{ descriptionText || '尚未生成 description.md' }}</pre>
    </section>
  </section>
</template>

<style scoped>
.page {
  display: grid;
  gap: 12px;
  min-height: 460px;
  min-width: 0;
  max-width: 100%;
  overflow-x: hidden;
}

.preview-card {
  border: 1px solid #d0ddee;
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.96);
  padding: 12px;
  box-sizing: border-box;
  min-width: 0;
  max-width: 100%;
  overflow: hidden;
}

h4 {
  margin: 0 0 8px;
  color: #254a76;
}

.desc {
  margin: 0;
  background: #f7fbff;
  border: 1px solid #d5e2f2;
  border-radius: 8px;
  padding: 10px;
  overflow: auto;
  max-height: 620px;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  word-break: break-word;
  box-sizing: border-box;
  min-width: 0;
  max-width: 100%;
  font-size: 12px;
}

</style>
