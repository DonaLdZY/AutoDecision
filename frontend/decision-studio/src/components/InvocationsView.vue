<script setup lang="ts">
import { computed, ref } from 'vue'
import Icon from './Icon.vue'
import { invocations, getPackage, openDialog, download } from '../store'
const query = ref('')
const filtered = computed(() =>
  invocations.value.filter((i) => `${i.title} ${i.id}`.toLowerCase().includes(query.value.toLowerCase())),
)
</script>
<template>
  <div class="standard-page">
    <div class="page-heading">
      <div>
        <h1>调用记录</h1>
      </div>
      <button class="btn secondary" @click="download('invocations-demo.json', { demo: true, invocations })">
        <Icon name="download" :size="16" />导出记录
      </button>
    </div>
    <div class="filter-toolbar">
      <div class="section-subtitle">{{ invocations.length }} 次模拟调用 <span>无需重复训练</span></div>
      <div class="search-box">
        <Icon name="search" :size="16" /><input
          v-model="query"
          placeholder="搜索调用记录…"
          aria-label="搜索调用记录"
        />
      </div>
    </div>
    <div class="records-table table-scroll">
      <table>
        <thead>
          <tr>
            <th>决策需求</th>
            <th>使用能力</th>
            <th>结果</th>
            <th>时间 / 耗时</th>
            <th />
          </tr>
        </thead>
        <tbody>
          <tr v-for="inv in filtered" :key="inv.id">
            <td>
              <button class="table-title" @click="openDialog('invocation', inv.id)">{{ inv.title }}</button>
            </td>
            <td>
              <div class="inline-packages">
                <span v-for="pid in inv.packageIds" :key="pid"
                  ><Icon name="package" :size="12" />{{ getPackage(pid)?.name }}</span
                >
              </div>
            </td>
            <td>
              <span class="tag success"><Icon name="check" :size="12" />模拟完成</span>
            </td>
            <td>
              {{ inv.created }}<small>{{ inv.duration }}</small>
            </td>
            <td>
              <button class="icon-btn" aria-label="查看调用详情" @click="openDialog('invocation', inv.id)">
                <Icon name="arrow" :size="17" />
              </button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
    <div v-if="!filtered.length" class="empty-state">
      <Icon name="history" :size="36" />
      <h3>还没有调用记录</h3>
      <p>暂无记录</p>
    </div>
  </div>
</template>
