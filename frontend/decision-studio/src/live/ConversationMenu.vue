<script setup lang="ts">
import { nextTick, onUnmounted, ref, useId } from 'vue'
import Icon from '../components/Icon.vue'
import { ui } from './store'
import { manageConversations } from './conversationManagement'
import type { ConversationAction, ConversationRef } from './conversationManagement'
const props = defineProps<{ item: ConversationRef; label?: string }>()
const trigger = ref<HTMLButtonElement>(),
  menu = ref<HTMLElement>(),
  opened = ref(false)
const menuId = useId()
async function toggle() {
  if (!menu.value || !trigger.value) return
  if (menu.value.matches(':popover-open')) {
    menu.value.hidePopover()
    return
  }
  const rect = trigger.value.getBoundingClientRect()
  menu.value.style.left = `${Math.max(8, Math.min(rect.right - 176, window.innerWidth - 184))}px`
  menu.value.style.top = `${Math.max(8, Math.min(rect.bottom + 6, window.innerHeight - 156))}px`
  menu.value.showPopover()
  await nextTick()
  menu.value.querySelector<HTMLButtonElement>('button')?.focus()
}
function choose(action: ConversationAction) {
  menu.value?.hidePopover()
  trigger.value?.focus()
  // A dialog belongs to the workspace, outside the mobile navigation focus trap.
  ui.mobile = false
  manageConversations(action, [props.item])
}
function keys(event: KeyboardEvent) {
  const buttons = Array.from(menu.value?.querySelectorAll<HTMLButtonElement>('button') || [])
  const index = buttons.indexOf(document.activeElement as HTMLButtonElement)
  if (['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) {
    event.preventDefault()
    const next =
      event.key === 'Home'
        ? 0
        : event.key === 'End'
          ? buttons.length - 1
          : (index + (event.key === 'ArrowDown' ? 1 : -1) + buttons.length) % buttons.length
    buttons[next]?.focus()
  } else if (event.key === 'Tab') menu.value?.hidePopover()
  else if (event.key === 'Escape') {
    event.preventDefault()
    event.stopPropagation()
    menu.value?.hidePopover()
    trigger.value?.focus()
  }
}
onUnmounted(() => menu.value?.hidePopover())
</script>
<template>
  <button
    ref="trigger"
    class="icon-btn conversation-menu-trigger"
    :aria-label="label || `对话操作：${item.title}`"
    aria-haspopup="menu"
    :aria-controls="menuId"
    :aria-expanded="opened"
    :disabled="!!ui.busy || !ui.online"
    @click.stop="toggle"
    @keydown.down.prevent="toggle"
  >
    <Icon name="dots" :size="18" />
  </button>
  <div
    ref="menu"
    :id="menuId"
    popover="auto"
    class="conversation-menu"
    role="menu"
    :aria-label="`对话操作：${item.title}`"
    @toggle="opened = ($event as ToggleEvent).newState === 'open'"
    @keydown="keys"
  >
    <button role="menuitem" @click="choose('rename')"><Icon name="edit" :size="16" />重命名</button>
    <button role="menuitem" @click="choose(item.archived ? 'restore' : 'archive')">
      <Icon :name="item.archived ? 'restore' : 'archive'" :size="16" />{{ item.archived ? '还原' : '归档' }}
    </button>
    <button role="menuitem" class="conversation-delete" @click="choose('delete')">
      <Icon name="trash" :size="16" />删除
    </button>
  </div>
</template>
