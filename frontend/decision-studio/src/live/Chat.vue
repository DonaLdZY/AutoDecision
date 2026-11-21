<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import Icon from '../components/Icon.vue'
import Modal from './Modal.vue'
import InvokeForm from './InvokeForm.vue'
import ResearchForm from './ResearchForm.vue'
import ChatResult from './ChatResult.vue'
import MarkdownView from './MarkdownView.vue'
import ConversationMenu from './ConversationMenu.vue'
import DegradationCard from './DegradationCard.vue'
import { projectDescription, usageSummary } from './presentation'
import {
  state,
  ui,
  project,
  chatDrafts,
  conversations,
  packages,
  tasks as allTasks,
  taskProjectId,
  conversation,
  request,
  refresh,
  run,
  newConversation,
  openNewConversation,
  navigate,
  download,
  phase,
} from './store'
import type { Message, Plan } from './store'
const emit = defineEmits<{ open: [kind: string, id: string] }>()
const input = computed({
    get: () => chatDrafts[ui.conversationId || `new:${ui.projectId}`] || '',
    set: (value: string) => {
      chatDrafts[ui.conversationId || `new:${ui.projectId}`] = value
    },
  }),
  scroller = ref<HTMLElement>(),
  packagePickerOpen = ref(false),
  packageQuery = ref(''),
  plan = ref<Plan | null>(null),
  research = ref(''),
  researchPlan = ref<Plan | null>(null)
