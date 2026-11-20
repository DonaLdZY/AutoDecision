<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import Icon from './Icon.vue'
import type { ResearchTask } from '../types'
import {
  state,
  stageNames,
  statusText,
  advanceTask,
  toggleTask,
  publishTask,
  openDialog,
  download,
} from '../store'
const props = defineProps<{ task: ResearchTask }>()
const active = ref(props.task.stage)
const reviewed = ref(false)
watch(
  () => props.task.stage,
  (s) => (active.value = s),
)
const nodes = [
  { id: 1, x: 70, y: 215, parent: 0, label: '季节性基线', score: 0.63, type: 'baseline' },
  { id: 2, x: 245, y: 75, parent: 1, label: '树模型', score: 0.76, type: 'draft' },
  { id: 3, x: 245, y: 215, parent: 1, label: '线性回归', score: 0.68, type: 'draft' },
  { id: 4, x: 245, y: 355, parent: 1, label: '序列网络', score: 0, type: 'failed' },
  { id: 5, x: 420, y: 55, parent: 2, label: '滞后特征', score: 0.84, type: 'improve' },
  { id: 6, x: 420, y: 155, parent: 2, label: '特征交互', score: 0.81, type: 'improve' },
  { id: 7, x: 420, y: 265, parent: 3, label: '残差修正', score: 0.78, type: 'improve' },
  { id: 8, x: 420, y: 375, parent: 4, label: '修复维度', score: 0.72, type: 'debug' },
  { id: 9, x: 595, y: 75, parent: 5, label: '滚动统计', score: 0.89, type: 'improve' },
  { id: 10, x: 595, y: 215, parent: 6, label: '约束特征', score: 0.86, type: 'improve' },
  { id: 11, x: 595, y: 355, parent: 8, label: '归一化修正', score: 0.8, type: 'improve' },
  { id: 12, x: 770, y: 110, parent: 9, label: '跨分支融合', score: 0.93, type: 'fusion' },
  { id: 13, x: 770, y: 315, parent: 11, label: '窗口改进', score: 0.85, type: 'improve' },
  { id: 14, x: 945, y: 215, parent: 12, label: '集成候选', score: 0.94, type: 'best' },
]
const selected = ref(12)
const node = computed(() => nodes.find((n) => n.id === selected.value)!)
const visibleNodes = computed(() =>
  nodes.filter((n) => n.id <= (props.task.candidates >= 16 ? 14 : props.task.candidates)),
)
const edges = computed(() =>
  visibleNodes.value
    .filter((n) => n.parent)
    .map((n) => ({ from: nodes.find((p) => p.id === n.parent)!, to: n })),
)
const project = computed(() => state.projects.find((p) => p.id === props.task.projectId)!)
const nodeCode = computed(
  () =>
    `# 演示候选 #${node.value.id}: ${node.value.label}\n# 展示候选算法改动的形态，不是实际运行代码\ndef build_candidate(train_data, frozen_contract):\n    features = make_time_safe_features(train_data)\n    ${node.value.type === 'fusion' ? '# 引用 #09 的时间特征与 #07 的残差建模\n    candidate = blend(tree_model, residual_model)' : node.value.type === 'failed' ? '# 该候选在张量维度检查时失败\n    raise ValueError("sequence feature shape mismatch")' : 'candidate = fit_candidate(features, frozen_contract)'}\n    return evaluate_on_development_split(candidate)\n\n# 独立留出集仅用于最终验收，不参与搜索评分。`,
)
</script>
<template>
  <div class="task-detail">
    <div class="detail-hero">
      <span class="hero-icon blue"><Icon name="branch" :size="30" /></span>
      <div>
        <div class="eyebrow">
          {{ task.id }}
          <span
            :class="[
              'tag',
              task.status === 'running' ? 'info' : task.status === 'completed' ? 'success' : 'neutral',
            ]"
            >{{ statusText(task.status) }}</span
          >
        </div>
        <h2>{{ task.title }}</h2>
        <p>{{ task.target }}</p>
      </div>
    </div>
    <div class="detail-actions">
      <span class="task-budget"><Icon name="cpu" :size="15" />{{ task.budget }}<span>·</span>模拟任务</span
      ><template v-if="task.status !== 'completed'"
        ><button class="btn secondary small" @click="toggleTask(task)">
          <Icon :name="task.status === 'running' ? 'pause' : 'play'" :size="14" />{{
            task.status === 'running' ? '暂停' : '继续'
          }}</button
        ><button class="btn primary small" :disabled="task.status !== 'running'" @click="advanceTask(task)">
          推进演示<Icon name="arrow" :size="14" /></button></template
      ><button
        v-else-if="task.packageId"
        class="btn primary small"
        @click="openDialog('package', task.packageId)"
      >
        <Icon name="package" :size="14" />查看已发布模型包</button
      ><span v-else class="tag warning">待审核发布</span>
    </div>
    <div class="task-stages">
      <button
        v-for="(name, i) in stageNames"
        :key="name"
        :class="{ active: active === i, done: task.stage > i || task.status === 'completed' }"
        @click="active = i"
      >
        <span
          ><Icon v-if="task.stage > i || task.status === 'completed'" name="check" :size="13" /><template
            v-else
            >{{ i + 1 }}</template
          ></span
        >{{ name }}
      </button>
    </div>
    <div class="detail-tab-content task-tab-content">
      <div v-if="active > task.stage" class="empty-state">
        <Icon name="clock" :size="32" />
        <h3>该阶段尚未开始</h3>
        <p>通过上方「推进演示」继续模拟研发过程。</p>
      </div>
      <template v-else-if="active === 0"
        ><div class="detail-two-col">
          <section class="detail-section">
            <h3>业务需求</h3>
            <blockquote>{{ task.target }}</blockquote>
            <h3>目标能力</h3>
            <p>{{ task.capability }}</p>
          </section>
          <section class="detail-section">
            <h3>需求确认清单</h3>
            <ul class="check-list">
              <li><Icon name="checkCircle" :size="17" />明确输出、目标和适用范围</li>
              <li><Icon name="checkCircle" :size="17" />先查找当前项目已有能力</li>
              <li><Icon name="checkCircle" :size="17" />单独确认需要研发的能力缺口</li>
              <li><Icon name="checkCircle" :size="17" />研发预算：{{ task.budget }}</li>
            </ul>
          </section>
        </div>
        <div class="info-banner">
          <Icon name="file" :size="17" />
          <p>本页展示意图识别的产品结构。具体需求合同将在真实后端接入后生成。</p>
        </div></template
      >
      <template v-else-if="active === 1"
        ><div class="detail-two-col">
          <section class="detail-section">
            <h3>项目数据证据</h3>
            <div v-for="table in project.tables" :key="table.name" class="evidence-row">
              <Icon name="table" :size="18" />
              <div>
                <strong>{{ table.title }}</strong>
                <p>{{ table.columns.length }} 个字段 · {{ table.updated }}</p>
              </div>
              <span class="tag success">示例已读</span>
            </div>
          </section>
          <section class="detail-section">
            <h3>约束与数据边界</h3>
            <ul class="check-list">
              <li><Icon name="lock" :size="17" />按时间划分训练、开发与留出集合</li>
              <li><Icon name="lock" :size="17" />特征只使用决策时可获得的数据</li>
              <li><Icon name="lock" :size="17" />冻结单位、特征定义与目标口径</li>
              <li><Icon name="lock" :size="17" />候选执行失败需保留原因和修复关系</li>
            </ul>
          </section>
        </div>
        <div class="info-banner">
          <Icon name="database" :size="17" />
          <p>数据理解与问题驱动调查的结果将在此关联来源片段、检查脚本与结论。当前为合成示例。</p>
        </div></template
      >
      <template v-else-if="active === 2"
        ><div class="search-stats">
          <div>
            <span>候选程序</span><strong>{{ task.candidates }}<small>/ 16</small></strong>
          </div>
          <div>
            <span>最高开发评分</span><strong>{{ task.candidates >= 16 ? '0.940' : '0.930' }}</strong>
          </div>
          <div><span>搜索对象</span><strong class="text-value">算法程序</strong></div>
          <div><span>留出集</span><strong class="text-value">不参与选型</strong></div>
        </div>
        <div class="graph-heading">
          <div>
            <h3>候选算法搜索树</h3>
            <p>点击节点查看程序差异、评估与父节点关系。</p>
          </div>
          <div class="graph-legend">
            <span><i class="legend-dot green" />有效候选</span
            ><span><i class="legend-dot amber" />失败 / 调试</span
            ><span><i class="legend-dot blue" />融合</span>
          </div>
        </div>
        <div class="search-tree">
          <svg viewBox="0 0 1030 430" role="group" aria-label="模拟候选算法搜索树">
            <defs>
              <pattern id="gridDots" width="20" height="20" patternUnits="userSpaceOnUse">
                <circle cx="1" cy="1" r="1" fill="#dfe7e7" />
              </pattern>
            </defs>
            <rect width="1030" height="430" fill="url(#gridDots)" />
            <path
              v-for="e in edges"
              :key="e.to.id"
              :d="`M${e.from.x + 57},${e.from.y} C${e.from.x + 95},${e.from.y} ${e.to.x - 95},${e.to.y} ${e.to.x - 57},${e.to.y}`"
              fill="none"
              :stroke="e.to.type === 'failed' ? '#d8b980' : '#b6cbc7'"
              stroke-width="1.7"
            />
            <path
              v-if="task.candidates >= 12"
              d="M477 265 C660 265 620 135 713 115"
              stroke="#81a9cb"
              stroke-dasharray="5 4"
              fill="none"
              stroke-width="1.7"
            />
            <g
              v-for="n in visibleNodes"
              :key="n.id"
              role="button"
              tabindex="0"
              :aria-label="'候选 ' + n.id + ' ' + n.label"
              :aria-pressed="selected === n.id"
              :class="['tree-node', n.type, { selected: selected === n.id }]"
              @click="selected = n.id"
              @keydown.enter.prevent="selected = n.id"
              @keydown.space.prevent="selected = n.id"
            >
              <rect :x="n.x - 57" :y="n.y - 29" width="114" height="58" rx="8" />
              <text :x="n.x - 44" :y="n.y - 10" class="node-id">
                #{{ String(n.id).padStart(2, '0') }} ·
                {{
                  n.type === 'fusion'
                    ? 'FUSION'
                    : n.type === 'debug'
                      ? 'DEBUG'
                      : n.type === 'failed'
                        ? 'FAILED'
                        : 'CANDIDATE'
                }}
              </text>
              <text :x="n.x - 44" :y="n.y + 7" class="node-label">{{ n.label }}</text>
              <text :x="n.x - 44" :y="n.y + 21" class="node-score">
                {{ n.score ? n.score.toFixed(3) : 'shape error' }}
              </text>
            </g>
          </svg>
        </div>
        <div class="candidate-details">
          <div>
            <h3>候选 #{{ node.id }} · {{ node.label }}</h3>
            <p>
              父节点 {{ node.parent ? '#' + node.parent : '无（基线）'
              }}{{ node.type === 'fusion' ? ' · 额外参考 #07' : '' }}
            </p>
            <div class="candidate-score">
              <span>开发评分（模拟）</span><strong>{{ node.score.toFixed(3) }}</strong>
            </div>
            <p class="hint">
              图中是候选程序的创建、改进、失败、修复与融合，不是业务动作枚举。为便于预览，展示 14
              个节点的固定示例。
            </p>
          </div>
          <pre class="dark-code">{{ nodeCode }}</pre>
        </div></template
      >
      <template v-else-if="active === 3"
        ><div class="info-banner">
          <Icon name="shield" :size="20" />
          <div>
            <strong>搜索完成后，使用独立留出集验证。</strong>
            <p>开发评分用于搜索；留出结果用于检查泛化与业务约束，两者分开保存。</p>
          </div>
        </div>
        <section class="detail-section">
          <h3>独立验证结果 <span class="tag neutral">合成示例</span></h3>
          <table>
            <thead>
              <tr>
                <th>检查项</th>
                <th>验收方式</th>
                <th>演示结果</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td>输入 / 输出合同</td>
                <td>字段、单位、类型、异常输入测试</td>
                <td><span class="tag success">通过</span></td>
              </tr>
              <tr>
                <td>独立留出集</td>
                <td>按时间隔离，不回流搜索</td>
                <td><span class="tag success">样例通过</span></td>
              </tr>
              <tr>
                <td>基线比较</td>
                <td>相同数据划分与评估口径</td>
                <td><span class="tag success">样例改善</span></td>
              </tr>
              <tr>
                <td>生产验收</td>
                <td>真实数据与业务人员复核</td>
                <td><span class="tag warning">未执行</span></td>
              </tr>
            </tbody>
          </table>
        </section>
        <p class="hint">这些指标与检查仅用于前端布局，不是 AutoDecision 的真实运行成绩。</p></template
      >
      <template v-else
        ><div class="report-hero">
          <span class="hero-icon"><Icon name="file" :size="32" /></span>
          <div>
            <h2>研发成果</h2>
            <p>候选选择、验证说明、模型文件与输入合同共同组成交付包。</p>
          </div>
          <button
            class="btn secondary small"
            @click="
              download(
                task.id + '-report-demo.md',
                `# ${task.title}\n\n> 前端模拟报告，没有真实训练或验证。\n\n目标：${task.target}\n候选：${task.candidates}\n发布能力：${task.capability}\n\n生产验收：未执行。`,
                'text/markdown',
              )
            "
          >
            <Icon name="download" :size="15" />导出报告
          </button>
        </div>
        <div class="artifact-grid">
          <div
            v-for="a in [
              { name: 'SKILL.md', desc: '能力与调用说明', icon: 'book' },
              { name: 'manifest.json', desc: '版本、入口与来源', icon: 'fileCode' },
              { name: 'model/', desc: '冻结模型与预处理', icon: 'box' },
              { name: 'validation/', desc: '验证与约束检查', icon: 'shield' },
            ]"
            :key="a.name"
          >
            <Icon :name="a.icon" :size="22" /><strong>{{ a.name }}</strong
            ><span>{{ a.desc }}</span>
          </div>
        </div>
        <div class="publish-panel">
          <div>
            <h3>{{ task.packageId ? '能力已加入模型包库' : '将研发成果发布为模型包' }}</h3>
            <p>发布后可在项目对话中直接复用。原有版本和来源任务保留。</p>
            <label v-if="!task.packageId" class="checkbox-label"
              ><input
                type="checkbox"
                v-model="reviewed"
              />我已检查演示合同与验证范围，理解此包没有真实模型文件。</label
            >
          </div>
          <button v-if="!task.packageId" class="btn primary" :disabled="!reviewed" @click="publishTask(task)">
            <Icon name="package" :size="16" />发布演示模型包</button
          ><button v-else class="btn primary" @click="openDialog('package', task.packageId)">
            查看模型包<Icon name="arrow" :size="16" />
          </button></div
      ></template>
    </div>
  </div>
</template>
