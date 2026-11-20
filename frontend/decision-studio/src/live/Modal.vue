<script setup lang="ts">
import { nextTick, onMounted, onUnmounted, ref, useId } from 'vue'
import Icon from '../components/Icon.vue'
import { ui } from './store'
defineProps<{ title: string; wide?: boolean; locked?: boolean }>()
const titleId = useId()
const emit = defineEmits<{ close: [] }>()
const dialog = ref<HTMLDialogElement>()
const previous = document.activeElement as HTMLElement | null
onMounted(async () => {
  await nextTick()
  dialog.value?.showModal()
})
onUnmounted(() => {
  if (previous?.isConnected) previous.focus()
})
</script>
<template>
  <dialog
    ref="dialog"
    class="detail-dialog"
    :class="{ wide }"
    :aria-labelledby="titleId"
    @cancel.prevent="!locked && emit('close')"
    @click="(e) => !locked && e.target === dialog && emit('close')"
  >
    <div class="dialog-shell">
      <header class="dialog-header">
        <strong :id="titleId">{{ title }}</strong
        ><button class="icon-btn" aria-label="关闭详情" :disabled="locked" @click="emit('close')"><Icon name="x" /></button>
      </header>
      <div class="dialog-body">
        <div v-if="ui.error" class="live-error" role="alert">
          {{ ui.error }}<button aria-label="关闭弹窗错误提示" @click="ui.error = ''">×</button>
        </div>
        <slot />
      </div>
    </div>
  </dialog>
</template>
