export type Page = 'chat' | 'projects' | 'packages' | 'tasks' | 'invocations' | 'settings'
export type Scenario = 'forecast' | 'compose' | 'anomaly' | 'research'
export interface DataTable {
  name: string
  title: string
  rows: string
  updated: string
  columns: { name: string; type: string; unit: string; description: string }[]
  preview: (string | number)[][]
}
export interface Project {
  id: string
  name: string
  short: string
  industry: string
  description: string
  icon: string
  color: string
  snapshot: string
  tables: DataTable[]
}
export interface ModelPackage {
  id: string
  projectId: string
  name: string
  version: string
  kind: string
  icon: string
  description: string
  scenario: Scenario
  input: { field: string; type: string; unit: string; required: boolean; description: string }[]
  output: string
  entry: string
  artifact: string
  metric: string
  metricValue: string
  validation: string
  taskId: string
  calls: number
  tags: string[]
  runtime: string
  parameters: string
  limits: string
  created: string
}
export interface ResearchTask {
  id: string
  projectId: string
  title: string
  target: string
  status: 'running' | 'paused' | 'queued' | 'completed'
  progress: number
  stage: number
  candidates: number
  budget: string
  created: string
  packageId?: string
  capability: string
}
export interface Invocation {
  id: string
  projectId: string
  conversationId: string
  title: string
  packageIds: string[]
  scenario: Scenario
  created: string
  duration: string
  snapshot: string
  aligned: boolean
  result: { label: string; value: string; unit: string; change?: string }[]
  mapping: { from: string; to: string; rule: string }[]
}
export interface Message {
  id: string
  role: 'user' | 'assistant'
  text: string
  kind?: 'result' | 'research' | 'mapping' | 'clarify'
  invocationId?: string
  taskId?: string
  capability?: string
  resolved?: boolean
}
export interface Conversation {
  id: string
  projectId: string
  title: string
  messages: Message[]
  created: string
}
export interface StudioState {
  schema: number
  projectId: string
  conversationId: string
  projects: Project[]
  packages: ModelPackage[]
  tasks: ResearchTask[]
  invocations: Invocation[]
  conversations: Conversation[]
  settings: {
    runner: string
    concurrency: number
    cpu: number
    memory: number
    confirmation: boolean
    provider: string
  }
}
