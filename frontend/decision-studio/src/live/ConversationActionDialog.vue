<script setup lang="ts">
import { onMounted, ref } from 'vue'
import Modal from './Modal.vue'
import { chatDrafts, refresh, request, state, toast, ui } from './store'
import { conversationAction, conversationActionLabels, conversationRevision } from './conversationManagement'
import type { ConversationPreview } from './conversationManagement'
const action = conversationAction.action,
  items = [...conversationAction.items],
  ids = items.map((item) => item.id)
const name = ref(items[0]?.title || ''),
  preview = ref<ConversationPreview>(),
  loading = ref(action !== 'rename')
const applying = ref(false),
  error = ref('')
function close() {
  if (!applying.value) conversationAction.items = []
}
async function load() {
  loading.value = true
  error.value = ''
  try {
    preview.value = await request('/studio/conversations/preview', { ids, action })
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : String(reason)
  } finally {
    loading.value = false
  }
}
onMounted(() => {
  if (action !== 'rename') void load()
})
async function apply() {
  if (
    applying.value ||
    ui.busy ||
    (action === 'rename' ? !name.value.trim() : !preview.value?.confirmation_token)
  )
    return
  applying.value = true
  ui.busy = 'manage-conversations'
  error.value = ''
  try {
    if (action === 'rename')
      await request(
        `/studio/conversations/${encodeURIComponent(ids[0]!)}`,
        { title: name.value.trim() },
        'PATCH',
      )
    else
      await request('/studio/conversations/manage', {
        ids,
        action,
        confirm: true,
        confirmation_token: preview.value!.confirmation_token,
      })
    if (action === 'delete') ids.forEach((id) => delete chatDrafts[id])
    if (action === 'delete' || action === 'archive') {
      state.conversations = state.conversations.filter((item) => !ids.includes(item.id))
      if (ids.includes(ui.conversationId)) {
        ui.conversationId = ''
        ui.packageId = ''
      }
    }
    await refresh()
    conversationRevision.value++
    conversationAction.items = []
    toast(`已${conversationActionLabels[action]}`)
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : String(reason)
    if (action !== 'rename') preview.value = undefined
  } finally {
    applying.value = false
    ui.busy = ''
  }
}
</script>
<template>
  <Modal
    class="conversation-action-modal"
    :title="action === 'rename' ? '重命名对话' : `${conversationActionLabels[action]}对话`"
    :locked="applying"
    @close="close"
  >
    <form class="conversation-confirm" @submit.prevent="apply">
      <label v-if="action === 'rename'" class="conversation-name-label"
        >对话名称<input v-model="name" autofocus required maxlength="120" :disabled="applying"
      /></label>
      <template v-else>
        <p v-if="action === 'archive'">
          归档后，对话会从标签页和使用中的对话列表隐藏，全部消息保留。可在「对话历史 → 已归档」中还原。
        </p>
        <p v-else-if="action === 'delete'">
          将永久删除所选对话及全部消息，无法还原。数据文件夹、研发任务、代码包和独立的调用记录仍保留。
        </p>
        <p v-else>还原后，对话将重新出现在所属项目的对话标签页，历史消息完整保留。</p>
        <p v-if="loading" role="status">正在核对对话…</p>
        <template v-if="preview">
          <div class="conversation-confirm-total">
            {{ preview.conversations.length }} 个对话 · {{ preview.message_count }} 条消息
          </div>
          <ul class="conversation-confirm-titles">
            <li v-for="item in preview.conversations" :key="item.id">{{ item.title }}</li>
          </ul>
          <ul v-if="preview.blockers.length" class="storage-blockers" role="alert">
            <li v-for="blocker in preview.blockers" :key="blocker">{{ blocker }}</li>
          </ul>
        </template>
      </template>
      <p v-if="error" class="live-error" role="alert">{{ error }}</p>
      <div class="form-actions">
        <button type="button" class="btn secondary" :disabled="applying" @click="close">取消</button>
        <button
          v-if="action !== 'rename' && !preview && !loading"
          type="button"
          class="btn secondary"
          :disabled="applying"
          @click="load"
        >
          重新核对
        </button>
        <button
          type="submit"
          class="btn"
          :class="action === 'delete' ? 'storage-danger' : 'primary'"
          :disabled="
            applying ||
            !!ui.busy ||
            loading ||
            (action === 'rename' ? !name.trim() : !preview?.confirmation_token)
          "
        >
          {{
            applying ? '处理中…' : action === 'rename' ? '保存' : `确认${conversationActionLabels[action]}`
          }}
        </button>
      </div>
    </form>
  </Modal>
</template>
