<script setup lang="ts">
import { computed, onMounted, reactive, shallowRef, watch } from 'vue'
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
const activePage = shallowRef<'models' | 'runtime' | 'services' | 'mlevolve'>('models')
const pythonEnvs = shallowRef<PythonEnvironment[]>([])
const envLoading = shallowRef(false)
const envError = shallowRef('')
const envFilter = shallowRef('')

const roleLabels: Array<{ key: keyof GlobalSettings['llm']['roleModels']; label: string; hint: string }> = [
  { key: 'autoRealize', label: 'AutoRealize 模型', hint: '数据认知、QDI、任务定义和 description 生成。' },
  { key: 'autoRealizeVision', label: 'AutoRealize 视觉模型', hint: '图片/视觉文件认知，受任务配置里的 VLLM 开关控制。' },
  { key: 'autoMlCode', label: 'AutoML 编码模型', hint: 'MLEvolve 生成方案和代码。' },
  { key: 'autoMlFeedback', label: 'AutoML feedback 模型', hint: '反馈、评审、修复建议和报告优先使用。' },
  { key: 'embedding', label: '向量化模型', hint: 'MLEvolve 全局记忆的远程 embedding 模型。' },
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
    if (visible) void refreshPythonEnvs()
  },
)

onMounted(() => {
  if (props.visible) void refreshPythonEnvs()
})

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
  <div v-if="props.visible" class="overlay" @click.self="emit('close')">
    <section class="drawer">
      <header>
        <h3>全局设置</h3>
        <button @click="emit('close')">关闭</button>
      </header>

      <div class="layout">
        <aside class="nav">
          <button :class="{ active: activePage === 'models' }" @click="activePage = 'models'">模型配置</button>
          <button :class="{ active: activePage === 'runtime' }" @click="activePage = 'runtime'">运行环境</button>
          <button :class="{ active: activePage === 'services' }" @click="activePage = 'services'">服务编排</button>
          <button :class="{ active: activePage === 'mlevolve' }" @click="activePage = 'mlevolve'">MLEvolve</button>
        </aside>

        <div class="body">
          <section v-if="activePage === 'models'" class="page">
            <div class="section-head">
              <div>
                <h4>模型角色选择</h4>
                <p>所有阶段都从同一个模型配置库里选择模型。Thinking default 表示不向 provider 传 thinking extra_body。</p>
              </div>
            </div>

            <div class="role-grid">
              <label v-for="role in roleLabels" :key="role.key" class="role-card">
                <span>{{ role.label }}</span>
                <select v-model="local.llm.roleModels[role.key]">
                  <option v-for="model in local.llm.modelLibrary" :key="model.id" :value="model.id">{{ modelLabel(model.id) }}</option>
                </select>
                <small>{{ role.hint }}</small>
              </label>
            </div>

            <div class="section-head models-head">
              <div>
                <h4>模型配置库</h4>
                <p>新增配置后，可在上方分别指定给 AutoRealize、AutoML、feedback、视觉和向量化角色。</p>
              </div>
              <button class="primary-soft" @click="addModel">+ 添加模型</button>
            </div>

            <div class="model-list">
              <article v-for="model in local.llm.modelLibrary" :key="model.id" class="model-card">
                <div class="model-card-head">
                  <strong>{{ model.name || model.id }}</strong>
                  <button class="danger-soft" :disabled="local.llm.modelLibrary.length <= 1" @click="removeModel(model.id)">删除</button>
                </div>
                <div class="grid2">
                  <label><span>备注名</span><input v-model="model.name" placeholder="例如 DeepSeek 主力模型" /></label>
                  <label><span>model_name</span><input v-model="model.model" placeholder="例如 deepseek-v4-pro" /></label>
                  <label><span>Base URL</span><input v-model="model.baseUrl" placeholder="https://api.deepseek.com" /></label>
                  <label>
                    <span>API Key</span>
                    <input
                      v-model="model.apiKey"
                      type="password"
                      autocomplete="new-password"
                      :placeholder="model.apiKeyConfigured ? '已配置，输入新值可替换' : '输入 API Key'"
                    />
                    <small v-if="model.apiKeyConfigured">已配置，后端不会将原值返回浏览器。</small>
                  </label>
                  <label>
                    <span>Thinking Mode</span>
                    <select v-model="model.thinkingMode">
                      <option value="default">default: 不指定 thinking</option>
                      <option value="enabled">enabled: thinking.enabled</option>
                      <option value="disabled">disabled: thinking.disabled</option>
                    </select>
                  </label>
                  <label>
                    <span>Reasoning Effort</span>
                    <select v-model="model.reasoningEffort">
                      <option value="default">default: 不指定强度</option>
                      <option value="low">low</option>
                      <option value="medium">medium</option>
                      <option value="high">high</option>
                      <option value="xhigh">xhigh</option>
                    </select>
                  </label>
                  <label>
                    <span>Max Tokens</span>
                    <input
                      v-model.number="model.maxTokens"
                      type="number"
                      min="32768"
                      step="1024"
                      placeholder="至少 32768"
                    />
                    <small>正常业务 LLM 调用的输出上限不得低于 32768；更高值会原样保留。</small>
                  </label>
                  <label>
                    <span>Context Window Tokens</span>
                    <input
                      v-model.number="model.contextWindowTokens"
                      type="number"
                      min="0"
                      step="1024"
                      placeholder="例如 131072"
                    />
                    <small>用于 MLEvolve 在超出上下文前预留推理和输出空间；0 表示使用内置默认值。</small>
                  </label>
                </div>
              </article>
            </div>
          </section>

          <section v-else-if="activePage === 'runtime'" class="page">
            <h4>Python 环境</h4>
            <label><span>Python 可执行文件</span><input v-model="local.python.executable" placeholder="例如 /usr/bin/python3 或 C:\\Python311\\python.exe" /></label>
            <div class="py-env-panel">
              <div class="py-env-top">
                <strong>Python 解释器</strong>
                <div class="py-actions">
                  <input v-model="envFilter" placeholder="搜索路径 / 版本 / 来源" />
                  <button @click="refreshPythonEnvs" :disabled="envLoading">{{ envLoading ? '扫描中...' : '刷新' }}</button>
                </div>
              </div>
              <p v-if="envError" class="env-error">扫描失败: {{ envError }}</p>
              <div class="py-env-list">
                <button
                  v-for="env in filteredEnvs"
                  :key="env.path"
                  class="py-env-item"
                  :class="{ selected: local.python.executable === env.path, missing: !env.exists }"
                  @click="pickPythonEnv(env.path)"
                >
                  <div class="line1"><code>{{ env.path }}</code></div>
                  <div class="line2">
                    <span>{{ env.version }}</span>
                    <span class="tag">{{ env.source }}</span>
                    <span v-if="!env.exists" class="tag warn">not-found</span>
                  </div>
                </button>
              </div>
            </div>
          </section>

          <section v-else-if="activePage === 'services'" class="page">
            <h4>Core 服务编排</h4>
            <label><span>AutoRealize Base URL</span><input v-model="local.coreServices.autoRealizeBaseUrl" placeholder="http://127.0.0.1:18101" /></label>
            <label><span>AutoML / MLEvolve Base URL</span><input v-model="local.coreServices.mlevolveBaseUrl" placeholder="http://127.0.0.1:18103" /></label>
            <label><span>AutoReport Base URL</span><input v-model="local.coreServices.autoReportBaseUrl" placeholder="http://127.0.0.1:18104" /></label>
            <label><span>请求超时(秒)</span><input type="number" min="1" v-model.number="local.coreServices.requestTimeoutSecs" /></label>
          </section>

          <section v-else class="page">
            <h4>MLEvolve 全局配置</h4>
            <label>
              <span>Torch Hub 目录</span>
              <input v-model="local.mlevolve.torchHubDir" placeholder="例如 D:\\model_cache\\torch_hub 或 /data/torch_hub" />
              <small>PyTorch Hub 缓存目录，减少重复下载和外网依赖。</small>
            </label>
            <label>
              <span>预训练模型目录</span>
              <input v-model="local.mlevolve.pretrainModelDir" placeholder="例如 D:\\pretrain_models 或 /data/pretrain_models" />
              <small>本地预训练权重仓库，便于离线/内网加载模型。</small>
            </label>
            <p class="note">向量化模型现在在“模型配置”页面选择，不再在这里单独填写 Base URL/API Key。</p>
          </section>
        </div>
      </div>

      <footer>
        <button @click="emit('close')">取消</button>
        <button class="primary" @click="saveCurrent">保存设置</button>
      </footer>
    </section>
  </div>
