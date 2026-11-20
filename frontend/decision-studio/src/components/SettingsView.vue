<script setup lang="ts">
import { reactive } from 'vue'
import Icon from './Icon.vue'
import { state, toast, openDialog, download } from '../store'
const draft = reactive({ ...state.settings })
function save() {
  state.settings = { ...draft }
  toast('已保存本浏览器的演示配置；未连接真实运行器')
}
</script>
<template>
  <div class="standard-page settings-page">
    <div class="page-heading">
      <div>
        <div class="eyebrow">LOCAL BY DESIGN</div>
        <h1>工作空间设置</h1>
        <p>按你的环境部署，用自己的算力执行。当前仅保存演示配置。</p>
      </div>
    </div>
    <form @submit.prevent="save">
      <section class="settings-card">
        <div class="settings-section-heading">
          <span class="square-icon"><Icon name="cpu" :size="22" /></span>
          <div>
            <h2>本地运行器</h2>
            <p>规划任务的计算资源与并发额度。</p>
          </div>
          <span class="tag neutral">未连接 · 演示配置</span>
        </div>
        <div class="form-grid">
          <label
            >运行环境<select v-model="draft.runner">
              <option>本机 · CPU</option>
              <option>本机 · GPU（规划）</option>
              <option>本地 Docker（规划）</option>
            </select></label
          ><label
            >并发任务数<select v-model.number="draft.concurrency">
              <option :value="1">1 个任务</option>
              <option :value="2">2 个任务</option>
              <option :value="4">4 个任务</option>
            </select></label
          ><label
            >可用 CPU 核心<input v-model.number="draft.cpu" type="number" min="1" max="256" required /></label
          ><label
            >内存预算（GB）<input v-model.number="draft.memory" type="number" min="2" max="1024" required
          /></label>
        </div>
        <p class="hint">这些字段不会启动容器或检测硬件；真实资源预检与调度将在后端适配阶段接入。</p>
      </section>
      <section class="settings-card">
        <div class="settings-section-heading">
          <span class="square-icon blue"><Icon name="sparkles" :size="22" /></span>
          <div>
            <h2>决策助手</h2>
            <p>预留模型服务与需求路由配置。</p>
          </div>
        </div>
        <div class="static-field">
          <span>当前响应来源</span><strong>演示响应器</strong><span class="tag neutral">无 API 请求</span>
        </div>
        <p class="hint">此版本按预设关键词选择场景，不进行真实 LLM 推理。界面不接收或存储 API 密钥。</p>
        <div class="setting-toggle">
          <div>
            <strong>创建研发任务前确认资源预算</strong>
            <p>当前演示始终需要显式确认；后续接入真实计算时继续保留。</p>
          </div>
          <span class="tag success"><Icon name="check" :size="12" />已启用</span>
        </div>
      </section>
      <div class="settings-save">
        <span class="hint">配置仅保存在当前浏览器。</span
        ><button type="submit" class="btn primary">保存演示配置</button>
      </div>
    </form>
    <section class="settings-card">
      <div class="settings-section-heading">
        <span class="square-icon"><Icon name="folder" :size="22" /></span>
        <div>
          <h2>演示与本地数据</h2>
          <p>Decision Studio 0.1.0 · 独立前端原型</p>
        </div>
      </div>
      <div class="setting-toggle">
        <div>
          <strong>导出工作空间快照</strong>
          <p>包含当前模拟项目、会话、任务、模型包与调用记录。</p>
        </div>
        <button
          class="btn secondary small"
          @click="download('studio-workspace-demo.json', { demo: true, ...state })"
        >
          <Icon name="download" :size="14" />导出 JSON
        </button>
      </div>
      <div class="setting-toggle">
        <div>
          <strong>重置演示</strong>
          <p>清除本 Demo 的浏览器状态并恢复初始样例。</p>
        </div>
        <button class="btn danger small" @click="openDialog('reset')">重置演示数据</button>
      </div>
    </section>
  </div>
</template>
