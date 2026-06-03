<script setup lang="ts">
import { computed, shallowRef } from 'vue'
import type { SnapshotPayload } from '../types'
import CognitionTreeNode from './CognitionTreeNode.vue'
import type { CognitionTreeNode as TreeNode, ReadState } from './cognition-tree-types'

const props = defineProps<{
  snapshot?: SnapshotPayload
}>()

const previewTitle = shallowRef('')
const previewContent = shallowRef('')

function normalizeRelPath(v: string) {
  return v.replaceAll('\\', '/').replace(/^\.?\//, '')
}

const ar = computed(() => props.snapshot?.auto_realize ?? {})
const events = computed(() => (ar.value.events as Record<string, unknown>[] | undefined) ?? [])
const fileCognitionIndex = computed(() => ar.value.file_cognition_index ?? {})
const dataDescriptionText = computed(() => String(ar.value.data_description_text ?? ''))
const cognitionCompleted = computed(() => {
  const state = ar.value.current_state as Record<string, unknown> | undefined
  return String(state?.status ?? '').toLowerCase() === 'completed'
})

const readStateByFile = computed(() => {
  const map: Record<string, ReadState> = {}
  const rows = [...events.value]
  rows.sort((a, b) => Number(a.seq ?? 0) - Number(b.seq ?? 0))
  for (const e of rows) {
    const component = String(e.component ?? '')
    const event = String(e.event ?? '').toUpperCase()
    const fields = (e.fields ?? {}) as Record<string, unknown>
    if (component.startsWith('stage.P1')) {
      const file = normalizeRelPath(String(fields.file ?? ''))
      if (!file) continue
      if (event === 'READING_FILE') map[file] = 'reading'
      else if (event === 'READ_FAILED') map[file] = 'failed'
      else if (event === 'READ_COMPLETED' && map[file] !== 'failed' && map[file] !== 'read') map[file] = 'reading'
      continue
    }
    if (component === 'module.data_cognition.file_artifact' && event === 'GENERATED_FILE') {
      const source = normalizeRelPath(String(fields.source ?? ''))
      if (!source) continue
      if (map[source] !== 'failed') map[source] = 'read'
    }
  }
  for (const k of Object.keys(fileCognitionIndex.value)) map[normalizeRelPath(k)] = 'read'
  return map
})

function aggregate(node: TreeNode): ReadState {
  if (!node.isDir || node.children.length === 0) return node.readState
  const states = node.children.map(aggregate)
  let merged: ReadState
  if (states.some((x) => x === 'reading')) merged = 'reading'
  else if (states.some((x) => x === 'failed')) merged = 'failed'
  else if (states.every((x) => x === 'read' || x === 'skipped')) merged = 'read'
  else if (states.every((x) => x === 'skipped')) merged = 'skipped'
  else if (states.every((x) => x === 'unread')) merged = 'unread'
  else merged = 'partial'
  node.readState = merged
  return merged
}

const tree = computed<TreeNode | null>(() => {
  const text = String(ar.value.directory_tree_text ?? '')
  if (!text.trim()) return null
  const lines = text
    .split('\n')
    .map((x) => x.replace(/\r$/, ''))
    .filter((x) => x.trim().length > 0)
  if (!lines.length) return null

  const root: TreeNode = { name: lines[0].trim(), path: '', isDir: true, children: [], readState: 'unread' }
  const stack: TreeNode[] = [root]
  for (let i = 1; i < lines.length; i += 1) {
    const m = lines[i].match(/^(\s*)- (.+)$/)
    if (!m) continue
    const level = Math.floor(m[1].length / 2) + 1
    const raw = m[2].trim()
    const isDir = raw.endsWith('/')
    const name = isDir ? raw.slice(0, -1) : raw
    const parent = stack[Math.max(0, level - 1)] ?? root
    const path = normalizeRelPath(`${parent.path ? `${parent.path}/` : ''}${name}`)
    const state: ReadState = isDir
      ? 'unread'
      : (readStateByFile.value[path] ?? (cognitionCompleted.value ? 'skipped' : 'unread'))
    const node: TreeNode = { name, path, isDir, children: [], readState: state }
    parent.children.push(node)
    stack[level] = node
    stack.length = level + 1
  }
  root.readState = aggregate(root)
  return root
})

function hasCognition(path: string) {
  return !!fileCognitionIndex.value[normalizeRelPath(path)]
}

function onNodeDblclick(path: string) {
  const key = normalizeRelPath(path)
  const payload = fileCognitionIndex.value[key]
  if (!payload) return
  previewTitle.value = key
  previewContent.value = String(payload.markdown ?? JSON.stringify(payload.json ?? {}, null, 2))
}

function onRootDblclick() {
  previewTitle.value = '(root) data_description.md'
  previewContent.value = dataDescriptionText.value || '暂无 data_description.md'
}
</script>

<template>
  <section class="page">
    <div class="left">
      <h4>数据目录树</h4>
      <ul v-if="tree" class="root">
        <li>
          <div class="title root-title" @dblclick.stop="onRootDblclick">{{ tree.name }}</div>
          <ul>
            <CognitionTreeNode
              v-for="child in tree.children"
              :key="child.path"
              :node="child"
              :depth="1"
              :bold-when="hasCognition"
              @preview="onNodeDblclick"
            />
          </ul>
        </li>
      </ul>
      <p v-else class="empty">尚无目录树数据</p>
      <p class="tip">单击目录展开/收起；双击文件预览认知；双击根目录预览 data_description.md。</p>
    </div>
    <div class="right">
      <h4>节点认知预览</h4>
      <div class="preview-title">{{ previewTitle || '请双击左侧可预览节点' }}</div>
      <pre class="preview">{{ previewContent || '暂无内容' }}</pre>
    </div>
  </section>
</template>

<style scoped>
.page {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
}

.left,
.right {
  border: 1px solid #d0ddee;
  border-radius: 10px;
  background: #fff;
  padding: 10px;
  min-height: 440px;
}

h4 {
  margin: 0 0 8px;
  color: #254a76;
}

.root,
.root ul {
  margin: 0;
  padding-left: 14px;
}

.title {
  font-weight: 600;
  color: #2f4b72;
}

.root-title {
  cursor: pointer;
}

.root-title:hover {
  text-decoration: underline;
}

.tip {
  margin-top: 8px;
  color: #57739a;
  font-size: 12px;
}

.empty {
  color: #597cae;
}

.preview-title {
  color: #3b5c89;
  font-size: 12px;
  margin-bottom: 6px;
}

.preview {
  margin: 0;
  background: #f7fbff;
  border: 1px solid #d5e2f2;
  border-radius: 8px;
  padding: 10px;
  overflow: auto;
  max-height: 540px;
  white-space: pre-wrap;
  font-size: 12px;
}

@media (max-width: 1100px) {
  .page {
    grid-template-columns: 1fr;
  }
}
</style>