</template>

<style scoped>
.overlay {
  position: fixed;
  inset: 0;
  background: rgba(7, 20, 44, 0.55);
  z-index: 30;
  display: flex;
  justify-content: flex-end;
}

.drawer {
  width: min(1040px, 96vw);
  background: #fff;
  height: 100%;
  display: grid;
  grid-template-rows: auto 1fr auto;
}

header,
footer {
  padding: 12px;
  border-bottom: 1px solid #dbe4f4;
  display: flex;
  justify-content: space-between;
  align-items: center;
}

footer {
  border-top: 1px solid #dbe4f4;
  border-bottom: 0;
}

.layout {
  min-height: 0;
  display: grid;
  grid-template-columns: 170px 1fr;
}

.nav {
  border-right: 1px solid #dbe4f4;
  background: #f7faff;
  padding: 12px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.nav button {
  text-align: left;
}

.nav button.active {
  background: #1f5db0;
  border-color: #1f5db0;
  color: #fff;
}

.body {
  padding: 12px;
  overflow: auto;
}

.page {
  display: grid;
  gap: 12px;
}

.section-head {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: flex-start;
}

.section-head h4,
.page h4 {
  margin: 0;
}

.section-head p,
.note {
  margin: 4px 0 0;
  color: #4c6690;
  font-size: 12px;
}

.grid2,
.role-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
}

