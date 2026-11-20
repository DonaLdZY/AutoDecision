<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import Icon from './components/Icon.vue'
import ChatView from './components/ChatView.vue'
import ProjectsView from './components/ProjectsView.vue'
import PackagesView from './components/PackagesView.vue'
import TasksView from './components/TasksView.vue'
import InvocationsView from './components/InvocationsView.vue'
import SettingsView from './components/SettingsView.vue'
import DetailDialog from './components/DetailDialog.vue'
import {
  state,
  ui,
  project,
  conversations,
  runningCount,
  navigate,
  newConversation,
  selectProject,
  selectConversation,
  openDialog,
} from './store'
import type { Page } from './types'
const nav: { id: Page; label: string; icon: string }[] = [
  { id: 'chat', label: '决策对话', icon: 'chat' },
  { id: 'projects', label: '数据项目', icon: 'database' },
  { id: 'packages', label: '算法模型包', icon: 'package' },
  { id: 'tasks', label: '研发任务', icon: 'branch' },
  { id: 'invocations', label: '调用记录', icon: 'history' },
]
const currentTitle = computed(() => nav.find((n) => n.id === ui.page)?.label || '工作空间设置')
const shortcut = (event: KeyboardEvent) => {
  if ((event.metaKey || event.ctrlKey) && event.key === 'k') {
    event.preventDefault()
    newConversation()
  }
  if (event.key === 'Escape') ui.mobileNav = false
}
const mainEl = ref<HTMLElement>()
watch(
  () => ui.page,
  () => mainEl.value?.scrollTo({ top: 0 }),
)
onMounted(() => window.addEventListener('keydown', shortcut))
onUnmounted(() => window.removeEventListener('keydown', shortcut))
</script>
<template>
  <div class="studio-shell">
    <button v-if="ui.mobileNav" class="nav-backdrop" aria-label="关闭导航" @click="ui.mobileNav = false" />
    <aside class="sidebar" :class="{ open: ui.mobileNav }">
      <a class="brand" href="#chat" @click.prevent="navigate('chat')"
        ><img src="/favicon.svg" alt="" /><span>AutoDecision<small>DECISION WORKSPACE</small></span></a
      >
      <div class="workspace-picker">
        <span class="workspace-icon"><Icon :name="project.icon" :size="19" /></span
        ><label class="sr-only" for="project-switch">当前数据项目</label
        ><select
          id="project-switch"
          :value="state.projectId"
          @change="selectProject(($event.target as HTMLSelectElement).value)"
        >
          <option v-for="p in state.projects" :key="p.id" :value="p.id">{{ p.name }}</option></select
        ><Icon name="chevron" :size="14" />
      </div>
      <button class="new-chat" @click="newConversation">
        <Icon name="plus" :size="18" /><span>新建对话</span><kbd>⌘ K</kbd>
      </button>
      <div class="nav-label">工作空间</div>
      <nav class="main-nav" aria-label="主导航">
        <button
          v-for="n in nav"
          :key="n.id"
          :class="{ active: ui.page === n.id }"
          :aria-current="ui.page === n.id ? 'page' : undefined"
          @click="navigate(n.id)"
        >
          <Icon :name="n.icon" /><span>{{ n.label }}</span
          ><span v-if="n.id === 'tasks' && runningCount" class="nav-count">{{ runningCount }}</span
          ><span v-if="n.id === 'chat' && ui.page === 'chat'" class="nav-active-dot" />
        </button>
      </nav>
      <div class="recent-section">
        <div class="nav-label">最近对话 <Icon name="history" :size="13" /></div>
        <button
          v-for="c in conversations.slice(0, 5)"
          :key="c.id"
          class="recent-item"
          :class="{ selected: c.id === state.conversationId && ui.page === 'chat' }"
          @click="selectConversation(c.id)"
        >
          <Icon name="chat" :size="14" /><span>{{ c.title }}</span>
        </button>
      </div>
      <div class="sidebar-bottom">
        <div class="local-status">
          <div><i class="status-dot" /><strong>本地工作空间</strong><span>DEMO</span></div>
          <p>数据与模型，留在你的环境中</p>
          <div class="resource-mini">
            <span><Icon name="cpu" :size="13" /> CPU {{ state.settings.cpu }} 核</span
            ><span>{{ state.settings.memory }} GB</span>
          </div>
        </div>
        <button
          class="settings-nav"
          :class="{ active: ui.page === 'settings' }"
          @click="navigate('settings')"
        >
          <Icon name="settings" /><span>设置</span><span class="version">v0.1.0</span>
        </button>
        <div class="profile">
          <div class="avatar user-avatar">D</div>
          <div><strong>我的工作空间</strong><span>本地管理员</span></div>
          <button class="icon-btn" aria-label="查看演示说明" @click="openDialog('help')">
            <Icon name="help" :size="17" />
          </button>
        </div>
      </div>
    </aside>
    <div class="workspace-main">
      <header class="topbar">
        <div class="breadcrumb">
          <button class="icon-btn mobile-toggle" aria-label="打开导航" @click="ui.mobileNav = true">
            <Icon name="menu" /></button
          ><Icon :name="nav.find((n) => n.id === ui.page)?.icon || 'settings'" :size="17" /><span
            >工作空间</span
          ><span class="slash">/</span><strong>{{ currentTitle }}</strong>
        </div>
        <div class="topbar-actions">
          <span class="demo-badge"><span />交互演示 · 模拟数据</span
          ><button class="icon-btn" aria-label="使用说明" @click="openDialog('help')">
            <Icon name="help" /></button
          ><span class="top-avatar">D</span>
        </div>
      </header>
      <main ref="mainEl" class="main-content" :class="{ 'chat-main': ui.page === 'chat' }">
        <ChatView v-if="ui.page === 'chat'" /><ProjectsView v-else-if="ui.page === 'projects'" /><PackagesView
          v-else-if="ui.page === 'packages'"
        /><TasksView v-else-if="ui.page === 'tasks'" /><InvocationsView
          v-else-if="ui.page === 'invocations'"
        /><SettingsView v-else />
      </main>
    </div>
    <DetailDialog v-if="ui.dialog" />
    <Transition name="toast"
      ><div v-if="ui.toast" class="toast-message" role="status">
        <Icon name="checkCircle" :size="18" />{{ ui.toast }}
      </div></Transition
    >
  </div>
</template>
