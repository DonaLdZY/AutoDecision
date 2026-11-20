<script setup lang="ts">
import Icon from './Icon.vue'
import LoadChart from './LoadChart.vue'
import type { Invocation } from '../types'
import { getPackage, openDialog } from '../store'
defineProps<{ invocation: Invocation }>()
</script>
<template>
  <article class="invocation-card">
    <div class="receipt-heading">
      <span class="receipt-icon"
        ><Icon :name="invocation.packageIds.length > 1 ? 'workflow' : 'chart'" :size="21"
      /></span>
      <div>
        <h3>{{ invocation.title }}</h3>
        <p>
          {{ invocation.packageIds.length > 1 ? '组合复用' : '直接复用' }} ·
          {{ invocation.packageIds.length }} 个算法模型包
        </p>
      </div>
      <span class="tag success"><Icon name="check" :size="12" />调用完成</span>
    </div>
    <div class="execution-ribbon">
      <span class="ribbon-source"><Icon name="database" :size="15" />项目数据</span
      ><template v-for="pid in invocation.packageIds" :key="pid"
        ><Icon name="arrow" :size="14" /><button @click="openDialog('package', pid)">
          <Icon :name="getPackage(pid)?.icon || 'box'" :size="14" />{{ getPackage(pid)?.name
          }}<small>v{{ getPackage(pid)?.version }}</small>
        </button></template
      ><Icon name="arrow" :size="14" /><span class="ribbon-output"
        ><Icon name="checks" :size="14" />结果</span
      >
    </div>
    <div class="result-metrics">
      <div v-for="r in invocation.result" :key="r.label">
        <span>{{ r.label }}</span>
        <div>
          <strong>{{ r.value }}</strong
          ><small>{{ r.unit }}</small>
        </div>
        <em v-if="r.change">{{ r.change }}</em>
      </div>
    </div>
    <LoadChart
      v-if="['forecast', 'compose'].includes(invocation.scenario)"
      :compose="invocation.scenario === 'compose'"
      :water="invocation.projectId === 'water'"
    />
    <div v-else class="result-note">
      <Icon name="shield" :size="18" /><span>{{
        invocation.scenario === 'anomaly'
          ? '已标记 3 个待复核时段。异常提示需要结合设备工况审核。'
          : '能力已从研发任务转为可复用模型包，本次仅演示推理调用。'
      }}</span>
    </div>
    <div v-if="invocation.scenario === 'compose'" class="decision-note">
      <Icon name="leaf" :size="16" /><span>建议将 2 组可调工序移至 22:00 后，保持原定产量。</span
      ><span class="tiny-tag">待业务审核</span>
    </div>
    <footer class="receipt-footer">
      <span><Icon name="lock" :size="13" />冻结版本 <i /> {{ invocation.duration }} <i /> 模拟结果</span
      ><button class="text-btn" @click="openDialog('invocation', invocation.id)">
        查看执行详情 <Icon name="arrow" :size="15" />
      </button>
    </footer>
  </article>
</template>