.role-card,
.model-card {
  border: 1px solid #d4e2f8;
  border-radius: 12px;
  background: #f8fbff;
  padding: 10px;
}

.model-list {
  display: grid;
  gap: 12px;
}

.model-card-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 10px;
}

label {
  display: grid;
  gap: 4px;
  font-size: 13px;
}

small {
  font-size: 12px;
  color: #4c6690;
}

input,
select {
  border: 1px solid #c8d5ed;
  border-radius: 8px;
  padding: 8px;
  background: #fff;
}

button {
  border: 1px solid #b9cced;
  background: #f0f6ff;
  border-radius: 8px;
  padding: 8px 12px;
}

button.primary,
button.primary-soft {
  background: #1f5db0;
  border-color: #1f5db0;
  color: #fff;
}

button.danger-soft {
  background: #fff0f0;
  border-color: #efc3c3;
  color: #9a2d2d;
}

button:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.py-env-panel {
  border: 1px solid #d4e2f8;
  border-radius: 10px;
  background: #f8fbff;
  padding: 10px;
}

.py-env-top {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  align-items: center;
}

.py-actions {
  display: flex;
  gap: 8px;
  align-items: center;
}

.py-actions input {
  width: 280px;
}

.py-env-list {
  margin-top: 10px;
  display: grid;
  gap: 8px;
  max-height: 260px;
  overflow: auto;
}

.py-env-item {
  text-align: left;
  border: 1px solid #cadbf4;
  background: #fff;
  border-radius: 8px;
  padding: 8px;
}

.py-env-item.selected {
  border-color: #2f6fbe;
  background: #edf5ff;
}

.py-env-item.missing {
  opacity: 0.7;
}

.line1 code {
  font-size: 12px;
  color: #28456e;
}

.line2 {
  margin-top: 4px;
  display: flex;
  gap: 6px;
  align-items: center;
  font-size: 12px;
  color: #48658c;
}

.tag {
  border: 1px solid #c8dcfa;
  border-radius: 999px;
  padding: 1px 6px;
  background: #f0f6ff;
}

.tag.warn {
  border-color: #f1c2c2;
  background: #fff0f0;
  color: #8f3333;
}

.env-error {
  margin: 8px 0 0;
  color: #9d2b2b;
  font-size: 12px;
}

@media (max-width: 760px) {
  .layout {
    grid-template-columns: 1fr;
  }

  .nav {
    flex-direction: row;
    overflow: auto;
    border-right: 0;
    border-bottom: 1px solid #dbe4f4;
  }

  .grid2,
  .role-grid {
    grid-template-columns: 1fr;
  }
}
</style>
