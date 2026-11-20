<script setup lang="ts">
import Icon from '../components/Icon.vue'
import { date, state, taskProjectId } from './store'
import { notices, unreadNotices, isRead, markRead, markAllRead } from './notices'
import type { Notice } from './notices'
const emit = defineEmits<{ open: [kind: string, id: string] }>()
const projectName = (taskId: string) => state.projects.find((p) => p.id === taskProjectId(taskId))?.name || ''
function go(notice: Notice, kind: string, id: string) {
  markRead(notice)
  emit('open', kind, id)
}
const icons = { done: 'checkCircle', pending: 'package', failed: 'shield' } as const
</script>
<template>
  <section class="live-page">
    <div class="page-heading">
      <div>
        <h1>研究通知</h1>
      </div>
      <button v-if="unreadNotices" class="btn secondary small" @click="markAllRead">全部标为已读</button>
    </div>
    <div v-if="!notices.length" class="live-empty">
      <Icon name="bell" :size="32" />
      <h2>暂无通知</h2>
    </div>
    <article
      v-for="n in notices"
      :key="n.key"
      class="live-panel notice-row"
      :class="[n.tone, { unread: !isRead(n) }]"
    >
      <span class="notice-icon"><Icon :name="icons[n.tone]" :size="20" /></span>
      <div class="notice-copy">
        <h3><i v-if="!isRead(n)" class="notice-dot" aria-label="未读"></i>{{ n.title }}</h3>
        <p>{{ n.detail }}</p>
        <small>{{ projectName(n.task.id) }} · {{ date(n.task.updated_at) }}</small>
      </div>
      <div class="notice-actions">
        <button v-if="n.hasReport" class="btn primary small" @click="go(n, 'report', n.task.id)">
          查看报告
        </button>
        <button
          v-if="n.action"
          class="btn small"
          :class="n.hasReport ? 'secondary' : 'primary'"
          @click="go(n, n.action.kind, n.action.id)"
        >
          {{ n.action.label }}
        </button>
      </div>
    </article>
  </section>
</template>
<style scoped>
.notice-row {
  display: grid;
  grid-template-columns: 40px minmax(0, 1fr) auto;
  gap: 14px;
  align-items: center;
  margin: 0 0 12px;
}
.notice-icon {
  display: grid;
  place-items: center;
  width: 40px;
  height: 40px;
  border-radius: 10px;
  background: #e7f5ee;
  color: #1f8a5b;
}
.pending .notice-icon {
  background: #fff4e5;
  color: #9a6516;
}
.failed .notice-icon {
  background: #fdeee6;
  color: #c2410c;
}
.notice-copy h3 {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 0 0 4px;
  font-size: 15px;
}
.notice-copy p {
  margin: 0 0 4px;
  color: var(--ink);
  font-size: 14px;
}
.notice-copy small {
  color: var(--muted);
  font-size: 12px;
}
.notice-dot {
  flex: none;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--primary);
}
.notice-row:not(.unread) {
  opacity: 0.78;
}
.notice-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  justify-content: flex-end;
}
@media (max-width: 760px) {
  .notice-row {
    grid-template-columns: 40px minmax(0, 1fr);
  }
  .notice-actions {
    grid-column: 1 / -1;
    justify-content: flex-start;
  }
}
</style>
