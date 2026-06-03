<script setup lang="ts">
import { computed } from 'vue'
import type { SnapshotPayload } from '../types'

const props = defineProps<{
  snapshot?: SnapshotPayload
  activeStepRunning?: boolean
}>()

const ar = computed(() => props.snapshot?.auto_realize ?? {})
const descriptionText = computed(() => String(ar.value.description_text ?? ''))
</script>

<template>
  <section class="page">
    <template v-if="!descriptionText && activeStepRunning">
      <div class="working">正在生成赛题描述，请稍候...</div>
    </template>
    <template v-else>
      <h4>description.md 预览</h4>
      <pre class="desc">{{ descriptionText || '尚未生成 description.md' }}</pre>
    </template>
  </section>
</template>

<style scoped>
.page {
  border: 1px solid #d0ddee;
  border-radius: 10px;
  background: #fff;
  padding: 10px;
  min-height: 460px;
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
  font-size: 12px;
}

.working {
  border: 1px solid #bcd4f1;
  border-radius: 10px;
  background: #e9f2ff;
  color: #264d81;
  padding: 20px;
}
</style>
