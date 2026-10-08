<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, shallowRef, watch } from 'vue'
import { Boxes, Check, ChevronRight, Cpu, Database, Network, Plus, RefreshCw, Save, Search, Settings2, Terminal, Trash2, X } from 'lucide-vue-next'
import type { GlobalSettings, ModelConfig, PythonEnvironment } from '../types'
import { cloneDeep } from '../utils/clone'
import { api } from '../api'

const props = defineProps<{
  visible: boolean
  modelValue: GlobalSettings
}>()

const emit = defineEmits<{
  close: []
  save: [payload: GlobalSettings]
}>()

const local = reactive<GlobalSettings>(cloneDeep(props.modelValue))
const activePage = shallowRef<'models' | 'runtime' | 'services' | 'algoevolve'>('models')
const pythonEnvs = shallowRef<PythonEnvironment[]>([])
const envLoading = shallowRef(false)
const envError = shallowRef('')
const envFilter = shallowRef('')
const drawer = shallowRef<HTMLElement | null>(null)
const closeButton = shallowRef<HTMLButtonElement | null>(null)
let previousFocus: HTMLElement | null = null
const pages = [
  { key: 'models', label: '模型配置', icon: Boxes },
  { key: 'runtime', label: '运行环境', icon: Terminal },
  { key: 'services', label: '服务编排', icon: Network },
  { key: 'algoevolve', label: 'AlgoEvolve', icon: Cpu },
] as const

const roleLabels: Array<{ key: keyof GlobalSettings['llm']['roleModels']; label: string }> = [
  { key: 'autoRealize', label: '数据认知与任务定义' },
  { key: 'autoRealizeVision', label: '图片与视觉认知' },
  { key: 'autoMlCode', label: 'AutoML 代码生成' },
  { key: 'autoMlFeedback', label: '结果评审与报告' },
  { key: 'embedding', label: '全局记忆向量模型' },
]

function modelLabel(modelId: string) {
  const item = local.llm.modelLibrary.find((model) => model.id === modelId)
  if (!item) return modelId || '未选择'
  return `${item.name || item.id} (${item.model || 'no model'})`
}

function createModelConfig(): ModelConfig {
  const stamp = Date.now().toString(36)
  return {
    id: `model-${stamp}`,
    name: `模型 ${local.llm.modelLibrary.length + 1}`,
    model: '',
    baseUrl: '',
    apiKey: '',
    thinkingMode: 'default',
    reasoningEffort: 'default',
    maxTokens: 32768,
    contextWindowTokens: 0,
  }
}

function ensureModelSettings(target: GlobalSettings) {
  target.llm.modelLibrary = Array.isArray(target.llm.modelLibrary) ? target.llm.modelLibrary : []
  target.llm.roleModels = target.llm.roleModels || {
    autoRealize: '',
    autoRealizeVision: '',
    autoMlCode: '',
    autoMlFeedback: '',
    embedding: '',
  }
  if (target.llm.modelLibrary.length === 0) {
    target.llm.modelLibrary.push(createModelConfig())
  }
  for (const model of target.llm.modelLibrary) {
    model.maxTokens = Math.max(32768, Number(model.maxTokens || 0))
    model.contextWindowTokens = Number(model.contextWindowTokens || 0)
  }
  const firstId = target.llm.modelLibrary[0]?.id || ''
  for (const role of roleLabels) {
    if (!target.llm.roleModels[role.key] || !target.llm.modelLibrary.some((item) => item.id === target.llm.roleModels[role.key])) {
      target.llm.roleModels[role.key] = firstId
    }
  }
}

ensureModelSettings(local)

watch(
  () => props.modelValue,
  (next) => {
    Object.assign(local, cloneDeep(next))
    ensureModelSettings(local)
  },
  { deep: true },
)

watch(
  () => props.visible,
  (visible) => {
    if (visible) { void refreshPythonEnvs(); void focusDrawer() }
    else restoreFocus()
  },
)

