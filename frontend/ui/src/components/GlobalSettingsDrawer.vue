<script setup lang="ts">
import { computed, onMounted, reactive, shallowRef, watch } from 'vue'
import type { GlobalSettings, PythonEnvironment } from '../types'
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
const pythonEnvs = shallowRef<PythonEnvironment[]>([])
const envLoading = shallowRef(false)
const envError = shallowRef('')
const envFilter = shallowRef('')

watch(
  () => props.modelValue,
  (next) => {
    Object.assign(local, cloneDeep(next))
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

function toThinkingMode(value: boolean | null | undefined) {
  if (value === true) return 'enabled'
  if (value === false) return 'disabled'
  return 'default'
}

function fromThinkingMode(value: string): boolean | null {
  if (value === 'enabled') return true
  if (value === 'disabled') return false
  return null
}

const codeThinkingMode = computed({
  get: () => toThinkingMode(local.llm.codeModel.enableThinking),
  set: (value: string) => {
    local.llm.codeModel.enableThinking = fromThinkingMode(value)
  },
})

const feedbackThinkingMode = computed({
  get: () => toThinkingMode(local.llm.feedbackModel.enableThinking),
  set: (value: string) => {
    local.llm.feedbackModel.enableThinking = fromThinkingMode(value)
  },
})

function saveCurrent() {
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
      <div class="body">
        <h4>资源限制</h4>
        <div class="grid2">
          <label><span>CPU 限制</span><input type="number" v-model.number="local.resource.cpuLimit" /></label>
          <label><span>内存限制(GB)</span><input type="number" v-model.number="local.resource.memoryLimitGb" /></label>
        </div>

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
              <div class="line1">
                <code>{{ env.path }}</code>
              </div>
              <div class="line2">
                <span>{{ env.version }}</span>
                <span class="tag">{{ env.source }}</span>
                <span v-if="!env.exists" class="tag warn">not-found</span>
              </div>
            </button>
          </div>
        </div>

        <h4>编码模型</h4>
        <label><span>模型名</span><input v-model="local.llm.codeModel.model" /></label>
        <label><span>Base URL</span><input v-model="local.llm.codeModel.baseUrl" /></label>
        <label><span>API Key</span><input v-model="local.llm.codeModel.apiKey" /></label>
        <div class="grid2">
          <label>
            <span>DeepSeek Thinking</span>
            <select v-model="codeThinkingMode">
              <option value="default">服务端默认</option>
              <option value="enabled">开启</option>
              <option value="disabled">关闭</option>
            </select>
            <small>AutoRealize 文本生成可使用；结构化 JSON 默认会关闭 thinking 以提升稳定性。</small>
          </label>
          <label>
            <span>Reasoning Effort</span>
            <select v-model="local.llm.codeModel.reasoningEffort">
              <option value="high">high</option>
              <option value="max">max</option>
            </select>
            <small>仅在 DeepSeek thinking 开启时生效；DeepSeek root/v1 会自动切到 beta。</small>
          </label>
        </div>
        <label>
          <span><input type="checkbox" v-model="local.llm.codeModel.structuredDisableThinking" /> 结构化 JSON 输出时关闭 thinking</span>
          <small>用于数据认知分类、探查计划等 Pydantic/JSON 输出，减少无效解释文本和解析失败。</small>
        </label>

        <h4>反馈模型</h4>
        <label><span>模型名</span><input v-model="local.llm.feedbackModel.model" /></label>
        <label><span>Base URL</span><input v-model="local.llm.feedbackModel.baseUrl" /></label>
        <label><span>API Key</span><input v-model="local.llm.feedbackModel.apiKey" /></label>
        <div class="grid2">
          <label>
            <span>DeepSeek Thinking</span>
            <select v-model="feedbackThinkingMode">
              <option value="default">服务端默认</option>
              <option value="enabled">开启</option>
              <option value="disabled">关闭</option>
            </select>
          </label>
          <label>
            <span>Reasoning Effort</span>
            <select v-model="local.llm.feedbackModel.reasoningEffort">
              <option value="high">high</option>
              <option value="max">max</option>
            </select>
          </label>
        </div>

        <h4>VLLM 视觉模型</h4>
        <label><span>模型名</span><input v-model="local.llm.vllm.model" /></label>
        <label><span>Base URL</span><input v-model="local.llm.vllm.baseUrl" /></label>
        <label><span>API Key</span><input v-model="local.llm.vllm.apiKey" /></label>

        <h4>MLEvolve 向量化模型配置</h4>
        <label>
          <span>Embedding 模型名</span>
          <input v-model="local.mlevolve.embeddingModel" placeholder="例如 text-embedding-v4" />
          <small>作用：远程 embedding 模型名，仅在 embedding 类型为远程 API 时使用。</small>
        </label>
        <label>
          <span>Embedding Base URL</span>
          <input v-model="local.mlevolve.embeddingBaseUrl" placeholder="例如 https://dashscope.aliyuncs.com/compatible-mode/v1" />
          <small>作用：远程 embedding 服务地址，仅在 embedding 类型为远程 API 时使用。</small>
        </label>
        <label>
          <span>Embedding API Key</span>
          <input v-model="local.mlevolve.embeddingApiKey" placeholder="远程 embedding 服务密钥" />
          <small>作用：远程 embedding 鉴权密钥，仅在 embedding 类型为远程 API 时使用。</small>
        </label>

        <h4>Core 服务编排</h4>
        <label><span>AutoRealize Base URL</span><input v-model="local.coreServices.autoRealizeBaseUrl" placeholder="http://127.0.0.1:18101" /></label>
        <label><span>AutoML Base URL</span><input v-model="local.coreServices.autoMlBaseUrl" placeholder="http://127.0.0.1:18102" /></label>
        <label><span>MLEvolve Base URL</span><input v-model="local.coreServices.mlevolveBaseUrl" placeholder="http://127.0.0.1:18103" /></label>
        <label><span>请求超时(秒)</span><input type="number" min="1" v-model.number="local.coreServices.requestTimeoutSecs" /></label>

        <h4>MLEvolve 全局配置</h4>
        <label>
          <span>Torch Hub 目录</span>
          <input v-model="local.mlevolve.torchHubDir" placeholder="例如 D:\\model_cache\\torch_hub 或 /data/torch_hub" />
          <small>作用：PyTorch Hub 缓存目录，减少重复下载和外网依赖。</small>
        </label>
        <label>
          <span>预训练模型目录</span>
          <input v-model="local.mlevolve.pretrainModelDir" placeholder="例如 D:\\pretrain_models 或 /data/pretrain_models" />
          <small>作用：本地预训练权重仓库，便于离线/内网加载模型。</small>
        </label>
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
  width: min(860px, 95vw);
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

.body {
  padding: 12px;
  overflow: auto;
  display: grid;
  gap: 10px;
}

.grid2 {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
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

button.primary {
  background: #1f5db0;
  border-color: #1f5db0;
  color: #fff;
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
</style>
