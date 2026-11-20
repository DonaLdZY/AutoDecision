<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import Icon from './Icon.vue'
import {
  state,
  project,
  packages,
  tasks,
  selectProject,
  openDialog,
  importDemoData,
  navigate,
} from '../store'
const selectedTable = ref(0)
const tableMode = ref('preview')
const table = computed(() => project.value.tables[selectedTable.value] || project.value.tables[0])
watch(
  () => project.value.id,
  () => (selectedTable.value = 0),
)
</script>
<template>
  <div class="standard-page">
    <div class="page-heading">
      <div>
        <div class="eyebrow">DATA WORKSPACE</div>
        <h1>数据项目</h1>
      </div>
      <button class="btn primary" @click="openDialog('create-project')">
        <Icon name="plus" :size="16" />新建项目
      </button>
    </div>
    <div class="project-grid">
      <button
        v-for="p in state.projects"
        :key="p.id"
        class="project-card"
        :class="{ selected: p.id === state.projectId }"
        @click="selectProject(p.id)"
      >
        <div class="project-card-top">
          <span :class="['square-icon', p.color]"><Icon :name="p.icon" :size="23" /></span
          ><span v-if="p.id === state.projectId" class="tag success"
            ><Icon name="check" :size="12" />当前项目</span
          ><Icon v-else name="arrow" :size="16" />
        </div>
        <h2>{{ p.name }}</h2>
        <p>{{ p.description }}</p>
        <footer>
          <span><Icon name="table" :size="14" />{{ p.tables.length }} 张数据表</span
          ><span
            ><Icon name="package" :size="14" />{{
              state.packages.filter((k) => k.projectId === p.id).length
            }}
            个模型包</span
          >
        </footer>
      </button>
    </div>
    <div class="section-heading">
      <div>
        <h2>{{ project.name }}</h2>
        <p>
          数据快照 <code>{{ project.snapshot }}</code>
        </p>
      </div>
      <button class="btn secondary small" @click="importDemoData">
        <Icon name="upload" :size="15" />{{ project.tables.length ? '检查演示数据' : '添加演示数据' }}
      </button>
    </div>
    <div class="data-workbench" v-if="project.tables.length">
      <aside class="table-list">
        <div class="nav-label">项目数据表</div>
        <button
          v-for="(t, i) in project.tables"
          :key="t.name"
          :class="{ active: selectedTable === i }"
          @click="selectedTable = i"
        >
          <Icon name="table" :size="17" />
          <div>
            <strong>{{ t.title }}</strong
            ><small>{{ t.name }}</small>
          </div>
          <span>{{ t.columns.length }}</span>
        </button>
        <div class="data-connection">
          <Icon name="database" :size="18" />
          <div>
            <strong>本地示例数据源</strong>
            <p>合成数据 · 只读预览</p>
          </div>
          <i class="status-dot" />
        </div>
      </aside>
      <section v-if="table" class="data-table-panel">
        <div class="table-panel-heading">
          <div>
            <h3>{{ table.title }}</h3>
            <p>{{ table.rows }} 行（场景设定） · {{ table.columns.length }} 列 · {{ table.updated }}</p>
          </div>
          <span class="tag neutral">快照数据</span>
        </div>
        <div class="tabs">
          <button :class="{ active: tableMode === 'preview' }" @click="tableMode = 'preview'">数据预览</button
          ><button :class="{ active: tableMode === 'schema' }" @click="tableMode = 'schema'">
            字段与语义
          </button>
        </div>
        <div class="table-scroll">
          <table v-if="tableMode === 'preview'">
            <thead>
              <tr>
                <th class="row-number">#</th>
                <th v-for="col in table.columns" :key="col.name">
                  {{ col.name }}<small>{{ col.type }}</small>
                </th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(row, i) in table.preview" :key="i">
                <td class="row-number">{{ i + 1 }}</td>
                <td v-for="(v, j) in row" :key="j">{{ v }}</td>
              </tr>
            </tbody>
          </table>
          <table v-else>
            <thead>
              <tr>
                <th>字段</th>
                <th>类型</th>
                <th>单位</th>
                <th>业务含义</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="col in table.columns" :key="col.name">
                <td>
                  <code>{{ col.name }}</code>
                </td>
                <td>{{ col.type }}</td>
                <td>{{ col.unit }}</td>
                <td>{{ col.description }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <div class="table-footnote">
          显示 {{ table.preview.length }} 行合成预览；此演示未读取任何实际数据库或用户文件。
        </div>
      </section>
    </div>
    <div v-else class="empty-state">
      <Icon name="database" :size="36" />
      <h3>给这个项目添加第一份数据</h3>
      <p>此原型可以载入一组能源数据，体验需求到能力的完整流程。</p>
      <button class="btn primary" @click="importDemoData">添加演示数据</button>
    </div>
    <div class="project-summary">
      <div>
        <span class="square-icon"><Icon name="package" :size="21" /></span>
        <div>
          <h3>{{ packages.length }} 个可复用模型包</h3>
          <p>数据项目的每次研发，都会积累新的能力。</p>
        </div>
        <button class="text-btn" @click="navigate('packages')">
          查看能力<Icon name="arrow" :size="15" />
        </button>
      </div>
      <div>
        <span class="square-icon blue"><Icon name="branch" :size="21" /></span>
        <div>
          <h3>{{ tasks.length }} 个研发任务</h3>
          <p>从需求、候选算法到验证结果，全程可追溯。</p>
        </div>
        <button class="text-btn" @click="navigate('tasks')">查看任务<Icon name="arrow" :size="15" /></button>
      </div>
    </div>
  </div>
</template>