const selected = computed(() => packages.value.find((p) => p.id === ui.packageId))
const suggestions = computed(() => {
  const ids = conversation.value?.task_ids || []
  const headline = ids.map((id) => state.research_briefs?.[id]?.headline).find(Boolean)
  if (!ids.length) return ['这份数据能做哪些研究？', '有哪些可以复用的算法包？']
  return [
    ...(headline ? [`为什么说「${headline}」？`] : ['主要结论是什么？']),
    '这些结论的依据在哪里？',
    '下一步该怎么做？',
  ]
})
// 从这段对话发起、遇到需求降级的研究计划，降级确认显示在对话里。
const degradations = computed(() => {
  const id = conversation.value?.id
  if (!id) return []
  const own = new Set(state.links.filter((l) => l.conversation_id === id).map((l) => l.id))
  return state.tasks.filter((t) => own.has(t.id) && t.degradation)
})
// 对话页只看当前对话所属数据下的研究计划。
const tasks = computed(() => allTasks.value.filter((t) => taskProjectId(t.id) === ui.projectId))
const basedOn = computed(() =>
  (conversation.value?.task_ids || []).map((id) => state.tasks.find((t) => t.id === id)?.task_name).filter(Boolean),
)
const filteredPackages = computed(() => {
  const query = packageQuery.value.trim().toLocaleLowerCase()
  if (!query) return packages.value
  return packages.value.filter((p) =>
    `${p.name} ${p.description} ${p.task_name || ''}`.toLocaleLowerCase().includes(query),
  )
})
function choosePackage(id: string) {
  ui.packageId = id
  packagePickerOpen.value = false
  packageQuery.value = ''
}
function clearPackage() {
  ui.packageId = ''
  packagePickerOpen.value = false
}
function openPackages() {
  packagePickerOpen.value = false
  navigate('packages')
}
const publishedCapabilityNotice = computed(() => {
  if (!packages.value.length) return null
  const staleCount = conversation.value?.messages.filter(isStaleCapabilityMessage).length || 0
  return { staleCount }
})
function isStaleCapabilityMessage(message: Message) {
  if (message.role !== 'assistant' || !packages.value.length) return false
  const text = message.text || ''
  const saysNoCapability =
    /(没有(?:任何)?可复用|没有可复用|无可复用|无法直接复用|不能直接当模型复用|不具备直接研发|没有任何可复用的算法能力)/.test(
      text,
    )
  if (!saysNoCapability) return false
  const createdAt = message.created_at || 0
  const packageCreatedAt = Math.min(...packages.value.map((item) => item.created_at).filter(Number.isFinite))
  return !createdAt || !Number.isFinite(packageCreatedAt) || createdAt < packageCreatedAt
}
function openCurrentPackages() {
  navigate('packages')
}
const pendingRequest = ref<{ id: string; text: string; conversation: string } | null>(null)
watch(
  () => ui.conversationId,
  () => {
    pendingRequest.value = null
    plan.value = null
    research.value = ''
    researchPlan.value = null
  },
)
async function send() {
  if (!input.value.trim() || ui.busy || !project.value) return
  const text = input.value.trim()
  if (!conversation.value) await newConversation()
  const c = conversation.value
  if (!c) return
  chatDrafts[c.id] = text
  await run('chat', async () => {
    const requestId =
      pendingRequest.value?.text === text && pendingRequest.value.conversation === c.id
        ? pendingRequest.value.id
        : crypto.randomUUID()
    pendingRequest.value = { id: requestId, text, conversation: c.id }
    try {
      await request(`/studio/conversations/${c.id}/messages`, {
        text,
        request_id: requestId,
        mode: ui.chatMode,
        package_id: ui.packageId,
      })
      delete chatDrafts[c.id]
      delete chatDrafts[`new:${c.project_id}`]
      if (pendingRequest.value?.conversation === c.id) pendingRequest.value = null
    } finally {
      await refresh()
    }
  })
}
watch(
  () => [conversation.value?.id, conversation.value?.messages.length, ui.busy],
  async () => {
    await nextTick()
    scroller.value?.scrollTo({ top: scroller.value.scrollHeight, behavior: 'smooth' })
  },
)
function publicationCandidates(message: Message) {
  return (message.publication_candidates || []).filter(
    (candidate) =>
      tasks.value.some((task) => task.id === candidate.task_id) &&
      !packages.value.some((pkg) => pkg.task_id === candidate.task_id),
  )
}
function execute(p: Plan) {
  plan.value = p
}
function invoked(id: string) {
  plan.value = null
  emit('open', 'invocation', id)
}
function openResearch(goal: string, nextPlan: Plan | null = null) {
  research.value = goal
  researchPlan.value = nextPlan
}
function researchFromMessage(message: Message) {
  const messages = conversation.value?.messages || []
  const index = messages.findIndex((item) => item.id === message.id)
  const latestUserRequest = messages
    .slice(0, Math.max(index, 0))
    .reverse()
    .find((item) => item.role === 'user')?.text
  openResearch(message.plan?.goal || latestUserRequest || message.text, message.plan || null)
}
function closeResearch() {
  research.value = ''
  researchPlan.value = null
}
function researchDone(id: string) {
  closeResearch()
  emit('open', 'task', id)
}
function handleComposerKeydown(event: KeyboardEvent) {
  if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
    event.preventDefault()
    void send()
  }
}
</script>
<template>
  <div class="chat-layout">
    <section class="chat-column">
      <div
        class="conversation-workspace"
        role="region"
        id="decision-conversation-panel"
        :aria-label="conversation?.title || '对话'"
      >
        <div class="conversation-heading">
          <div class="eyebrow">
            {{ project?.name || 'AutoDecision'
            }}<template v-if="basedOn.length"> · 基于 {{ basedOn.join('、') }}</template>
          </div>
          <div class="conversation-title">
            <h1 :title="conversation?.title">{{ conversation?.title || '对话' }}</h1>
            <button
              class="icon-btn"
              :disabled="!conversation"
              aria-label="导出当前对话"
              @click="download('conversation.json', conversation)"
            >
              <Icon name="download" />
            </button>
            <ConversationMenu v-if="conversation" :item="conversation" label="当前对话操作" />
          </div>
        </div>
        <div ref="scroller" class="message-scroll">
          <div v-if="publishedCapabilityNotice" class="chat-capability-banner" role="status">
            <div class="chat-capability-icon"><Icon name="package" :size="18" /></div>
            <div class="chat-capability-copy">
              <strong>当前项目已有 {{ packages.length }} 个已发布算法包，可直接复用</strong>
              <p v-if="publishedCapabilityNotice.staleCount">
                本对话中有
                {{ publishedCapabilityNotice.staleCount }}
                条消息是在发布前生成的旧状态；其中“没有可复用能力”的判断已被当前能力目录纠正，不能作为现在的结论。
              </p>
              <p v-else>当前能力目录已更新；如果要调用，请先核对算法包输入与预测基准。</p>
            </div>
            <button type="button" class="btn secondary small" @click="openCurrentPackages">
              查看当前算法包<Icon name="arrow" />
            </button>
          </div>
          <div v-if="!conversation?.messages.length" class="chat-empty">
            <div class="empty-project-mark"><Icon name="workflow" :size="30" /></div>
            <h2>{{ conversation ? project?.name || '数据项目' : '开始一段对话' }}</h2>
            <p v-if="selected">已选择 {{ selected.name }}</p>
            <p v-else-if="basedOn.length">基于 {{ basedOn.join('、') }}</p>
            <button v-if="!state.projects.length" class="btn primary" @click="navigate('projects')">
              导入项目数据<Icon name="arrow" />
            </button>
            <button v-else-if="!conversation" class="btn primary" @click="openNewConversation()">
              新建对话<Icon name="arrow" />
            </button>
            <div v-else-if="!basedOn.length" class="starter-grid">
              <button v-if="packages.length" type="button" @click="openCurrentPackages">
                <Icon name="package" :size="22" /><strong>查看可用算法包</strong>
              </button>
              <button v-else type="button" @click="input = '这个项目有哪些可以复用的决策能力？'">
                <Icon name="package" :size="22" /><strong>查询可复用能力</strong>
              </button>
              <button type="button" @click="openResearch('为该项目开展新的研究')">
                <Icon name="flask" :size="22" /><strong>新建研究计划</strong>
              </button>
            </div>
          </div>
          <div v-for="m in conversation?.messages || []" :key="m.id" class="message" :class="m.role">
            <template v-if="m.role === 'user'"
              ><div class="user-bubble">{{ m.text }}</div>
              <div class="avatar user-avatar">D</div></template
            ><template v-else
              ><div class="assistant-avatar"><img src="/favicon.svg" alt="" /></div>
              <div class="assistant-content">
                <div class="assistant-label">AutoDecision</div>
                <div v-if="isStaleCapabilityMessage(m)" class="message-correction-note" role="note">
                  <Icon name="refresh" :size="14" /><span
                    >历史状态：这条消息生成于算法包发布前，当前能力目录已经更新。</span
                  >
                  <button type="button" class="text-btn" @click="openCurrentPackages">查看当前算法包</button>
                </div>
                <MarkdownView :text="m.text" class="message-text" />
                <div
                  v-if="m.plan && (m.plan.action !== 'clarify' || m.plan.steps.length || m.plan.missing_inputs.length)"
                  class="action-card"
                >
                  <div class="action-heading">
                    <span class="square-icon"
                      ><Icon :name="m.plan.action === 'research' ? 'flask' : 'workflow'"
                    /></span>
                    <div>
                      <h3>
                        {{
                          m.plan.action === 'reuse'
                            ? '建议复用以下算法包'
                            : m.plan.action === 'research'
                              ? '新建研究计划'
                              : '补充输入与目标'
                        }}
                      </h3>
                    </div>
                  </div>
                  <div v-for="(step, i) in m.plan.steps" :key="i" class="plan-step">
                    <span>{{ i + 1 }}</span>
                    <div>
                      <button class="text-btn" @click="emit('open', 'package', step.package_id)">
                        {{ state.packages.find((p) => p.id === step.package_id)?.name || step.package_id }}
                      </button>
                      <p>{{ step.reason }}</p>
                    </div>
                  </div>
                  <p v-if="m.plan.missing_inputs.length" class="hint">
                    需要补充：{{ m.plan.missing_inputs.join('；') }}
                  </p>
                  <footer>
                    <button
                      v-if="m.plan.action === 'reuse'"
                      class="btn primary small"
                      @click="execute(m.plan)"
                    >
                      核对输入并调用<Icon name="arrow" /></button
                    ><button
                      v-else-if="m.plan.action === 'research'"
                      class="btn primary small"
                      @click="researchFromMessage(m)"
                    >
                      配置研究计划</button
                    ><button v-else class="btn secondary small" @click="navigate('packages')">
                      查看算法包</button
                    ><button
                      v-if="m.plan.action !== 'research'"
                      class="btn secondary small"
                      @click="researchFromMessage(m)"
                    >
                      改为新研究<Icon name="flask" :size="14" />
                    </button>
                  </footer>
                </div>
                <div v-if="publicationCandidates(m).length" class="action-card">
                  <h3>已有研究成果待发布</h3>
                  <p>先审核现有交付的用途、输入和试算结果，发布后即可在对话中复用。</p>
                  <div
                    v-for="candidate in publicationCandidates(m)"
                    :key="candidate.task_id"
                    class="plan-step"
                  >
                    <span>{{ candidate.task_name }}</span>
                    <span v-if="candidate.verification_status === 'passed'" class="tag success"
                      >交付试算通过</span
                    >
                    <button class="btn secondary small" @click="emit('open', 'delivery', candidate.task_id)">
                      审核并发布
                    </button>
                  </div>
                </div>
                <ChatResult
                  v-if="m.invocation_id"
                  :id="m.invocation_id"
                  @open="(kind, id) => emit('open', kind, id)"
                />
                <button
                  v-if="m.invocation_id"
                  class="live-list-row"
                  @click="emit('open', 'invocation', m.invocation_id)"
                >
                  <Icon name="workflow" /><strong>查看调用结果</strong><Icon name="right" />
                </button>
                <details v-if="m.usage && Object.keys(m.usage).length" class="usage-detail">
                  <summary>本次用量</summary>
                  <dl class="summary-list compact">
                    <div v-for="item in usageSummary(m.usage)" :key="item.label">
                      <dt>{{ item.label }}</dt>
                      <dd>{{ item.value }}</dd>
                    </div>
                  </dl>
                  <button class="text-btn" @click="download(`usage-${m.id}.json`, m.usage)">
                    导出用量记录
                  </button>
                </details>
              </div></template
            >
          </div>
          <DegradationCard
            v-for="t in degradations"
            :key="t.id"
            :task="t"
            :conversation-id="conversation?.id"
          />
          <div v-if="ui.busy === 'chat'" class="typing-message" role="status">
            <img src="/favicon.svg" alt="" /><span class="typing-dots"><i /><i /><i /></span>正在生成回复…
          </div>
        </div>
        <div class="composer-area">
          <div v-if="conversation" class="suggestion-row">
            <span>试着问</span
            ><button v-for="q in suggestions" :key="q" type="button" :disabled="!!ui.busy" @click="input = q">
              {{ q }}<Icon name="up" :size="12" />
            </button>
          </div>
          <form class="composer" @submit.prevent="send">
            <div v-if="selected" class="pinned-package">
              <Icon name="package" />{{ selected.name }} · v{{ selected.version
              }}<button type="button" class="icon-btn" aria-label="移除指定算法包" @click="ui.packageId = ''">
                <Icon name="x" />
              </button>
            </div>
            <label class="sr-only" for="live-chat">决策需求</label
            ><textarea
              id="live-chat"
              v-model="input"
              :disabled="!project"
              rows="2"
              placeholder="输入问题或目标…"
              @keydown="handleComposerKeydown"
            />
            <div class="composer-toolbar">
              <div>
                <button type="button" class="context-pill" @click="packagePickerOpen = true">
                  <Icon name="package" :size="14" />{{ selected ? '更换指定包' : '指定算法包' }}
                </button>
              </div>
              <div>
                <details class="composer-options">
                  <summary aria-label="对话设置"><Icon name="sliders" :size="16" /></summary>
                  <label for="chat-mode">模型使用</label>
                  <select id="chat-mode" v-model="ui.chatMode">
                    <option value="llm">自动匹配</option>
                    <option value="catalog">手动选择</option>
                  </select>
                </details>
                <button
                  class="send-button"
                  :disabled="!input.trim() || !project || !!ui.busy || !ui.online"
                  aria-label="发送需求"
                  :title="
                    !project
                      ? '请先选择或创建数据项目'
                      : !ui.online
                        ? '本地服务未连接，请先重新连接'
                        : ui.busy
                          ? '当前正在处理上一项操作'
                          : !input.trim()
                            ? '请先填写决策需求'
                            : '发送需求'
                  "
                >
                  <Icon :name="ui.busy === 'chat' ? 'loader' : 'up'" />
                </button>
              </div>
            </div>
            <p v-if="!ui.online" class="composer-hint warning">本地服务未连接</p>
          </form>
        </div>
      </div>
    </section>
    <aside class="context-rail">
      <div class="rail-label">对话上下文<Icon name="sliders" :size="15" /></div>
      <div class="rail-project">
        <span class="square-icon"><Icon name="database" :size="22" /></span>
        <h3>{{ project?.name || '尚未选择项目' }}</h3>
        <p v-if="project">{{ projectDescription(project.description) }}</p>
        <button class="text-btn" @click="navigate('projects')">查看项目数据<Icon name="arrow" /></button>
      </div>
      <div class="rail-section">
        <div class="rail-section-title">
          <h3>可复用算法包</h3>
          <span>{{ packages.length }}</span>
        </div>
        <button v-for="p in packages" :key="p.id" class="rail-table" @click="emit('open', 'package', p.id)">
          <Icon name="package" />
          <div>
            <strong>{{ p.name }}</strong
            ><small>v{{ p.version }}</small>
          </div>
        </button>
      </div>
      <div class="rail-section">
        <div class="rail-section-title">
          <h3>研究计划</h3>
          <span>{{ tasks.length }}</span>
        </div>
        <button
          v-for="t in tasks.slice(0, 5)"
          :key="t.id"
          class="rail-table"
          @click="emit('open', 'task', t.id)"
        >
          <Icon name="branch" />
          <div>
            <strong>{{ t.task_name }}</strong
            ><small>{{ phase(t.phase) }}</small>
          </div></button
        ><button class="text-btn" :disabled="!project" @click="openResearch('为该项目开展新的研究')">
          新建研究计划<Icon name="plus" :size="14" />
        </button>
      </div>
    </aside>
    <Modal v-if="packagePickerOpen" title="指定本次使用的算法包" wide @close="packagePickerOpen = false">
      <div class="package-picker">
        <p>指定后，本次决策只会使用所选算法包；不指定则由系统自动匹配。</p>
        <label class="live-search">
          <Icon name="search" /><input
            v-model="packageQuery"
            aria-label="搜索算法包"
            placeholder="按名称或研究计划搜索"
          />
        </label>
        <div v-if="filteredPackages.length" class="package-picker-list">
          <button
            v-for="p in filteredPackages"
            :key="p.id"
            type="button"
            class="package-picker-option"
            :class="{ selected: ui.packageId === p.id }"
            :aria-pressed="ui.packageId === p.id"
            @click="choosePackage(p.id)"
          >
            <Icon name="package" />
            <span
              ><strong>{{ p.name }}</strong
              ><small>v{{ p.version }} · {{ p.task_name || '已发布算法包' }}</small></span
            >
            <Icon v-if="ui.packageId === p.id" name="check" />
          </button>
        </div>
        <div v-else class="package-picker-empty">
          <p>{{ packages.length ? '没有匹配的算法包。' : '当前项目还没有已发布算法包。' }}</p>
          <button v-if="!packages.length" type="button" class="text-btn" @click="openPackages">
            查看算法包与研究成果<Icon name="arrow" />
          </button>
        </div>
        <footer class="package-picker-footer">
          <button type="button" class="btn secondary small" @click="clearPackage">自动匹配</button>
        </footer>
      </div>
    </Modal>
    <Modal v-if="plan" title="确认模型调用" wide @close="plan = null"
      ><InvokeForm
        :package-ids="plan.steps.map((s) => s.package_id)"
        :suggested-steps="plan.steps"
        :conversation-id="conversation?.id || ''"
        @done="invoked" /></Modal
    ><Modal v-if="research" title="新建研究计划" @close="closeResearch"
      ><ResearchForm
        :goal="research"
        :conversation-id="conversation?.id || ''"
        :package-id="researchPlan?.steps?.[0]?.package_id || ''"
        :plan="researchPlan || undefined"
        @done="researchDone"
    /></Modal>
  </div>
