<script setup lang="ts">
import { onMounted, shallowRef, watch } from 'vue'
import { api } from '../api'
import type { DirectoryEntry } from '../types'

const props = defineProps<{
  visible: boolean
  initialPath: string
  title?: string
}>()

const emit = defineEmits<{
  close: []
  select: [path: string]
}>()

const roots = shallowRef<string[]>([])
const currentPath = shallowRef('')
const children = shallowRef<DirectoryEntry[]>([])
const loading = shallowRef(false)
const error = shallowRef('')

async function loadRoots() {
  const res = await api.listRoots()
  roots.value = res.roots
}

async function loadDir(path: string) {
  loading.value = true
  error.value = ''
  try {
    const res = await api.listDir(path)
    currentPath.value = res.path
    children.value = res.children
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    loading.value = false
  }
}

function parentPath(path: string): string {
  const p = (path || '').trim()
  if (!p) return ''
  const normalized = p.replace(/\\/g, '/')

  if (normalized === '/') return '/'
  if (/^[A-Za-z]:\/?$/.test(normalized)) {
    return `${normalized[0]}:/`
  }

  const trimmed = normalized.replace(/\/+$/, '')
  const idx = trimmed.lastIndexOf('/')
  if (idx < 0) return trimmed
  if (idx === 0) return '/'

  const parent = trimmed.slice(0, idx)
  if (/^[A-Za-z]:$/.test(parent)) {
    return `${parent}/`
  }
  return parent
}

function goParent() {
  if (!currentPath.value) return
  const parent = parentPath(currentPath.value)
  if (!parent || parent === currentPath.value) return
  loadDir(parent)
}

function pickCurrent() {
  emit('select', currentPath.value)
}

async function initialize() {
  await loadRoots()
  const target = props.initialPath?.trim() || roots.value[0] || ''
  if (target) {
    await loadDir(target)
  }
}

onMounted(async () => {
  await initialize()
})

watch(
  () => props.visible,
  async (v) => {
    if (v) {
      await initialize()
    }
  },
)
</script>

<template>
  <div v-if="props.visible" class="overlay" @click.self="emit('close')">
    <section class="picker">
      <header>
        <h3>{{ props.title || '选择目录' }}</h3>
        <button @click="emit('close')">关闭</button>
      </header>

      <div class="toolbar">
        <label>
          <span>根目录</span>
          <select @change="loadDir(($event.target as HTMLSelectElement).value)">
            <option v-for="r in roots" :key="r" :value="r">{{ r }}</option>
          </select>
        </label>
        <button @click="goParent">上一级</button>
        <button @click="pickCurrent" :disabled="!currentPath">选择当前目录</button>
      </div>

      <div class="path-row">当前路径: {{ currentPath || '-' }}</div>
      <div class="error" v-if="error">{{ error }}</div>
      <div class="list" v-if="!loading">
        <button
          v-for="c in children.filter((x) => x.is_dir)"
          :key="c.path"
          class="dir-item"
          @dblclick="loadDir(c.path)"
        >
          📁 {{ c.name }}
        </button>
      </div>
      <div class="loading" v-else>加载中...</div>
      <footer>
        <small>双击目录进入；点击“选择当前目录”确认。</small>
      </footer>
    </section>
  </div>
</template>

<style scoped>
.overlay {
  position: fixed;
  inset: 0;
  background: rgba(8, 20, 40, 0.55);
  display: grid;
  place-items: center;
  z-index: 50;
}

.picker {
  width: min(760px, 94vw);
  max-height: 84vh;
  background: #fff;
  border-radius: 14px;
  border: 1px solid #c3d5f0;
  display: grid;
  grid-template-rows: auto auto auto 1fr auto;
}

header,
footer {
  padding: 10px 12px;
  border-bottom: 1px solid #d7e2f6;
  display: flex;
  justify-content: space-between;
  align-items: center;
}

footer {
  border-top: 1px solid #d7e2f6;
  border-bottom: 0;
}

.toolbar {
  padding: 10px 12px;
  display: flex;
  gap: 8px;
  align-items: end;
}

.toolbar label {
  display: grid;
  gap: 4px;
  font-size: 12px;
}

.path-row {
  padding: 0 12px 8px;
  color: #385a86;
  font-size: 13px;
}

.list {
  padding: 0 12px 12px;
  overflow: auto;
  display: grid;
  gap: 6px;
}

.dir-item {
  text-align: left;
  border: 1px solid #c6d8f3;
  border-radius: 8px;
  padding: 8px;
  background: #f6f9ff;
  cursor: pointer;
}

.loading,
.error {
  padding: 0 12px 12px;
}

.error {
  color: #9a2c2c;
}
</style>
