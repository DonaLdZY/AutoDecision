<script setup lang="ts">
import { computed, shallowRef } from 'vue'
import type { AutoMLConfig } from '../types'

const props = withDefaults(defineProps<{
  disabled?: boolean
}>(), {
  disabled: false,
})

const model = defineModel<AutoMLConfig>({ required: true })

type SectionKey =
  | 'definition'
  | 'budget'
  | 'draft'
  | 'tree'
  | 'exploration'
  | 'fusion'
  | 'context'
  | 'review'
  | 'memory'
  | 'runtime'

const sections: Array<{ key: SectionKey; label: string }> = [
  { key: 'definition', label: '任务目标' },
  { key: 'budget', label: '搜索预算' },
  { key: 'draft', label: '草稿生成' },
  { key: 'tree', label: '树搜索' },
  { key: 'exploration', label: '探索调度' },
  { key: 'fusion', label: '分支融合' },
  { key: 'context', label: '上下文管理' },
  { key: 'review', label: '生成与评审' },
  { key: 'memory', label: '记忆与经验' },
  { key: 'runtime', label: '运行与交付' },
]

const activeSection = shallowRef<SectionKey>('definition')
const embeddingEnabled = computed(() => model.value.use_global_memory)
const embeddingMode = computed({
  get: () => (model.value.memory_embedding_backend.toLowerCase() === 'local' ? 'local' : 'remote'),
  set: (mode: 'local' | 'remote') => {
    model.value.memory_embedding_backend = mode === 'local' ? 'local' : 'openai'
    commit()
  },
})

function commit() {
  model.value = { ...model.value }
}
</script>

