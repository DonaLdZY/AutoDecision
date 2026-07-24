<script setup lang="ts">
import DOMPurify from 'dompurify'
import { marked } from 'marked'
import { computed, shallowRef, watch } from 'vue'

interface ReportSection {
  id: string
  title: string
  content: string
}

const props = defineProps<{
  title: string
  markdown: string
  sections: ReportSection[]
  outputDir?: string
}>()

const selectedId = shallowRef('__full__')

watch(
  () => props.markdown,
  () => {
    selectedId.value = '__full__'
  },
)

const selected = computed(() => props.sections.find((section) => section.id === selectedId.value) ?? null)
const fullMarkdownWithoutTitle = computed(() => props.markdown.replace(/^#\s+[^\r\n]+\r?\n+/, ''))
const visibleMarkdown = computed(() => selected.value?.content || fullMarkdownWithoutTitle.value)
const visibleTitle = computed(() => selected.value?.title || props.title)
const safeHtml = computed(() => DOMPurify.sanitize(String(marked.parse(visibleMarkdown.value || ''))))
</script>

<template>
  <section v-if="props.markdown" class="document-shell">
    <aside class="chapters">
      <div class="chapter-heading">
        <span>报告目录</span>
        <strong>{{ props.sections.length }}</strong>
      </div>
      <button type="button" :class="{ active: selectedId === '__full__' }" @click="selectedId = '__full__'">
        完整报告
      </button>
      <button
        v-for="section in props.sections"
        :key="section.id"
        type="button"
        :class="{ active: selectedId === section.id }"
        @click="selectedId = section.id"
      >
        {{ section.title }}
      </button>
    </aside>

    <article class="document">
      <header class="document-heading">
        <div>
          <p>{{ selected ? '章节预览' : '最终报告' }}</p>
          <h2>{{ visibleTitle }}</h2>
        </div>
        <span v-if="props.outputDir" :title="props.outputDir">{{ props.outputDir }}</span>
      </header>
      <div class="markdown-body" v-html="safeHtml"></div>
    </article>
  </section>

  <section v-else class="empty-report">
    <strong>报告正文尚未生成</strong>
    <span>完成方法分析、写作和检查后将在这里显示最终报告。</span>
  </section>
</template>

<style scoped>
.document-shell {
  display: grid;
  grid-template-columns: minmax(190px, 250px) minmax(0, 1fr);
  min-height: 620px;
  overflow: hidden;
  border: 1px solid #d1dcdf;
  border-radius: 8px;
  background: #fff;
}

.chapters {
  display: grid;
  align-content: start;
  gap: 3px;
  border-right: 1px solid #dce5e7;
  padding: 14px 10px;
  background: #f5f8f8;
}

.chapter-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 4px 8px 10px;
  color: #62777d;
  font-size: 11px;
  font-weight: 800;
  text-transform: uppercase;
}

.chapter-heading strong {
  color: #1d6968;
}

.chapters button {
  min-height: 38px;
  overflow: hidden;
  border: 0;
  border-left: 3px solid transparent;
  border-radius: 4px;
  padding: 8px 10px;
  background: transparent;
  color: #465f67;
  cursor: pointer;
  font-size: 12px;
  text-align: left;
  text-overflow: ellipsis;
}

.chapters button:hover {
  background: #eaf1f1;
}

.chapters button.active {
  border-left-color: #247b77;
  background: #e3efed;
  color: #165d5a;
  font-weight: 800;
}

.document {
  min-width: 0;
  padding: 24px clamp(18px, 4vw, 54px) 48px;
}

.document-heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 18px;
  border-bottom: 1px solid #e0e7e8;
  padding-bottom: 16px;
}

.document-heading p {
  margin: 0 0 5px;
  color: #70858a;
  font-size: 11px;
  font-weight: 800;
  text-transform: uppercase;
}

.document-heading h2 {
  margin: 0;
  color: #173e49;
  font-size: 22px;
  letter-spacing: 0;
}

.document-heading > span {
  max-width: 38%;
  overflow: hidden;
  color: #71858a;
  font-family: Consolas, monospace;
  font-size: 10px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.markdown-body {
  color: #293f46;
  font-size: 14px;
  line-height: 1.75;
}

.markdown-body :deep(h1),
.markdown-body :deep(h2),
.markdown-body :deep(h3),
.markdown-body :deep(h4) {
  margin: 1.6em 0 0.65em;
  color: #173f49;
  letter-spacing: 0;
  line-height: 1.3;
}

.markdown-body :deep(h1) { font-size: 25px; }
.markdown-body :deep(h2) { font-size: 20px; }
.markdown-body :deep(h3) { font-size: 17px; }
.markdown-body :deep(p) { margin: 0.7em 0; }
.markdown-body :deep(ul),
.markdown-body :deep(ol) { padding-left: 1.5em; }

.markdown-body :deep(code) {
  border-radius: 3px;
  padding: 2px 4px;
  background: #edf2f2;
  color: #205e61;
  font-family: Consolas, monospace;
  font-size: 0.9em;
}

.markdown-body :deep(pre) {
  overflow: auto;
  border: 1px solid #d7e1e2;
  border-radius: 6px;
  padding: 14px;
  background: #f5f8f8;
}

.markdown-body :deep(pre code) {
  padding: 0;
  background: transparent;
}

.markdown-body :deep(table) {
  width: 100%;
  border-collapse: collapse;
  margin: 1em 0;
  font-size: 13px;
}

.markdown-body :deep(th),
.markdown-body :deep(td) {
  border: 1px solid #d8e2e3;
  padding: 8px 10px;
  text-align: left;
  vertical-align: top;
}

.markdown-body :deep(th) {
  background: #edf4f3;
  color: #244e53;
}

.empty-report {
  display: grid;
  justify-items: center;
  gap: 6px;
  min-height: 320px;
  align-content: center;
  border: 1px dashed #c9d7da;
  border-radius: 8px;
  color: #687f85;
  background: #f8fafa;
}

.empty-report strong {
  color: #395c64;
}

.empty-report span {
  font-size: 12px;
}

@media (max-width: 820px) {
  .document-shell {
    grid-template-columns: 1fr;
  }

  .chapters {
    display: flex;
    overflow-x: auto;
    border-right: 0;
    border-bottom: 1px solid #dce5e7;
  }

  .chapter-heading {
    display: none;
  }

  .chapters button {
    flex: 0 0 auto;
    max-width: 220px;
    border-left: 0;
    border-bottom: 3px solid transparent;
  }

  .chapters button.active {
    border-bottom-color: #247b77;
  }

  .document-heading {
    display: grid;
  }

  .document-heading > span {
    max-width: 100%;
  }
}
</style>
