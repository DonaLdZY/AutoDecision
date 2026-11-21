<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import Icon from '../components/Icon.vue'
import Chat from './Chat.vue'
import ConversationHistory from './ConversationHistory.vue'
import ConversationActionDialog from './ConversationActionDialog.vue'
import { conversationAction, conversationHistory, openConversationHistory } from './conversationManagement'
import Projects from './Projects.vue'
import Packages from './Packages.vue'
import Tasks from './Tasks.vue'
import Settings from './Settings.vue'
import Storage from './Storage.vue'
import StorageActionDialog from './StorageActionDialog.vue'
import { storageDialog, storageRevision } from './storage'
import InvocationDetail from './InvocationDetail.vue'
import TaskDetail from './TaskDetail.vue'
import PackageDetail from './PackageDetail.vue'
import Modal from './Modal.vue'
import ResearchForm from './ResearchForm.vue'
import Notices from './Notices.vue'
import NewConversation from './NewConversation.vue'
import { unreadNotices } from './notices'
import { formatDuration } from './presentation'
import {
  state,
  ui,
  invocations,
  tasks,
  conversations,
  selectConversation,
  openNewConversation,
  unassigned,
  request,
  refresh,
  run,
  navigate,
  status,
  date,
  phase,
} from './store'
import './live.css'
import './product.css'
import './storage.css'
import './conversations.css'
const nav = [
  { id: 'projects', label: '项目数据', icon: 'database' },
  { id: 'tasks', label: '研究计划', icon: 'branch' },
  { id: 'packages', label: '算法包', icon: 'package' },
  { id: 'chat', label: '对话', icon: 'chat' },
  { id: 'invocations', label: '调用记录', icon: 'history' },
  { id: 'storage', label: '本地存储', icon: 'folder' },
]
const title = computed(() =>
  ui.page === 'notices' ? '研究通知' : nav.find((n) => n.id === ui.page)?.label || '工作空间设置',
)
const hasActiveWork = computed(
  () =>
    state.tasks.some((task) => task.status === 'running') ||
    state.invocations.some((invocation) => invocation.status === 'running'),
)
// 侧栏「对话」：按项目数据分文件夹，最近活跃的文件夹和对话排在前面；折叠状态记在本机。
const FOLDER_LIMIT = 6
const collapsed = ref(new Set<string>(JSON.parse(localStorage.getItem('studio.chat.collapsed') || '[]') as string[]))
const activity = (c: { created_at?: number; updated_at?: number }) => c.updated_at || c.created_at || 0
const chatFolders = computed(() =>
  state.projects
    .map((p) => {
      const items = conversations.value.filter((c) => c.project_id === p.id).sort((a, b) => activity(b) - activity(a))
      return { project: p, items, latest: items.length ? activity(items[0]!) : 0 }
    })
    .filter((folder) => folder.items.length)
    .sort((a, b) => b.latest - a.latest),
)
function toggleFolder(id: string) {
  const next = new Set(collapsed.value)
  if (next.has(id)) next.delete(id)
  else next.add(id)
  collapsed.value = next
  localStorage.setItem('studio.chat.collapsed', JSON.stringify([...next]))
}
function openChat(id: string) {
  selectConversation(id)
  navigate('chat')
}
function onShortcut(event: KeyboardEvent) {
  if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k' && state.projects.length) {
    event.preventDefault()
    openNewConversation()
  }
}
const detail = ref<{ kind: string; id: string } | null>(null)
watch(storageRevision, () => {
  detail.value = null
})
const taskTab = ref(0)
const help = ref(false)
const researchOpen = ref(false)
const navigation = ref<HTMLElement>()
const navigationToggle = ref<HTMLButtonElement>()
const mobileQuery = window.matchMedia('(max-width: 760px)')
const mobileViewport = ref(mobileQuery.matches)
function closeNavigation() {
  ui.mobile = false
}
function showHelp() {
  closeNavigation()
  help.value = true
}
function onViewportChange(event: MediaQueryListEvent) {
  mobileViewport.value = event.matches
  if (!event.matches) closeNavigation()
}
function onNavigationKeydown(event: KeyboardEvent) {
  if (!mobileViewport.value || !ui.mobile) return
  if (event.key === 'Escape') {
    event.preventDefault()
    closeNavigation()
  } else if (event.key === 'Tab') {
    const elements = Array.from(
      navigation.value?.querySelectorAll<HTMLElement>(
        'a[href], button:not([disabled]), select:not([disabled]), [tabindex="0"]',
      ) || [],
    ).filter((element) => element.getClientRects().length && element.tabIndex >= 0)
    const first = elements[0],
      last = elements[elements.length - 1]
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault()
      last?.focus()
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault()
      first?.focus()
    }
  }
}
watch(
  () => ui.mobile,
  async (open, wasOpen) => {
    await nextTick()
    if (!mobileViewport.value) return
    if (open) navigation.value?.querySelector<HTMLElement>('.main-nav button')?.focus()
    else if (wasOpen) navigationToggle.value?.focus()
  },
)
function open(kind: string, id: string) {
  if (kind === 'research') {
    researchOpen.value = true
    return
  }
  if (kind === 'conversation') {
    openChat(id)
    return
  }
  // report：直达研究结论；有结论页时任务详情默认打开它，没有就打开工作汇报（第 5 个标签）。
  taskTab.value = kind === 'delivery' ? 3 : kind === 'report' && !state.research_briefs?.[id] ? 4 : 0
  detail.value = { kind: kind === 'delivery' || kind === 'report' ? 'task' : kind, id }
}
function navigateFromDetail(page: string) {
  detail.value = null
  navigate(page)
}
let timer: ReturnType<typeof setTimeout> | undefined,
  disposed = false,
  polling = false
