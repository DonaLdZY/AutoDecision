<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from 'vue'
import Icon from '../components/Icon.vue'
import Modal from './Modal.vue'
import ConversationMenu from './ConversationMenu.vue'
import { date, navigate, request, selectProject, selectConversation, state, ui } from './store'
import { conversationHistory, conversationRevision, manageConversations } from './conversationManagement'
import type { ConversationSummary } from './conversationManagement'
const rows = ref<ConversationSummary[]>([]),
  loading = ref(true),
  error = ref(''),
  query = ref('')
const projectId = ref(ui.projectId),
  selected = ref(new Set<string>())
let sequence = 0
const projects = computed(() => [...state.projects, ...state.archived_projects])
const scoped = computed(() =>
  rows.value.filter((row) => !projectId.value || row.project_id === projectId.value),
)
const visible = computed(() =>
  scoped.value.filter(
    (row) =>
      row.archived === (conversationHistory.tab === 'archived') &&
      `${row.title} ${row.project_name}`.toLowerCase().includes(query.value.trim().toLowerCase()),
  ),
)
const picked = computed(() => rows.value.filter((row) => selected.value.has(row.id)))
const bulkHint = computed(() => {
  if (loading.value) return '正在读取对话，完成后才能管理。'
  if (!ui.online) return '本地服务未连接，请先重新连接。'
  if (!picked.value.length) return '先勾选要归档或删除的对话。历史消息不会因归档丢失。'
  return '已选择对话；删除不可恢复，归档可在“已归档”中还原。'
})
const allChecked = computed(
  () => visible.value.length > 0 && visible.value.every((row) => selected.value.has(row.id)),
)
function select(ids: string[], checked: boolean) {
  const next = new Set(selected.value)
  ids.forEach((id) => (checked ? next.add(id) : next.delete(id)))
  selected.value = next
}
async function load() {
  const current = ++sequence
  loading.value = true
  error.value = ''
  try {
    const value = await request<ConversationSummary[]>('/studio/conversations')
    if (current === sequence) {
      rows.value = value
      selected.value = new Set()
    }
  } catch (reason) {
    if (current === sequence) error.value = reason instanceof Error ? reason.message : String(reason)
  } finally {
    if (current === sequence) loading.value = false
  }
}
function open(row: ConversationSummary) {
  selectProject(row.project_id)
  selectConversation(row.id)
  conversationHistory.open = false
  navigate('chat')
}
watch(conversationRevision, load, { immediate: true })
watch([() => conversationHistory.tab, projectId], () => {
  selected.value = new Set()
})
onUnmounted(() => sequence++)
</script>
<template>
  <Modal class="conversation-history-modal" title="对话历史" @close="conversationHistory.open = false">
    <div class="conversation-history">
      <div class="live-tabs">
        <button
          :class="{ active: conversationHistory.tab === 'active' }"
          @click="conversationHistory.tab = 'active'"
        >
          全部对话 <span>{{ scoped.filter((row) => !row.archived).length }}</span>
        </button>
        <button
          :class="{ active: conversationHistory.tab === 'archived' }"
          @click="conversationHistory.tab = 'archived'"
        >
          已归档 <span>{{ scoped.filter((row) => row.archived).length }}</span>
        </button>
      </div>
      <div class="conversation-history-filters">
        <label class="live-search"
          ><Icon name="search" :size="16" /><input
            v-model="query"
            autofocus
            type="search"
            placeholder="搜索对话"
            aria-label="搜索对话"
        /></label>
        <select v-model="projectId" aria-label="筛选数据项目">
          <option value="">所有项目</option>
          <option v-for="p in projects" :key="p.id" :value="p.id">{{ p.name }}</option>
        </select>
      </div>
      <div class="conversation-bulk-bar">
        <label
          ><input
            type="checkbox"
            :checked="allChecked"
            :indeterminate="!allChecked && visible.some((row) => selected.has(row.id))"
            :disabled="!visible.length || loading || !!ui.busy"
            @change="
              select(
                visible.map((row) => row.id),
                ($event.target as HTMLInputElement).checked,
              )
            "
          />全选</label
        >
        <span>已选 {{ picked.length }}</span>
        <div class="storage-actions">
          <button
            class="btn secondary small"
            :disabled="!picked.length || !!ui.busy || !ui.online"
            :title="bulkHint"
            @click="
              manageConversations(conversationHistory.tab === 'archived' ? 'restore' : 'archive', picked)
            "
          >
            {{ conversationHistory.tab === 'archived' ? '还原' : '归档' }}
          </button>
          <button
            class="btn secondary small storage-delete"
            :disabled="!picked.length || !!ui.busy || !ui.online"
            :title="bulkHint"
            @click="manageConversations('delete', picked)"
          >
            删除
          </button>
        </div>
      </div>
      <p class="conversation-bulk-hint" :class="{ warning: !picked.length || !ui.online }">{{ bulkHint }}</p>
      <p v-if="error" class="live-error" role="alert">
        {{ error }} <button class="text-btn" @click="load">重试</button>
      </p>
      <p v-if="loading" role="status">正在读取对话…</p>
      <div v-else-if="!visible.length" class="conversation-history-empty">
        <Icon :name="conversationHistory.tab === 'archived' ? 'archive' : 'chat'" :size="28" />
        <p>
          {{
            query
              ? `没有匹配“${query}”的对话`
              : conversationHistory.tab === 'archived'
                ? '没有已归档对话'
                : '还没有对话'
          }}
        </p>
        <button v-if="query" type="button" class="btn secondary small" @click="query = ''">清除搜索，查看全部对话</button>
        <button v-else-if="conversationHistory.tab === 'archived'" type="button" class="btn secondary small" @click="conversationHistory.tab = 'active'">查看使用中对话</button>
      </div>
      <div v-else class="conversation-history-list">
        <article
          v-for="row in visible"
          :key="row.id"
          class="conversation-history-row"
          :data-conversation="row.id"
        >
          <input
            type="checkbox"
            :aria-label="`选择对话 ${row.title}`"
            :checked="selected.has(row.id)"
            :disabled="!!ui.busy"
            @change="select([row.id], ($event.target as HTMLInputElement).checked)"
          />
          <button
            class="conversation-history-copy"
            :disabled="row.archived"
            :title="row.title"
            @click="open(row)"
          >
            <strong>{{ row.title }}</strong
            ><span>{{ row.project_name }} · {{ row.message_count }} 条消息 · {{ date(row.updated_at) }}</span>
          </button>
          <span v-if="row.busy" class="tag info">进行中</span
          ><span v-else-if="row.inherited_archive" class="tag neutral">项目已归档</span>
          <ConversationMenu :item="row" />
        </article>
      </div>
    </div>
  </Modal>
</template>
