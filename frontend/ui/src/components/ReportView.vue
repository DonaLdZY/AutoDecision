<script setup lang="ts">
import { computed } from 'vue'
import type { SnapshotPayload } from '../types'
import ReportDocument from './ReportDocument.vue'
import ReportProgress from './ReportProgress.vue'

const props = defineProps<{
  snapshot?: SnapshotPayload
}>()

interface ReportSection {
  id: string
  title: string
  content: string
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value) ? (value as Record<string, unknown>) : {}
}

const reportSnapshot = computed(() => props.snapshot?.auto_report ?? {})
const report = computed(() => asRecord(reportSnapshot.value.report))
const currentState = computed(() => asRecord(reportSnapshot.value.current_state))
const events = computed(() => reportSnapshot.value.events ?? [])
const markdown = computed(() => String(reportSnapshot.value.report_markdown ?? report.value.article_markdown ?? ''))
const outputDir = computed(() => String(reportSnapshot.value.output_dir ?? ''))
const title = computed(() => String(report.value.report_title ?? '最终方案报告'))
const sections = computed<ReportSection[]>(() => {
  const rows = Array.isArray(report.value.sections) ? report.value.sections : []
  return rows.map((value, index) => {
    const row = asRecord(value)
    return {
      id: String(row.id ?? `section_${index + 1}`),
      title: String(row.title ?? `章节 ${index + 1}`),
      content: String(row.content ?? ''),
    }
  })
})
</script>

<template>
  <section class="report-page">
    <ReportProgress :current-state="currentState" :events="events" />
    <ReportDocument
      :title="title"
      :markdown="markdown"
      :sections="sections"
      :output-dir="outputDir"
    />
  </section>
</template>

<style scoped>
.report-page {
  display: grid;
  gap: 16px;
  min-width: 0;
}
</style>
