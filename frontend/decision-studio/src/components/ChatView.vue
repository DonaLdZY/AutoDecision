<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import Icon from './Icon.vue'
import InvocationCard from './InvocationCard.vue'
import {
  state,
  ui,
  project,
  packages,
  tasks,
  conversation,
  runningCount,
  getInvocation,
  getPackage,
  sendMessage,
  openDialog,
  navigate,
  startResearch,
  confirmMapping,
  download,
} from '../store'
const input = ref('')
const unit = ref('kW')
const scroller = ref<HTMLElement>()
const textarea = ref<HTMLTextAreaElement>()
const suggestions = computed(() =>
  project.value.id === 'water'
    ? ['预测明天的分区用水需求', '寻找管网泄漏定位算法', '优化明天的供水调度']
    : ['预测明天的用电负荷', '排查设备能耗异常', '预测设备剩余寿命'],
)
const pinned = computed(() => getPackage(ui.pinnedPackageId))
onMounted(async () => {
  await nextTick()
  scroller.value?.scrollTo({ top: scroller.value.scrollHeight, behavior: 'instant' })
})
async function send(text = input.value) {
  if (!text.trim() || ui.busyId) return
  input.value = ''
  await sendMessage(text)
  await nextTick()
  scroller.value?.scrollTo({ top: scroller.value.scrollHeight, behavior: 'smooth' })
  textarea.value?.focus()
}
function keydown(e: KeyboardEvent) {
  if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) {
    e.preventDefault()
    send()
  }
}
watch(
  () => [conversation.value.id, conversation.value.messages.length, ui.busyId],
  async () => {
    await nextTick()
    scroller.value?.scrollTo({ top: scroller.value.scrollHeight, behavior: 'smooth' })
  },
)
</script>
<template>
  <div class="chat-layout">
    <section class="chat-column">
      <div class="conversation-heading">
        <div class="eyebrow">
          <span class="status-dot" /> {{ project.short }}
        </div>
        <div class="conversation-title">
          <h1>{{ conversation.messages.length ? conversation.title : '决策对话' }}</h1>
          <button
            class="icon-btn"
            aria-label="导出当前对话"
            @click="download('conversation-demo.json', { demo: true, ...conversation })"
          >
            <Icon name="download" :size="17" />
          </button>
        </div>
      </div>
      <div ref="scroller" class="message-scroll">
        <div v-if="!conversation.messages.length" class="chat-empty">
          <div class="empty-orbit"><Icon name="sparkles" :size="32" /></div>
          <h2>{{ pinned ? `使用「${pinned.name}」` : '新建对话' }}</h2>
          <p v-if="pinned">{{ pinned.description }}</p>
          <div class="starter-grid">
            <button v-for="(s, i) in suggestions" :key="s" @click="send(s)">
              <Icon :name="['chart', 'workflow', 'flask'][i]" :size="21" /><strong>{{ s }}</strong>
              <Icon name="arrow" :size="16" />
            </button>
          </div>
        </div>
        <div v-for="message in conversation.messages" :key="message.id" class="message" :class="message.role">
          <template v-if="message.role === 'user'"
            ><div class="user-bubble">{{ message.text }}</div>
            <div class="avatar user-avatar">D</div></template
          >
          <template v-else
            ><div class="assistant-avatar"><img src="/favicon.svg" alt="AutoDecision" /></div>
            <div class="assistant-content">
              <div class="assistant-label">AutoDecision <span>决策助手</span></div>
              <p class="message-text">{{ message.text }}</p>
              <div v-if="message.kind === 'result' && getInvocation(message.invocationId)">
                <div class="reuse-proof">
                  <Icon name="checkCircle" :size="14" /> 已匹配可复用能力 <span>·</span> 无需新增训练
                </div>
                <InvocationCard :invocation="getInvocation(message.invocationId)!" />
              </div>
              <div v-if="message.kind === 'research'" class="action-card research-card">
                <div class="action-heading">
                  <span class="square-icon amber"><Icon name="flask" :size="20" /></span>
                  <div>
                    <h3>{{ message.capability }}</h3>
                    <p>研发新能力 · 完成后可发布模型包</p>
                  </div>
                  <span class="tag warning">{{ message.resolved ? '任务已建立' : '能力缺口' }}</span>
                </div>
                <div class="research-plan">
                  <span>01 确认目标与数据</span><Icon name="arrow" :size="12" /><span>02 搜索候选算法</span
                  ><Icon name="arrow" :size="12" /><span>03 验证与打包</span>
                </div>
                <div class="budget-line">
                  <Icon name="cpu" :size="15" /> 本地 CPU <span>最多 16 个候选</span><span>30 分钟预算</span>
                </div>
                <footer>
                  <small>本次为交互演示，不产生计算或 API 费用。</small
                  ><button v-if="!message.resolved" class="btn primary small" @click="startResearch(message)">
                    创建研发任务<Icon name="arrow" :size="14" /></button
                  ><button v-else class="btn secondary small" @click="openDialog('task', message.taskId)">
                    查看研发任务<Icon name="arrow" :size="14" />
                  </button>
                </footer>
              </div>
              <div v-if="message.kind === 'mapping'" class="action-card">
                <div class="action-heading">
                  <span class="square-icon"><Icon name="sliders" :size="20" /></span>
                  <div>
                    <h3>确认输入对齐</h3>
                    <p>源字段 power_kw → 模型字段 load_mw</p>
                  </div>
                </div>
                <label class="mapping-control"
                  >源字段的实际单位<select v-model="unit" :disabled="message.resolved">
                    <option>kW</option>
                    <option>MW</option>
                    <option>kWh</option>
                  </select></label
                >
                <p class="hint">
                  {{
                    unit === 'kW'
                      ? '换算规则：load_mw = power_kw ÷ 1000。保留时间索引与采样间隔。'
                      : unit === 'MW'
                        ? '仅重命名字段；源数据的实际单位须确认为 MW。'
                        : 'kWh 表示能量，不能直接作为功率输入；此映射会被阻止。'
                  }}
                </p>
                <footer>
                  <span class="hint"><Icon name="lock" :size="13" />模型权重与特征定义冻结</span
                  ><button
                    class="btn primary small"
                    :disabled="message.resolved"
                    @click="confirmMapping(message, unit)"
                  >
                    {{ message.resolved ? '已确认并调用' : '确认对齐并调用' }}
                  </button>
                </footer>
              </div>
              <div v-if="message.kind === 'clarify'" class="clarify-actions">
                <button class="btn secondary small" @click="navigate('projects')">查看项目数据</button
                ><button class="btn secondary small" @click="navigate('packages')">查看可用模型包</button>
              </div>
            </div></template
          >
        </div>
        <div v-if="ui.busyId === conversation.id" class="typing-message" role="status">
          <img src="/favicon.svg" alt="" /><span class="typing-dots"><i /><i /><i /></span
          ><span>正在匹配演示场景与项目能力…</span>
        </div>
      </div>
      <div class="composer-area">
        <div class="suggestion-row">
          <span>试着问</span
          ><button v-for="s in suggestions" :key="s" :disabled="!!ui.busyId" @click="send(s)">
            {{ s }}<Icon name="up" :size="12" />
          </button>
        </div>
        <form class="composer" @submit.prevent="send()">
          <div v-if="pinned" class="pinned-package">
            <Icon name="package" :size="14" />已选择 {{ pinned.name }} · v{{ pinned.version
            }}<button
              type="button"
              class="icon-btn"
              aria-label="移除指定模型包"
              @click="ui.pinnedPackageId = ''"
            >
              <Icon name="x" :size="13" />
            </button>
          </div>
          <label class="sr-only" for="chat-input">决策需求</label
          ><textarea
            id="chat-input"
            ref="textarea"
            v-model="input"
            rows="2"
            placeholder="描述你的目标，让已有的决策能力为你工作…"
            @keydown="keydown"
          />
          <div class="composer-toolbar">
            <div>
              <button type="button" class="context-pill" @click="openDialog('data')">
                <Icon name="database" :size="14" />项目数据 <span>{{ project.tables.length }} 张表</span
                ><Icon name="chevron" :size="12" /></button
              ><button type="button" class="context-pill" @click="navigate('packages')">
                <Icon name="package" :size="14" />选择模型包
              </button>
            </div>
            <div>
              <span class="composer-mode"><i class="status-dot" />自动匹配</span
              ><button
                class="send-button"
                type="submit"
                :disabled="!input.trim() || !!ui.busyId"
                aria-label="发送需求"
              >
                <Icon :name="ui.busyId ? 'loader' : 'up'" :size="19" :class="{ spin: !!ui.busyId }" />
              </button>
            </div>
          </div>
        </form>
        <div class="composer-caption">
          Enter 发送 · Shift + Enter 换行 <span>演示响应与结果均为模拟，未连接模型或任务后端</span>
        </div>
      </div>
    </section>
    <aside class="context-rail">
      <div class="rail-label">对话上下文<Icon name="sliders" :size="15" /></div>
      <div class="rail-project">
        <span class="square-icon"><Icon :name="project.icon" :size="22" /></span>
        <h3>{{ project.name }}</h3>
        <p>{{ project.industry }}<i />{{ project.tables.length }} 个数据源</p>
        <button class="text-btn" @click="navigate('projects')">
          查看数据项目<Icon name="arrow" :size="14" />
        </button>
      </div>
      <div class="rail-section">
        <div class="rail-section-title">
          <h3>已连接的数据</h3>
          <span>{{ project.tables.length }}</span>
        </div>
        <button
          v-for="table in project.tables"
          :key="table.name"
          class="rail-table"
          @click="openDialog('data')"
        >
          <Icon name="table" :size="16" />
          <div>
            <strong>{{ table.title }}</strong
            ><span>{{ table.rows }} 行 · 合成示例</span>
          </div>
          <i class="status-dot" />
        </button>
        <p v-if="!project.tables.length" class="hint">尚未添加数据</p>
      </div>
      <div class="rail-section">
        <div class="rail-section-title">
          <h3>可复用能力</h3>
          <span>{{ packages.length }}</span>
        </div>
        <button
          v-for="pkg in packages.slice(0, 4)"
          :key="pkg.id"
          class="rail-package"
          @click="openDialog('package', pkg.id)"
        >
          <span
            :class="[
              'mini-icon',
              pkg.scenario === 'compose' ? 'blue' : pkg.scenario === 'anomaly' ? 'amber' : '',
            ]"
            ><Icon :name="pkg.icon" :size="16"
          /></span>
          <div>
            <strong>{{ pkg.name }}</strong
            ><span>v{{ pkg.version }} · {{ pkg.kind }}</span>
          </div>
          <Icon name="right" :size="13" /></button
        ><button class="text-btn rail-more" @click="navigate('packages')">
          浏览模型包<Icon name="arrow" :size="14" />
        </button>
      </div>
      <div v-if="runningCount" class="rail-running">
        <div>
          <span class="pulse-dot" /><strong>{{ runningCount }} 个任务正在研发</strong
          ><Icon name="branch" :size="15" />
        </div>
        <p>{{ tasks.find((t) => t.status === 'running')?.title || '任务排队中' }}</p>
        <div class="progress-track">
          <span :style="{ width: (tasks.find((t) => t.status === 'running')?.progress || 0) + '%' }" />
        </div>
        <button class="text-btn" @click="navigate('tasks')">
          查看任务进度<Icon name="arrow" :size="14" />
        </button>
      </div>
      <div class="rail-note">
        <Icon name="shield" :size="17" />
        <p>每次调用都有据可查<br /><span>数据快照、包版本与执行步骤随结果保存。</span></p>
      </div>
    </aside>
  </div>
</template>
