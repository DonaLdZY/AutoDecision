<script setup lang="ts">
import { onUnmounted, ref, watch } from 'vue'
import Icon from '../components/Icon.vue'
import { request, run, ui } from './store'
import { formatBytes, manageStorage, readStorage, storageRevision } from './storage'
import type { ResourceKind, StorageDetails, StoragePath } from './storage'
const props = withDefaults(defineProps<{ kind: ResourceKind; id: string; compact?: boolean; actions?: boolean }>(), { actions: true })
const info = ref<StorageDetails>(), error = ref('')
let sequence = 0
watch(() => [props.kind, props.id, storageRevision.value], async () => {
  const current = ++sequence
  info.value = undefined
  error.value = ''
  try {
    const value = await readStorage({ kind: props.kind, id: props.id })
    if (current === sequence) info.value = value
  } catch (reason) {
    if (current === sequence) error.value = reason instanceof Error ? reason.message : String(reason)
  }
}, { immediate: true })
onUnmounted(() => sequence++)
function open(path: StoragePath) {
  void run('open-resource', async () => {
    await request('/studio/storage/open', { kind: props.kind, id: props.id, path: path.path })
  })
}
</script>
<template>
  <div class="resource-storage" :class="{ compact }" @click.stop>
    <div v-if="info" class="storage-location">
      <div class="storage-measure"><Icon name="folder" :size="14" />
        <strong>{{ formatBytes(info.bytes) }}</strong><span>{{ info.files }} 个文件</span>
        <span v-if="!info.complete" class="storage-warning">统计未完成</span>
      </div>
      <div v-for="path in info.paths.slice(0, compact ? 1 : 2)" :key="path.path" class="storage-path-row">
        <button class="storage-path" :disabled="!path.exists || !!ui.busy || !ui.online" :title="path.path"
          :aria-label="`打开目录 ${path.path}`" @click="open(path)">
          <code>{{ path.path }}</code><Icon name="external" :size="13" />
        </button><span v-if="info.paths.length > 1 || !path.exists" class="storage-path-size">{{ path.exists ? formatBytes(path.bytes) : '不存在' }}</span>
      </div>
      <details v-if="info.paths.length > (compact ? 1 : 2)" class="storage-more-paths">
        <summary>另 {{ info.paths.length - (compact ? 1 : 2) }} 个位置</summary>
        <div v-for="path in info.paths.slice(compact ? 1 : 2)" :key="path.path" class="storage-path-row">
          <button class="storage-path" :aria-label="'打开目录 ' + path.path"
            :disabled="!path.exists || !!ui.busy || !ui.online" :title="path.path" @click="open(path)">
            <code>{{ path.path }}</code><Icon name="external" :size="13" />
          </button><span class="storage-path-size">{{ path.exists ? formatBytes(path.bytes) : '不存在' }}</span>
        </div>
      </details>
    </div>
    <p v-else-if="error" class="storage-read-error" role="status">{{ error }}</p>
    <span v-else class="storage-loading" role="status">正在统计目录…</span>
    <div v-if="actions !== false" class="storage-actions">
      <button class="btn secondary small" :disabled="!!ui.busy || !ui.online || !info"
        @click="manageStorage(info?.archived ? 'restore' : 'archive', [{ kind, id }])">
        {{ info?.archived ? '还原' : '归档' }}
      </button>
      <button v-if="info?.can_delete" class="btn secondary small storage-delete" :disabled="!!ui.busy || !ui.online"
        @click="manageStorage('delete', [{ kind, id }])">删除</button>
    </div>
  </div>
</template>
