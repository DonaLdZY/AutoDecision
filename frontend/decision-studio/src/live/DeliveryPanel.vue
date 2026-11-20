<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from 'vue'
import { request, run, refresh, ui } from './store'
import DecisionResult from './DecisionResult.vue'
import { inspectionReads } from './readCache'
import { humanFinalEvaluationStatus, humanReportStatus } from './presentation'
import SchemaInput from './SchemaInput.vue'
import SchemaFields from './SchemaFields.vue'
import OutputFields from './OutputFields.vue'
import ProjectCsvInput from './ProjectCsvInput.vue'
import { canEditSchema } from './schemaInput'
const props = defineProps<{ id: string; running: boolean; inputRoot: string }>()
const emit = defineEmits<{ prepared: [data: any]; report: []; publish: [] }>()
const data = ref<any>(),
  error = ref(''),
  mode = ref('csv'),
  input = ref(''),
  csv = ref(''),
  frames = ref('[]'),
  timeout = ref(30),
  confirmed = ref(false),
  checking = ref(false)
const loading = ref(false)
const finalEvaluation = ref<any>()
const reportPresentation = computed(() => {
  const status = data.value?.report_status
  if (status === 'ready') return { label: humanReportStatus(status), tone: 'success' }
  if (status === 'generating') return { label: humanReportStatus(status), tone: 'info' }
  if (status === 'failed' || status === 'blocked') return { label: humanReportStatus(status), tone: 'warning' }
  return { label: humanReportStatus(status), tone: 'neutral' }
})
const splitSeedCheck = computed(() => finalEvaluation.value?.split_seed_check || { status: 'unverified' })
function metricRows(metrics: Record<string, unknown> = {}) {
  const labels: Record<string, string> = {
    wape: '加权绝对百分比误差（WAPE）',
    mape: '平均绝对百分比误差（MAPE）',
    average_precision: '平均精确率（AP）',
    rmse: '均方根误差（RMSE）',
    log_rmse: '对数均方根误差',
    rmse_log: '对数均方根误差',
    holdout_log_rmse: '留出集对数 RMSE',
    holdout_rmse_ln: '留出集对数 RMSE',
    holdout_rmse_price: '留出集价格 RMSE',
    mae: '平均绝对误差（MAE）',
    r2: '决定系数（R²）',
    accuracy: '准确率',
    roc_auc: 'ROC-AUC',
    log_loss: 'Log loss',
    brier_score: 'Brier score',
    precision_at_0_5: 'Precision @ 0.5',
    recall_at_0_5: 'Recall @ 0.5',
    f1_at_0_5: 'F1 @ 0.5',
  }
  return Object.entries(metrics)
    .filter(([key, value]) => typeof value === 'number' && Number.isFinite(value)
      && key !== 'n' && !/(rows|count|positives|samples|seed|time|seconds)/i.test(key))
    .map(([key, value]) => ({ key, label: labels[key.toLowerCase()] || key, value: Number(value).toFixed(4) }))
}
const finalMetricRows = computed(() => metricRows(finalEvaluation.value?.result?.metrics))
const repairMetricRows = computed(() => metricRows(finalEvaluation.value?.inference_repair?.metrics))
const finalEvaluationPresentation = computed(() => {
  const status = String(finalEvaluation.value?.status || 'not_started')
  const tone = status === 'completed'
    ? 'success'
    : ['failed', 'invalid_result_fields', 'no_eligible_candidate'].includes(status)
      ? 'warning'
      : 'neutral'
  return { label: humanFinalEvaluationStatus(status), tone }
})
let sequence = 0
const deliveryCacheKey = (id: string) => `delivery:${id}:`
function invalidateDelivery(id = props.id) {
  inspectionReads.invalidate(deliveryCacheKey(id))
}
async function load(force = false) {
  const n = ++sequence
  const id = props.id
  loading.value = true
  try {
    const [result, final] = await Promise.all([
      inspectionReads.read(
        `${deliveryCacheKey(id)}contract`,
        () => request(`/studio/tasks/${id}/delivery`, undefined, 'GET', { timeoutMs: 45000 }),
        15000,
        force,
      ),
      inspectionReads.read(
        `${deliveryCacheKey(id)}evaluation`,
        () => request(`/studio/tasks/${id}/final-evaluation`, undefined, 'GET', { timeoutMs: 20000 }).catch(() => ({
          status: 'unavailable',
          can_repair_loading: false,
        })),
        5000,
        force,
      ),
    ])
    if (n !== sequence) return
    if (!data.value && canEditSchema(result.draft?.input_schema)
      && !result.draft?.dataframes?.some((frame: { pointer: string }) => frame.pointer === '')
      && result.draft?.observed_input_kind !== 'dataframe') mode.value = 'json'
    data.value = result
    finalEvaluation.value = final
    error.value = ''
    if (!frames.value || frames.value === '[]')
      frames.value = JSON.stringify(result.draft?.dataframes || [], null, 2)
    emit('prepared', result)
  } catch (e) {
    if (n === sequence) error.value = e instanceof Error ? e.message : String(e)
  } finally {
    if (n === sequence) loading.value = false
  }
}
async function repairFinalLoading() {
  await run('repair-final-loading', async () => {
    finalEvaluation.value = await request(`/studio/tasks/${props.id}/final-evaluation/repair-loading`, {
      confirm: true,
      expected_status_sha256: finalEvaluation.value.status_sha256,
    })
    invalidateDelivery()
    await load(true)
  })
}
function requestReport() {
  invalidateDelivery()
  emit('report')
}
async function verify() {
  await run('verify-delivery', async () => {
    checking.value = true
    try {
      data.value.verification = await request(`/studio/tasks/${props.id}/delivery/verify`, {
        delivery_id: data.value.delivery_id,
        input_mode: mode.value,
        data_json: input.value,
        csv_path: csv.value,
        dataframes: mode.value === 'json' ? JSON.parse(frames.value) : [],
        timeout_seconds: timeout.value,
        confirm: confirmed.value,
      })
      invalidateDelivery()
      await load(true)
      await refresh()
    } finally {
      checking.value = false
    }
  })
}
onUnmounted(() => {
  sequence++
})
watch(
  () => props.id,
  () => {
    data.value = undefined
    finalEvaluation.value = undefined
    input.value = ''
    csv.value = ''
    frames.value = '[]'
    confirmed.value = false
    void load()
  },
  { immediate: true },
)
watch(() => props.running, (running, previous) => {
  if (previous && !running) void load(true)
})
watch([mode, input, csv, frames, timeout], () => {
  confirmed.value = false
})
</script>
<template>
  <section class="live-panel delivery-panel">
    <div class="panel-heading">
      <div>
        <h3>报告与算法包</h3>
      </div>
      <span v-if="data" class="tag" :class="reportPresentation.tone">{{ reportPresentation.label }}</span>
    </div>
    <p v-if="error" class="live-error" role="alert">{{ error }}</p>
    <div v-if="finalEvaluation && finalEvaluation.status !== 'not_started'" class="delivery-evaluation">
      <div class="delivery-status-line">
        <h4>{{ finalEvaluation.inference_repair ? '原始保留集评估' : '保留集评估' }}</h4>
        <span class="tag" :class="finalEvaluationPresentation.tone">{{ finalEvaluationPresentation.label }}</span>
      </div>
      <p v-if="finalEvaluation.status === 'failed'" class="live-error">
        最终评估未完成，研究搜索结果不能作为最终评估结论。
      </p>
      <p v-else-if="finalEvaluation.status === 'invalid_result_fields'" class="live-error">
        运行返回了结果，但结果字段未通过系统校验；这些数值不计为有效的最终评估。
      </p>
      <p v-else-if="finalEvaluation.status === 'completed' && finalEvaluation.independent_verification === 'pending'">
        评估计算已完成，独立复核尚未完成；这不代表交付试算或业务验收通过。
      </p>
      <p v-else-if="finalEvaluation.status === 'completed'">
        此状态只说明最终评估计算完成；交付试算和业务验收分别记录。
      </p>
      <p v-if="splitSeedCheck.status === 'mismatch'" class="live-error">
        评价数据的划分与任务要求不一致，本次分数暂不作为任务结果。
      </p>
      <p v-else-if="splitSeedCheck.status === 'unverified' && finalEvaluation.status === 'completed'" class="hint">
        评价数据的划分尚未核对，以下数值暂供参考。
      </p>
      <p v-if="finalEvaluation.can_repair_loading">
        冻结模型的自定义类加载失败。重试将保留失败记录，使用相同候选、划分和模型重新执行最终评估。
      </p>
      <button
        v-if="finalEvaluation.can_repair_loading"
        class="btn secondary small"
        :disabled="!!ui.busy || running"
        @click="repairFinalLoading"
      >
        {{ ui.busy === 'repair-final-loading' ? '正在恢复最终评估…' : '修复模型加载并重试最终评估' }}
      </button>
      <dl
        v-if="finalEvaluation.status === 'completed' && splitSeedCheck.status !== 'mismatch' && finalMetricRows.length"
        class="final-metrics"
      >
        <div v-for="metric in finalMetricRows" :key="metric.key">
          <dt>{{ metric.label }}</dt>
          <dd>{{ metric.value }}</dd>
        </div>
      </dl>
      <p
        v-if="finalEvaluation.status === 'completed' && splitSeedCheck.status !== 'mismatch' && finalEvaluation.result?.metrics?.holdout_rows"
        class="hint"
      >
        评估样本 {{ finalEvaluation.result.metrics.holdout_rows }} 条，正例
        {{ finalEvaluation.result.metrics.holdout_positives ?? '未记录' }} 条。
      </p>
      <details>
        <summary>技术详情</summary>
        <p v-if="finalEvaluation.error" class="live-error">{{ finalEvaluation.error }}</p>
        <pre>{{ JSON.stringify(finalEvaluation, null, 2) }}</pre>
      </details>
    </div>
    <div v-if="finalEvaluation?.inference_repair" class="delivery-evaluation" role="region" aria-label="修复后的回归复验">
      <h4>修复后的回归复验</h4>
      <template v-if="finalEvaluation.inference_repair.status === 'recorded'">
        <p>{{ finalEvaluation.inference_repair.scope }}</p>
        <p class="hint">本次复验对应当前交付实现与模型，原始搜索成绩及评估记录继续保留。</p>
        <dl class="final-metrics"><div v-for="metric in repairMetricRows" :key="metric.key"><dt>{{ metric.label }}</dt><dd>{{ metric.value }}</dd></div></dl>
        <p class="hint">复验样本 {{ finalEvaluation.inference_repair.metrics.n ?? '未记录' }} 条；交付试算状态在下方单独记录。</p>
      </template>
      <template v-else><p class="live-error">修复记录与当前交付文件无法对应，请重新核对。</p><p v-for="issue in finalEvaluation.inference_repair.issues" :key="issue" class="hint">{{ issue }}</p><button type="button" class="btn secondary small" :disabled="loading" @click="load(true)">重新读取评估记录</button></template>
    </div>
    <p v-if="data?.report_status === 'failed'" class="live-error" role="alert">
      本轮没有生成可发布的报告交付材料。方案可试算状态、最终评估和报告状态各自独立。
    </p>
    <p v-else-if="data?.report_status === 'blocked'" class="live-error" role="alert">
      报告交付条件未满足；请先处理下方列出的问题，再重新生成报告。
    </p>
    <p v-for="issue in data?.issues" :key="issue" class="hint">{{ issue }}</p>
    <div class="form-actions">
      <button
        type="button"
        class="btn secondary small"
        :disabled="!!ui.busy || running"
        @click="requestReport"
      >
        {{ data?.report_ready ? '重新生成报告与交付包' : '生成报告与交付包' }}
      </button>
      <button type="button" class="btn secondary small" :disabled="!!ui.busy || loading" @click="load(true)">
        {{ loading ? '读取中…' : '刷新交付状态' }}
      </button>
    </div>
    <template v-if="data?.report_ready && data?.draft">
      <h4>使用说明</h4>
      <SchemaFields :schema="data.draft.input_schema" :dataframes="data.draft.dataframes" />
      <OutputFields :result="data.verification?.trial?.result" />
      <details>
        <summary>技术详情 · 完整调用约定</summary>
        <p>{{ data.draft.input_description }}</p>
        <p>{{ data.draft.output_description }}</p>
        <p class="hint">
          来源：{{ data.draft.implementation_path }}:{{ data.draft.source_line }} ·
          {{ data.draft.entrypoint }}({{ data.draft.signature }})
        </p>
      </details>
      <div v-if="data.draft.unresolved?.length" class="delivery-open-items">
        <h4>交付前需确认</h4>
        <p v-for="item in data.draft.unresolved" :key="item" class="hint">{{ item }}</p>
      </div>
    </template>
    <form v-if="data?.delivery_id && data.structure_ready" class="live-form" @submit.prevent="verify">
      <h4>交付试算</h4>
      <label
        >试算数据<select v-model="mode" aria-label="交付试算输入格式">
          <option value="json">填写字段或导入输入文件</option>
          <option value="csv">本地 CSV 文件</option>
        </select></label
      >
      <SchemaInput v-if="mode === 'json'" v-model="input" :schema="data.draft?.input_schema" />
      <ProjectCsvInput v-else v-model="csv" :input-root="inputRoot" />
      <details v-if="mode === 'json'">
        <summary>高级设置 · 表格转换</summary>
        <label>交付试算 DataFrame 转换<textarea v-model="frames" rows="3" spellcheck="false" /></label>
        <p class="hint">pointer 留空表示整个输入，/history 表示 history 字段；columns 须与实际数据列一致。</p>
      </details>
      <label
        >交付试算超时（秒）<input v-model.number="timeout" type="number" min="1" max="120" required
      /></label>
      <label class="check-line"
        ><input v-model="confirmed" type="checkbox" />已核对输入，执行本地推理，不重新训练</label
      >
      <button class="btn secondary" :disabled="!!ui.busy || !confirmed">
        {{ checking ? '试算中…' : '运行交付试算' }}
      </button>
      <p v-if="!confirmed" class="hint">请先核对试算数据并勾选上方确认项，再运行交付试算。</p>
      <p class="hint">试算结果只覆盖本次输入；结构检查与试算成功都不代表业务验收通过。</p>
    </form>
    <div v-if="data" role="status">
      <span
        class="tag"
        :class="
          data.verification?.status === 'passed'
            ? 'success'
            : data.verification?.status === 'failed'
              ? 'warning'
              : 'neutral'
        "
        >{{
          data.verification?.status === 'passed'
            ? '上次提交输入试算成功'
            : data.verification?.status === 'failed'
              ? '上次提交输入试算失败'
              : '尚未执行交付试算'
        }}</span
      >
      <div v-if="data.report_ready && data.verification?.status === 'passed'" class="form-actions">
        <p>试算已通过，下一步核对并发布，才能在对话中使用。</p>
        <button class="btn primary small" @click="emit('publish')">前往核对发布信息</button>
      </div>
      <DecisionResult v-if="data.verification?.trial" :result="data.verification.trial.result" />
      <p v-if="data.verification?.error" class="live-error">{{ data.verification.error }}</p>
    </div>
  </section>
</template>
<style scoped>
.delivery-status-line {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 8px;
}
.final-metrics {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0 24px;
  margin: 8px 0;
}
.final-metrics > div {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  padding: 9px 0;
  border-bottom: 1px solid var(--line, #dbe5e3);
}
.final-metrics dt {
  color: var(--secondary, #58706b);
}
.final-metrics dd {
  margin: 0;
  font-variant-numeric: tabular-nums;
}
@media (max-width: 540px) {
  .final-metrics {
    grid-template-columns: 1fr;
  }
}
</style>
