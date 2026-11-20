<script setup lang="ts">
import { computed } from 'vue'
const props = defineProps<{ facts: Record<string, unknown>; text: Record<string, unknown> }>()
type Row = Record<string, unknown>
const obj = (v: unknown): Row => (v && typeof v === 'object' && !Array.isArray(v) ? (v as Row) : {})
const arr = (v: unknown): Row[] => (Array.isArray(v) ? (v as Row[]) : [])
const num = (v: unknown): number | null => (typeof v === 'number' && Number.isFinite(v) ? v : null)
const str = (v: unknown): string => (v === null || v === undefined ? '' : String(v))

const SHOWN = 3
const rules = computed(() =>
  arr(obj(obj(props.facts['发现'])['检查规则'])['风险最高的规则'])
    .map((row) => ({
      id: str(row['编号']),
      conditions: str(row['规则'])
        .split(' 且 ')
        .map((c) =>
          c
            .replace(/（[^）]*）/g, '')
            .replace(/\s*([≤≥<>=])\s*/, ' $1 ')
            .trim(),
        )
        .filter(Boolean),
      hits: num(row['验收集中命中次数']),
      faults: num(row['验收集中真实故障次数']),
      rate: num(row['验收集中实际故障率百分比']),
    }))
    .sort((a, b) => (b.rate ?? -1) - (a.rate ?? -1)),
)
const shown = computed(() => rules.value.slice(0, SHOWN))
const rest = computed(() => rules.value.slice(SHOWN))
// 分档只看验收数据：命中太少不下结论。
function tier(rule: { hits: number | null; rate: number | null }) {
  if (rule.hits === null || rule.rate === null) return { tone: 'neutral', label: '待核实' }
  if (rule.hits < 5) return { tone: 'neutral', label: '样本少，先观察' }
  if (rule.rate >= 60) return { tone: 'high', label: '立即点检' }
  if (rule.rate >= 20) return { tone: 'mid', label: '结合模型判断' }
  return { tone: 'low', label: '低风险' }
}
const dots = (rule: { hits: number | null; faults: number | null }) =>
  Array.from({ length: Math.min(rule.hits || 0, 40) }, (_, i) => i < (rule.faults || 0))
</script>
<template>
  <section v-if="rules.length" class="brief-block">
    <h3>点检规则</h3>
    <div class="rule-grid">
      <article v-for="rule in shown" :key="rule.id" class="live-panel rule-card">
        <span class="rule-tier" :class="tier(rule).tone">{{ tier(rule).label }}</span>
        <div class="rule-conds">
          <template v-for="(cond, i) in rule.conditions" :key="i">
            <em v-if="i">并且</em><span>{{ cond }}</span>
          </template>
        </div>
        <p v-if="rule.hits !== null && rule.faults !== null" class="rule-hit">
          <b>{{ rule.faults }}</b> / {{ rule.hits }} 次报警是真故障
        </p>
        <div class="rule-dots" aria-hidden="true">
          <i v-for="(fault, i) in dots(rule)" :key="i" :class="{ fault }"></i>
        </div>
      </article>
    </div>
    <details v-if="rest.length" class="rule-more">
      <summary>其余 {{ rest.length }} 条</summary>
      <div class="rule-grid">
        <article v-for="rule in rest" :key="rule.id" class="live-panel rule-card">
          <span class="rule-tier" :class="tier(rule).tone">{{ tier(rule).label }}</span>
          <div class="rule-conds">
            <template v-for="(cond, i) in rule.conditions" :key="i">
              <em v-if="i">并且</em><span>{{ cond }}</span>
            </template>
          </div>
          <p v-if="rule.hits !== null && rule.faults !== null" class="rule-hit">
            <b>{{ rule.faults }}</b> / {{ rule.hits }} 次报警是真故障
          </p>
        </article>
      </div>
    </details>
  </section>
</template>
<style scoped>
.brief-block > h3 {
  margin: 0 0 12px;
  font-size: 17px;
}
.rule-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 14px;
}
.rule-card {
  margin: 0;
}
.rule-tier {
  display: inline-block;
  margin-bottom: 10px;
  padding: 2px 9px;
  border-radius: 999px;
  font-size: 12px;
}
.rule-tier.high {
  background: #fdeee6;
  color: #c2410c;
}
.rule-tier.mid {
  background: #fff4e5;
  color: #9a6516;
}
.rule-tier.low {
  background: #e7f5ee;
  color: #1f8a5b;
}
.rule-tier.neutral {
  background: #f1f3f7;
  color: var(--secondary);
}
.rule-conds {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-bottom: 12px;
}
.rule-conds span {
  padding: 5px 9px;
  border-radius: 6px;
  background: #f4f6fa;
  font-size: 13px;
  overflow-wrap: anywhere;
}
.rule-conds em {
  color: var(--muted);
  font-size: 12px;
  font-style: normal;
}
.rule-hit {
  margin: 0;
  color: var(--secondary);
  font-size: 13px;
}
.rule-hit b {
  color: var(--ink);
  font-size: 20px;
  font-variant-numeric: tabular-nums;
}
.rule-dots {
  display: flex;
  flex-wrap: wrap;
  gap: 3px;
  margin-top: 8px;
}
.rule-dots i {
  width: 9px;
  height: 9px;
  border-radius: 50%;
  background: #d6dde8;
}
.rule-dots i.fault {
  background: #c2410c;
}
.rule-more {
  margin-top: 10px;
}
.rule-more summary {
  margin-bottom: 10px;
  color: var(--primary);
  font-size: 13px;
  cursor: pointer;
}
@media (max-width: 900px) {
  .rule-grid {
    grid-template-columns: 1fr;
  }
}
</style>
