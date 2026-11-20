<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import Icon from '../components/Icon.vue'
import { ui, request, run, refresh, toast } from './store'
import { resourceSummary } from './presentation'
const settings = ref<any>(),
  readiness = ref<any>(),
  inventory = ref<any>(),
  resourcesError = ref(''),
  envs = ref<{ path: string; version: string }[]>([]),
  settingsFormError = ref('')
const roles = [
  ['autoRealize', '数据分析（要求多模态模型）'],
  ['autoMlCode', '算法编码'],
  ['autoMlFeedback', '评审与报告'],
  ['promptOptimizer', '研发提示词优化'],
  ['embedding', '搜索经验检索（向量模型，可选）'],
]
const resourceItems = computed(() => resourceSummary(inventory.value))
async function load() {
  await run('settings', async () => {
    settings.value = await request('/settings/global')
  })
}
onMounted(load)
async function save() {
  await run('settings-save', async () => {
    await request('/settings/global', settings.value, 'PUT')
    settings.value = await request('/settings/global')
    toast('设置已保存')
  })
}
async function check() {
  await run('readiness', async () => {
    readiness.value = await request('/system/readiness')
  })
}
async function resources() {
  await run('resources', async () => {
    resourcesError.value = ''
    try {
      inventory.value = await request('/resources/inventory')
    } catch (e) {
      resourcesError.value = String(e)
    }
  })
}
async function environments() {
  await run('envs', async () => {
    envs.value = await request(
      `/python/environments?current=${encodeURIComponent(settings.value.python.executable)}`,
    )
  })
}
async function probe(role: string) {
  await run('probe', async () => {
    await request('/system/probe-model', { role, capability: role === 'autoRealize' ? 'image' : 'text' })
    toast(role === 'autoRealize' ? '图像请求测试通过' : '连接测试通过')
  })
}
function token() {
  if (ui.token) sessionStorage.setItem('studio.token', ui.token)
  else sessionStorage.removeItem('studio.token')
  refresh()
}
async function reconnect() {
  token()
  await load()
}
function addModel() {
  settings.value.llm.modelLibrary.push({
    id: crypto.randomUUID(),
    name: '新模型',
    model: '',
    baseUrl: '',
    apiKey: '',
    thinkingMode: 'default',
  })
}
</script>
<template>
  <section class="live-page">
    <div class="page-heading">
      <div>
        <h1>设置</h1>
      </div>
      <button class="btn secondary" :disabled="!!ui.busy" @click="load"><Icon name="refresh" />刷新</button>
    </div>
    <form v-if="settings" class="live-form" @submit.prevent="settingsFormError = ''; save()" @invalid.capture="settingsFormError = '请补齐标记为必填的配置后再保存；API Key 留空表示保留已配置密钥。'">
      <p v-if="settingsFormError" class="live-error" role="alert">{{ settingsFormError }}</p>
      <section class="live-panel">
        <div class="panel-heading">
          <h2>模型配置</h2>
          <button type="button" class="btn secondary small" @click="addModel">
            <Icon name="plus" />添加模型
          </button>
        </div>
        <div v-for="m in settings.llm.modelLibrary" :key="m.id" class="model-editor">
          <div class="live-grid two">
            <label>显示名称<input v-model="m.name" required /></label
            ><label>模型 ID<input v-model="m.model" required /></label
            ><label>API 地址<input v-model="m.baseUrl" required placeholder="https://.../v1" /></label
            ><label
              >API Key<input
                v-model="m.apiKey"
                type="password"
                autocomplete="new-password"
                :placeholder="m.apiKeyConfigured ? '已有密钥；留空保留' : '填写提供方密钥'"
            /></label>
          </div>
          <details>
            <summary>模型高级参数</summary>
            <div class="live-grid two">
              <label
                >思考模式<select v-model="m.thinkingMode">
                  <option value="default">模型默认</option>
                  <option value="enabled">开启</option>
                  <option value="disabled">关闭</option>
                </select></label
              ><label>最大输出 token<input v-model.number="m.maxTokens" type="number" min="1" /></label>
            </div>
          </details>
        </div>
      </section>
      <section class="live-panel">
        <h2>角色模型分配</h2>
        <div class="live-grid two">
          <label v-for="[key, label] in roles" :key="key"
            >{{ label
            }}<select v-model="settings.llm.roleModels[key]">
              <option v-if="key === 'embedding'" value="">不启用</option>
              <option v-for="m in settings.llm.modelLibrary" :key="m.id" :value="m.id">
                {{ m.name }} · {{ m.model }}
              </option>
            </select></label
          >
        </div>
      </section>
      <section class="live-panel">
        <h2>运行环境</h2>
        <label>Python 解释器绝对路径<input v-model="settings.python.executable" required /></label
        ><button type="button" class="btn secondary small" :disabled="!!ui.busy" @click="environments">
          发现本机 Python 环境</button
        ><button
          v-for="e in envs"
          :key="e.path"
          type="button"
          class="live-list-row"
          @click="settings.python.executable = e.path"
        >
          {{ e.path }} · {{ e.version }}
        </button>
      </section>
      <details class="live-panel">
        <summary>本地服务与访问</summary>
        <div class="live-form">
          <label>本地访问令牌<input v-model="ui.token" type="password" autocomplete="off" /></label>
          <button type="button" class="btn secondary small" @click="token">应用访问令牌</button>
          <div v-if="settings.coreServices" class="live-grid two">
            <label>数据理解服务地址<input v-model="settings.coreServices.autoRealizeBaseUrl" /></label>
            <label>方案搜索服务地址<input v-model="settings.coreServices.algoEvolveBaseUrl" /></label>
            <label>报告服务地址<input v-model="settings.coreServices.autoReportBaseUrl" /></label>
            <label>请求超时（秒）<input v-model.number="settings.coreServices.requestTimeoutSecs" type="number" min="1" /></label>
          </div>
          <details class="developer-details">
            <summary>开发者配置原文</summary>
            <pre>{{ JSON.stringify(settings.coreServices || {}, null, 2) }}</pre>
          </details>
        </div>
      </details>
      <button class="btn primary" :disabled="!!ui.busy" :title="ui.busy ? '当前正在处理上一项操作' : '保存全部模型、角色分配、运行环境与本地服务设置'">保存设置</button>
    </form>
    <section v-else-if="!ui.busy" class="live-panel live-form">
      <label>本地访问令牌<input v-model="ui.token" type="password" autocomplete="off" /></label>
      <button class="btn secondary small" @click="reconnect">应用访问令牌并重试</button>
    </section>
    <section class="live-panel">
      <div class="panel-heading">
        <h2>环境检查</h2>
        <button class="btn secondary small" :disabled="!!ui.busy" @click="check">检查</button>
      </div>
      <div v-for="c in readiness?.checks" :key="c.key" class="check-row">
        <span
          class="tag"
          :class="c.status === 'pass' ? 'success' : c.status === 'fail' ? 'warning' : 'neutral'"
          >{{ c.status === 'pass' ? '通过' : c.status === 'fail' ? '需处理' : '未检查' }}</span
        >
        <div>
          <strong>{{ c.label }}</strong>
          <p>{{ c.detail }}</p>
        </div>
      </div>
      <details>
        <summary>模型连接测试（会调用 API）</summary>
        <div class="form-actions">
          <button
            v-for="[role, label] in roles.slice(0, 4)"
            :key="role"
            class="btn secondary small"
            :disabled="!!ui.busy"
            @click="probe(role)"
          >
            测试 {{ label }}
          </button>
        </div>
      </details>
    </section>
    <section class="live-panel">
      <div class="panel-heading">
        <h2>计算资源</h2>
        <button class="btn secondary small" :disabled="!!ui.busy" @click="resources">检测资源</button>
      </div>
      <p v-if="resourcesError" class="live-error">{{ resourcesError }}</p>
      <dl v-if="inventory" class="summary-list">
        <div v-for="item in resourceItems" :key="item.label + item.value">
          <dt>{{ item.label }}</dt><dd>{{ item.value }}</dd>
        </div>
      </dl>
      <p v-else class="hint">尚未检测</p>
    </section>
  </section>
</template>
