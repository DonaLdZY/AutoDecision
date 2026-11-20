<script setup lang="ts">
import { computed, ref } from 'vue'
import Icon from './Icon.vue'
import { packages, project, openDialog, usePackage, newConversation } from '../store'
const query = ref('')
const filter = ref('全部能力')
function clearFilters() {
  query.value = ''
  filter.value = '全部能力'
}
const filters = ['全部能力', '预测模型', '优化算法', '检测模型', '决策模型']
const filtered = computed(() =>
  packages.value.filter(
    (p) =>
      (filter.value === '全部能力' || p.kind === filter.value) &&
      `${p.name} ${p.description} ${p.tags.join(' ')}`.toLowerCase().includes(query.value.toLowerCase()),
  ),
)
</script>
<template>
  <div class="standard-page">
    <div class="page-heading">
      <div>
        <h1>
          算法模型包 <span class="heading-count">{{ packages.length }}</span>
        </h1>
      </div>
      <button class="btn primary" @click="newConversation"><Icon name="plus" :size="16" />新建研发任务</button>
    </div>
    <div class="filter-toolbar">
      <div class="pill-tabs">
        <button v-for="f in filters" :key="f" :class="{ active: filter === f }" @click="filter = f">
          {{ f }}
        </button>
      </div>
      <div class="search-box">
        <Icon name="search" :size="16" /><input
          v-model="query"
          aria-label="搜索模型包"
          placeholder="搜索名称、用途或算法…"
        />
      </div>
    </div>
    <div class="package-grid">
      <article v-for="pkg in filtered" :key="pkg.id" class="package-card">
        <div class="package-card-heading">
          <span
            :class="[
              'square-icon',
              pkg.scenario === 'compose' ? 'blue' : pkg.scenario === 'anomaly' ? 'amber' : '',
            ]"
            ><Icon :name="pkg.icon" :size="23" /></span
          ><span class="tag neutral">{{ pkg.kind }}</span
          ><button
            class="icon-btn"
            :aria-label="'查看' + pkg.name + '详情'"
            @click="openDialog('package', pkg.id)"
          >
            <Icon name="arrow" :size="17" />
          </button>
        </div>
        <button class="package-title" @click="openDialog('package', pkg.id)">
          {{ pkg.name }}<span>v{{ pkg.version }}</span>
        </button>
        <p class="package-description">{{ pkg.description }}</p>
        <div class="package-tags">
          <span v-for="tag in pkg.tags" :key="tag">{{ tag }}</span>
        </div>
        <div class="package-quality">
          <div>
            <span>{{ pkg.metric }}</span
            ><strong>{{ pkg.metricValue }}<small>模拟</small></strong>
          </div>
          <div><Icon name="lock" :size="13" />版本已冻结</div>
        </div>
        <div class="package-entry">
          <Icon name="terminal" :size="14" /><code>{{ pkg.entry.split(' → ')[0] }}</code>
        </div>
        <footer>
          <span>{{ pkg.calls }} 次调用</span
          ><button class="text-btn" @click="usePackage(pkg)">
            在对话中使用<Icon name="arrow" :size="15" />
          </button>
        </footer>
      </article>
      <button class="package-create" @click="newConversation">
        <span><Icon name="plus" :size="26" /></span>
        <h3>还没有合适的能力？</h3>
        <p>从一个新需求开始<br />让 AutoDecision 探索解决方案</p>
        <strong>提出需求<Icon name="arrow" :size="15" /></strong>
      </button>
    </div>
    <div v-if="!filtered.length && packages.length" class="empty-state compact-empty">
      <Icon name="search" :size="30" />
      <h3>没有匹配的模型包</h3>
      <p>试试其他关键词或能力类型。</p>
      <button class="text-btn" @click="clearFilters">清除筛选</button>
    </div>
    <div class="bottom-hint">
      <Icon
        name="shield"
        :size="16"
      />模型包仅对当前项目可用。跨项目复用前，需重新检查数据语义、适用范围与输入合同。
    </div>
  </div>
</template>
