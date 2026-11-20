<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from 'vue'
import Icon from '../components/Icon.vue'
import StorageRow from './StorageRow.vue'
import { request, ui } from './store'
import { manageStorage, resourceKey, storageRevision } from './storage'
import { groupStorage, isDataFolder } from './storageGroups'
import type { Resource } from './storage'
const props = defineProps<{ projectId?: string; embedded?: boolean }>()
const resources = ref<Resource[]>([]), loading = ref(true), error = ref(''), query = ref('')
const filter = ref('all'), tab = ref<'active' | 'archived' | 'all'>('active'), selected = ref(new Set<string>())
const actionHint = computed(() => {
  if (loading.value) return '正在读取资源，完成后才能选择和管理。'
  if (!ui.online) return '本地服务未连接，请先点击顶部“重新连接”。'
  if (ui.busy) return '正在处理上一项操作，请稍候。'
  if (!picked.value.length) return '先勾选要管理的资源；删除前还会再次核对目录和占用情况。'
  if (!deletable.value) return '当前选中的资源包含受保护内容，只能归档；如需删除，请先处理关联任务或交付记录。'
  return '已选择资源，可归档或删除。删除是永久操作，提交前会显示目录占用和阻拦原因。'
})
let sequence = 0
const scoped = computed(() => resources.value.filter(r => !props.projectId || (r.project_id === props.projectId && !isDataFolder(r))))
const visible = computed(() => scoped.value.filter(resource =>
  (tab.value === 'all' || resource.archived === (tab.value === 'archived')) &&
  (filter.value === 'all' || (filter.value === 'data' ? isDataFolder(resource) :
    filter.value === 'artifacts' ? !isDataFolder(resource) :
    filter.value === 'development' ? ['tasks', 'runs'].includes(resource.kind) : resource.kind === 'packages')) &&
  (!query.value.trim() || [resource.name, resource.data_name, resource.data_path, resource.task_name, ...resource.paths]
    .join(' ').toLowerCase().includes(query.value.trim().toLowerCase())),
))
const groups = computed(() => groupStorage(visible.value))
const picked = computed(() => scoped.value.filter(resource => selected.value.has(resourceKey(resource))))
const deletable = computed(() => picked.value.length > 0 && picked.value.every(r => r.can_delete))
function allChecked(rows: Resource[]) { return rows.length > 0 && rows.every(r => selected.value.has(resourceKey(r))) }
function someChecked(rows: Resource[]) { return !allChecked(rows) && rows.some(r => selected.value.has(resourceKey(r))) }
function selectMany(rows: Resource[], checked: boolean) {
  const next = new Set(selected.value)
  for (const resource of rows) {
    if (checked) next.add(resourceKey(resource))
    else next.delete(resourceKey(resource))
  }
  selected.value = next
}
async function load() {
  const current = ++sequence
  loading.value = true
  error.value = ''
  try {
    const data = await request<{ resources: Resource[] }>('/studio/storage')
    if (sequence === current) {
      resources.value = data.resources
      selected.value = new Set([...selected.value].filter(id => scoped.value.some(resource => resourceKey(resource) === id)))
    }
  } catch (reason) { if (sequence === current) error.value = reason instanceof Error ? reason.message : String(reason) }
  finally { if (sequence === current) loading.value = false }
}
watch([storageRevision, () => props.projectId], load, { immediate: true })
onUnmounted(() => sequence++)
</script>
<template>
  <section :class="[embedded ? 'storage-embedded' : 'live-page', 'storage-page']">
    <div class="page-heading"><div><component :is="embedded ? 'h2' : 'h1'">{{ embedded ? '开发目录与代码包' : '本地存储' }}</component><p>{{ scoped.length }} 项资源</p></div>
      <button class="btn secondary small" :disabled="loading || !!ui.busy" @click="storageRevision++"><Icon name="refresh" :size="14" />刷新</button>
    </div>
    <div class="live-tabs">
      <button :class="{ active: tab === 'all' }" @click="tab = 'all'">全部 <span>{{ scoped.length }}</span></button>
      <button :class="{ active: tab === 'active' }" @click="tab = 'active'">使用中 <span>{{ scoped.filter(r => !r.archived).length }}</span></button>
      <button :class="{ active: tab === 'archived' }" @click="tab = 'archived'">已归档 <span>{{ scoped.filter(r => r.archived).length }}</span></button>
    </div>
    <div class="storage-filters">
      <label class="live-search"><Icon name="search" :size="16" /><input v-model="query" type="search" placeholder="搜索数据、任务或真实路径" aria-label="搜索本地存储" /></label>
      <select v-model="filter" aria-label="资源类型"><option value="all">全部类型</option><option v-if="!embedded" value="data">数据文件夹</option><option value="artifacts">开发目录和代码包</option><option value="development">开发目录</option><option value="packages">代码包</option></select>
    </div>
    <div class="storage-toolbar">
      <label><input type="checkbox" :checked="allChecked(visible)" :indeterminate="someChecked(visible)" :disabled="!visible.length || !!ui.busy" @change="selectMany(visible, ($event.target as HTMLInputElement).checked)" />全选</label>
      <span>已选 {{ picked.length }} 项</span>
      <button v-if="picked.length" class="text-btn" :disabled="!!ui.busy" @click="selected = new Set()">清空选择</button>
      <div class="storage-actions"><button class="btn secondary small" :disabled="!picked.length || !!ui.busy || !ui.online" :title="actionHint" @click="manageStorage(picked.every(r => r.archived) ? 'restore' : 'archive', picked)">{{ picked.length && picked.every(r => r.archived) ? '还原' : '归档' }}</button>
        <button class="btn secondary small storage-delete" :disabled="!deletable || !!ui.busy || !ui.online" :title="actionHint" @click="manageStorage('delete', picked)">删除</button>
      </div>
    </div>
    <p class="storage-action-hint" :class="{ warning: !picked.length || !ui.online || !deletable }">{{ actionHint }}</p>
    <p v-if="error" class="live-error" role="alert">{{ error }}</p>
    <p v-if="loading" class="storage-loading" role="status">正在读取本地资源…</p>
    <div v-else-if="!visible.length" class="live-empty"><Icon name="folder" :size="32" /><h2>{{ tab === 'archived' ? '没有已归档资源' : query.trim() ? `没有匹配“${query}”的本地资源` : '没有匹配的本地资源' }}</h2><button v-if="query.trim()" type="button" class="btn secondary small" @click="query = ''">清除搜索，查看全部资源</button><button v-else-if="tab === 'archived'" type="button" class="btn secondary small" @click="tab = 'active'">查看使用中资源</button></div>
    <div v-else class="storage-groups">
      <section v-for="group in groups" :key="group.id" class="storage-data-group" :data-group="group.id">
        <header class="storage-group-heading">
          <input type="checkbox" :aria-label="'选择数据分组 ' + group.name" :checked="allChecked(group.resources)" :indeterminate="someChecked(group.resources)" :disabled="!!ui.busy" @change="selectMany(group.resources, ($event.target as HTMLInputElement).checked)" />
          <Icon name="database" :size="18" /><h2>{{ group.name }}</h2><span>{{ group.tasks.filter(t => t.id !== 'unlinked').length }} 个任务</span>
        </header>
        <StorageRow v-for="resource in group.folders" :key="resourceKey(resource)" :resource="resource" :checked="selected.has(resourceKey(resource))" @select="selectMany([resource], $event)" />
        <section v-for="task in group.tasks" :key="task.id" class="storage-task-group" :data-task="task.id">
          <header class="storage-task-heading">
            <input type="checkbox" :aria-label="'选择任务分组 ' + task.name" :checked="allChecked(task.resources)" :indeterminate="someChecked(task.resources)" :disabled="!!ui.busy" @change="selectMany(task.resources, ($event.target as HTMLInputElement).checked)" />
            <Icon name="branch" :size="15" /><h3>{{ task.name }}</h3><span>{{ task.resources.length }} 项</span>
          </header>
          <StorageRow v-for="resource in task.resources" :key="resourceKey(resource)" :resource="resource" :checked="selected.has(resourceKey(resource))" @select="selectMany([resource], $event)" />
        </section>
      </section>
    </div>
  </section>
</template>
