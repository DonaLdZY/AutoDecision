<script setup lang="ts">
import { computed, shallowRef } from 'vue'
import type { AutoReportConfig } from '../types'
import { normalizeAutoReportConfig } from '../utils/autoReport'

const props = withDefaults(defineProps<{
  disabled?: boolean
}>(), {
  disabled: false,
})

const model = defineModel<AutoReportConfig>({ required: true })

type SectionKey = 'content' | 'analysis' | 'generation'

const sections: Array<{ key: SectionKey; label: string }> = [
  { key: 'content', label: '报告内容' },
  { key: 'analysis', label: '方法分析' },
  { key: 'generation', label: '生成与检查' },
]

const activeSection = shallowRef<SectionKey>('content')

const estimatedCalls = computed(() => {
  const base = 2 + (model.value.enable_report_audit ? 1 : 0)
  return model.value.max_retrieval_rounds > 0
    ? `${base}-${base + model.value.max_retrieval_rounds}`
    : String(base)
})

function update<K extends keyof AutoReportConfig>(key: K, value: AutoReportConfig[K]) {
  model.value = normalizeAutoReportConfig({ ...model.value, [key]: value })
}
</script>

<template>
  <div class="stage-settings">
    <nav class="settings-nav" aria-label="AutoReport 配置分类">
      <button
        v-for="section in sections"
        :key="section.key"
        type="button"
        class="settings-nav-button"
        :class="{ active: activeSection === section.key }"
        :aria-current="activeSection === section.key ? 'page' : undefined"
        @click="activeSection = section.key"
      >
        {{ section.label }}
      </button>
    </nav>

    <div class="settings-content">
      <section v-if="activeSection === 'content'" class="settings-section">
        <h3 class="section-title">报告内容</h3>
        <div class="toggle-list">
          <label class="toggle-row emphasis">
            <input
              type="checkbox"
              :checked="model.enabled"
              :disabled="props.disabled"
              @change="update('enabled', ($event.target as HTMLInputElement).checked)"
            />
            生成最终方案报告
          </label>
        </div>
        <div class="settings-grid">
          <label class="setting-field emphasis">
            <span>主要读者</span>
            <select
              :value="model.audience"
              :disabled="props.disabled || !model.enabled"
              @change="update('audience', ($event.target as HTMLSelectElement).value as AutoReportConfig['audience'])"
            >
              <option value="technical">技术复现</option>
              <option value="delivery">模型交付</option>
              <option value="executive">管理摘要</option>
            </select>
          </label>
          <label class="setting-field emphasis">
            <span>详细程度</span>
            <select
              :value="model.detail_level"
              :disabled="props.disabled || !model.enabled"
              @change="update('detail_level', ($event.target as HTMLSelectElement).value as AutoReportConfig['detail_level'])"
            >
              <option value="concise">精简</option>
              <option value="standard">标准</option>
              <option value="detailed">详细</option>
            </select>
          </label>
        </div>
        <p class="settings-note">当前配置预计调用模型 {{ estimatedCalls }} 次。</p>
      </section>

      <section v-else-if="activeSection === 'analysis'" class="settings-section">
        <h3 class="section-title">方法分析</h3>
        <div class="settings-grid">
          <label class="setting-field emphasis">
            <span>比较候选数量</span>
            <input
              type="number"
              min="2"
              max="12"
              step="1"
              :value="model.comparison_candidate_limit"
              :disabled="props.disabled || !model.enabled"
              @input="update('comparison_candidate_limit', Number(($event.target as HTMLInputElement).value))"
            />
          </label>
          <label class="setting-field">
            <span>代码补读轮次</span>
            <input
              type="number"
              min="0"
              max="4"
              step="1"
              :value="model.max_retrieval_rounds"
              :disabled="props.disabled || !model.enabled"
              @input="update('max_retrieval_rounds', Number(($event.target as HTMLInputElement).value))"
            />
          </label>
        </div>
      </section>

      <section v-else class="settings-section">
        <h3 class="section-title">生成与检查</h3>
        <div class="toggle-list">
          <label class="toggle-row">
            <input
              type="checkbox"
              :checked="model.enable_report_audit"
              :disabled="props.disabled || !model.enabled"
              @change="update('enable_report_audit', ($event.target as HTMLInputElement).checked)"
            />
            审查最终报告的方法说明、候选对比和模型使用方式
          </label>
        </div>
        <p class="settings-note">开启审查会增加 1 次模型调用。</p>
      </section>
    </div>
  </div>
</template>

<style scoped>
.stage-settings {
  display: grid;
  grid-template-columns: 184px minmax(0, 1fr);
  min-height: 420px;
  border-block: 1px solid #c9d7ec;
  background: #fff;
}

.settings-nav {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 12px 10px;
  border-right: 1px solid #d5dfef;
  background: #eef3fa;
}

.settings-nav-button {
  min-height: 40px;
  border: 0;
  border-left: 3px solid transparent;
  padding: 8px 10px;
  background: transparent;
  color: #315074;
  text-align: left;
  font: inherit;
  letter-spacing: 0;
  cursor: pointer;
}

.settings-nav-button:hover {
  background: #e2eaf5;
}

.settings-nav-button.active {
  border-left-color: #247067;
  background: #dce9e7;
  color: #174f49;
  font-weight: 700;
}

.settings-content {
  min-width: 0;
  padding: 16px 18px 20px;
}

.settings-section {
  display: grid;
  gap: 16px;
}

.section-title {
  margin: 0;
  padding-bottom: 10px;
  border-bottom: 1px solid #dbe3ef;
  color: #183550;
  font-size: 15px;
  letter-spacing: 0;
}

.settings-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px 14px;
}

.setting-field {
  display: grid;
  gap: 6px;
  min-width: 0;
  color: #314a67;
  font-size: 13px;
}

.setting-field.emphasis > span,
.toggle-row.emphasis {
  color: #174f49;
  font-weight: 700;
}

.setting-field input,
.setting-field select {
  width: 100%;
  min-width: 0;
  box-sizing: border-box;
  border: 1px solid #b8c8dd;
  border-radius: 5px;
  padding: 8px 9px;
  background: #fff;
  color: #172f49;
  font: inherit;
}

.toggle-list {
  display: grid;
  gap: 9px;
}

.toggle-row {
  display: flex;
  align-items: flex-start;
  gap: 9px;
  min-width: 0;
  color: #294460;
  font-size: 13px;
  line-height: 1.45;
}

.toggle-row input {
  flex: 0 0 auto;
  margin-top: 2px;
}

.settings-note {
  margin: 0;
  color: #647991;
  font-size: 12px;
  line-height: 1.45;
}

@media (max-width: 760px) {
  .stage-settings {
    grid-template-columns: 1fr;
  }

  .settings-nav {
    flex-direction: row;
    overflow-x: auto;
    border-right: 0;
    border-bottom: 1px solid #d5dfef;
  }

  .settings-nav-button {
    flex: 0 0 auto;
    border-left: 0;
    border-bottom: 3px solid transparent;
    white-space: nowrap;
  }

  .settings-nav-button.active {
    border-bottom-color: #247067;
  }

  .settings-grid {
    grid-template-columns: 1fr;
  }
}
</style>
