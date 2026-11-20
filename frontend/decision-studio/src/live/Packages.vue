<script setup lang="ts">
import { computed, ref } from 'vue'
import Icon from '../components/Icon.vue'
import ResourceStorage from './ResourceStorage.vue'
import { usePackage, ui, state } from './store'
// 算法包是研究计划的产出：按来源研究计划分组，标明用的哪份数据；待交付、待发布的提醒统一放在研究通知里。
const emit = defineEmits<{ open: [kind: string, id: string]; navigate: [page: string] }>(),
  query = ref('')
const filtered = computed(() =>
  state.packages.filter((p) => (p.name + p.description).toLowerCase().includes(query.value.toLowerCase())),
)
const groupedPackages = computed(() => {
  const groups = new Map<
    string,
    { id: string; name: string; project?: (typeof state.projects)[number]; packages: typeof filtered.value }
  >()
  for (const item of filtered.value) {
    const id = item.task_id || 'unlinked'
    if (!groups.has(id))
      groups.set(id, {
        id,
        name: item.task_name || state.tasks.find((t) => t.id === id)?.task_name || '未关联研究计划',
        project: state.projects.find((p) => p.id === item.project_id),
        packages: [],
      })
    groups.get(id)!.packages.push(item)
  }
  return [...groups.values()]
})
</script>
<template>
  <section class="live-page">
    <div class="page-heading">
      <div>
        <h1>算法包</h1>
      </div>
    </div>
    <label v-if="state.packages.length" class="live-search"
      ><Icon name="search" /><input v-model="query" placeholder="搜索算法包" aria-label="搜索算法包"
    /></label>
    <section
      v-for="group in groupedPackages"
      :key="group.id"
      class="package-task-group"
      :data-task="group.id"
    >
      <h2>
        <button
          v-if="group.id !== 'unlinked'"
          class="package-source"
          @click="emit('open', 'report', group.id)"
        >
          {{ group.name }}<Icon name="right" :size="14" /></button
        ><template v-else>{{ group.name }}</template>
        <small v-if="group.project" class="package-data"
          ><i :style="{ background: group.project.color }"></i>{{ group.project.name }}</small
        >
      </h2>
      <div class="live-grid three">
        <article v-for="p in group.packages" :key="p.id" class="live-panel package-tile">
          <div class="panel-heading">
            <span class="square-icon"><Icon name="package" :size="24" /></span
            ><span class="tag neutral">v{{ p.version }}</span>
          </div>
          <h2>{{ p.name }}</h2>
          <p>{{ p.description }}</p>
          <div class="package-meta">
            <span>{{ p.file_count ?? p.files?.length ?? 0 }} 个文件</span>
            <span>{{ p.input_binding ? '支持项目数据直接调用' : '填写输入调用' }}</span>
          </div>
          <footer>
            <button class="btn secondary small" @click="emit('open', 'package', p.id)">查看详情</button
            ><button class="btn primary small" :disabled="!!ui.busy" @click="usePackage(p)">
              在对话中使用<Icon name="arrow" :size="14" />
            </button>
          </footer>
          <ResourceStorage kind="packages" :id="p.id" />
        </article>
      </div>
    </section>
    <div v-if="!filtered.length" class="live-empty">
      <Icon name="package" :size="32" />
      <template v-if="query.trim()">
        <h2>没有匹配“{{ query }}”的算法包</h2>
        <button class="btn secondary small" @click="query = ''">清除搜索</button>
      </template>
      <template v-else>
        <h2>还没有算法包</h2>
        <p>研究计划完成并发布后会出现在这里。</p>
        <button class="btn secondary small" @click="emit('navigate', 'notices')">查看研究通知</button>
      </template>
    </div>
  </section>
</template>
<style scoped>
.package-task-group > h2 {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  align-items: center;
}
.package-source {
  display: inline-flex;
  gap: 4px;
  align-items: center;
  padding: 0;
  border: 0;
  background: none;
  color: inherit;
  font: inherit;
  cursor: pointer;
}
.package-source:hover {
  color: var(--primary);
}
.package-data {
  color: var(--muted);
  font-size: 12px;
  font-weight: 400;
}
.package-data i {
  display: inline-block;
  width: 8px;
  height: 8px;
  margin-right: 5px;
  border-radius: 50%;
}
</style>
