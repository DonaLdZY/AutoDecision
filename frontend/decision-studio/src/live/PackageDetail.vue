<script setup lang="ts">
import { onUnmounted, ref, watch } from 'vue'
import Icon from '../components/Icon.vue'
import Modal from './Modal.vue'
import InvokeForm from './InvokeForm.vue'
import SchemaFields from './SchemaFields.vue'
import OutputFields from './OutputFields.vue'
import ResultValue from './ResultValue.vue'
import ResourceStorage from './ResourceStorage.vue'
import { ui, request, run, bundle, date } from './store'
import type { Package } from './store'
const props = defineProps<{ id: string }>()
const emit = defineEmits<{ open: [kind: string, id: string] }>()
const data = ref<Package>(),
  full = ref<Package>(),
  error = ref(''),
  technicalError = ref('')
const invoke = ref(false),
  technicalLoading = ref(false)
let sequence = 0
watch(
  () => props.id,
  async (id) => {
    const n = ++sequence
    data.value = undefined
    full.value = undefined
    error.value = ''
    technicalError.value = ''
    technicalLoading.value = false
    try {
      const result = await request<Package>(`/studio/packages/${id}?view=summary`)
      if (n === sequence) data.value = result
    } catch (e) {
      if (n === sequence) error.value = String(e)
    }
  },
  { immediate: true },
)
onUnmounted(() => {
  sequence++
})
async function loadTechnical(event: Event) {
  if (!(event.target as HTMLDetailsElement).open || full.value || technicalLoading.value) return
  const n = sequence,
    id = props.id
  technicalLoading.value = true
  technicalError.value = ''
  try {
    const result = await request<Package>(`/studio/packages/${id}`)
    if (n === sequence) full.value = result
  } catch (e) {
    if (n === sequence) technicalError.value = String(e)
  } finally {
    if (n === sequence) technicalLoading.value = false
  }
}
function windowLabel(seconds: number) {
  return seconds >= 86400 ? `${seconds / 86400} 天` : `${seconds / 3600} 小时`
}
</script>
<template>
  <div v-if="data" class="live-detail">
    <ResourceStorage kind="packages" :id="id" />
    <div class="detail-hero">
      <span class="hero-icon"><Icon name="package" :size="30" /></span>
      <div>
        <div class="eyebrow">算法模型包 · v{{ data.version }}</div>
        <h2>{{ data.name }}</h2>
        <p>{{ data.description }}</p>
      </div>
    </div>
    <div class="detail-actions">
      <span class="hint">{{ date(data.created_at) }}</span>
      <button
        class="btn secondary small"
        :disabled="!!ui.busy"
        @click="run('download', () => bundle(data!.id))"
      >
        <Icon name="download" />导出模型包
      </button>
      <button class="btn secondary small" @click="emit('open', 'task', data.task_id)">查看来源任务</button>
      <button class="btn primary small" @click="invoke = true">使用模型包</button>
    </div>
    <section class="live-panel">
      <h3>质量与可用性</h3>
      <div class="quality-grid">
        <div>
          <span class="hint">调用试算</span
          ><strong>{{
            data.validation?.trial_status === 'passed'
              ? '已成功运行'
              : data.validation?.trial_status === 'failed'
                ? '运行失败'
                : '尚未试算'
          }}</strong>
        </div>
        <div>
          <span class="hint">独立质量评估</span
          ><strong>{{
            data.validation?.quality_status === 'below_baseline'
              ? '低于基线，需继续改进'
              : data.validation?.quality_status === 'beats_baseline'
                ? '优于记录的基线'
                : data.validation?.quality_status === 'evaluated'
                  ? '已评估，请核对指标'
                  : '尚无可确认的结论'
          }}</strong>
        </div>
      </div>
      <ResultValue
        v-if="data.validation?.metrics && Object.keys(data.validation.metrics).length"
        :value="data.validation.metrics"
      />
      <p v-for="note in data.validation?.notes || []" :key="note">{{ note }}</p>
      <p v-if="data.validation?.trial_error" class="live-error">{{ data.validation.trial_error }}</p>
    </section>
    <section class="live-panel">
      <h3>输入</h3>
      <SchemaFields :schema="data.input_schema" :dataframes="data.dataframes" />
    </section>
    <section v-if="data.input_binding" class="live-panel">
      <h3>项目数据</h3>
      <div v-for="source in data.input_binding.sources" :key="source.field" class="check-row">
        <Icon name="database" />
        <div>
          <strong>{{ source.path }}</strong>
          <p>
            使用截止时刻前 {{ windowLabel(source.window_seconds) }} 的观测 ·
            {{ source.columns.length }} 个字段
          </p>
        </div>
      </div>
      <p>时区：{{ data.input_binding.timezone }}</p>
    </section>
    <section class="live-panel">
      <h3>输出</h3>
      <OutputFields :shape="data.output_view" />
    </section>
    <details class="live-panel" @toggle="loadTechnical">
      <summary>技术详情</summary>
      <p v-if="technicalLoading" role="status">正在读取…</p>
      <p v-if="technicalError" class="live-error">{{ technicalError }}</p>
      <template v-if="full">
        <p>{{ full.output_description }}</p>
        <p>{{ full.entrypoint }}(model_path, data) · {{ full.model_path }}</p>
        <details>
          <summary>文件清单（{{ full.files?.length || 0 }}）</summary>
          <div class="table-scroll">
            <table class="live-table">
              <thead>
                <tr>
                  <th>文件</th>
                  <th>大小</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="file in full.files" :key="file.path">
                  <td>{{ file.path }}</td>
                  <td>{{ (file.size / 1024).toFixed(1) }} KB</td>
                </tr>
              </tbody>
            </table>
          </div>
        </details>
        <details>
          <summary>调用合同与说明原文</summary>
          <details v-for="(text, path) in full.contracts" :key="path">
            <summary>{{ path }}</summary>
            <pre>{{ text }}</pre>
          </details>
        </details>
        <details>
          <summary>原始验证记录</summary>
          <pre>{{ JSON.stringify(full.verification, null, 2) }}</pre>
        </details>
        <details>
          <summary>接口与指纹</summary>
          <p>{{ full.fingerprint }}</p>
          <pre>{{ JSON.stringify(full.manifest, null, 2) }}</pre>
          <pre>{{ JSON.stringify(full.input_schema, null, 2) }}</pre>
        </details>
      </template>
    </details>
    <Modal v-if="invoke" title="模型调用" wide @close="invoke = false"
      ><InvokeForm
        :package-ids="[data.id]"
        @done="
          (id) => {
            invoke = false
            emit('open', 'invocation', id)
          }
        "
    /></Modal>
  </div>
  <p v-else-if="error" class="live-error">{{ error }}</p>
  <p v-else class="hint" role="status">正在读取模型包…</p>
</template>
