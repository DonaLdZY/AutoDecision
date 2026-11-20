<script setup lang="ts">
import { computed, shallowRef, watch } from 'vue'
import { Code2, Download, FileText, FileJson, BookOpen } from 'lucide-vue-next'
import type { SnapshotPayload } from '../types'
import type { ReplayArtifact } from '../utils/replay'
import { useSafeMarkdown } from '../utils/markdown'

type ArtifactId = 'description' | 'automl_context' | 'main_protocol'

const props = defineProps<{
  snapshot?: SnapshotPayload
  replayArtifact?: ReplayArtifact
}>()

const activeArtifact = shallowRef<ArtifactId>('description')
watch(() => props.replayArtifact, artifact => {
  if (artifact) activeArtifact.value = artifact
}, { immediate: true })
const sourceVisible = shallowRef(false)
const ar = computed(() => props.snapshot?.auto_realize ?? {})
const taskDefinitionReport = computed(() => {
  const value = ar.value.task_definition_report
  return value && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {}
})
const mainTaskProtocol = computed(() => {
  const direct = ar.value.main_task_protocol
  if (direct && Object.keys(direct).length > 0) return direct
  const fallback = taskDefinitionReport.value.main_task_protocol
  return fallback && typeof fallback === 'object' && !Array.isArray(fallback)
    ? fallback as Record<string, unknown>
    : {}
})

function prettyJson(value: unknown) {
  if (!value || typeof value !== 'object') return ''
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return String(value)
  }
}

const artifacts = computed(() => [
  {
    id: 'description' as const,
    label: '任务说明',
    filename: 'description.md',
    purpose: '任务目标、边界和评价要求',
    content: String(ar.value.description_text ?? ''),
  },
  {
    id: 'automl_context' as const,
    label: '搜索补充信息',
    filename: 'automl_context.md',
    purpose: '供方案搜索使用的数据与实现约束',
    content: String(ar.value.automl_context_text ?? ''),
  },
  {
    id: 'main_protocol' as const,
    label: '技术协议',
    filename: 'main_task_protocol.json',
    purpose: '任务目标、评价标准和结果形式的核对摘要',
    content: prettyJson(mainTaskProtocol.value),
  },
])

const selectedArtifact = computed(() => {
  return artifacts.value.find((item) => item.id === activeArtifact.value) ?? artifacts.value[0]
})

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {}
}

function text(value: unknown): string {
  return typeof value === 'string' || typeof value === 'number'
    ? String(value).trim()
    : ''
}

