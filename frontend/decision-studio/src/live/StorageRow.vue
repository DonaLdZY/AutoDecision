<script setup lang="ts">
import ResourceStorage from './ResourceStorage.vue'
import { ui } from './store'
import { kindLabel, resourceKey } from './storage'
import type { Resource } from './storage'
defineProps<{ resource: Resource; checked: boolean }>()
defineEmits<{ select: [checked: boolean] }>()
</script>
<template>
  <article class="storage-item" :data-resource="resourceKey(resource)">
    <input type="checkbox" :aria-label="'选择 ' + kindLabel[resource.kind] + ' ' + resource.name" :checked="checked" :disabled="!!ui.busy" @change="$emit('select', ($event.target as HTMLInputElement).checked)" />
    <div class="storage-item-content"><div class="storage-item-heading"><h4>{{ resource.kind === 'tasks' ? '开发目录' : resource.name }}</h4><span v-if="resource.kind !== 'tasks'" class="tag neutral">{{ kindLabel[resource.kind] }}</span><span v-if="resource.archived" class="tag neutral">已归档</span></div>
      <ResourceStorage :kind="resource.kind" :id="resource.id" compact />
    </div>
  </article>
</template>