onMounted(() => {
  if (props.visible) { void refreshPythonEnvs(); void focusDrawer() }
})

async function focusDrawer() {
  previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null
  await nextTick()
  closeButton.value?.focus({ preventScroll: true })
}

function restoreFocus() { previousFocus?.focus({ preventScroll: true }); previousFocus = null }
onBeforeUnmount(restoreFocus)

function trapFocus(event: KeyboardEvent) {
  const controls = [...(drawer.value?.querySelectorAll<HTMLElement>('button:not(:disabled), input:not(:disabled), select:not(:disabled), [tabindex="0"]') ?? [])].filter(element => element.getClientRects().length)
  const first = controls[0], last = controls.at(-1)
  if (!first || !last) return
  if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus() }
  else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus() }
}

function moveTab(event: KeyboardEvent, index: number) {
  if (!['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown', 'Home', 'End'].includes(event.key)) return
  event.preventDefault()
  const next = event.key === 'Home' ? 0 : event.key === 'End' ? pages.length - 1 : (index + (['ArrowLeft', 'ArrowUp'].includes(event.key) ? -1 : 1) + pages.length) % pages.length
  activePage.value = pages[next]!.key
  drawer.value?.querySelector<HTMLButtonElement>(`#global-tab-${activePage.value}`)?.focus()
}

const filteredEnvs = computed(() => {
  const q = envFilter.value.trim().toLowerCase()
  if (!q) return pythonEnvs.value
  return pythonEnvs.value.filter((item) => {
    return item.path.toLowerCase().includes(q) || item.version.toLowerCase().includes(q) || item.source.toLowerCase().includes(q)
  })
})

async function refreshPythonEnvs() {
  envLoading.value = true
  envError.value = ''
  try {
    pythonEnvs.value = await api.listPythonEnvs(local.python.executable || '')
  } catch (e) {
    envError.value = (e as Error).message
  } finally {
    envLoading.value = false
  }
}

function pickPythonEnv(path: string) {
  local.python.executable = path
}

function addModel() {
  const item = createModelConfig()
  local.llm.modelLibrary.push(item)
}

function removeModel(modelId: string) {
  if (local.llm.modelLibrary.length <= 1) return
  const index = local.llm.modelLibrary.findIndex((item) => item.id === modelId)
  if (index < 0) return
  local.llm.modelLibrary.splice(index, 1)
  const fallback = local.llm.modelLibrary[0]?.id || ''
  for (const role of roleLabels) {
    if (local.llm.roleModels[role.key] === modelId) {
      local.llm.roleModels[role.key] = fallback
    }
  }
}

function saveCurrent() {
  ensureModelSettings(local)
  emit('save', cloneDeep(local))
}
</script>

