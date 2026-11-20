<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ui, state, packages, request, refresh, run } from './store'
import SchemaInput from './SchemaInput.vue'
import SchemaFields from './SchemaFields.vue'
import ProjectCsvInput from './ProjectCsvInput.vue'
import { canEditSchema } from './schemaInput'
import { invocationBlockers } from './taskWorkflow'
const props = defineProps<{
  packageIds: string[]
  conversationId?: string
  suggestedSteps?: {
    package_id: string
    mappings?: { source: string; target: string; source_unit: string; target_unit: string }[]
    output_pointer?: string
  }[]
}>()
const emit = defineEmits<{ done: [id: string] }>()
const steps = ref(
  props.packageIds.map((id, i) => ({
    package_id: id,
    input_mode: i ? 'previous' : packages.value.find((p) => p.id === id)?.input_binding ? 'project'
      : !packages.value.find((p) => p.id === id)?.dataframes?.some(frame => frame.pointer === '')
        && canEditSchema(packages.value.find((p) => p.id === id)?.input_schema) ? 'json' : 'csv',
    cutoff: 'latest',
    prepared: null as any,
    data_json: '{}',
    frameText: '[]',
    csv_path: '',
    output_pointer: props.suggestedSteps?.[i]?.output_pointer || '',
    mappingText: JSON.stringify(props.suggestedSteps?.[i]?.mappings || [], null, 2),
  })),
)
const timeout = ref(30),
  confirmed = ref(false),
  decisionMode = ref(!!props.conversationId && !!state.capabilities?.includes('decision_program')),
  resultId = ref('')
