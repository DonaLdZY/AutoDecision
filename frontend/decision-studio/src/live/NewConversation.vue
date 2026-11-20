<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { state, tasks, ui, taskProjectId, newConversation } from './store'
// 对话基于研究计划：先选数据，再勾选要依据的研究计划（只列已完成的）。
const latest = [...tasks.value].sort((a, b) => b.updated_at - a.updated_at)[0]
const projectId = ref(
  state.projects.find((p) => p.id === ui.newChatProjectId)?.id ||
    (latest && taskProjectId(latest.id)) ||
    state.projects.find((p) => p.id === ui.projectId)?.id ||
    state.projects[0]?.id ||
    '',
)
const plans = computed(() =>
  tasks.value
    .filter((t) => t.status === 'completed' && taskProjectId(t.id) === projectId.value)
    .sort((a, b) => b.updated_at - a.updated_at),
)
const picked = ref<string[]>([])
watch(
  plans,
  (rows) => {
    picked.value = rows.slice(0, 1).map((t) => t.id)
  },
  { immediate: true },
)
async function start() {
  ui.newChat = false
  await newConversation(projectId.value, picked.value)
}
</script>
<template>
  <form class="start-chat" @submit.prevent="start">
    <label class="start-chat-field"
      ><span>项目数据</span
      ><select v-model="projectId" required>
        <option v-for="p in state.projects" :key="p.id" :value="p.id">{{ p.name }}</option>
      </select></label
    >
    <div class="start-chat-field">
      <span>基于哪些研究计划</span>
      <p v-if="!plans.length" class="start-chat-hint">这份数据还没有完成的研究计划，对话将只基于数据。</p>
      <label
        v-for="t in plans"
        :key="t.id"
        class="start-chat-plan"
        :class="{ picked: picked.includes(t.id) }"
      >
        <input v-model="picked" type="checkbox" :value="t.id" />
        <span>
          <strong>{{ t.task_name }}</strong>
          <small v-if="state.research_briefs?.[t.id]">{{ state.research_briefs[t.id]!.headline }}</small>
        </span>
      </label>
    </div>
    <button class="btn primary" :disabled="!projectId || !!ui.busy">开始对话</button>
  </form>
</template>
<style scoped>
.start-chat {
  display: flex;
  flex-direction: column;
  gap: 20px;
  min-width: min(520px, 100%);
  background: #fff;
}
.start-chat-field {
  display: flex;
  flex-direction: column;
  gap: 8px;
  color: var(--ink);
  font-size: 13px;
}
.start-chat-field > span {
  font-weight: 600;
}
.start-chat-field select {
  width: 100%;
  padding: 10px 12px;
  border: 1px solid var(--line);
  border-radius: 7px;
  background: #fff;
  color: var(--ink);
  font: inherit;
}
.start-chat-hint {
  margin: 0;
  color: var(--secondary);
}
.start-chat-plan {
  display: flex;
  gap: 10px;
  align-items: flex-start;
  padding: 12px 14px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: #fff;
  cursor: pointer;
}
.start-chat-plan.picked {
  border-color: var(--primary);
  background: var(--primary-soft);
}
.start-chat-plan input {
  width: auto;
  margin-top: 3px;
}
.start-chat-plan span {
  display: grid;
  gap: 2px;
}
.start-chat-plan strong {
  font-size: 14px;
}
.start-chat-plan small {
  color: var(--secondary);
  font-size: 12px;
}
.start-chat > .btn {
  align-self: flex-start;
}
</style>
