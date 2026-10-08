<script setup lang="ts">
import { computed, shallowRef } from 'vue'
import { ChevronRight, Folder, FileText } from 'lucide-vue-next'
import { readStateLabel, type CognitionTreeNode } from './cognition-tree-types'

const props = defineProps<{
  node: CognitionTreeNode
  depth?: number
  boldWhen?: (path: string) => boolean
}>()

const emit = defineEmits<{
  preview: [path: string]
}>()

const expanded = shallowRef((props.depth ?? 0) <= 1)

const hasChildren = computed(() => props.node.children.length > 0)
const canToggle = computed(() => props.node.isDir && hasChildren.value)

function toggle() {
  if (!canToggle.value) return
  expanded.value = !expanded.value
}

function onDblclick() {
  emit('preview', props.node.path)
}

const canPreview = computed(() => {
  if (!props.boldWhen) return !props.node.isDir
  return !!props.boldWhen(props.node.path)
})
</script>

<template>
  <li>
    <div
      class="node-row"
      :class="{ clickable: canToggle, previewable: canPreview, bold: canPreview }"
    >
      <button v-if="canToggle" class="caret tree-toggle" :class="{ open: expanded }" :aria-label="`${expanded ? '收起' : '展开'} ${node.name}`" :aria-expanded="expanded" @click="toggle"><ChevronRight :size="13" /></button>
      <span class="caret empty" v-else></span>
      <component :is="node.isDir ? Folder : FileText" :size="14" />
      <button class="tree-file" :disabled="!canPreview && !canToggle" :title="node.path" @click="canPreview ? onDblclick() : toggle()">{{ node.name }}<span v-if="node.isDir">/</span></button>
      <span class="dot" :class="node.readState"></span>
      <small>{{ readStateLabel(node.readState) }}</small>
    </div>
    <ul v-if="hasChildren && expanded">
      <CognitionTreeNode
        v-for="child in node.children"
        :key="child.path"
        :node="child"
        :depth="(depth ?? 0) + 1"
        :bold-when="boldWhen"
        @preview="emit('preview', $event)"
      />
    </ul>
  </li>
</template>

<style scoped>
li {
  margin: 0;
  padding: 0;
}

ul {
  margin: 0;
  padding-left: 16px;
}

.node-row {
  display: flex;
  gap: 6px;
  align-items: center;
  font-size: 11px;
  color: #78896c;
  line-height: 1.5;
}
.tree-toggle { border: 0; padding: 0; background: transparent; height: 22px; display: inline-flex; align-items: center; }
.tree-file { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; text-align: left; color: #4c6540; background: transparent; border: 0; padding: 7px 0; font-size: 11px; font-weight: 500; }
.node-row small { margin-left: auto; font-size: 9px; white-space: nowrap; }

.node-row.clickable {
  cursor: pointer;
  user-select: none;
}

.node-row.clickable:hover {
  color: #1b3e6f;
}

.node-row small {
  color: #637ea6;
}

.node-row.bold {
  font-weight: 700;
}

.node-row.previewable {
  text-decoration: underline dotted transparent;
}

.node-row.previewable:hover {
  text-decoration-color: #3d5f8f;
}

.caret {
  width: 12px;
  display: inline-block;
  color: #5876a4;
  transform: rotate(0deg);
  transition: transform 120ms ease;
}

.caret.open {
  transform: rotate(90deg);
}

.caret.empty {
  visibility: hidden;
}

.dot {
  width: 9px;
  height: 9px;
  border-radius: 50%;
  display: inline-block;
  background: #b0b8c5;
}

.dot.unread {
  background: #9ba9bc;
}

.dot.read {
  background: #28a745;
}

.dot.reading {
  background: #2b74ff;
  box-shadow: 0 0 0 3px rgba(43, 116, 255, 0.2);
}

.dot.skipped {
  background: #8c9aab;
}

.dot.failed {
  background: #d33d3d;
}

.dot.partial {
  background: #d18a2d;
}
</style>
