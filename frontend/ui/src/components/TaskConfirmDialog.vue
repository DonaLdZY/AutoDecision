<script setup lang="ts">
const props = withDefaults(defineProps<{
  open: boolean
  title: string
  message: string
  confirmLabel?: string
  cancelLabel?: string
  confirmTone?: 'positive' | 'danger' | 'primary'
  cancelTone?: 'neutral' | 'danger'
  checkboxLabel?: string
  showCancel?: boolean
  busy?: boolean
}>(), {
  confirmLabel: '确认',
  cancelLabel: '取消',
  confirmTone: 'primary',
  cancelTone: 'neutral',
  checkboxLabel: '',
  showCancel: true,
  busy: false,
})

const checked = defineModel<boolean>('checked', { default: false })

const emit = defineEmits<{
  confirm: []
  cancel: []
}>()
</script>

<template>
  <div v-if="props.open" class="dialog-overlay" @click.self="emit('cancel')">
    <section class="dialog-panel" role="dialog" aria-modal="true" :aria-label="props.title">
      <header class="dialog-header">
        <h2>{{ props.title }}</h2>
      </header>
      <p class="dialog-message">{{ props.message }}</p>
      <label v-if="props.checkboxLabel" class="dialog-checkbox">
        <input v-model="checked" type="checkbox" :disabled="props.busy" />
        <span>{{ props.checkboxLabel }}</span>
      </label>
      <footer class="dialog-actions">
        <button
          v-if="props.showCancel"
          type="button"
          class="dialog-button"
          :class="`cancel-${props.cancelTone}`"
          :disabled="props.busy"
          @click="emit('cancel')"
        >
          {{ props.cancelLabel }}
        </button>
        <button
          type="button"
          class="dialog-button"
          :class="`confirm-${props.confirmTone}`"
          :disabled="props.busy"
          @click="emit('confirm')"
        >
          {{ props.busy ? '处理中...' : props.confirmLabel }}
        </button>
      </footer>
    </section>
  </div>
</template>

<style scoped>
.dialog-overlay {
  position: fixed;
  inset: 0;
  z-index: 1000;
  display: grid;
  place-items: center;
  padding: 20px;
  background: rgba(17, 29, 47, 0.55);
}

.dialog-panel {
  width: min(480px, 100%);
  box-sizing: border-box;
  border: 1px solid #c9d4e2;
  border-radius: 8px;
  padding: 20px;
  background: #fff;
  box-shadow: 0 18px 48px rgba(20, 37, 58, 0.24);
}

.dialog-header h2 {
  margin: 0;
  color: #17344f;
  font-size: 18px;
  letter-spacing: 0;
}

.dialog-message {
  margin: 14px 0;
  color: #38516b;
  line-height: 1.65;
  white-space: pre-line;
}

.dialog-checkbox {
  display: flex;
  align-items: flex-start;
  gap: 9px;
  margin: 16px 0;
  color: #334d68;
  line-height: 1.5;
}

.dialog-checkbox input {
  margin-top: 3px;
}

.dialog-actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  margin-top: 20px;
}

.dialog-button {
  min-width: 96px;
  min-height: 38px;
  border: 1px solid transparent;
  border-radius: 7px;
  padding: 8px 14px;
  font: inherit;
  letter-spacing: 0;
  cursor: pointer;
}

.confirm-positive {
  border-color: #2c7c5a;
  background: #2c7c5a;
  color: #fff;
}

.confirm-danger,
.cancel-danger {
  border-color: #b63d43;
  background: #b63d43;
  color: #fff;
}

.confirm-primary {
  border-color: #326aa3;
  background: #326aa3;
  color: #fff;
}

.cancel-neutral {
  border-color: #bec8d3;
  background: #e8edf2;
  color: #34495f;
}

.dialog-button:disabled {
  cursor: wait;
  opacity: 0.6;
}
</style>
