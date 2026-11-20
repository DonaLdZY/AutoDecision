<script setup lang="ts">
import { computed } from 'vue'
import { resultLabel } from './resultLabels'
const props = defineProps<{ evaluation?: Record<string, any>; requested?: string }>()
const hasCriteria = computed(() => !!props.evaluation?.primary_metric)
const label = (name: string) => ({
  dev_log_rmse: '开发集对数 RMSE', holdout_log_rmse: '留出集对数 RMSE',
  holdout_rmse_ln: '留出集对数 RMSE', ln_rmse: '对数 RMSE',
}[name] || resultLabel(name))
const direction = (value: string) => value === 'minimize' ? '越低越好' : value === 'maximize' ? '越高越好' : '方向待确认'
</script>
<template>
  <section class="evaluation-criteria" aria-label="评价标准">
    <h3>评价标准</h3>
    <div v-if="hasCriteria" class="criteria-grid">
      <article>
        <span>搜索比较</span>
        <strong>{{ label(evaluation!.primary_metric) }}</strong>
        <small>{{ direction(evaluation!.metric_direction) }}</small>
      </article>
      <article v-if="evaluation!.final_evaluation_metric">
        <span>最终评估</span>
        <strong>{{ label(evaluation!.final_evaluation_metric) }}</strong>
        <small>{{ direction(evaluation!.final_evaluation_direction) }} · 方案冻结后计算</small>
      </article>
    </div>
    <p v-else>{{ requested || '数据理解完成后显示评价指标。' }}</p>
    <p v-if="evaluation?.computation_scope" class="criteria-scope">{{ evaluation.computation_scope }}</p>
    <details v-if="hasCriteria">
      <summary>计算方法与数据要求</summary>
      <p>{{ evaluation!.metric_formula }}</p>
      <p v-if="evaluation!.final_evaluation_formula">{{ evaluation!.final_evaluation_formula }}</p>
      <p v-if="evaluation!.validation_protocol">{{ evaluation!.validation_protocol }}</p>
      <ul v-if="evaluation!.leakage_guards?.length">
        <li v-for="rule in evaluation!.leakage_guards" :key="rule">{{ rule }}</li>
      </ul>
    </details>
  </section>
</template>
