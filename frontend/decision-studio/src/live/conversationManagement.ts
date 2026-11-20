import { reactive, ref } from 'vue'

export type ConversationAction = 'archive' | 'restore' | 'delete' | 'rename'
export interface ConversationRef {
  id: string
  title: string
  archived?: boolean
}
export interface ConversationSummary extends ConversationRef {
  project_id: string
  project_name: string
  message_count: number
  created_at: number
  updated_at: number
  archived: boolean
  inherited_archive: boolean
  busy: boolean
}
export interface ConversationPreview {
  conversations: ConversationSummary[]
  message_count: number
  invocation_count: number
  blockers: string[]
  confirmation_token: string
}
export const conversationRevision = ref(0)
export const conversationHistory = reactive({ open: false, tab: 'active' as 'active' | 'archived' })
export const conversationAction = reactive<{ action: ConversationAction; items: ConversationRef[] }>({
  action: 'archive',
  items: [],
})
export const conversationActionLabels = { archive: '归档', restore: '还原', delete: '删除', rename: '重命名' }
export function openConversationHistory(tab: 'active' | 'archived' = 'active') {
  conversationHistory.tab = tab
  conversationHistory.open = true
}
export function manageConversations(action: ConversationAction, items: ConversationRef[]) {
  conversationAction.action = action
  conversationAction.items = items.map((item) => ({
    id: item.id,
    title: item.title,
    archived: item.archived,
  }))
}