<template>
  <div v-if="props.visible" class="settings-overlay" @click.self="emit('close')">
    <section ref="drawer" class="settings-drawer" role="dialog" aria-modal="true" aria-labelledby="global-settings-title" @keydown.tab="trapFocus" @keydown.esc.stop="emit('close')">
      <header class="drawer-heading">
        <h3 id="global-settings-title"><Settings2 :size="19" />全局设置</h3>
        <button ref="closeButton" type="button" class="settings-icon" title="关闭全局设置" aria-label="关闭全局设置" @click="emit('close')"><X :size="19" /></button>
      </header>

      <div class="layout">
        <nav class="settings-nav" role="tablist" aria-label="全局设置分类">
          <button v-for="(page, index) in pages" :id="`global-tab-${page.key}`" :key="page.key" type="button" role="tab" :aria-selected="activePage === page.key" aria-controls="global-settings-panel" :tabindex="activePage === page.key ? 0 : -1" :class="{ active: activePage === page.key }" @click="activePage = page.key" @keydown="moveTab($event, index)"><component :is="page.icon" :size="16" /><span>{{ page.label }}</span><ChevronRight :size="12" class="nav-chevron" /></button>
        </nav>

        <div id="global-settings-panel" class="settings-body" role="tabpanel" :aria-labelledby="`global-tab-${activePage}`">
          <section v-if="activePage === 'models'" class="page">
            <div class="section-head">
              <div>
                <h4>角色模型</h4>
              </div>
            </div>

            <div class="role-grid">
              <label v-for="role in roleLabels" :key="role.key" class="role-field">
                <span>{{ role.label }}</span>
                <select v-model="local.llm.roleModels[role.key]">
                  <option v-for="model in local.llm.modelLibrary" :key="model.id" :value="model.id">{{ modelLabel(model.id) }}</option>
                </select>
              </label>
            </div>

            <div class="section-head models-head">
              <div>
                <h4>模型库 <span class="section-count">{{ local.llm.modelLibrary.length }}</span></h4>
              </div>
              <button type="button" class="settings-command" @click="addModel"><Plus :size="15" />添加模型</button>
            </div>

            <div class="model-list">
              <article v-for="model in local.llm.modelLibrary" :key="model.id" class="model-card">
                <div class="model-card-head">
                  <strong><Boxes :size="16" />{{ model.name || model.id }}</strong>
                  <button type="button" class="settings-icon danger" :disabled="local.llm.modelLibrary.length <= 1" :title="`删除 ${model.name || '模型'}`" :aria-label="`删除 ${model.name || '模型'}`" @click="removeModel(model.id)"><Trash2 :size="15" /></button>
                </div>
                <div class="grid2">
                  <label><span>显示名称</span><input v-model="model.name" placeholder="主力代码模型" /></label>
                  <label><span>API 模型标识</span><input v-model="model.model" placeholder="gpt-5.6-sol" spellcheck="false" /></label>
                  <label><span>Base URL</span><input v-model="model.baseUrl" placeholder="https://api.example.com/v1" spellcheck="false" /></label>
                  <label>
                    <span>API Key</span>
                    <input
                      v-model="model.apiKey"
                      type="password"
                      autocomplete="new-password"
                      :placeholder="model.apiKeyConfigured ? '已配置，输入新值可替换' : '输入 API Key'"
                    />
                    <small v-if="model.apiKeyConfigured" class="configured"><Check :size="12" />已配置，留空保留</small>
                  </label>
                  <label>
                    <span>思考模式</span>
                    <select v-model="model.thinkingMode">
                      <option value="default">遵循供应商默认</option>
                      <option value="enabled">启用</option>
                      <option value="disabled">禁用</option>
                    </select>
                  </label>
                  <label>
                    <span>推理强度</span>
                    <select v-model="model.reasoningEffort">
                      <option value="default">遵循供应商默认</option>
                      <option value="low">low</option>
                      <option value="medium">medium</option>
                      <option value="high">high</option>
                      <option value="xhigh">xhigh</option>
                    </select>
                  </label>
                  <label>
                    <span>输出 Token 上限</span>
                    <input
                      v-model.number="model.maxTokens"
                      type="number"
                      min="32768"
                      step="1024"
                      placeholder="至少 32768"
                    />
                    <small>最低 32768</small>
                  </label>
                  <label>
                    <span>上下文窗口 Token</span>
                    <input
                      v-model.number="model.contextWindowTokens"
                      type="number"
                      min="0"
                      step="1024"
                      placeholder="例如 131072"
                    />
                    <small>0 使用内置默认窗口</small>
                  </label>
                </div>
              </article>
            </div>
          </section>

          <section v-else-if="activePage === 'runtime'" class="page">
            <h4>Python 环境</h4>
            <label><span>Python 可执行文件</span><input v-model="local.python.executable" placeholder="例如 /usr/bin/python3 或 C:\\Python311\\python.exe" /></label>
            <div class="py-env-section">
              <div class="py-env-top">
                <strong>可用解释器 <span class="section-count">{{ filteredEnvs.length }}</span></strong>
                <div class="py-actions">
                  <label class="env-search"><Search :size="14" /><input v-model="envFilter" aria-label="搜索 Python 环境" placeholder="路径、版本或来源" /></label>
                  <button type="button" class="settings-icon" title="刷新 Python 环境" aria-label="刷新 Python 环境" :aria-busy="envLoading" @click="refreshPythonEnvs" :disabled="envLoading"><RefreshCw :size="16" :class="{ spinning: envLoading }" /></button>
                </div>
              </div>
              <p v-if="envError" class="env-error" role="alert">扫描失败: {{ envError }}</p>
              <p v-else-if="envLoading" class="env-state" role="status">正在检测环境...</p>
              <p v-else-if="!filteredEnvs.length" class="env-state">{{ envFilter ? '没有匹配的环境' : '未发现可用环境' }}</p>
              <div class="py-env-list">
                <button
                  v-for="env in filteredEnvs"
                  :key="env.path"
                  type="button"
                  class="py-env-item"
                  :class="{ selected: local.python.executable === env.path, missing: !env.exists }"
                  :aria-pressed="local.python.executable === env.path"
                  @click="pickPythonEnv(env.path)"
                >
                  <div class="line1"><Terminal :size="14" /><code>{{ env.path }}</code><Check v-if="local.python.executable === env.path" :size="15" class="env-check" /></div>
                  <div class="line2">
                    <span>{{ env.version }}</span>
                    <span class="tag">{{ env.source }}</span>
                    <span v-if="!env.exists" class="tag warn">路径不存在</span>
                  </div>
                </button>
              </div>
            </div>
          </section>

          <section v-else-if="activePage === 'services'" class="page">
            <h4>核心服务</h4>
            <label><span>AutoRealize Base URL</span><input v-model="local.coreServices.autoRealizeBaseUrl" placeholder="http://127.0.0.1:18101" /></label>
            <label><span>AutoML / AlgoEvolve Base URL</span><input v-model="local.coreServices.algoEvolveBaseUrl" placeholder="http://127.0.0.1:18103" /></label>
            <label><span>AutoReport Base URL</span><input v-model="local.coreServices.autoReportBaseUrl" placeholder="http://127.0.0.1:18104" /></label>
            <label><span>请求超时(秒)</span><input type="number" min="1" v-model.number="local.coreServices.requestTimeoutSecs" /></label>
          </section>

          <section v-else class="page">
            <h4>AlgoEvolve 全局配置</h4>
            <label>
              <span>Torch Hub 目录</span>
              <input v-model="local.algoevolve.torchHubDir" placeholder="例如 D:\\model_cache\\torch_hub 或 /data/torch_hub" />
            </label>
            <label>
              <span>预训练模型目录</span>
              <input v-model="local.algoevolve.pretrainModelDir" placeholder="例如 D:\\pretrain_models 或 /data/pretrain_models" />
            </label>
            <button type="button" class="settings-command related-setting" @click="activePage = 'models'"><Database :size="15" />向量模型配置<ChevronRight :size="14" /></button>
          </section>
        </div>
      </div>

      <footer class="drawer-footer">
        <button type="button" class="settings-command" @click="emit('close')">取消</button>
        <button type="button" class="settings-command primary" @click="saveCurrent"><Save :size="15" />保存设置</button>
      </footer>
    </section>
  </div>