const protocolHighlights = computed(() => {
  const task = record(mainTaskProtocol.value.task_protocol)
  const evaluation = record(mainTaskProtocol.value.evaluation_contract)
  const output = record(mainTaskProtocol.value.output_contract)
  const direction = text(evaluation.metric_direction).toLowerCase()
  const outputKind = text(output.output_kind)
  const outputLabels: Record<string, string> = {
    predict_json_and_frozen_model_package: '预测结果与可复用模型包',
    frozen_model_package: '可复用模型包',
    model_package: '可复用模型包',
    optimization_solution: '决策方案与验证结果',
  }
  const directionLabel = ['maximize', 'max', 'higher_is_better', '越大越好'].includes(direction)
    ? '数值越大越好'
    : ['minimize', 'min', 'lower_is_better', '越小越好'].includes(direction)
      ? '数值越小越好'
      : ''

  return [
    { label: '任务目标', value: text(task.task_goal ?? task.overview) },
    {
      label: '主要评价指标',
      value: [text(evaluation.primary_metric), directionLabel].filter(Boolean).join(' · '),
    },
    { label: '评分依据', value: text(evaluation.metric_formula ?? evaluation.scalar_score_formula) },
    { label: '结果形式', value: outputLabels[outputKind] ?? (outputKind ? '已记录结果交付要求' : '') },
  ].filter((item) => item.value)
})
const rendered = useSafeMarkdown(() => sourceVisible.value || activeArtifact.value === 'main_protocol' ? '' : selectedArtifact.value.content)
function downloadArtifact() {
  const blob = new Blob([selectedArtifact.value.content], { type: activeArtifact.value === 'main_protocol' ? 'application/json;charset=utf-8' : 'text/markdown;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a'); link.href = url; link.download = selectedArtifact.value.filename; link.click()
  window.setTimeout(() => URL.revokeObjectURL(url), 1000)
}

function selectArtifact(id: ArtifactId) {
  activeArtifact.value = id
}
</script>

<template>
  <section class="artifact-workspace">
    <header class="artifact-header">
      <h3 class="artifact-title"><FileText :size="18" />任务定义材料</h3>
    </header>

    <div class="artifact-tabs" role="tablist" aria-label="任务定义最终产物">
      <button
        v-for="item in artifacts"
        :key="item.id"
        class="artifact-tab"
        :class="{ active: item.id === activeArtifact }"
        type="button"
        role="tab"
        :aria-selected="item.id === activeArtifact"
        @click="selectArtifact(item.id)"
      >
        <component :is="item.id === 'main_protocol' ? FileJson : FileText" :size="15" aria-hidden="true" />
        <span>{{ item.label }}</span>
      </button>
    </div>

    <div class="artifact-preview">
      <div class="preview-toolbar">
        <div class="preview-heading">
          <strong>{{ selectedArtifact.label }}</strong>
          <span>{{ selectedArtifact.purpose }}</span>
        </div>
        <div class="artifact-tools">
          <div v-if="activeArtifact !== 'main_protocol'" class="segmented" aria-label="文档显示方式">
            <button :class="{ active: !sourceVisible }" title="阅读文档" aria-label="阅读文档" @click="sourceVisible = false"><BookOpen :size="14" /></button>
            <button :class="{ active: sourceVisible }" title="查看源文本" aria-label="查看源文本" @click="sourceVisible = true"><Code2 :size="14" /></button>
          </div>
          <button class="icon-button" title="下载当前材料" aria-label="下载当前材料" :disabled="!selectedArtifact.content" @click="downloadArtifact"><Download :size="16" /></button>
        </div>
      </div>
      <article v-if="selectedArtifact.content && !sourceVisible && activeArtifact !== 'main_protocol'" class="artifact-prose" v-html="rendered" />
      <div v-else-if="activeArtifact === 'main_protocol' && selectedArtifact.content" class="protocol-summary">
        <dl v-if="protocolHighlights.length > 0" class="protocol-facts">
          <div v-for="item in protocolHighlights" :key="item.label">
            <dt>{{ item.label }}</dt>
            <dd>{{ item.value }}</dd>
          </div>
        </dl>
        <p v-else class="artifact-empty">技术协议已生成</p>
        <details class="protocol-technical">
          <summary>查看完整技术协议</summary>
          <pre>{{ selectedArtifact.content }}</pre>
        </details>
      </div>
      <pre v-else-if="selectedArtifact.content">{{ selectedArtifact.content }}</pre>
      <div v-else class="artifact-empty">
        <strong>{{ selectedArtifact.label }}尚未生成</strong>
      </div>
    </div>
  </section>
</template>

<style scoped>
.artifact-workspace { min-width: 0; overflow: hidden; background: #fff; }
.artifact-header { padding: 18px 22px; border-bottom: 1px solid var(--line); }
.artifact-title { display: flex; align-items: center; gap: 9px; margin: 0; color: #1d1d1f; font-size: 16px; font-weight: 600; }
.artifact-tabs { display: flex; flex-wrap: wrap; padding: 0 18px; border-bottom: 1px solid var(--line); }
.artifact-tab { display: flex; align-items: center; gap: 7px; padding: 13px 12px; border: 0; border-bottom: 2px solid transparent; border-radius: 0; background: transparent; color: #626267; font-size: 13px; }
.artifact-tab.active { border-bottom-color: #0071e3; color: #0066cc; }
.preview-toolbar { display: flex; justify-content: space-between; align-items: center; gap: 16px; padding: 9px 20px; border-bottom: 1px solid var(--line); background: #f5f5f7; }
.preview-heading { display: grid; gap: 2px; min-width: 0; }
.preview-heading strong { color: #1d1d1f; font-size: 12px; }
.preview-heading span { color: #6e6e73; font-size: 11px; }
.artifact-tools { display: flex; align-items: center; gap: 8px; flex-shrink: 0; }
.artifact-prose { max-width: 980px; padding: 24px 35px; color: #303034; font-size: 13px; line-height: 1.8; }
.artifact-preview > pre,
.protocol-technical pre { max-height: 760px; margin: 0; overflow: auto; padding: 22px; background: #f5f5f7; color: #303034; font-size: 11px; line-height: 1.7; }
.protocol-summary { padding: 22px; }
.protocol-facts { display: grid; gap: 0; max-width: 980px; margin: 0; }
.protocol-facts > div { display: grid; grid-template-columns: minmax(130px, 190px) minmax(0, 1fr); gap: 16px; padding: 12px 0; border-bottom: 1px solid var(--line); }
.protocol-facts dt { color: #6e6e73; font-size: 12px; }
.protocol-facts dd { margin: 0; color: #1d1d1f; font-size: 13px; line-height: 1.65; overflow-wrap: anywhere; white-space: pre-wrap; }
.protocol-technical { margin-top: 20px; color: #424247; font-size: 12px; }
.protocol-technical summary { width: fit-content; cursor: pointer; }
.artifact-empty { padding: 65px 20px; color: #6e6e73; font-size: 13px; text-align: center; }
@media(max-width:600px) {
  .artifact-header { padding: 16px; }
  .artifact-tabs { padding: 0 6px; }
  .artifact-tab { padding: 11px 8px; font-size: 12px; }
  .preview-toolbar { align-items: flex-start; padding: 9px 12px; }
  .preview-heading span { max-width: 210px; }
  .artifact-prose { padding: 18px; font-size: 12px; }
  .protocol-summary { padding: 16px; }
  .protocol-facts > div { grid-template-columns: 1fr; gap: 4px; }
}
</style>
