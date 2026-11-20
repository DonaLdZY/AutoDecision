<script setup lang="ts">
import { ref, watch } from 'vue'
import { api, saveBlob, type Readiness } from '../api'
const props = defineProps<{ taskId?: string }>()
defineEmits<{ settings: [] }>()
const data = ref<Readiness | null>(null)
const busy = ref(false)
const error = ref('')
const probeBusy = ref('')
let generation = 0
async function refresh() {
  const id = ++generation
  busy.value = true; error.value = ''; data.value = null
  try { const result = await api.getReadiness(props.taskId); if (id === generation) data.value = result }
  catch (e) { if (id === generation) error.value = String(e) }
  finally { if (id === generation) busy.value = false }
}
async function probe(role: string) {
  probeBusy.value = role; error.value = ''
  try { await api.probeModel(role); await refresh() }
  catch (e) { error.value = String(e) }
  finally { probeBusy.value = '' }
}
async function diagnostics() {
  try { saveBlob(new Blob([JSON.stringify(await api.getDiagnostics(), null, 2)], { type: 'application/json' }), 'autodecision-diagnostics.json') }
  catch (e) { error.value = String(e) }
}
watch(() => props.taskId, refresh, { immediate: true })
</script>
<template>
  <section class="product-panel" aria-label="本地运行检查">
    <div class="product-panel-heading"><div><h3>本地运行检查</h3><p>先连接环境与模型，再开始实验。检查本身不调用模型 API。</p></div><button class="command" :disabled="busy || !!probeBusy" @click="refresh">{{ busy ? '检查中…' : '重新检查' }}</button></div>
    <p v-if="error" class="product-error" role="alert">{{ error }}</p>
    <template v-if="data">
      <p class="product-status" :class="{ blocked: !data.ready }">{{ data.ready ? '基础检查通过；模型能力请以验证记录为准' : '有项目需要处理，暂不启动实验' }} · {{ new Date(data.checked_at * 1000).toLocaleString() }}</p>
      <ul class="readiness-list"><li v-for="check in data.checks" :key="check.key"><span class="check-state" :class="check.status">{{ { pass: '通过', warn: '待验证', fail: '需处理' }[check.status] }}</span><div><strong>{{ check.label }}</strong><p>{{ check.detail }}</p></div><button v-if="['autoRealize', 'autoMlCode', 'autoMlFeedback'].includes(check.key)" class="command" :disabled="!!probeBusy || busy" @click="probe(check.key)">{{ probeBusy === check.key ? '验证中…' : '测试文本请求' }}</button></li></ul>
      <p class="product-note">“测试文本请求”会向已配置的 Provider 发送一条短消息，可能产生 API 费用，不发送任务数据。测试只验证文本响应，不验证视觉或向量能力。</p>
      <details><summary>数据流、存储与运行器</summary><p>{{ data.data_policy }}</p><ul><li v-for="provider in data.providers" :key="provider.role">{{ provider.model || '未配置模型' }} → {{ provider.host || '未配置地址' }}（{{ provider.local ? '本机端点' : '非本机端点' }}）</li></ul><p>{{ data.lifecycle }}</p><p>输出根目录：<code>{{ data.output_root }}</code></p><p>输入目录使用本机路径；容器或 WSL 部署应填写运行器可见的挂载路径。方案导出不复制原始输入目录。删除记录与清理运行文件分别确认。</p></details>
      <div class="product-actions"><button class="command primary" @click="$emit('settings')">配置模型与环境</button><button class="command" @click="diagnostics">导出诊断摘要</button><span class="product-note">安装版本 {{ data.version }}</span></div>
    </template>
    <button v-else-if="error" class="command" @click="$emit('settings')">打开系统设置</button>
  </section>
</template>
