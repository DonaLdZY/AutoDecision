<script setup lang="ts">
import { computed } from 'vue'
import MarkdownView from './MarkdownView.vue'
import ProducerChart from './ProducerChart.vue'
const props = defineProps<{ markdown: string; facts: Record<string, unknown> }>()
// Split on [[chart:kind]] placeholder lines; odd indices are chart kinds, even ones are prose.
const segments = computed(() =>
  props.markdown
    .split(/^\[\[chart:([a-z_]+)\]\][ \t]*$/m)
    .map((part, i) => (i % 2 ? { chart: part, text: '' } : { chart: '', text: part }))
    .filter((s) => s.chart || s.text.trim()),
)
</script>
<template>
  <div class="producer-report">
    <template v-for="(s, i) in segments" :key="i">
      <ProducerChart v-if="s.chart" :kind="s.chart" :facts="facts" />
      <MarkdownView v-else :text="s.text" />
    </template>
  </div>
</template>
<style scoped>
.producer-report {
  min-width: 0;
}
</style>
