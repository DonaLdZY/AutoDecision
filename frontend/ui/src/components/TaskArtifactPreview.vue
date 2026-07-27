<script setup lang="ts">
import { computed, shallowRef } from 'vue'
import type { SnapshotPayload } from '../types'

type ArtifactId = 'description' | 'automl_context' | 'main_protocol'

const props = defineProps<{
  snapshot?: SnapshotPayload
}>()

const activeArtifact = shallowRef<ArtifactId>('description')
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

function selectArtifact(id: ArtifactId) {
  activeArtifact.value = id
}
</script>

<template>
  <section class="artifact-workspace">
    <header class="artifact-header">
      <div>
        <p class="artifact-eyebrow">Compiled Artifacts</p>
        <h3 class="artifact-title">最终产物</h3>
        <p class="artifact-subtitle">查看 AutoRealize 交付给用户与 AlgoEvolve 的实际文件，而不是内部生成事件。</p>
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
        <span>
          <strong>{{ item.label }}</strong>
          <small>{{ item.purpose }}</small>
        </span>
      </button>
    </div>

    <div class="artifact-preview">
      <div class="preview-toolbar">
        <strong>{{ selectedArtifact.label }}</strong>
        <span>{{ selectedArtifact.content ? 'ready' : 'waiting' }}</span>
      </div>
      <pre v-if="selectedArtifact.content">{{ selectedArtifact.content }}</pre>
      <div v-else class="artifact-empty">
        <strong>{{ selectedArtifact.label }} 尚未生成</strong>
        <p>任务定义阶段完成后，文件内容会直接显示在这里。</p>
      </div>
    </div>
  </section>
</template>

<style scoped>
.artifact-workspace {
  overflow: hidden;
  border: 1px solid #c9d9e6;
  border-radius: 18px;
  background: #f8fbfd;
  box-shadow: 0 16px 36px rgba(37, 74, 105, 0.07);
}

.artifact-header {
  display: flex;
  justify-content: space-between;
  gap: 20px;
  align-items: flex-end;
  padding: 20px 22px 16px;
  border-bottom: 1px solid #d7e3eb;
  background:
    linear-gradient(100deg, rgba(239, 247, 250, 0.92), rgba(255, 255, 255, 0.9)),
    repeating-linear-gradient(90deg, transparent 0 36px, rgba(38, 96, 125, 0.04) 36px 37px);
}

.artifact-eyebrow {
  margin: 0 0 5px;
  color: #16776f;
  font-size: 11px;
  font-weight: 800;
  letter-spacing: 0.12em;
  text-transform: uppercase;
}

.artifact-title {
  margin: 0;
  color: #173f5a;
  font-size: 24px;
}

.artifact-subtitle {
  margin: 7px 0 0;
  color: #617d91;
  font-size: 13px;
}

.artifact-stats,
.preview-toolbar,
.artifact-header {
  display: flex;
}

.artifact-stats {
  gap: 7px;
}

.artifact-stats span,
.preview-toolbar span {
  border-radius: 999px;
  background: #e5eff4;
  color: #5b7486;
  font-size: 11px;
  font-weight: 700;
  padding: 5px 9px;
}

.artifact-tabs {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
  padding: 12px;
  background: #edf4f7;
}

.artifact-tab {
  display: grid;
  grid-template-columns: 10px minmax(0, 1fr);
  gap: 9px;
  align-items: start;
  padding: 11px 12px;
  border: 1px solid transparent;
  border-radius: 12px;
  background: transparent;
  text-align: left;
  cursor: pointer;
}

.artifact-tab:hover,
.artifact-tab.active {
  border-color: #b7d0da;
  background: #ffffff;
}

.artifact-tab.active {
  box-shadow: 0 7px 18px rgba(42, 86, 109, 0.08);
}

.artifact-dot {
  width: 8px;
  height: 8px;
  margin-top: 4px;
  border-radius: 50%;
  background: #a7b6c0;
}

.artifact-dot.ready {
  background: #24946d;
  box-shadow: 0 0 0 3px rgba(36, 148, 109, 0.12);
}

.artifact-tab span:last-child {
  display: grid;
  gap: 4px;
  min-width: 0;
}

.artifact-tab strong {
  color: #264e67;
  font-size: 12px;
}

.artifact-tab small {
  color: #718797;
  font-size: 10px;
  line-height: 1.4;
}

.artifact-preview {
  margin: 0 12px 12px;
  overflow: hidden;
  border: 1px solid #d0dfe7;
  border-radius: 13px;
  background: #ffffff;
}

.preview-toolbar {
  justify-content: space-between;
  gap: 12px;
  align-items: center;
  padding: 9px 12px;
  border-bottom: 1px solid #d8e4ea;
  background: #f5f9fb;
}

.preview-toolbar strong {
  color: #31576d;
  font-family: Consolas, monospace;
  font-size: 12px;
}

.artifact-preview pre {
  max-height: 680px;
  margin: 0;
  overflow: auto;
  padding: 18px;
  color: #2d4d60;
  font-family: "Microsoft YaHei UI", "PingFang SC", sans-serif;
  font-size: 12px;
  line-height: 1.72;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  word-break: break-word;
}

.artifact-empty {
  padding: 48px 18px;
  color: #496b7f;
  text-align: center;
}

.artifact-empty p {
  margin: 7px 0 0;
  color: #78909e;
  font-size: 12px;
}

@media (max-width: 760px) {
  .artifact-header {
    align-items: flex-start;
    flex-direction: column;
  }

  .artifact-tabs {
    grid-template-columns: 1fr;
  }
}
</style>