<template>
  <div class="stage-settings">
    <nav class="settings-nav" aria-label="AlgoEvolve 配置分类">
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
      <section v-if="activeSection === 'definition'" class="settings-section">
        <h3 class="section-title">无需 AutoRealize 时的任务合同</h3>
        <label class="setting-field emphasis">
          <span>Goal</span>
          <textarea
            v-model="model.goal"
            rows="6"
            :disabled="props.disabled"
            placeholder="明确描述要预测、优化或决策的目标，以及必须满足的业务约束。"
            @input="commit"
          />
        </label>
        <label class="setting-field emphasis">
          <span>Eval</span>
          <textarea
            v-model="model.eval"
            rows="5"
            :disabled="props.disabled"
            placeholder="明确评估指标、方向、验证方式，以及输出应满足的验收规则。"
            @input="commit"
          />
        </label>
      </section>

      <section v-else-if="activeSection === 'budget'" class="settings-section">
        <h3 class="section-title">搜索预算</h3>
        <div class="settings-grid">
          <label class="setting-field emphasis">
            <span>本次搜索时限（秒）</span>
            <input v-model.number="model.time_limit_secs" type="number" min="60" step="60" :disabled="props.disabled" @input="commit" />
          </label>
          <label class="setting-field emphasis">
            <span>本次搜索节点数</span>
            <input v-model.number="model.steps" type="number" min="1" :disabled="props.disabled" @input="commit" />
          </label>
          <label class="setting-field emphasis">
            <span>并行完整 Worker 数</span>
            <input v-model.number="model.parallel_search_num" type="number" min="1" :disabled="props.disabled" @input="commit" />
          </label>
          <label class="setting-field">
            <span>初始强制草稿数</span>
            <input v-model.number="model.initial_drafts" type="number" min="1" :disabled="props.disabled" @input="commit" />
          </label>
          <label class="setting-field">
            <span>单节点执行时限（秒）</span>
            <input v-model.number="model.exec_timeout_secs" type="number" min="10" step="10" :disabled="props.disabled" @input="commit" />
          </label>
        </div>
      </section>

      <section v-else-if="activeSection === 'draft'" class="settings-section">
        <h3 class="section-title">草稿生成</h3>
        <div class="toggle-list">
          <label class="toggle-row">
            <input v-model="model.fast_first_draft" type="checkbox" :disabled="props.disabled" @change="commit" />
            首个草稿使用 Fast Draft
          </label>
          <label class="toggle-row">
            <input v-model="model.fast_first_draft_skip_pre_review" type="checkbox" :disabled="props.disabled || !model.fast_first_draft" @change="commit" />
            Fast Draft 先执行，仅在运行证据需要时评审
          </label>
          <label class="toggle-row">
            <input v-model="model.use_stepwise_after_first" type="checkbox" :disabled="props.disabled" @change="commit" />
            后续草稿使用三阶段 Stepwise 生成
          </label>
        </div>
      </section>

      <section v-else-if="activeSection === 'tree'" class="settings-section">
        <h3 class="section-title">树搜索结构</h3>
        <div class="settings-grid">
          <label class="setting-field emphasis">
            <span>根节点最多草稿分支</span>
            <input v-model.number="model.search_num_drafts" type="number" min="1" :disabled="props.disabled" @input="commit" />
          </label>
          <label class="setting-field emphasis">
            <span>新根草稿竞争概率</span>
            <input v-model.number="model.search_root_new_draft_probability" type="number" min="0" max="1" step="0.05" :disabled="props.disabled" @input="commit" />
          </label>
          <label class="setting-field">
            <span>每个成功节点 Improve 分支数</span>
            <input v-model.number="model.search_num_improves" type="number" min="0" :disabled="props.disabled" @input="commit" />
          </label>
          <label class="setting-field">
            <span>每个错误节点 Debug 分支数</span>
            <input v-model.number="model.search_num_bugs" type="number" min="0" :disabled="props.disabled" @input="commit" />
          </label>
          <label class="setting-field">
            <span>Top-K 最大改进次数</span>
            <input v-model.number="model.search_topk_max_improves" type="number" min="0" :disabled="props.disabled" @input="commit" />
          </label>
          <label class="setting-field">
            <span>候选池大小</span>
            <input v-model.number="model.search_top_candidates_size" type="number" min="1" :disabled="props.disabled" @input="commit" />
          </label>
          <label class="setting-field">
            <span>最大连续 Debug 深度</span>
            <input v-model.number="model.search_max_debug_depth" type="number" min="0" :disabled="props.disabled" @input="commit" />
          </label>
          <label class="setting-field">
            <span>回溯 Debug 深度</span>
            <input v-model.number="model.search_back_debug_depth" type="number" min="0" :disabled="props.disabled" @input="commit" />
          </label>
          <label class="setting-field">
            <span>Debug 选择概率</span>
            <input v-model.number="model.search_debug_prob" type="number" min="0" max="1" step="0.05" :disabled="props.disabled" @input="commit" />
          </label>
          <label class="setting-field">
            <span>最小有效指标变化</span>
            <input v-model.number="model.metric_improvement_threshold" type="number" min="0" step="0.0001" :disabled="props.disabled" @input="commit" />
          </label>
          <label class="setting-field">
            <span>连续 Improve 失败阈值</span>
            <input v-model.number="model.max_improve_failure" type="number" min="1" :disabled="props.disabled" @input="commit" />
          </label>
        </div>
      </section>

      <section v-else-if="activeSection === 'exploration'" class="settings-section">
        <h3 class="section-title">探索与利用调度</h3>
        <div class="settings-grid">
          <label class="setting-field emphasis">
            <span>初始 UCT 探索常数</span>
            <input v-model.number="model.exploration_constant" type="number" min="0" step="0.01" :disabled="props.disabled" @input="commit" />
          </label>
          <label class="setting-field">
            <span>探索常数下限</span>
            <input v-model.number="model.lower_bound" type="number" min="0" step="0.01" :disabled="props.disabled" @input="commit" />
          </label>
          <label class="setting-field">
            <span>混合探索起点</span>
            <input v-model.number="model.search_explore_switch_start" type="number" min="0" max="1" step="0.05" :disabled="props.disabled" @input="commit" />
          </label>
          <label class="setting-field">
            <span>偏利用模式起点</span>
            <input v-model.number="model.search_explore_switch_end" type="number" min="0" max="1" step="0.05" :disabled="props.disabled" @input="commit" />
          </label>
          <label class="setting-field">
            <span>最小探索权重</span>
            <input v-model.number="model.search_min_exploration_weight" type="number" min="0" max="1" step="0.05" :disabled="props.disabled" @input="commit" />
          </label>
          <label class="setting-field">
            <span>普通分支停滞阈值</span>
            <input v-model.number="model.search_branch_stagnation_threshold" type="number" min="1" :disabled="props.disabled" @input="commit" />
          </label>
          <label class="setting-field">
            <span>Top-K 停滞阈值</span>
            <input v-model.number="model.search_topk_stagnation_threshold" type="number" min="1" :disabled="props.disabled" @input="commit" />
          </label>
          <label class="setting-field">
            <span>停滞检测窗口</span>
            <input v-model.number="model.search_stagnation_window" type="number" min="1" :disabled="props.disabled" @input="commit" />
          </label>
        </div>
      </section>

      <section v-else-if="activeSection === 'fusion'" class="settings-section">
        <h3 class="section-title">分支融合</h3>
        <div class="settings-grid">
          <label class="setting-field emphasis">
            <span>满足条件后的融合触发概率</span>
            <input v-model.number="model.branch_fusion_trigger_prob" type="number" min="0" max="1" step="0.05" :disabled="props.disabled" @input="commit" />
          </label>
          <label class="setting-field emphasis">
            <span>停滞时融合替代演化概率</span>
            <input v-model.number="model.fusion_vs_evolution_prob" type="number" min="0" max="1" step="0.05" :disabled="props.disabled" @input="commit" />
          </label>
          <label class="setting-field">
            <span>单次最多融合草稿数</span>
            <input v-model.number="model.max_fusion_drafts" type="number" min="1" :disabled="props.disabled" @input="commit" />
          </label>
          <label class="setting-field">
            <span>融合最少剩余时间（秒）</span>
            <input v-model.number="model.search_fusion_min_remaining_seconds" type="number" min="0" step="30" :disabled="props.disabled" @input="commit" />
          </label>
          <label class="setting-field">
            <span>每分支最少成功节点数</span>
            <input v-model.number="model.search_fusion_min_successful_nodes" type="number" min="1" :disabled="props.disabled" @input="commit" />
          </label>
          <label class="setting-field">
            <span>融合所需独立分支数</span>
            <input v-model.number="model.search_fusion_min_branches" type="number" min="2" :disabled="props.disabled" @input="commit" />
          </label>
        </div>
      </section>

      <section v-else-if="activeSection === 'context'" class="settings-section">
        <h3 class="section-title">Provider 友好上下文</h3>
        <div class="settings-grid">
          <label class="setting-field emphasis">
            <span>Stepwise 压缩触发 Token</span>
            <input v-model.number="model.stepwise_context_max_tokens" type="number" min="4096" step="1024" :disabled="props.disabled || !model.use_stepwise_after_first" @input="commit" />
          </label>
          <label class="setting-field">
            <span>预留推理与输出比例</span>
            <input v-model.number="model.stepwise_context_headroom_ratio" type="number" min="0.05" max="0.5" step="0.01" :disabled="props.disabled || !model.use_stepwise_after_first" @input="commit" />
          </label>
          <label class="setting-field">
            <span>压缩时保留最近步骤数</span>
            <input v-model.number="model.stepwise_compaction_keep_recent_steps" type="number" min="1" max="10" :disabled="props.disabled || !model.use_stepwise_after_first" @input="commit" />
          </label>
          <label class="setting-field">
            <span>单次压缩输出 Token</span>
            <input v-model.number="model.stepwise_compaction_max_tokens" type="number" min="512" step="512" :disabled="props.disabled || !model.use_stepwise_after_first" @input="commit" />
          </label>
        </div>
      </section>

      <section v-else-if="activeSection === 'review'" class="settings-section">
        <h3 class="section-title">生成与评审</h3>
        <div class="settings-grid">
          <label class="setting-field emphasis">
            <span>编码模型温度</span>
            <input v-model.number="model.code_temperature" type="number" min="0" max="2" step="0.1" :disabled="props.disabled" @input="commit" />
          </label>
          <label class="setting-field emphasis">
            <span>评审模型温度</span>
            <input v-model.number="model.feedback_temperature" type="number" min="0" max="2" step="0.1" :disabled="props.disabled" @input="commit" />
          </label>
          <label class="setting-field">
            <span>编码请求超时（秒）</span>
            <input v-model.number="model.code_request_timeout_secs" type="number" min="30" step="30" :disabled="props.disabled" @input="commit" />
          </label>
          <label class="setting-field">
            <span>评审请求超时（秒）</span>
            <input v-model.number="model.feedback_request_timeout_secs" type="number" min="30" step="30" :disabled="props.disabled" @input="commit" />
          </label>
          <label class="setting-field">
            <span>编码生成最大尝试次数</span>
            <input v-model.number="model.code_generation_max_retries" type="number" min="1" :disabled="props.disabled" @input="commit" />
          </label>
          <label class="setting-field">
            <span>评审生成最大尝试次数</span>
            <input v-model.number="model.feedback_generation_max_retries" type="number" min="1" :disabled="props.disabled" @input="commit" />
          </label>
          <label class="setting-field">
            <span>编码截断续写轮数</span>
            <input v-model.number="model.code_continuation_max_rounds" type="number" min="0" :disabled="props.disabled" @input="commit" />
          </label>
          <label class="setting-field">
            <span>评审截断续写轮数</span>
            <input v-model.number="model.feedback_continuation_max_rounds" type="number" min="0" :disabled="props.disabled" @input="commit" />
          </label>
          <label class="setting-field">
            <span>执行前代码审查次数</span>
            <input v-model.number="model.code_review_max_attempts" type="number" min="1" :disabled="props.disabled" @input="commit" />
          </label>
          <label class="setting-field emphasis">
            <span>预检查拒绝后整稿重生次数</span>
            <input v-model.number="model.preflight_regeneration_max_attempts" type="number" min="0" :disabled="props.disabled" @input="commit" />
          </label>
          <label class="setting-field">
            <span>代码提取失败重生成次数</span>
            <input v-model.number="model.code_generation_extract_max_attempts" type="number" min="1" :disabled="props.disabled" @input="commit" />
          </label>
          <label class="setting-field">
            <span>指标方向判断尝试次数</span>
            <input v-model.number="model.metric_direction_max_attempts" type="number" min="1" :disabled="props.disabled" @input="commit" />
          </label>
          <label class="setting-field">
            <span>结果评审尝试次数</span>
            <input v-model.number="model.result_review_max_attempts" type="number" min="1" :disabled="props.disabled" @input="commit" />
          </label>
          <label class="setting-field">
            <span>搜索记忆规划尝试次数</span>
            <input v-model.number="model.refine_plan_max_attempts" type="number" min="1" :disabled="props.disabled" @input="commit" />
          </label>
        </div>
        <div class="toggle-list">
          <label class="toggle-row">
            <input v-model="model.result_adjudicator_on_anomaly" type="checkbox" :disabled="props.disabled" @change="commit" />
            对极端或不确定分数调用第二次可信度复核
          </label>
          <label class="toggle-row">
            <input v-model="model.code_review_escalate_to_code" type="checkbox" :disabled="props.disabled" @change="commit" />
            Feedback 审查异常时升级到编码模型
          </label>
          <label class="toggle-row">
            <input v-model="model.use_diff_mode" type="checkbox" :disabled="props.disabled" @change="commit" />
            改进与调试使用 Diff Patch
          </label>
          <label class="toggle-row">
            <input v-model="model.check_data_leakage" type="checkbox" :disabled="props.disabled" @change="commit" />
            检查预测任务的数据泄漏
          </label>
        </div>
      </section>

      <section v-else-if="activeSection === 'memory'" class="settings-section">
        <h3 class="section-title">记忆与优化经验</h3>
        <div class="toggle-list">
          <label class="toggle-row">
            <input v-model="model.use_global_memory" type="checkbox" :disabled="props.disabled" @change="commit" />
            启用跨节点向量记忆
          </label>
          <label class="toggle-row">
            <input v-model="model.use_coldstart" type="checkbox" :disabled="props.disabled" @change="commit" />
            启用预测任务 Cold-start 知识
          </label>
          <label class="toggle-row">
            <input v-model="model.use_optimization_experience_library" type="checkbox" :disabled="props.disabled" @change="commit" />
            启用决策任务优化方法经验库
          </label>
        </div>
        <div class="settings-grid">
          <label v-if="embeddingEnabled" class="setting-field emphasis">
            <span>记忆相似度阈值</span>
            <input v-model.number="model.memory_similarity_threshold" type="number" min="0" max="1" step="0.01" :disabled="props.disabled" @input="commit" />
          </label>
          <label v-if="embeddingEnabled" class="setting-field">
            <span>Embedding 后端</span>
            <select v-model="embeddingMode" :disabled="props.disabled">
              <option value="remote">远程 API</option>
              <option value="local">本地模型</option>
            </select>
          </label>
          <label v-if="embeddingEnabled && embeddingMode === 'local'" class="setting-field">
            <span>本地 Embedding Device</span>
            <input v-model="model.memory_embedding_device" :disabled="props.disabled" @input="commit" />
          </label>
          <label v-if="embeddingEnabled && embeddingMode === 'local'" class="setting-field wide">
            <span>本地 Embedding 模型或路径</span>
            <input v-model="model.memory_embedding_model_path" :disabled="props.disabled" @input="commit" />
          </label>
          <label v-if="model.use_optimization_experience_library" class="setting-field">
            <span>单次注入经验卡数</span>
            <input v-model.number="model.optimization_experience_max_cards" type="number" min="0" :disabled="props.disabled" @input="commit" />
          </label>
          <label v-if="model.use_optimization_experience_library" class="setting-field">
            <span>经验命中最低分</span>
            <input v-model.number="model.optimization_experience_min_score" type="number" min="0" step="0.5" :disabled="props.disabled" @input="commit" />
          </label>
          <label v-if="model.use_optimization_experience_library" class="setting-field">
            <span>经验上下文最大字符数</span>
            <input v-model.number="model.optimization_experience_max_chars" type="number" min="500" step="500" :disabled="props.disabled" @input="commit" />
          </label>
        </div>
      </section>

      <section v-else class="settings-section">
        <h3 class="section-title">运行与交付</h3>
        <div class="toggle-list">
          <label class="toggle-row">
            <input v-model="model.auto_install_missing_dependencies" type="checkbox" :disabled="props.disabled" @change="commit" />
            缺少依赖时安装到任务隔离目录
          </label>
          <label class="toggle-row">
            <input v-model="model.generate_submission" type="checkbox" :disabled="props.disabled" @change="commit" />
            任务协议要求时生成 submission.csv
          </label>
          <label class="toggle-row">
            <input v-model="model.copy_data" type="checkbox" :disabled="props.disabled" @change="commit" />
            复制输入数据到 AlgoEvolve 工作区
          </label>
        </div>
        <div v-if="model.auto_install_missing_dependencies" class="settings-grid">
          <label class="setting-field emphasis">
            <span>依赖安装超时（秒）</span>
            <input v-model.number="model.dependency_install_timeout_secs" type="number" min="30" step="30" :disabled="props.disabled" @input="commit" />
          </label>
          <label class="setting-field">
            <span>单节点最多补充依赖数</span>
            <input v-model.number="model.dependency_install_max_packages" type="number" min="1" :disabled="props.disabled" @input="commit" />
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
  min-height: 520px;
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

.setting-field.wide {
  grid-column: 1 / -1;
}

.setting-field.emphasis > span {
  color: #174f49;
  font-weight: 700;
}

.setting-field input,
.setting-field select,
.setting-field textarea {
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

  .setting-field.wide {
    grid-column: auto;
  }
}
</style>
