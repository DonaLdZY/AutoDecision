import { computed, reactive } from 'vue'
import { state, tasks } from './store'
import type { Task } from './store'
import { degradationChanges, taskWorkflow } from './taskWorkflow'
import { summarizeGoal } from './presentation'

// 研究通知：每个研究计划最多一条，内容随任务状态和交付进度变化；已读记录只存在本机浏览器。
export interface Notice {
  key: string
  task: Task
  tone: 'done' | 'pending' | 'failed'
  title: string
  detail: string
  hasReport: boolean
  action?: { label: string; kind: string; id: string }
}
const READ_KEY = 'studio.notices.read'
const read = reactive(new Set<string>(JSON.parse(localStorage.getItem(READ_KEY) || '[]') as string[]))
function save() {
  localStorage.setItem(READ_KEY, JSON.stringify([...read].slice(-500)))
}
export const notices = computed<Notice[]>(() =>
  tasks.value
    .filter((task) => ['completed', 'failed', 'awaiting_input'].includes(task.status))
    .sort((a, b) => b.updated_at - a.updated_at)
    .map((task) => {
      const flow = taskWorkflow(task, state.task_deliveries?.[task.id])
      const headline = state.research_briefs?.[task.id]?.headline || ''
      const key = `${task.id}:${task.updated_at}:${flow.stage}`
      const degraded =
        task.degradation?.status === 'applied' ? `（已降级 ${degradationChanges(task.degradation)} 项）` : ''
      const chat = state.links.find((l) => l.id === task.id)?.conversation_id
      if (task.status === 'awaiting_input')
        return {
          key,
          task,
          tone: 'pending',
          title: `「${task.task_name}」需要你确认降级`,
          detail: `有 ${degradationChanges(task.degradation)} 项需求要调整，同意后继续研究`,
          hasReport: false,
          action: chat
            ? { label: '去对话里确认', kind: 'conversation', id: chat }
            : { label: '查看降级清单', kind: 'task', id: task.id },
        }
      if (task.status === 'failed')
        return {
          key,
          task,
          tone: 'failed',
          title: `「${task.task_name}」需要处理`,
          detail: summarizeGoal(task.last_error || '运行未完成，可以查看原因后恢复。', 80),
          hasReport: false,
          action: { label: '查看并处理', kind: 'task', id: task.id },
        }
      return {
        key,
        task,
        tone: flow.pendingDelivery ? 'pending' : 'done',
        title: `「${task.task_name}」研究完成`,
        detail: (headline || '报告已生成') + degraded,
        hasReport: true,
        action: flow.pendingDelivery
          ? { label: flow.action, kind: flow.kind, id: flow.packageId || task.id }
          : undefined,
      }
    }),
)
export const unreadNotices = computed(() => notices.value.filter((n) => !read.has(n.key)).length)
export const isRead = (notice: Notice) => read.has(notice.key)
export function markRead(notice: Notice) {
  read.add(notice.key)
  save()
}
export function markAllRead() {
  notices.value.forEach((n) => read.add(n.key))
  save()
}