</template>

<style scoped>
.settings-overlay {
  position: fixed;
  inset: 0;
  background: #17221b52;
  z-index: 90;
  display: flex;
  justify-content: flex-end;
  animation: overlay-enter 100ms ease-out;
}

.settings-drawer {
  width: min(940px, 100%);
  min-width: 0;
  background: #fff;
  height: 100dvh;
  display: grid;
  grid-template-rows: 64px minmax(0, 1fr) 66px;
  color: #26352b;
  border-left: 1px solid #dce3dc;
  box-shadow: -12px 0 44px #13251b12;
  animation: drawer-enter 150ms ease-out;
}

.drawer-heading,
.drawer-footer {
  padding: 0 24px;
  border-bottom: 1px solid #e4e8e4;
  display: flex;
  justify-content: space-between;
  align-items: center;
  min-width: 0;
}

.drawer-heading h3 {
  display: flex;
  align-items: center;
  gap: 10px;
  margin: 0;
  font-size: 16px;
  font-weight: 600;
}

.drawer-heading h3 svg { color: #598368; }

.drawer-footer {
  justify-content: flex-end;
  gap: 9px;
  border-top: 1px solid #e4e8e4;
  border-bottom: 0;
}

.layout {
  min-width: 0;
  min-height: 0;
  display: grid;
  grid-template-columns: 174px minmax(0, 1fr);
}

.settings-nav {
  border-right: 1px solid #e4e8e4;
  background: #f7f9f6;
  padding: 18px 10px;
  display: flex;
  flex-direction: column;
  gap: 5px;
  min-width: 0;
}

.settings-nav button {
  border: 1px solid transparent;
  background: transparent;
  color: #7b857b;
  border-radius: 5px;
  min-height: 41px;
  padding: 9px 10px;
  display: flex;
  align-items: center;
  gap: 9px;
  font-size: 12px;
  text-align: left;
}

.settings-nav button:hover { background: #eef2ed; }
.settings-nav button.active { background: #e8f0e6; color: #356446; border-color: #dbe7d8; }
.nav-chevron { margin-left: auto; opacity: 0; }
.active .nav-chevron { opacity: 1; }

.settings-body {
  padding: 26px;
  min-width: 0;
  min-height: 0;
  overflow: auto;
  overscroll-behavior: contain;
}

.page {
  display: grid;
  gap: 20px;
  min-width: 0;
  align-content: start;
}

.section-head {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: center;
  min-width: 0;
}

.models-head { border-top: 1px solid #e4e8e4; padding-top: 22px; margin-top: 4px; }
.section-head h4, .page h4 { margin: 0; font-size: 13px; font-weight: 600; color: #384b3e; }
.section-count { margin-left: 5px; color: #8f9a8d; font-size: 11px; font-weight: 400; font-variant-numeric: tabular-nums; }

.grid2, .role-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 17px 20px;
  min-width: 0;
}

.role-field { align-content: start; }
.model-list { display: grid; gap: 16px; min-width: 0; }
.model-card {
  border: 1px solid #e0e6df;
  border-radius: 6px;
  background: #fff;
  padding: 18px;
  min-width: 0;
}

.model-card-head {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  align-items: center;
  margin-bottom: 18px;
  min-width: 0;
}

.model-card-head strong { min-width: 0; display: flex; align-items: center; gap: 8px; overflow-wrap: anywhere; font-size: 13px; font-weight: 550; }
.model-card-head strong svg { color: #6e8d73; }

label { display: grid; gap: 7px; font-size: 11px; color: #6c786d; min-width: 0; }
small { font-size: 10px; color: #8c978a; overflow-wrap: anywhere; }
.configured { color: #57866a; display: flex; align-items: center; gap: 4px; }
input, select {
  width: 100%;
  min-width: 0;
  max-width: 100%;
  height: 36px;
  border: 1px solid #dce3db;
  border-radius: 4px;
  padding: 7px 9px;
  background: #fff;
  color: #354239;
  font: inherit;
  font-size: 12px;
}

input::placeholder { color: #a3aaa1; }
input:focus, select:focus { border-color: #73967a; }
button { font: inherit; letter-spacing: 0; cursor: pointer; }
.settings-command {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 7px;
  min-height: 34px;
  padding: 7px 12px;
  border: 1px solid #dce3db;
  border-radius: 4px;
  background: #fff;
  color: #566955;
  font-size: 11px;
}

.settings-command:hover:not(:disabled) { background: #f1f5ef; border-color: #b6cbb4; }
.settings-command.primary { color: #fff; border-color: #26714b; background: #26714b; }
.settings-command.primary:hover:not(:disabled) { background: #1d623e; }
.related-setting { justify-self: start; margin-top: 10px; }
.settings-icon {
  width: 32px;
  height: 32px;
  padding: 0;
  flex-shrink: 0;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: 1px solid transparent;
  border-radius: 4px;
  background: transparent;
  color: #7f8a7d;
}

.settings-icon:hover:not(:disabled) { background: #eef3ec; color: #446b48; }
.settings-icon.danger:hover:not(:disabled) { background: #fcf0ef; color: #b8534c; }
button:disabled { opacity: .45; cursor: not-allowed; }
.py-env-section { margin-top: 4px; padding-top: 22px; border-top: 1px solid #e4e8e4; min-width: 0; }
.py-env-top {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  align-items: center;
  min-width: 0;
}

.py-env-top > strong { font-size: 12px; font-weight: 550; white-space: nowrap; }
.py-actions { display: flex; gap: 6px; align-items: center; min-width: 0; }
.env-search { display: flex; align-items: center; border: 1px solid #dce3db; padding-left: 8px; border-radius: 4px; color: #98a192; width: min(230px, 100%); }
.env-search input { border: 0; height: 32px; }
.py-env-list {
  margin-top: 14px;
  display: grid;
  gap: 7px;
  max-height: 430px;
  overflow: auto;
  min-width: 0;
}

.py-env-item {
  text-align: left;
  border: 1px solid #e1e7de;
  background: #fff;
  border-radius: 5px;
  padding: 12px;
  min-width: 0;
  width: 100%;
}

.py-env-item:hover { border-color: #aac2a8; background: #f7f9f5; }
.py-env-item.selected { border-color: #91b38f; background: #f0f6ed; }
.py-env-item.missing { opacity: .7; }
.line1 { display: flex; align-items: flex-start; gap: 8px; min-width: 0; color: #7c9073; }
.line1 code { font-size: 11px; color: #52634d; overflow-wrap: anywhere; min-width: 0; }
.env-check { color: #357b49; margin-left: auto; }
.line2 { margin: 7px 0 0 22px; display: flex; flex-wrap: wrap; gap: 8px; align-items: center; font-size: 10px; color: #8a9981; }
.tag { color: #76906b; }
.tag.warn { color: #b57542; }
.env-error { margin: 10px 0 0; color: #ac514b; font-size: 12px; overflow-wrap: anywhere; }
.env-state { font-size: 12px; color: #99a18f; margin: 24px 0; }
.spinning { animation: icon-spin 1s linear infinite; }
@keyframes icon-spin { to { transform: rotate(360deg); } }
@keyframes overlay-enter { from { opacity: 0; } to { opacity: 1; } }
@keyframes drawer-enter { from { transform: translateX(18px); } to { transform: translateX(0); } }
@media (max-width: 760px) {
  .layout { grid-template-columns: minmax(0, 1fr); grid-template-rows: auto minmax(0, 1fr); }
  .settings-nav { flex-direction: row; padding: 8px 10px; overflow-x: auto; border-right: 0; border-bottom: 1px solid #e4e8e4; }
  .settings-nav button { flex-shrink: 0; padding: 8px 9px; gap: 6px; min-height: 35px; font-size: 11px; }
  .nav-chevron { display: none; }
  .settings-body { padding: 20px; }
}
@media (max-width: 480px) {
  .settings-drawer { grid-template-rows: 58px minmax(0, 1fr) 62px; }
  .drawer-heading, .drawer-footer { padding: 0 16px; }
  .settings-body { padding: 19px 16px; }
  .grid2, .role-grid { grid-template-columns: minmax(0, 1fr); gap: 15px; }
  .model-card { padding: 15px; }
  .py-env-top { align-items: flex-start; flex-direction: column; gap: 13px; }
  .py-actions { width: 100%; }
  .env-search { flex: 1; width: auto; }
  .settings-nav { gap: 1px; }
  .settings-nav button { font-size: 10px; padding: 8px; }
}
@media (prefers-reduced-motion: reduce) {
  .settings-overlay, .settings-drawer, .spinning { animation: none; }
}
</style>
