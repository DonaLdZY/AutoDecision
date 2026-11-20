<script setup lang="ts">
import { computed, ref } from 'vue'
import Icon from './Icon.vue'
import LoadChart from './LoadChart.vue'
import type { Invocation } from '../types'
import { getPackage, openDialog, download, selectConversation, toast } from '../store'
const props = defineProps<{ invocation: Invocation }>()
const tab = ref('chain')
const selected = computed(() => props.invocation.packageIds.map((id) => getPackage(id)!))
const code = computed(
  () =>
    `# 调用计划示意；不是当前可运行的 SDK\n# 下方模型、数据和结果均来自前端演示\ncontext = {\n    "project": "${props.invocation.projectId}",\n    "snapshot": "${props.invocation.snapshot}",\n    "mode": "inference_only",\n}\n\n${selected.value.map((p, i) => `# ${i + 1}. ${p.name}（冻结版本 ${p.version}）\nstep_${i + 1} = {\n    "package_id": "${p.id}",\n    "version": "${p.version}",\n    "entry": "${p.entry.split('(')[0]}",\n    "input_source": "${i ? 'step_1.output + energy_tariffs' : 'validated_project_snapshot'}",\n    "allow_training": False,\n}`).join('\n\n')}\n\n# 由后续本地运行器验证合同、执行依赖图、记录产物\n# 此前端不会执行上述计划，也不会下发设备指令。`,
)
const exportData = computed(() => ({
  demo: true,
  invocation: props.invocation,
  packages: selected.value.map((p) => ({ id: p.id, version: p.version })),
  note: '预设演示结果，未调用真实算法或 LLM',
}))
async function copy() {
  try {
    await navigator.clipboard.writeText(code.value)
    toast('已复制调用计划示意')
  } catch {
    toast('复制不可用，可下载调用计划')
  }
}
</script>
<template>
  <div>
    <div class="detail-hero">
      <span class="hero-icon"><Icon name="workflow" :size="30" /></span>
      <div>
        <div class="eyebrow">DECISION RECEIPT <span class="tag success">模拟完成</span></div>
        <h2>{{ invocation.title }}</h2>
        <p>{{ invocation.id }} · {{ invocation.created }} · {{ invocation.duration }}</p>
      </div>
    </div>
    <div class="detail-actions">
      <button class="btn secondary" @click="selectConversation(invocation.conversationId)">
        <Icon name="chat" :size="16" />返回来源对话</button
      ><button class="btn secondary" @click="download(invocation.id + '-demo.json', exportData)">
        <Icon name="download" :size="16" />导出执行记录</button
      ><span class="hint">包版本与输入快照已固定</span>
    </div>
    <div class="tabs">
      <button
        v-for="t in [
          { id: 'chain', name: '执行步骤' },
          { id: 'mapping', name: '输入对齐' },
          { id: 'code', name: '调用代码' },
          { id: 'result', name: '结果与输出' },
        ]"
        :key="t.id"
        :class="{ active: tab === t.id }"
        @click="tab = t.id"
      >
        {{ t.name }}
      </button>
    </div>
    <div class="detail-tab-content">
      <template v-if="tab === 'chain'"
        ><div class="execution-context">
          <div>
            <span>数据快照</span><code>{{ invocation.snapshot }}</code>
          </div>
          <div>
            <span>执行方式</span
            ><strong>{{ invocation.packageIds.length > 1 ? '依赖顺序组合' : '单包直接调用' }}</strong>
          </div>
          <div><span>新增训练</span><strong>0 次</strong></div>
        </div>
        <div class="audit-steps">
          <div class="audit-step">
            <span class="step-number">1</span>
            <div>
              <h3>需求与能力匹配 <span class="tag neutral">模拟路由</span></h3>
              <p>根据场景选择当前项目中适用的模型包，核对目标、数据与输入合同。</p>
            </div>
            <Icon name="checkCircle" :size="18" />
          </div>
          <div class="audit-step">
            <span class="step-number">2</span>
            <div>
              <h3>准备输入与校验合同</h3>
              <p>
                {{
                  invocation.aligned
                    ? '已确认 kW → MW 换算；保留时间语义。'
                    : '读取固定项目快照，检查字段、单位、时间范围和缺失值。'
                }}
              </p>
              <button class="text-btn" @click="tab = 'mapping'">
                查看字段映射<Icon name="arrow" :size="13" />
              </button>
            </div>
            <Icon name="checkCircle" :size="18" />
          </div>
          <div v-for="(p, i) in selected" :key="p.id" class="audit-step">
            <span class="step-number">{{ i + 3 }}</span>
            <div>
              <h3>
                {{ p.name }}<span class="tag neutral">v{{ p.version }}</span>
              </h3>
              <p>
                {{
                  i
                    ? '使用上一步输出，并合并项目约束与电价。'
                    : '使用已校验的项目数据；不进行训练或修改权重。'
                }}
              </p>
              <button class="inline-package-link" @click="openDialog('package', p.id)">
                <Icon name="package" :size="14" />{{ p.entry }}<Icon name="right" :size="13" />
              </button>
            </div>
            <Icon name="checkCircle" :size="18" />
          </div>
          <div class="audit-step">
            <span class="step-number">{{ selected.length + 3 }}</span>
            <div>
              <h3>整理结果，等待业务审核</h3>
              <p>保存结构化输出、输入映射、版本与调用状态。决策建议不直接下发到生产系统。</p>
            </div>
            <Icon name="checkCircle" :size="18" />
          </div>
        </div>
        <div class="info-banner">
          <Icon name="file" :size="17" />
          <p>这里呈现可审计的工具调用与数据处理记录。当前步骤由演示场景生成。</p>
        </div></template
      >
      <template v-else-if="tab === 'mapping'"
        ><div class="section-heading">
          <div>
            <h3>从业务数据到模型输入</h3>
            <p>所有适配显式记录，输入语义保持一致。</p>
          </div>
          <span class="tag success">合同校验 · 模拟通过</span>
        </div>
        <div class="table-scroll">
          <table>
            <thead>
              <tr>
                <th>数据来源</th>
                <th>目标字段</th>
                <th>适配规则</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="m in invocation.mapping" :key="m.to">
                <td>
                  <code>{{ m.from }}</code>
                </td>
                <td>
                  <code>{{ m.to }}</code>
                </td>
                <td>{{ m.rule }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <div class="frozen-items margin-top">
          <span><Icon name="lock" :size="14" />冻结权重</span
          ><span><Icon name="lock" :size="14" />冻结预处理器</span
          ><span><Icon name="check" :size="14" />明确单位换算</span
          ><span><Icon name="check" :size="14" />输入快照可追溯</span>
        </div></template
      >
      <template v-else-if="tab === 'code'"
        ><div class="code-toolbar">
          <span><Icon name="code" :size="16" />调用计划 · Python 示意</span>
          <div>
            <button class="icon-btn" aria-label="复制调用代码" @click="copy">
              <Icon name="copy" :size="16" /></button
            ><button
              class="icon-btn"
              aria-label="下载调用计划"
              @click="download('invocation_plan_demo.py', code, 'text/plain')"
            >
              <Icon name="download" :size="16" />
            </button>
          </div>
        </div>
        <pre class="dark-code">{{ code }}</pre>
        <p class="hint">
          这份代码用于说明编排协议；当前没有可执行的运行器 SDK，前端也不执行 Python。
        </p></template
      >
      <template v-else
        ><div class="result-metrics detail-result">
          <div v-for="r in invocation.result" :key="r.label">
            <span>{{ r.label }}</span>
            <div>
              <strong>{{ r.value }}</strong
              ><small>{{ r.unit }}</small>
            </div>
            <em>{{ r.change }}</em>
          </div>
        </div>
        <LoadChart
          v-if="['forecast', 'compose'].includes(invocation.scenario)"
          :compose="invocation.scenario === 'compose'"
          :water="invocation.projectId === 'water'"
        />
        <section class="detail-section">
          <h3>结构化结果 <span class="tag neutral">模拟数据</span></h3>
          <pre class="light-code">{{
            JSON.stringify(
              { demo: true, status: 'completed', results: invocation.result, requires_business_review: true },
              null,
              2,
            )
          }}</pre>
        </section>
        <div class="info-banner">
          <Icon name="shield" :size="18" />
          <p>模拟结果用于评审交互与信息结构，没有真实模型执行或效益验证。</p>
        </div></template
      >
    </div>
  </div>
</template>
