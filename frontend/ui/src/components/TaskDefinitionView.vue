<script setup lang="ts">
import { computed } from 'vue'
import type { SnapshotPayload } from '../types'
import TaskArtifactPreview from './TaskArtifactPreview.vue'
import TaskDefinitionProcessView from './TaskDefinitionProcessView.vue'

const props = defineProps<{
  snapshot?: SnapshotPayload
  activeStepRunning?: boolean
}>()

const hasTaskDefinitionData = computed(() => {
  const ar = props.snapshot?.auto_realize
  return Boolean(
    ar?.task_definition_report
    || ar?.description_text
    || ar?.automl_context_text
    || ar?.main_task_protocol,
  )
})
</script>

<template>
  <section class="page">
    <TaskDefinitionProcessView
      :snapshot="snapshot"
      :active-step-running="activeStepRunning"
    />
    <TaskArtifactPreview v-if="hasTaskDefinitionData || activeStepRunning" :snapshot="snapshot" />
  </section>
</template>

<style scoped>
.page {
  display: grid;
  gap: 16px;
  min-height: 460px;
  min-width: 0;
  max-width: 100%;
  overflow-x: hidden;
}
</style>
