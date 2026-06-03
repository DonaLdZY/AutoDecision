<script setup lang="ts">
import { computed, shallowRef } from 'vue'
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
  if (!props.node.isDir) emit('preview', props.node.path)
}

const canPreview = computed(() => {
  if (props.node.isDir) return false
  if (!props.boldWhen) return true
  return !!props.boldWhen(props.node.path)
})
</script>

<template>
  <li>
    <span
      class="node-row"
      :class="{ clickable: canToggle, previewable: canPreview, bold: canPreview }"
      @click="toggle"
      @dblclick.stop="canPreview && onDblclick()"
    >
      <span class="caret" :class="{ open: expanded }" v-if="canToggle">▸</span>
      <span class="caret empty" v-else></span>
      <span class="dot" :class="node.readState"></span>
      <span>{{ node.name }}<span v-if="node.isDir">/</span></span>
      <small>{{ readStateLabel(node.readState) }}</small>
    </span>
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
  display: inline-flex;
  gap: 6px;
  align-items: center;
  font-size: 13px;
  color: #2f4a72;
  line-height: 1.5;
}

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