</template>

<style scoped>
.package-picker > p {
  margin: 0 0 14px;
  color: var(--muted);
}
.package-picker-list {
  display: grid;
  gap: 6px;
  max-height: min(52vh, 440px);
  overflow: auto;
  margin-top: 12px;
}
.package-picker-option {
  display: grid;
  grid-template-columns: 20px minmax(0, 1fr) 18px;
  align-items: center;
  gap: 12px;
  width: 100%;
  min-height: 58px;
  padding: 9px 12px;
  border: 1px solid var(--line);
  border-radius: 6px;
  background: var(--surface);
  color: var(--ink);
  text-align: left;
  cursor: pointer;
}
.package-picker-option:hover,
.package-picker-option.selected {
  border-color: var(--primary);
  background: var(--primary-soft);
}
.package-picker-option span {
  display: grid;
  gap: 3px;
  min-width: 0;
}
.package-picker-option strong,
.package-picker-option small {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.package-picker-option small {
  color: var(--muted);
}
.package-picker-empty {
  padding: 22px 8px;
  text-align: center;
}
.package-picker-empty p {
  margin: 0 0 10px;
  color: var(--muted);
}
.package-picker-footer {
  display: flex;
  justify-content: flex-end;
  padding-top: 14px;
  border-top: 1px solid var(--line);
  margin-top: 14px;
}
</style>
