<script setup lang="ts">
import { shallowRef } from 'vue'
import type { AutoRealizeConfig } from '../types'

const props = withDefaults(defineProps<{
  disabled?: boolean
}>(), {
  disabled: false,
})

const model = defineModel<AutoRealizeConfig>({ required: true })

type SectionKey = 'throughput' | 'cognition' | 'investigation' | 'context' | 'quality'

const sections: Array<{ key: SectionKey; label: string }> = [
  { key: 'throughput', label: '成本与吞吐' },
  { key: 'cognition', label: '数据认知' },
  { key: 'investigation', label: '问题调查' },
  { key: 'context', label: '上下文管理' },
  { key: 'quality', label: '质量与交付' },
]

const activeSection = shallowRef<SectionKey>('throughput')

function commit() {
  model.value = { ...model.value }
}
</script>

<template>
  <div class="stage-settings">
    <nav class="settings-nav" aria-label="AutoRealize 配置分类">
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
      <section v-if="activeSection === 'throughput'" class="settings-section">
        <h3 class="section-title">成本与吞吐</h3>
        <div class="settings-grid">
          <label class="setting-field emphasis">
            <span>LLM 并发请求数</span>
            <input v-model.number="model.llm_concurrency" type="number" min="1" max="512" :disabled="props.disabled" @input="commit" />
          </label>
          <label class="setting-field emphasis">
            <span>单次 LLM 超时（秒）</span>
            <input v-model.number="model.llm_timeout" type="number" min="30" step="30" :disabled="props.disabled" @input="commit" />
          </label>
        </div>
        <div class="toggle-list">
          <label class="toggle-row">
            <input v-model="model.optimize_llm_cost" type="checkbox" :disabled="props.disabled" @change="commit" />
            启用低 Token Headroom 路径
          </label>
          <label class="toggle-row">
            <input v-model="model.enable_fewshot" type="checkbox" :disabled="props.disabled" @change="commit" />
            在支持的环节注入 few-shot 示例
          </label>
        </div>
      </section>

      <section v-else-if="activeSection === 'cognition'" class="settings-section">
        <h3 class="section-title">数据认知</h3>
        <div class="settings-grid">
          <label class="setting-field emphasis">
            <span>逐文件 LLM 认知范围</span>
            <select v-model="model.llm_file_cognition_mode" :disabled="props.disabled" @change="commit">
              <option value="all">全部支持文件</option>
              <option value="documents_only">仅文档与非结构化文件</option>
              <option value="none">关闭逐文件 LLM 认知</option>
            </select>
          </label>
          <label class="setting-field">
            <span>表格画像采样行数</span>
            <input v-model.number="model.table_profile_sample_rows" type="number" min="0" step="1000" :disabled="props.disabled" @input="commit" />
          </label>
        </div>
        <div class="toggle-list">
          <label class="toggle-row">
            <input v-model="model.enable_vllm" type="checkbox" :disabled="props.disabled" @change="commit" />
            启用视觉模型认知图片
          </label>
        </div>
      </section>

      <section v-else-if="activeSection === 'investigation'" class="settings-section">
        <h3 class="section-title">问题驱动调查</h3>
        <div class="toggle-list">
          <label class="toggle-row">
            <input v-model="model.enable_question_investigator" type="checkbox" :disabled="props.disabled" @change="commit" />
            启用跨文件 Question-Driven Investigator
          </label>
        </div>
        <div v-if="model.enable_question_investigator" class="settings-grid">
          <label class="setting-field emphasis">
            <span>最多调查问题数</span>
            <input v-model.number="model.investigation_max_questions" type="number" min="1" :disabled="props.disabled" @input="commit" />
          </label>
          <label class="setting-field emphasis">
            <span>每个问题最多动作轮数</span>
            <input v-model.number="model.investigation_max_rounds_per_question" type="number" min="1" :disabled="props.disabled" @input="commit" />
          </label>
          <label class="setting-field">
            <span>每个问题最多脚本数</span>
            <input v-model.number="model.investigation_max_scripts_per_question" type="number" min="0" :disabled="props.disabled" @input="commit" />
          </label>
          <label class="setting-field">
            <span>调查脚本超时（秒）</span>
            <input v-model.number="model.investigation_script_timeout_secs" type="number" min="1" step="5" :disabled="props.disabled" @input="commit" />
          </label>
        </div>
      </section>

      <section v-else-if="activeSection === 'context'" class="settings-section">
        <h3 class="section-title">上下文管理</h3>
        <div class="settings-grid">
          <label class="setting-field emphasis">
            <span>单次提示 Token 预算</span>
            <input v-model.number="model.prompt_token_budget" type="number" min="2000" step="1000" :disabled="props.disabled" @input="commit" />
          </label>
          <label class="setting-field">
            <span>输入上下文占比</span>
            <input v-model.number="model.cross_stage_headroom_ratio" type="number" min="0.4" max="0.9" step="0.01" :disabled="props.disabled" @input="commit" />
          </label>
        </div>
        <div class="toggle-list">
          <label class="toggle-row">
            <input v-model="model.cross_stage_memory_enabled" type="checkbox" :disabled="props.disabled" @change="commit" />
            启用跨阶段稳定前缀与动态记忆压缩
          </label>
          <label class="toggle-row">
            <input v-model="model.cross_stage_retrieval_enabled" type="checkbox" :disabled="props.disabled || !model.cross_stage_memory_enabled" @change="commit" />
            允许按需取回被压缩的精确证据
          </label>
        </div>
      </section>

      <section v-else class="settings-section">
        <h3 class="section-title">质量与交付</h3>
        <div class="toggle-list">
          <label class="toggle-row">
            <input v-model="model.artifact_consistency_enabled" type="checkbox" :disabled="props.disabled" @change="commit" />
            审查最终描述与机器合同的一致性
          </label>
          <label class="toggle-row">
            <input v-model="model.generate_sample_submission" type="checkbox" :disabled="props.disabled" @change="commit" />
            为需要提交协议的任务生成 sample_submission.csv
          </label>
        </div>
        <div v-if="model.artifact_consistency_enabled" class="settings-grid">
          <label class="setting-field">
            <span>一致性审查最大轮数</span>
            <input v-model.number="model.artifact_consistency_max_rounds" type="number" min="1" max="6" :disabled="props.disabled" @input="commit" />
          </label>
        </div>
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

.setting-field.emphasis > span {
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