const requestId = ref(crypto.randomUUID())
const fingerprint = ref('')
const schemas = computed(() => steps.value.map((s) => packages.value.find((p) => p.id === s.package_id)))
function addStep() {
  if (steps.value.length >= 4 || !packages.value.length) return
  steps.value.push({
    package_id: packages.value[0].id,
    input_mode: 'previous',
    cutoff: 'latest',
    prepared: null as any,
    data_json: '{}',
    frameText: '[]',
    csv_path: '',
    output_pointer: '',
    mappingText: '[]',
  })
}
watch(
  () =>
    steps.value.map((s) => [
      s.package_id,
      s.input_mode,
      s.cutoff,
      s.data_json,
      s.csv_path,
      s.frameText,
      s.mappingText,
      s.output_pointer,
    ]),
  () => {
    confirmed.value = false
  },
  { deep: true },
)
async function prepare(index: number) {
  const step = steps.value[index]
  await run('prepare-input', async () => {
    step.prepared = null
    confirmed.value = false
    const result = await request(`/studio/packages/${step.package_id}/prepare-input`, {
      cutoff: step.cutoff || 'latest',
    })
    step.prepared = { ...result, requestedCutoff: step.cutoff }
  })
}
const blockers = computed(() => invocationBlockers(steps.value, packages.value.map(p => p.id)))
const ready = computed(() =>
  steps.value.every(
    (s) =>
      s.input_mode !== 'project' ||
      (s.prepared?.package_id === s.package_id && s.prepared?.requestedCutoff === s.cutoff),
  ),
)
async function execute() {
  if (blockers.value.length || !ready.value || !confirmed.value) return
  await run('invoke', async () => {
    const payload = {
      project_id: ui.projectId,
      conversation_id: props.conversationId || '',
      title: schemas.value.map((p) => p?.name).join(' → '),
      steps: steps.value.map((s) => ({
        package_id: s.package_id,
        input_mode: s.input_mode,
        prepared_input_id: s.input_mode === 'project' ? s.prepared?.id : '',
        data_json: s.data_json,
        csv_path: s.csv_path,
        output_pointer: s.output_pointer,
        mappings: s.input_mode === 'project' ? [] : JSON.parse(s.mappingText),
        dataframes: s.input_mode === 'project' ? [] : JSON.parse(s.frameText),
      })),
      timeout_seconds: timeout.value,
      confirm: confirmed.value,
      decision_mode: decisionMode.value,
    }
    const signature = JSON.stringify(payload)
    if (signature !== fingerprint.value) {
      requestId.value = crypto.randomUUID()
      fingerprint.value = signature
    }
    const result = await request('/studio/invocations', { ...payload, request_id: requestId.value })
    resultId.value = result.id
    await refresh()
    emit('done', result.id)
  })
}
</script>
<template>
  <form class="live-form" @submit.prevent="execute">
    <section v-for="(step, i) in steps" :key="i" class="live-panel">
      <div class="panel-heading">
        <h3>
          {{ i + 1 }}. {{ schemas[i]?.name }} <span class="tag neutral">v{{ schemas[i]?.version }}</span>
        </h3>
        <button
          v-if="steps.length > 1"
          type="button"
          class="text-btn"
          :disabled="!!ui.busy"
          @click="steps.splice(i, 1)"
        >
          删除步骤
        </button>
      </div>
      <p>{{ schemas[i]?.description }}</p>
      <SchemaFields :schema="schemas[i]?.input_schema" :dataframes="schemas[i]?.dataframes" />
      <details>
        <summary>技术详情 · 输入合同与接口</summary>
        <pre>{{ JSON.stringify(schemas[i]?.input_schema, null, 2) }}</pre>
        <p>{{ schemas[i]?.entrypoint }}(model_path, data)</p>
        <p>{{ schemas[i]?.output_description || '请核对包内冻结合同与实现；尚未登记结构化输出说明。' }}</p>
      </details>
      <label
        >调用哪个模型包<select v-model="step.package_id">
          <option v-for="p in packages" :key="p.id" :value="p.id">{{ p.name }} · v{{ p.version }}</option>
        </select></label
      ><label
        >输入方式<select v-model="step.input_mode" aria-label="输入方式">
          <option v-if="schemas[i]?.input_binding" value="project">从项目数据准备输入</option>
          <option value="json">填写字段或导入输入文件</option>
          <option value="csv">本地 CSV 文件</option>
          <option v-if="i" value="previous">上一模型的输出</option>
        </select></label
      >
      <SchemaInput v-if="step.input_mode === 'json'" v-model="step.data_json" :schema="schemas[i]?.input_schema" />
      <ProjectCsvInput v-if="step.input_mode === 'csv'" v-model="step.csv_path" />
      <label v-if="step.input_mode === 'previous'"
        >上游输出路径（JSON Pointer）<input
          v-model="step.output_pointer"
          placeholder="留空使用完整结果；例如 /predictions"
      /></label>
      <div v-if="step.input_mode === 'project'" class="live-panel">
        <label>数据截止时间<input v-model="step.cutoff" placeholder="latest 或 2026-05-25 16:00:00" /></label>
        <p class="hint">latest 使用数据源最新观测时刻。下一小时以此为基准；历史数据不会当作当前实时数据。</p>
        <button type="button" class="btn secondary" :disabled="!!ui.busy" @click="prepare(i)">
          {{ ui.busy === 'prepare-input' ? '正在读取项目数据…' : '准备项目输入' }}
        </button>
        <div v-if="step.prepared" role="status">
          <h4>输入已准备 · {{ step.prepared.cutoff }}（{{ step.prepared.timezone }}）</h4>
          <p v-for="source in step.prepared.sources" :key="source.field">
            {{ source.path }} → {{ source.field }} · {{ source.rows }} 行 · {{ source.first_observation }} 至
            {{ source.last_observation }}
          </p>
          <p v-if="!ready" class="live-error">包或截止时间已变化，请重新准备输入。</p>
          <details>
            <summary>查看输入来源与指纹</summary>
            <pre>{{ JSON.stringify(step.prepared, null, 2) }}</pre>
          </details>
        </div>
      </div>
      <details v-if="!['csv', 'project'].includes(step.input_mode)">
        <summary>高级设置 · 字段映射与单位转换</summary>
        <p class="hint">
          映射项为 source、target、source_unit、target_unit。只允许同量纲单位换算，不插补、不执行自定义代码。
        </p>
        <p class="hint">
          例如 [{"source":"power_kw","target":"load_mw","source_unit":"kW","target_unit":"MW"}]
        </p>
        <textarea v-model="step.mappingText" rows="4" aria-label="字段映射 JSON" spellcheck="false" />
      </details>
      <details v-if="!['csv', 'project'].includes(step.input_mode)">
        <summary>高级设置 · 表格转换</summary>
        <p class="hint">
          某些冻结接口要求 DataFrame，或要求对象中的 history 为
          DataFrame。显式填写路径与完整列顺序；不会隐式补列或删除多余列。空 pointer 转换整个输入，/history
          转换嵌套历史。
        </p>
        <p class="hint">例如 [{"pointer":"/history","columns":["SampleTime","power_kw"]}]</p>
        <textarea v-model="step.frameText" rows="4" aria-label="DataFrame 适配 JSON" spellcheck="false" />
      </details>
    </section>
    <label v-if="conversationId && state.capabilities?.includes('decision_program')" class="check-line"><input v-model="decisionMode" type="checkbox" />生成决策答案</label>
    <p v-else-if="conversationId" class="hint">当前后端仅返回计算结果。重启本地服务后可使用决策答案。</p>
    <details class="developer-details"><summary>组合调用与执行设置</summary>
    <button
      type="button"
      class="btn secondary small"
      :disabled="steps.length >= 4 || !!ui.busy"
      @click="addStep"
    >
      添加下游模型包步骤</button
    ><label
      >每步超时（秒，1–120）<input v-model.number="timeout" type="number" min="1" max="120" required /></label>
    </details>
    <label class="check-line"
      ><input
        v-model="confirmed"
        type="checkbox"
      />已核对输入与单位，执行本地推理</label
    >
    <div class="invocation-next-step" role="status" aria-live="polite">
      <p v-for="problem in blockers" :key="problem" class="hint">{{ problem }}</p>
      <p v-if="!blockers.length && !confirmed" class="hint">输入就绪后，请勾选上方“已核对输入与单位”，再确认调用。</p>
    </div>
    <div class="form-actions">
      <button class="btn primary" :disabled="!confirmed || !ready || blockers.length > 0 || !!ui.busy">
        {{ ui.busy === 'invoke' ? (decisionMode ? '正在生成决策并计算…' : '正在计算…') : '确认调用' }}
      </button>
    </div>
  </form>
</template>
