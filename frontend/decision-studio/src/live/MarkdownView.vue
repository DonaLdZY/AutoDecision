<script setup lang="ts">
import { computed } from 'vue'
import DOMPurify from 'dompurify'
import { marked } from 'marked'
const props = defineProps<{ text?: string }>()
const html = computed(() => DOMPurify.sanitize(marked.parse(props.text || '', { async: false }), {
  FORBID_TAGS: ['img', 'iframe', 'style', 'form', 'input'],
  FORBID_ATTR: ['style'],
}))
</script>
<template>
  <article class="report-prose" v-html="html" />
</template>
<style scoped>
.report-prose { color: var(--ink); line-height: 1.85; overflow-wrap: anywhere; min-width: 0; }
.report-prose :deep(h1) { font-size: 25px; }
.report-prose :deep(h2) { margin-top: 2em; font-size: 20px; border-bottom: 1px solid var(--line); padding-bottom: 10px; }
.report-prose :deep(h3) { margin-top: 1.6em; font-size: 16px; }
.report-prose :deep(p), .report-prose :deep(ul), .report-prose :deep(ol) { margin: 0.8em 0; }
.report-prose :deep(ul), .report-prose :deep(ol) { padding-left: 1.8em; }
.report-prose :deep(a) { color: var(--primary); text-decoration: underline; text-underline-offset: 3px; }
.report-prose :deep(table) { display: block; width: 100%; overflow-x: auto; border-collapse: collapse; font-size: 13px; }
.report-prose :deep(th), .report-prose :deep(td) { padding: 10px 14px; text-align: left; border: 1px solid var(--line); white-space: normal; }
.report-prose :deep(th) { background: #f5f5f7; }
.report-prose :deep(pre) { overflow-x: auto; white-space: pre; padding: 16px; border-radius: 8px; background: #f5f5f7; }
.report-prose :deep(code) { font-family: "Cascadia Code", Consolas, monospace; font-size: 0.88em; }
.report-prose :deep(blockquote) { border-left: 3px solid var(--line); padding-left: 18px; margin-inline: 0; color: var(--secondary); }
</style>
