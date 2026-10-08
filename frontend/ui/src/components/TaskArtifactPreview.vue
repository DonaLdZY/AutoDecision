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
    label: 'description.md',
    purpose: '给人和下游模型共同阅读的完整任务书',
    content: String(ar.value.description_text ?? ''),
  },
  {
    id: 'automl_context' as const,
    label: 'automl_context.md',
    purpose: 'AlgoEvolve 直接消费的精确补充上下文',
    content: String(ar.value.automl_context_text ?? ''),
  },
  {
    id: 'main_protocol' as const,
    label: 'main_task_protocol.json',
    purpose: '机器可读的任务、评价和交付合同',
    content: prettyJson(mainTaskProtocol.value),
  },
])

const selectedArtifact = computed(() => {
  return artifacts.value.find((item) => item.id === activeArtifact.value) ?? artifacts.value[0]
})

const contentStats = computed(() => {
  const content = selectedArtifact.value.content
  return {
    chars: content.length,
    lines: content ? content.split(/\r?\n/).length : 0,
  }
})
const rendered = useSafeMarkdown(() => sourceVisible.value || activeArtifact.value === 'main_protocol' ? '' : selectedArtifact.value.content)
function downloadArtifact() {
  const blob = new Blob([selectedArtifact.value.content], { type: activeArtifact.value === 'main_protocol' ? 'application/json;charset=utf-8' : 'text/markdown;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a'); link.href = url; link.download = selectedArtifact.value.label; link.click()
  window.setTimeout(() => URL.revokeObjectURL(url), 1000)
}

function selectArtifact(id: ArtifactId) {
  activeArtifact.value = id
}
</script>

<template>
  <section class="artifact-workspace">
    <header class="artifact-header">
      <div>
        <h3 class="artifact-title"><FileText :size="18" />任务合同</h3>
      </div>
      <div class="artifact-stats">
        <span>{{ contentStats.lines }} 行</span>
        <span>{{ contentStats.chars }} 字符</span>
      </div>
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
        <span class="artifact-dot" :class="{ ready: Boolean(item.content) }"></span>
        <component :is="item.id === 'main_protocol' ? FileJson : FileText" :size="15" />
        <span>
          <strong>{{ item.label }}</strong>
        </span>
      </button>
    </div>

    <div class="artifact-preview">
      <div class="preview-toolbar">
        <strong>{{ selectedArtifact.label }}</strong>
        <div class="artifact-tools"><div v-if="activeArtifact !== 'main_protocol'" class="segmented"><button :class="{ active: !sourceVisible }" title="文档预览" aria-label="文档预览" @click="sourceVisible = false"><BookOpen :size="14" /></button><button :class="{ active: sourceVisible }" title="查看源文件" aria-label="查看源文件" @click="sourceVisible = true"><Code2 :size="14" /></button></div><button class="icon-button" title="下载当前产物" aria-label="下载当前产物" :disabled="!selectedArtifact.content" @click="downloadArtifact"><Download :size="16" /></button></div>
      </div>
      <article v-if="selectedArtifact.content && !sourceVisible && activeArtifact !== 'main_protocol'" class="artifact-prose" v-html="rendered" />
      <pre v-else-if="selectedArtifact.content">{{ selectedArtifact.content }}</pre>
      <div v-else class="artifact-empty">
        <strong>{{ selectedArtifact.label }} 尚未生成</strong>
      </div>
    </div>
  </section>
</template>

<style scoped>
.artifact-workspace { min-width: 0; background: #fff; overflow: hidden; }
.artifact-header { display: flex; justify-content: space-between; align-items: center; padding: 18px 22px; border-bottom: 1px solid var(--line); }
.artifact-title { display: flex; align-items: center; gap: 9px; margin: 0; font-size: 15px; font-weight: 600; color: #4d6641; }
.artifact-stats { display: flex; gap: 12px; color: #96a18d; font-size: 10px; }
.artifact-tabs { display: flex; flex-wrap: wrap; padding: 0 18px; border-bottom: 1px solid var(--line); }
.artifact-tab { display: flex; align-items: center; gap: 7px; background: transparent; border: 0; border-bottom: 2px solid transparent; border-radius: 0; padding: 13px 12px; color: #849379; }
.artifact-tab.active { border-bottom-color: #548b46; color: #507c42; }
.artifact-tab strong { font: 11px Consolas, monospace; }.artifact-dot { display: none; }
.preview-toolbar { display: flex; justify-content: space-between; align-items: center; padding: 7px 20px; background: #fafcf8; border-bottom: 1px solid var(--line); }
.preview-toolbar strong { color: #97a28c; font: 10px Consolas, monospace; }
.artifact-tools { display: flex; align-items: center; gap: 8px; }
.artifact-prose { padding: 24px 35px; max-width: 980px; color: #4a5742; font-size: 13px; line-height: 1.9; }
.artifact-preview > pre { padding: 24px; color: #627554; font-size: 11px; line-height: 1.7; max-height: 760px; overflow: auto; margin: 0; }
.artifact-empty { padding: 65px 20px; text-align: center; color: #9dab90; font-size: 12px; }
@media(max-width:600px) { .artifact-header { padding: 16px; }.artifact-stats { font-size: 9px; gap: 6px; }.artifact-tabs { padding: 0 8px; }.artifact-tab { padding: 10px 5px; gap: 4px; }.artifact-tab strong { font-size: 9px; }.artifact-prose { padding: 18px; font-size: 12px; } }
</style>
