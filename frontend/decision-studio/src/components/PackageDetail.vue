<script setup lang="ts">
import { ref } from 'vue'
import Icon from './Icon.vue'
import type { ModelPackage } from '../types'
import { usePackage, download, manifest, openDialog } from '../store'
defineProps<{ pkg: ModelPackage }>()
const tab = ref('overview')
</script>
<template>
  <div class="package-detail">
    <div class="detail-hero">
      <span class="hero-icon"><Icon :name="pkg.icon" :size="32" /></span>
      <div>
        <div class="eyebrow">
          ALGORITHM PACKAGE <span class="tag success"><Icon name="lock" :size="11" />版本冻结</span>
        </div>
        <h2>
          {{ pkg.name }} <small>v{{ pkg.version }}</small>
        </h2>
        <p>{{ pkg.description }}</p>
      </div>
    </div>
    <div class="detail-actions">
      <button class="btn primary" @click="usePackage(pkg)"><Icon name="chat" :size="16" />在对话中使用</button
      ><button class="btn secondary" @click="download(pkg.id + '-manifest-demo.json', manifest(pkg))">
        <Icon name="download" :size="16" />导出包说明</button
      ><span class="hint">{{ pkg.calls }} 次模拟调用</span>
    </div>
    <div class="tabs">
      <button
        v-for="t in [
          { id: 'overview', name: '能力与范围' },
          { id: 'contract', name: '输入 / 输出合同' },
          { id: 'files', name: '文件与调用' },
          { id: 'versions', name: '版本与来源' },
        ]"
        :key="t.id"
        :class="{ active: tab === t.id }"
        @click="tab = t.id"
      >
        {{ t.name }}
      </button>
    </div>
    <div class="detail-tab-content">
      <template v-if="tab === 'overview'"
        ><div class="info-banner">
          <Icon name="shield" :size="18" />
          <div>
            <strong>可以调整输入，让冻结能力复用到新的需求。</strong>
            <p>调整须符合单位、时间、特征与范围约定；超出合同的需求需要新的研发任务。</p>
          </div>
        </div>
        <div class="detail-two-col">
          <section class="detail-section">
            <h3>适用范围与边界</h3>
            <p>{{ pkg.limits }}</p>
            <div class="package-tags">
              <span v-for="tag in pkg.tags" :key="tag">{{ tag }}</span>
            </div>
          </section>
          <section class="detail-section metric-feature">
            <span>{{ pkg.metric }}</span
            ><strong>{{ pkg.metricValue }}</strong>
            <p>演示指标 · {{ pkg.validation }}</p>
          </section>
        </div>
        <section class="detail-section">
          <h3>运行时允许调整</h3>
          <code class="code-line">{{ pkg.parameters }}</code>
        </section>
        <section class="detail-section">
          <h3>与版本共同冻结</h3>
          <div class="frozen-items">
            <span
              v-for="item in [
                '模型权重 / 算法源码',
                '特征顺序与业务语义',
                '预处理与标准化状态',
                '输入 / 输出合同',
              ]"
              :key="item"
              ><Icon name="lock" :size="14" />{{ item }}</span
            >
          </div>
        </section></template
      >
      <template v-else-if="tab === 'contract'"
        ><section class="detail-section">
          <h3>输入合同</h3>
          <p>先做兼容性检查，再执行字段映射和显式转换。</p>
          <div class="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>字段</th>
                  <th>类型</th>
                  <th>单位 / 时区</th>
                  <th>约束</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="f in pkg.input" :key="f.field">
                  <td>
                    <code>{{ f.field }}</code
                    ><span v-if="f.required" class="required-mark">*</span>
                  </td>
                  <td>{{ f.type }}</td>
                  <td>{{ f.unit }}</td>
                  <td>{{ f.description }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </section>
        <section class="detail-section">
          <h3>输出合同</h3>
          <code class="code-line">{{ pkg.output }}</code>
        </section>
        <div class="info-banner">
          <Icon name="sliders" :size="18" />
          <div>
            <strong>映射不是重新训练</strong>
            <p>可做字段重命名、明确的单位换算、合法时间对齐。不能擅自插补缺失特征，或把能量当作功率。</p>
          </div>
        </div></template
      >
      <template v-else-if="tab === 'files'"
        ><section class="detail-section">
          <h3>推理 / 求解入口</h3>
          <code class="code-line">{{ pkg.entry }}</code>
          <p>调用仅使用已冻结的版本；训练应由独立研发任务发起。</p>
        </section>
        <section class="detail-section">
          <h3>包内文件布局 <span class="tag neutral">拟定路径 · 示例</span></h3>
          <pre class="light-code">{{
            `package/\n├── SKILL.md              # 能力、适用范围与调用说明\n├── manifest.json         # 版本、合同、文件指纹\n├── schema/\n│   ├── input.schema.json\n│   └── output.schema.json\n├── model/                # 冻结模型与预处理状态\n├── algorithm/            # 推理或求解入口\n├── environment.lock      # 可复现运行依赖\n└── validation/           # 留出验证与来源任务`
          }}</pre>
        </section>
        <section class="detail-section">
          <h3>模型 / 算法位置</h3>
          <code class="code-line">{{ pkg.artifact }}</code>
          <p>当前浏览器 Demo 中没有真实模型文件，路径仅用于产品设计。</p>
        </section>
        <section class="detail-section">
          <h3>运行环境</h3>
          <p>{{ pkg.runtime }}</p>
        </section></template
      >
      <template v-else
        ><div class="version-timeline">
          <span class="timeline-dot" />
          <div>
            <span class="tag success">当前版本</span>
            <h3>v{{ pkg.version }}</h3>
            <p>{{ pkg.created }} · 从任务发布</p>
            <button class="text-btn" @click="openDialog('task', pkg.taskId)">
              查看来源任务 {{ pkg.taskId }}<Icon name="arrow" :size="14" />
            </button>
            <p class="hint">
              模型、预处理状态、输入合同作为同一个版本发布。任何训练变更应创建新版本，已有调用仍指向原版本。
            </p>
          </div>
        </div>
        <div class="info-banner">
          <Icon name="file" :size="18" />
          <div>
            <strong>验证记录</strong>
            <p>{{ pkg.validation }}</p>
          </div>
        </div></template
      >
    </div>
  </div>
</template>
