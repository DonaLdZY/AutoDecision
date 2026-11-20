<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref } from 'vue'
import Icon from './Icon.vue'
import PackageDetail from './PackageDetail.vue'
import InvocationDetail from './InvocationDetail.vue'
import TaskDetail from './TaskDetail.vue'
import {
  state,
  ui,
  project,
  getPackage,
  getInvocation,
  closeDialog,
  createProject,
  navigate,
  resetDemo,
} from '../store'
const dialog = ref<HTMLDialogElement>()
const previousFocus = document.activeElement as HTMLElement | null
const name = ref('')
const industry = ref('工业制造')
const selectedTable = ref(0)
const pkg = computed(() => getPackage(ui.detailId))
const invocation = computed(() => getInvocation(ui.detailId))
const task = computed(() => state.tasks.find((t) => t.id === ui.detailId))
const titles: Record<string, string> = {
  package: '算法模型包',
  invocation: '调用详情',
  task: '研发工作区',
  'create-project': '创建数据项目',
  help: '关于决策工作台',
  data: '项目数据上下文',
  reset: '重置演示数据',
}
onMounted(async () => {
  await nextTick()
  dialog.value?.showModal()
})
onUnmounted(() => {
  previousFocus?.isConnected && previousFocus.focus()
})
function backdrop(event: MouseEvent) {
  if (event.target === dialog.value) closeDialog()
}
function trapFocus(event: KeyboardEvent) {
  if (event.key !== 'Tab' || !dialog.value) return
  const elements = Array.from(
    dialog.value.querySelectorAll<HTMLElement>(
      'button:not(:disabled), [href], input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [tabindex="0"]',
    ),
  ).filter((el) => el.getClientRects().length > 0)
  const first = elements[0]
  const last = elements.at(-1)
  if (!first) {
    event.preventDefault()
    dialog.value.focus()
    return
  }
  if (
    event.shiftKey &&
    (document.activeElement === first || !elements.includes(document.activeElement as HTMLElement))
  ) {
    event.preventDefault()
    last?.focus()
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault()
    first.focus()
  }
}
</script>
<template>
  <dialog
    ref="dialog"
    class="detail-dialog"
    :class="{ wide: ui.dialog === 'task', small: ['create-project', 'help', 'reset'].includes(ui.dialog) }"
    aria-labelledby="dialog-title"
    @cancel.prevent="closeDialog"
    @click="backdrop"
    @keydown="trapFocus"
  >
    <div class="dialog-shell">
      <header class="dialog-header">
        <div>
          <Icon
            :name="
              ui.dialog === 'task'
                ? 'branch'
                : ui.dialog === 'package'
                  ? 'package'
                  : ui.dialog === 'data'
                    ? 'database'
                    : 'file'
            "
            :size="18"
          /><strong id="dialog-title">{{ titles[ui.dialog] }}</strong
          ><span class="tiny-tag">交互演示</span>
        </div>
        <button class="icon-btn" aria-label="关闭详情" @click="closeDialog">
          <Icon name="x" :size="20" />
        </button>
      </header>
      <div class="dialog-body">
        <PackageDetail v-if="ui.dialog === 'package' && pkg" :key="pkg.id" :pkg="pkg" /><InvocationDetail
          v-else-if="ui.dialog === 'invocation' && invocation"
          :key="invocation.id"
          :invocation="invocation"
        /><TaskDetail v-else-if="ui.dialog === 'task' && task" :key="task.id" :task="task" />
        <form
          v-else-if="ui.dialog === 'create-project'"
          class="simple-dialog"
          @submit.prevent="createProject(name, industry)"
        >
          <span class="hero-icon"><Icon name="database" :size="28" /></span>
          <h2>新建数据项目</h2>
          <label
            >项目名称<input
              v-model="name"
              autofocus
              maxlength="48"
              required
              placeholder="例如：华东工厂 · 设备运维" /></label
          ><label
            >业务领域<select v-model="industry">
              <option>工业制造</option>
              <option>城市公用</option>
              <option>交通物流</option>
              <option>科研分析</option>
              <option>其他</option>
            </select></label
          >
          <div class="info-banner">
            <Icon name="database" :size="17" />
            <p>创建后可以添加合成示例表。当前原型未接入真实文件或数据库连接。</p>
          </div>
          <footer>
            <button class="btn secondary" type="button" @click="closeDialog">取消</button
            ><button class="btn primary" :disabled="!name.trim()">
              创建演示项目<Icon name="arrow" :size="15" />
            </button>
          </footer>
        </form>
        <div v-else-if="ui.dialog === 'help'" class="simple-dialog">
          <span class="hero-icon"><Icon name="sparkles" :size="30" /></span>
          <h2>AutoDecision</h2>
          <div class="info-banner">
            <Icon name="flask" :size="18" />
            <p>
              全部数据、指标、计算耗时和路由均为模拟；未连接
              AutoDecision、LLM、数据库或运行器。更改只保存在当前浏览器。
            </p>
          </div>
          <footer>
            <button class="btn primary" @click="closeDialog">开始体验<Icon name="arrow" :size="16" /></button>
          </footer>
        </div>
        <div v-else-if="ui.dialog === 'reset'" class="simple-dialog">
          <h2>恢复初始演示？</h2>
          <p>将清除本 Demo 中新建的项目、对话、任务和发布的模拟模型包。项目源码与原有前端数据不受影响。</p>
          <footer>
            <button class="btn secondary" @click="closeDialog">取消</button
            ><button class="btn danger" @click="resetDemo">确认重置演示</button>
          </footer>
        </div>
        <div v-else-if="ui.dialog === 'data'" class="data-dialog">
          <div class="detail-hero">
            <span class="hero-icon"><Icon name="database" :size="28" /></span>
            <div>
              <h2>{{ project.name }}</h2>
              <p>对话使用当前项目快照，算法包调用前检查输入合同。</p>
            </div>
          </div>
          <div class="pill-tabs">
            <button
              v-for="(t, i) in project.tables"
              :key="t.name"
              :class="{ active: selectedTable === i }"
              @click="selectedTable = i"
            >
              {{ t.title }}
            </button>
          </div>
          <div v-if="project.tables[selectedTable]" class="table-scroll margin-top">
            <table>
              <thead>
                <tr>
                  <th>字段</th>
                  <th>类型</th>
                  <th>单位</th>
                  <th>说明</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="col in project.tables[selectedTable].columns" :key="col.name">
                  <td>
                    <code>{{ col.name }}</code>
                  </td>
                  <td>{{ col.type }}</td>
                  <td>{{ col.unit }}</td>
                  <td>{{ col.description }}</td>
                </tr>
              </tbody>
            </table>
          </div>
          <p v-else class="hint">项目尚未添加数据。</p>
          <div class="info-banner margin-top">
            <Icon name="lock" :size="18" />
            <p>当前为合成数据上下文，没有实际连接或上传数据。新增数据源和权限将在后端适配时实现。</p>
          </div>
          <button class="btn secondary margin-top" @click="navigate('projects')">
            前往数据项目<Icon name="arrow" :size="15" />
          </button>
        </div>
        <div v-else class="empty-state">
          <Icon name="search" :size="32" />
          <h3>未找到这条演示记录</h3>
          <button class="btn secondary" @click="closeDialog">关闭</button>
        </div>
      </div>
    </div>
  </dialog>
</template>
