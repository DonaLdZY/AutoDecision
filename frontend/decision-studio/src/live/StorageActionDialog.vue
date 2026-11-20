<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import Modal from './Modal.vue'
import Icon from '../components/Icon.vue'
import { refresh, request, run, ui, toast } from './store'
import { actionLabel, formatBytes, kindLabel, storageDialog, storageRevision } from './storage'
import type { ResourceKind, StoragePreview } from './storage'
const action = storageDialog.action
const resources = storageDialog.resources.map(({ kind, id }) => ({ kind, id }))
const preview = ref<StoragePreview>(), loading = ref(true), applying = ref(false), checked = ref(false), error = ref('')
const failureHint = computed(() => {
  if (!error.value) return ''
  if (action === 'delete' && /删除未完成|权限|拒绝访问|占用|WinError\s*5/i.test(error.value)) {
    return '删除动作被文件权限或占用阻拦。请关闭正在打开该目录或文件的编辑器、终端、资源管理器和运行服务，必要时修复目录权限；然后点击“重新核对”再试。记录仍保留，不会被误删。'
  }
  return '操作没有完成，原有记录仍保留。请先按上方原因处理，再点击“重新核对”。'
})
function close() { if (!applying.value) storageDialog.resources = [] }
async function load() {
  loading.value = true
  error.value = ''
  checked.value = false
  try { preview.value = await request('/studio/storage/preview', { resources, action }) }
  catch (reason) { error.value = reason instanceof Error ? reason.message : String(reason) }
  finally { loading.value = false }
}
onMounted(load)
async function openPath(path: { path: string }) {
  const resource = resources[0]
  if (!resource) return
  await run('open-storage-path', async () => {
    await request('/studio/storage/open', { kind: resource.kind, id: resource.id, path: path.path })
    toast('已打开目录')
  })
}
async function apply() {
  if (applying.value || !preview.value?.confirmation_token || (action === 'delete' && !checked.value)) return
  applying.value = true
  error.value = ''
  ui.busy = `storage-${action}`
  try {
    await request('/studio/storage/apply', { resources, action, confirm: true, confirmation_token: preview.value.confirmation_token })
    await refresh()
    storageRevision.value++
    storageDialog.resources = []
    toast(action === 'delete' ? '已删除磁盘内容和关联记录' : action === 'archive' ? '已归档' : '已还原')
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : String(reason)
    // Keep the affected paths visible so the user can open the directory and fix the issue in place.
    if (preview.value) preview.value = { ...preview.value, confirmation_token: '' }
    checked.value = false
    storageRevision.value++
  } finally {
    applying.value = false
    ui.busy = ''
  }
}
</script>
<template>
  <Modal class="storage-action-modal" :title="`${actionLabel[action]}确认`" :locked="applying" @close="close">
    <div class="storage-confirm">
      <p v-if="action === 'delete'">将永久删除所选开发目录、代码包内的真实文件及关联记录，无法还原。删除任务的开发目录也会删除其训练成果、交付副本和已发布代码包，范围如下。导入的数据文件夹始终保留，不允许删除。</p>
      <p v-else-if="action === 'archive'">归档会从日常列表中隐藏所选资源，磁盘文件保持原位，不释放空间。归档数据文件夹时，其关联内容也会隐藏。可在「本地存储 → 已归档」中还原。</p>
      <p v-else>还原后，所选资源将重新显示在工作空间，继续使用原来的文件和目录。还原数据项目时，其关联内容也会重新显示。</p>
      <div v-if="loading" class="storage-pending" role="status"><Icon name="loader" />正在核对目录和关联记录…</div>
      <p v-if="error" class="live-error" role="alert">{{ error }}</p>
      <p v-if="failureHint" class="storage-recovery-hint">{{ failureHint }}</p>
      <template v-if="preview">
        <div class="storage-confirm-total"><strong>{{ formatBytes(preview.bytes) }}</strong><span>{{ preview.files }} 个文件</span></div>
        <div class="storage-confirm-counts">
          <template v-for="(count, kind) in preview.counts" :key="kind">
            <span v-if="count">{{ kind === 'invocations' ? '调用记录' : kindLabel[kind as ResourceKind] }} {{ count }}</span>
          </template>
        </div>
        <div class="storage-confirm-resources"><span v-for="resource in preview.resources" :key="resource.kind + resource.id">{{ resource.name }}</span></div>
        <div class="storage-confirm-paths">
          <div v-for="path in preview.paths" :key="path.path">
            <code>{{ path.path }}</code><span>{{ path.exists ? formatBytes(path.bytes) : '目录不存在，仅处理记录' }}</span>
            <button v-if="path.exists" type="button" class="text-btn" :disabled="!!ui.busy || applying" @click="openPath(path)">打开目录</button>
            <span v-if="path.links">{{ path.links }} 个链接（不处理目标文件）</span>
            <p v-for="issue in path.errors" :key="issue" class="live-error">{{ issue }}</p>
          </div>
        </div>
        <ul v-if="preview.blockers.length" class="storage-blockers" role="alert"><li v-for="blocker in preview.blockers" :key="blocker">{{ blocker }}</li></ul>
        <label v-if="action === 'delete' && !preview.blockers.length" class="storage-acknowledge">
          <input v-model="checked" type="checkbox" :disabled="applying" />我已核对以上目录，确认永久删除
        </label>
      </template>
      <div class="form-actions">
        <button type="button" class="btn secondary" :disabled="applying" @click="close">取消</button>
        <button v-if="(!preview || !preview.confirmation_token) && !loading" class="btn secondary" :disabled="applying" @click="load">重新核对</button>
        <button class="btn" :class="action === 'delete' ? 'storage-danger' : 'primary'"
          :disabled="loading || applying || !!ui.busy || !preview?.confirmation_token || (action === 'delete' && !checked)" @click="apply">
          {{ applying ? `正在${actionLabel[action]}…` : `确认${actionLabel[action]}` }}
        </button>
      </div>
    </div>
  </Modal>
</template>
