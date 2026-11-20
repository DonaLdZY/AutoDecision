<script setup lang="ts">
import { computed, ref } from 'vue'
import Icon from '../components/Icon.vue'
import Modal from './Modal.vue'
import ResourceStorage from './ResourceStorage.vue'
import Storage from './Storage.vue'
import { state, ui, request, refresh, run, toast } from './store'
import { projectDescription } from './presentation'
// 项目数据只做数据管理：点开某个项目时在下方查看它的数据文件，不再切换全局项目。
const opened = ref(state.projects[0]?.id || '')
const openedProject = computed(() => state.projects.find((p) => p.id === opened.value) || state.projects[0])
const create = ref(false),
  name = ref(''),
  root = ref(''),
  description = ref('')
async function save() {
  await run('project', async () => {
    const p = await request('/studio/projects', {
      name: name.value,
      input_root: root.value,
      description: description.value,
    })
    await refresh()
    opened.value = p.id
    create.value = false
    toast('本地数据项目已创建')
  })
}
async function pick() {
  await run('directory', async () => {
    const r = await request('/fs/pick-directory', { initial_path: root.value, title: '选择项目数据目录' })
    if (r.ok) root.value = r.path
    else toast('未选择目录，可直接填写绝对路径')
  })
}
</script>
<template>
  <section class="live-page">
    <div class="page-heading">
      <div>
        <h1>项目数据</h1>
      </div>
      <button class="btn primary" :disabled="!ui.online" @click="create = true">
        <Icon name="plus" />导入项目数据
      </button>
    </div>
    <div class="live-grid three">
      <article
        v-for="p in state.projects"
        :key="p.id"
        class="live-panel project-tile"
        :class="{ chosen: p.id === openedProject?.id }"
        :style="{ '--project-color': p.color }"
        :data-project="p.id"
      >
        <button
          class="project-select"
          :aria-label="`查看项目数据 ${p.name}`"
          :aria-pressed="p.id === openedProject?.id"
          @click="opened = p.id"
        >
          <span class="square-icon project-color-mark"><Icon name="database" /></span>
          <div class="project-select-copy">
            <h3>{{ p.name }}</h3>

          </div>
          <p>{{ projectDescription(p.description) }}</p>
          <span class="tag neutral"
            >{{
              state.links.filter((l) => l.project_id === p.id && state.tasks.some((t) => t.id === l.id))
                .length
            }}
            个研究计划</span
          >
        </button>
        <ResourceStorage kind="projects" :id="p.id" />
      </article>
    </div>
    <div v-if="!state.projects.length" class="live-empty">
      <Icon name="database" :size="32" />
      <h2>连接第一个数据目录</h2>
      <p>原始文件保留在本机目录中。</p>
    </div>
    <Storage v-if="openedProject" :key="openedProject.id" :project-id="openedProject.id" embedded />
    <details v-if="state.archived_projects.length" class="live-panel archived-projects">
      <summary>已归档项目（{{ state.archived_projects.length }}）</summary>
      <div v-for="p in state.archived_projects" :key="p.id" class="panel-heading">
        <div>
          <h3><span class="archived-project-dot" :style="{ background: p.color }" />{{ p.name }}</h3>
          <ResourceStorage kind="projects" :id="p.id" />
        </div>
      </div>
    </details>
    <Modal v-if="create" title="导入项目数据" @close="create = false"
      ><form class="live-form" @submit.prevent="save">
        <label>项目名称<input v-model="name" required maxlength="120" /></label
        ><label
          >数据目录（本机绝对路径）<input v-model="root" required placeholder="D:\Data\my-project" /></label
        ><button type="button" class="btn secondary small" :disabled="!!ui.busy" @click="pick">
          选择本机目录</button
        ><label
          >项目说明<textarea v-model="description" rows="3" placeholder="业务范围、数据含义和决策目标" />
        </label>
        <p class="hint">该目录会作为新任务输入源。数据表内容不会因创建项目发送到模型。</p>
        <button class="btn primary" :disabled="!!ui.busy">导入</button>
      </form></Modal
    >
  </section>
</template>
