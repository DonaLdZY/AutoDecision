<script setup lang="ts">
import { computed } from 'vue'
import Icon from '../components/Icon.vue'
import { state } from './store'
import type { Task } from './store'
import { taskWorkflow } from './taskWorkflow'
const props = defineProps<{ task: Task; compact?: boolean }>()
const emit = defineEmits<{ open: [kind: string, id: string] }>()
const next = computed(() => taskWorkflow(props.task, state.task_deliveries?.[props.task.id]))
</script>
<template>
  <section v-if="task.status === 'completed' || task.phase === 'report_failed'"
    class="task-next-step" :class="{ compact }" :data-task-id="task.id" aria-label="成果交付下一步">
    <Icon :name="next.stage === 'published' ? 'checkCircle' : 'package'" :size="20" />
    <div class="task-next-copy"><strong>{{ next.label }}</strong><p>{{ next.detail }}</p></div>
    <button class="btn small" :class="next.stage === 'published' ? 'secondary' : 'primary'"
      @click="emit('open', next.kind, next.packageId || task.id)">{{ next.action }}<Icon name="right" :size="14" /></button>
  </section>
</template>
