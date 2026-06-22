<script setup lang="ts">
import { computed, shallowRef } from 'vue'
import type { SnapshotPayload } from '../types'

const props = defineProps<{
  snapshot?: SnapshotPayload
}>()

const selectedSectionId = shallowRef('')

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value) ? (value as Record<string, unknown>) : {}
}

function asArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : []
}

const reportSnapshot = computed(() => props.snapshot?.auto_report ?? {})
const report = computed(() => asRecord(reportSnapshot.value.report))
const sections = computed(() => asArray(report.value.sections).map((item) => asRecord(item)))
const events = computed(() => (reportSnapshot.value.events ?? []).slice(-120).reverse())
const markdown = computed(() => String(reportSnapshot.value.report_markdown ?? ''))
const currentState = computed(() => asRecord(reportSnapshot.value.current_state))
const outputDir = computed(() => String(reportSnapshot.value.output_dir ?? ''))
const summary = computed(() => asRecord(report.value.summary))
const warnings = computed(() => asArray(report.value.warnings).map((x) => String(x)))
const stdout = computed(() => String(reportSnapshot.value.stdout ?? ''))
const stderr = computed(() => String(reportSnapshot.value.stderr ?? ''))

const selectedSection = computed(() => {
  if (!selectedSectionId.value) return sections.value[0] ?? {}
  return sections.value.find((section) => String(section.id ?? '') === selectedSectionId.value) ?? sections.value[0] ?? {}
})

function selectSection(section: Record<string, unknown>) {
  selectedSectionId.value = String(section.id ?? '')
}

function eventTitle(eventRow: Record<string, unknown>) {
  return `${String(eventRow.component ?? '-')}.${String(eventRow.event ?? '-')}`
}
</script>

<template>
  <section class="report-page">
    <aside class="left">
      <header class="header-card">
        <p class="eyebrow">AutoReport</p>
        <h3>{{ String(report.report_title ?? '报告生成') }}</h3>
        <span class="state-pill" :class="String(currentState.status ?? 'idle')">{{ String(currentState.status ?? 'idle') }}</span>
      </header>

      <section class="metric-grid">
        <div><span>证据路径</span><strong>{{ summary.evidence_paths ?? 0 }}</strong></div>
        <div><span>证据文件</span><strong>{{ summary.evidence_items ?? 0 }}</strong></div>
        <div><span>文章章节</span><strong>{{ sections.length }}</strong></div>
        <div><span>证据告警</span><strong>{{ warnings.length }}</strong></div>
      </section>

      <section class="section-list">
        <h4>报告章节</h4>
        <button
          v-for="section in sections"
          :key="String(section.id ?? section.title)"
          :class="{ active: String(selectedSection.id ?? '') === String(section.id ?? '') }"
          type="button"
          @click="selectSection(section)"
        >
          {{ String(section.title ?? section.id ?? '-') }}
        </button>
        <p v-if="sections.length === 0" class="empty">暂无章节，等待 AutoReport 生成。</p>
      </section>

      <section v-if="events.length > 0" class="event-list">
        <h4>最近事件</h4>
        <article v-for="eventRow in events.slice(0, 10)" :key="`${String(eventRow.seq ?? '')}-${String(eventRow.ts ?? '')}`">
          <strong>{{ eventTitle(eventRow) }}</strong>
          <span>{{ String(eventRow.ts ?? '') }}</span>
        </article>
      </section>
    </aside>

    <main class="right">
      <section class="section-preview">
        <div class="preview-head">
          <div>
            <p class="eyebrow">Section Preview</p>
            <h3>{{ String(selectedSection.title ?? '请选择章节') }}</h3>
          </div>
          <span v-if="outputDir" class="dir-pill">{{ outputDir }}</span>
        </div>
        <pre>{{ String(selectedSection.content ?? '暂无章节内容') }}</pre>
      </section>

      <section class="markdown-preview">
        <h4>完整方案文章 report.md</h4>
        <pre>{{ markdown || '暂无 report.md' }}</pre>
      </section>

      <section v-if="stdout || stderr" class="raw-output">
        <h4>AutoReport 原始输出</h4>
        <pre v-if="stdout">{{ stdout }}</pre>
        <pre v-if="stderr" class="stderr">{{ stderr }}</pre>
      </section>
    </main>
  </section>
</template>

<style scoped>
.report-page {
  display: grid;
  grid-template-columns: minmax(300px, 0.75fr) minmax(420px, 1.25fr);
  gap: 12px;
}

.left,
.right {
  display: grid;
  gap: 12px;
}

.header-card,
.section-list,
.event-list,
.section-preview,
.markdown-preview,
.raw-output {
  border: 1px solid #d0ddee;
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.95);
  padding: 12px;
}

.eyebrow {
  margin: 0 0 4px;
  color: #6a82a5;
  font-size: 12px;
}

h3,
h4 {
  margin: 0;
  color: #244a74;
}

.state-pill,
.dir-pill {
  display: inline-block;
  margin-top: 8px;
  border-radius: 999px;
  padding: 4px 9px;
  background: #eef5ff;
  color: #315b8a;
  font-size: 12px;
}

.state-pill.completed {
  background: #d8f9e7;
  color: #24744b;
}

.state-pill.running {
  background: #dcecff;
  color: #275f9c;
}

.state-pill.failed {
  background: #ffe2e2;
  color: #8a2020;
}

.metric-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
}

.metric-grid div {
  border: 1px solid #d4e1f2;
  border-radius: 12px;
  background: #f8fbff;
  padding: 10px;
}

.metric-grid span {
  display: block;
  color: #667f9f;
  font-size: 12px;
}

.metric-grid strong {
  color: #254e7a;
}

.section-list {
  display: grid;
  gap: 8px;
}

.section-list button {
  border: 1px solid #c4d5ef;
  border-radius: 10px;
  background: #f2f6ff;
  color: #264a73;
  cursor: pointer;
  padding: 8px 10px;
  text-align: left;
}

.section-list button.active {
  background: #1f4e8c;
  color: #fff;
  border-color: #1f4e8c;
}

.event-list article {
  display: grid;
  gap: 3px;
  padding: 7px 0;
  border-bottom: 1px dashed #d9e2ef;
  color: #506f91;
  font-size: 12px;
}

.event-list article:last-child {
  border-bottom: 0;
}

.preview-head {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: start;
}

pre {
  margin: 10px 0 0;
  border: 1px solid #d5e2f2;
  border-radius: 10px;
  background: #f7fbff;
  padding: 10px;
  white-space: pre-wrap;
  overflow: auto;
  max-height: 560px;
  color: #243f60;
  font-size: 12px;
}

.stderr {
  background: #fff7f7;
  border-color: #f0c9c9;
}

.empty {
  color: #617d9f;
}

@media (max-width: 1100px) {
  .report-page {
    grid-template-columns: 1fr;
  }
}
</style>