function clearPoll() {
  if (timer) clearTimeout(timer)
  timer = undefined
}
function schedulePoll(delay = 5000) {
  clearPoll()
  if (!disposed && !document.hidden && hasActiveWork.value) timer = setTimeout(poll, delay)
}
async function poll() {
  clearPoll()
  if (disposed || polling || !hasActiveWork.value) return
  polling = true
  try {
    if (!document.hidden) await refresh(true)
  } finally {
    polling = false
    schedulePoll()
  }
}
function onVisibilityChange() {
  if (document.hidden) clearPoll()
  else if (hasActiveWork.value) void poll()
}
onMounted(async () => {
  disposed = false
  mobileQuery.addEventListener('change', onViewportChange)
  window.addEventListener('keydown', onShortcut)
  document.addEventListener('visibilitychange', onVisibilityChange)
  await refresh()
  if (hasActiveWork.value) schedulePoll()
})
onUnmounted(() => {
  disposed = true
  clearPoll()
  mobileQuery.removeEventListener('change', onViewportChange)
  window.removeEventListener('keydown', onShortcut)
  document.removeEventListener('visibilitychange', onVisibilityChange)
})
watch(hasActiveWork, (active) => {
  if (active && !document.hidden) void poll()
  else clearPoll()
})
watch(
  () => ui.page,
  () => (detail.value = null),
)
async function importTasks() {
  await run('import', async () => {
    await request('/studio/import-tasks', { task_ids: unassigned.value.map((t) => t.id) })
    await refresh()
    navigate('projects')
  })
}
</script>
<template>
  <div class="studio-shell live-studio" style="--project-color: #386bfa">
    <button
      v-if="ui.mobile && mobileViewport"
      class="nav-backdrop"
      tabindex="-1"
      aria-label="关闭导航"
      @click="closeNavigation"
    />
    <aside
      ref="navigation"
      id="studio-navigation"
      class="sidebar"
      :class="{ open: ui.mobile }"
      :inert="mobileViewport && !ui.mobile"
      :aria-hidden="mobileViewport && !ui.mobile ? true : undefined"
      aria-label="主导航"
      @keydown="onNavigationKeydown"
    >
      <a class="brand" href="#projects" @click="closeNavigation"
        ><img src="/favicon.svg" alt="" /><span>AutoDecision<small>DECISION WORKSPACE</small></span></a
      >
      <button
        class="sidebar-project-context sidebar-notices"
        :class="{ active: ui.page === 'notices' }"
        @click="navigate('notices')"
      >
        <Icon name="bell" :size="18" />
        <span><strong>研究通知</strong></span>
        <span v-if="unreadNotices" class="nav-count">{{ unreadNotices }}</span>
        <Icon name="right" :size="15" />
      </button>
      <button class="new-chat" :disabled="!state.projects.length" @click="openNewConversation()">
        <Icon name="plus" :size="18" /><span>新建对话</span><kbd>⌘ K</kbd>
      </button>
      <div class="nav-label">工作空间</div>
      <nav class="main-nav">
        <button
          v-for="n in nav.slice(0, 3)"
          :key="n.id"
          :class="{ active: ui.page === n.id }"
          @click="navigate(n.id)"
        >
          <Icon :name="n.icon" /><span>{{ n.label }}</span>
          <span v-if="n.id === 'tasks' && tasks.some((t) => t.status === 'running')" class="nav-count">{{
            tasks.filter((t) => t.status === 'running').length
          }}</span>
        </button>
      </nav>
      <div class="recent-section chat-folders">
        <div class="nav-label chat-folders-label">
          对话<button class="icon-btn" aria-label="对话历史" title="对话历史" @click="openConversationHistory()">
            <Icon name="history" :size="13" />
          </button>
        </div>
        <p v-if="!chatFolders.length" class="chat-folders-empty">还没有对话</p>
        <div v-for="folder in chatFolders" :key="folder.project.id" class="chat-folder">
          <div class="chat-folder-head">
            <button
              class="chat-folder-toggle"
              :aria-expanded="!collapsed.has(folder.project.id)"
              @click="toggleFolder(folder.project.id)"
            >
              <Icon name="chevron" :size="12" :class="{ folded: collapsed.has(folder.project.id) }" /><Icon
                name="folder"
                :size="14"
              /><span>{{ folder.project.name }}</span>
            </button>
            <button
              class="icon-btn"
              :aria-label="`在 ${folder.project.name} 下新建对话`"
              :title="`在 ${folder.project.name} 下新建对话`"
              @click="openNewConversation(folder.project.id)"
            >
              <Icon name="plus" :size="13" />
            </button>
          </div>
          <template v-if="!collapsed.has(folder.project.id)">
            <button
              v-for="c in folder.items.slice(0, FOLDER_LIMIT)"
              :key="c.id"
              class="recent-item chat-folder-item"
              :class="{ selected: c.id === ui.conversationId && ui.page === 'chat' }"
              @click="openChat(c.id)"
            >
              <Icon name="chat" :size="14" /><span>{{ c.title || '新的对话' }}</span>
            </button>
            <button
              v-if="folder.items.length > FOLDER_LIMIT"
              class="recent-item chat-folder-item chat-folder-more"
              @click="openConversationHistory()"
            >
              <span>全部 {{ folder.items.length }} 个对话</span>
            </button>
          </template>
        </div>
      </div>
      <div class="sidebar-bottom">
        <nav class="workspace-utilities" aria-label="工作空间工具">
          <button
            v-for="n in nav.slice(4)"
            :key="n.id"
            :class="{ active: ui.page === n.id }"
            @click="navigate(n.id)"
          >
            <Icon :name="n.icon" :size="16" /><span>{{ n.label }}</span>
          </button>
        </nav>
        <div class="local-status">
          <div>
            <i class="status-dot" :class="{ offline: !ui.online }" /><strong>{{
              ui.online ? '本地服务已连接' : '本地服务未连接'
            }}</strong>
          </div>
        </div>
        <button
          class="settings-nav"
          :class="{ active: ui.page === 'settings' }"
          @click="navigate('settings')"
        >
          <Icon name="settings" /><span>设置</span><span class="version">v{{ state.version }}</span>
        </button>
        <div class="profile">
          <div class="avatar user-avatar">D</div>
          <div><strong>我的工作空间</strong><span>本地部署</span></div>
          <button class="icon-btn" aria-label="使用说明" @click="showHelp">
            <Icon name="help" />
          </button>
        </div>
      </div>
    </aside>
    <div class="workspace-main" :inert="mobileViewport && ui.mobile">
      <header class="topbar">
        <div class="breadcrumb">
          <button
            ref="navigationToggle"
            class="icon-btn mobile-toggle"
            aria-label="打开导航"
            aria-controls="studio-navigation"
            :aria-expanded="ui.mobile"
            @click="ui.mobile = true"
          >
            <Icon name="menu" /></button
          ><Icon :name="ui.page === 'notices' ? 'bell' : nav.find((n) => n.id === ui.page)?.icon || 'settings'" /><span>工作空间</span
          ><span class="slash">/</span><strong>{{ title }}</strong>
        </div>
        <div class="topbar-actions">
          <span class="tag" :class="ui.online ? 'success' : 'warning'">{{
            ui.online ? '已连接' : '离线'
          }}</span
          ><button class="icon-btn" aria-label="刷新工作空间" @click="refresh()">
            <Icon name="refresh" />
          </button>
        </div>
      </header>
      <div v-if="ui.error" class="live-error" role="alert">
        {{ ui.error
        }}<button @click="ui.error = ''" aria-label="关闭错误提示"><Icon name="x" :size="16" /></button>
      </div>
      <div v-if="!ui.online && ui.loaded" class="live-banner">
        本地服务未连接，请运行启动程序。<button class="text-btn" @click="refresh()">重新连接</button
        ><button class="text-btn" @click="navigate('settings')">设置</button>
      </div>
      <div v-if="unassigned.length" class="live-banner">
        发现 {{ unassigned.length }} 个尚未归属项目的已有任务。<button
          class="text-btn"
          :disabled="!!ui.busy"
          @click="importTasks"
        >
          导入已有任务
        </button>
      </div>

      <main class="main-content" :class="{ 'chat-main': ui.page === 'chat' }">
        <Notices v-if="ui.page === 'notices'" @open="open" /><Chat
          v-else-if="ui.page === 'chat'"
          @open="open"
        /><Projects
          v-else-if="ui.page === 'projects'"
        /><Packages v-else-if="ui.page === 'packages'" @open="open" @navigate="navigate" /><Tasks
          v-else-if="ui.page === 'tasks'"
          @open="open"
          @navigate="navigate"
        />
        <section v-else-if="ui.page === 'invocations'" class="live-page">
          <div class="page-heading">
            <div>
              <h1>调用记录</h1>
            </div>
          </div>
          <div v-if="!invocations.length" class="live-empty">
            <Icon name="history" :size="28" />
            <h2>还没有调用记录</h2>
            <p>从对话或算法包详情发起一次调用。</p>
            <button class="btn primary small" @click="navigate('packages')">查看可用算法包</button>
          </div>
          <button
            v-for="i in invocations"
            :key="i.id"
            class="live-list-row"
            @click="open('invocation', i.id)"
          >
            <span class="square-icon"><Icon name="workflow" /></span>
            <div>
              <h3>{{ i.title }}</h3>
              <p>{{ date(i.created_at) }} · {{ i.package_ids.length }} 个算法包</p>
            </div>
            <span class="tag" :class="i.status === 'completed' ? 'success' : 'warning'">{{
              status(i.status)
            }}</span
            ><span>{{ i.duration_seconds == null ? '执行中' : formatDuration(i.duration_seconds) }}</span
            ><Icon name="right" />
          </button>
        </section>
        <Storage v-else-if="ui.page === 'storage'" />
        <Settings v-else />
      </main>
    </div>
    <Modal
      v-if="detail"
      :title="detail.kind === 'task' ? '研究计划' : detail.kind === 'package' ? '算法包' : '调用详情'"
      wide
      @close="detail = null"
      ><TaskDetail
        v-if="detail.kind === 'task'"
        :key="detail.id"
        :id="detail.id"
        :initial-tab="taskTab"
        @open="open"
        @navigate="navigateFromDetail" /><PackageDetail
        :key="detail.id"
        v-else-if="detail.kind === 'package'"
        :id="detail.id"
        @open="open" /><InvocationDetail v-else :key="detail.id" :id="detail.id" @open="open" @navigate="navigateFromDetail"
    /></Modal>
    <StorageActionDialog
      v-if="storageDialog.resources.length"
      :key="storageDialog.action + JSON.stringify(storageDialog.resources)"
    />
    <ConversationHistory v-if="conversationHistory.open" />
    <Modal v-if="ui.newChat" title="新建对话" @close="ui.newChat = false"><NewConversation /></Modal>
    <ConversationActionDialog
      v-if="conversationAction.items.length"
      :key="conversationAction.action + JSON.stringify(conversationAction.items)"
    />
    <Modal v-if="researchOpen" title="新建研究计划" @close="researchOpen = false">
      <ResearchForm
        @done="
          (id) => {
            researchOpen = false
            open('task', id)
          }
        "
      />
    </Modal>
    <Modal v-if="help" title="关于决策工作台" @close="help = false"
      ><div class="simple-dialog">
        <h2>关于 AutoDecision</h2>
        <p>
          创建或导入数据项目 → 对话提出需求 → 检查能力与输入 →
          调用已发布模型；能力不足时新建研究计划，完成后审核发布。
        </p>
        <p>
          关闭浏览器不会停止研究计划。远程 LLM
          会接收规划所需的项目说明、能力卡、目录表头与最近消息；推理在本机运行。
        </p>
        <p>完成、发布与业务达标分别记录。组合计划需要核对每一步实际输入输出。</p>
        <a class="btn secondary" href="/?demo=1#chat">打开独立演示模式</a>
      </div></Modal
    >
    <div v-if="ui.toast" class="toast-message" role="status"><Icon name="checkCircle" />{{ ui.toast }}</div>
  </div>
</template>
