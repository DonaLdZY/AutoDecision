<script setup lang="ts">
import { computed } from 'vue'
const props = defineProps<{ facts: Record<string, unknown>; text: Record<string, unknown> }>()
type Row = Record<string, unknown>
const obj = (v: unknown): Row => (v && typeof v === 'object' && !Array.isArray(v) ? (v as Row) : {})
const num = (v: unknown): number | null => (typeof v === 'number' && Number.isFinite(v) ? v : null)
const str = (v: unknown): string => (v === null || v === undefined ? '' : String(v))
// 「主轴扭矩（kgf·m）」→「主轴扭矩」：看板上只留名称，单位在工作汇报里。
const plain = (name: string) => name.replace(/（[^）]*）/g, '').trim()

const brief = computed(() => obj(props.text['brief']))
const headline = computed(() => str(brief.value['headline']) || str(props.text['headline']))
const dataNote = computed(() => str(obj(props.facts['数据'])['说明']))
const demoTag = computed(() => (dataNote.value.includes('合成') ? '合成数据 · 仅演示' : ''))
const warn = computed(() => obj(props.facts['预警效果']))
const model = computed(() => obj(warn.value['模型']))
const single = computed(() => obj(warn.value['单一指标']))
const total = computed(() => num(warn.value['其中真实故障次数']))
const baselineName = computed(() => plain(str(obj(warn.value['单一指标说明'])['指标'])))
const keys = computed(() =>
  Object.keys(model.value)
    .filter((key) => Number.isFinite(Number(key)) && num(model.value[key]) !== null)
    .sort((a, b) => Number(a) - Number(b)),
)
const kpis = computed(() => {
  const list = keys.value
  if (!list.length) return []
  const first = list.includes('50') ? '50' : list[0]
  const last = list[list.length - 1]
  const rows: { value: string; unit: string; label: string }[] = [
    { value: str(model.value[first]), unit: `/ ${first}`, label: `前 ${first} 次检查命中` },
  ]
  if (last !== first && total.value !== null)
    rows.push({ value: str(model.value[last]), unit: `/ ${total.value}`, label: `前 ${last} 次抓到的故障` })
  const ours = num(model.value[last])
  const theirs = num(single.value[last])
  if (ours !== null && theirs !== null && baselineName.value)
    rows.push({
      value: `${ours - theirs >= 0 ? '+' : ''}${ours - theirs}`,
      unit: '次',
      label: `比只看${baselineName.value}多抓`,
    })
  return rows
})
// 预警效果小图：每个检查次数一组柱子，模型对单一指标。
const W = 400
const H = 170
const TOP = 20
const BOTTOM = 26
const bars = computed(() => {
  const max = Math.max(total.value || 0, ...keys.value.map((k) => num(model.value[k]) || 0), 1)
  const gw = W / Math.max(keys.value.length, 1)
  const bw = Math.min(36, gw / 3)
  const y = (v: number) => H - BOTTOM - ((H - BOTTOM - TOP) * v) / max
  return keys.value.map((key, i) => {
    const cx = gw * i + gw / 2
    const ours = num(model.value[key]) || 0
    const theirs = num(single.value[key])
    return {
      key,
      cx,
      bw,
      ours: { x: cx - bw - 3, y: y(ours), h: H - BOTTOM - y(ours), v: ours },
      theirs: theirs === null ? null : { x: cx + 3, y: y(theirs), h: H - BOTTOM - y(theirs), v: theirs },
    }
  })
})
const totalY = computed(() => (total.value === null ? null : TOP))
</script>
<template>
  <section v-if="headline || kpis.length" class="live-panel brief-head">
    <div class="brief-head-main">
      <span v-if="demoTag" class="brief-demo" :title="dataNote">{{ demoTag }}</span>
      <h2 v-if="headline" class="brief-headline">{{ headline }}</h2>
      <div v-if="kpis.length" class="brief-kpis">
        <div v-for="item in kpis" :key="item.label" class="brief-kpi">
          <strong
            >{{ item.value }}<small>{{ item.unit }}</small></strong
          >
          <span>{{ item.label }}</span>
        </div>
      </div>
    </div>
    <figure v-if="bars.length" class="brief-capture">
      <figcaption>预警效果</figcaption>
      <svg :viewBox="`0 0 ${W} ${H}`" role="img" aria-label="预警效果：按模型风险检查与只看单一指标的对比">
        <template v-if="totalY !== null">
          <line x1="0" :x2="W" :y1="totalY" :y2="totalY" class="brief-total" />
          <text :x="W" :y="totalY - 6" text-anchor="end" class="brief-axis">共 {{ total }} 次故障</text>
        </template>
        <g v-for="b in bars" :key="b.key">
          <rect :x="b.ours.x" :y="b.ours.y" :width="b.bw" :height="b.ours.h" rx="4" class="brief-ours" />
          <text :x="b.ours.x + b.bw / 2" :y="b.ours.y - 5" text-anchor="middle" class="brief-value">
            {{ b.ours.v }}
          </text>
          <template v-if="b.theirs">
            <rect
              :x="b.theirs.x"
              :y="b.theirs.y"
              :width="b.bw"
              :height="b.theirs.h"
              rx="4"
              class="brief-theirs"
            />
            <text :x="b.theirs.x + b.bw / 2" :y="b.theirs.y - 5" text-anchor="middle" class="brief-value">
              {{ b.theirs.v }}
            </text>
          </template>
          <text :x="b.cx" :y="H - 8" text-anchor="middle" class="brief-axis">前 {{ b.key }} 次</text>
        </g>
      </svg>
      <div class="brief-legend">
        <span><i class="ours"></i>模型</span
        ><span v-if="baselineName"><i class="theirs"></i>只看{{ baselineName }}</span>
      </div>
    </figure>
  </section>
</template>
<style scoped>
.brief-head {
  display: grid;
  grid-template-columns: minmax(0, 1.35fr) minmax(0, 1fr);
  gap: 28px;
  padding: 24px 26px;
}
.brief-demo {
  display: inline-block;
  padding: 2px 9px;
  border-radius: 999px;
  background: #fff4e5;
  color: #9a6516;
  font-size: 12px;
  cursor: help;
}
.brief-headline {
  margin: 10px 0 22px;
  color: var(--ink);
  font-size: 28px;
  line-height: 1.3;
  letter-spacing: 0.5px;
}
.brief-kpis {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
}
.brief-kpi {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
  padding: 12px 14px;
  border-radius: 10px;
  background: #f4f6fa;
}
.brief-kpi strong {
  color: var(--ink);
  font-size: 24px;
  font-variant-numeric: tabular-nums;
}
.brief-kpi small {
  margin-left: 3px;
  color: var(--secondary);
  font-size: 14px;
  font-weight: 500;
}
.brief-kpi span {
  color: var(--secondary);
  font-size: 12px;
}
.brief-capture {
  min-width: 0;
  margin: 0;
}
.brief-capture figcaption {
  margin-bottom: 6px;
  color: var(--ink);
  font-size: 13px;
  font-weight: 600;
}
.brief-capture svg {
  display: block;
  width: 100%;
  max-width: 460px;
  height: auto;
}
.brief-total {
  stroke: #c9d2df;
  stroke-dasharray: 4 4;
}
.brief-ours {
  fill: var(--primary);
}
.brief-theirs {
  fill: #c9d2df;
}
.brief-value {
  fill: var(--ink);
  font-size: 12px;
  font-weight: 600;
}
.brief-axis {
  fill: var(--muted);
  font-size: 11px;
}
.brief-legend {
  display: flex;
  gap: 14px;
  color: var(--secondary);
  font-size: 12px;
}
.brief-legend i {
  display: inline-block;
  width: 10px;
  height: 10px;
  margin-right: 5px;
  border-radius: 2px;
  vertical-align: -1px;
}
.brief-legend .ours {
  background: var(--primary);
}
.brief-legend .theirs {
  background: #c9d2df;
}
@media (max-width: 900px) {
  .brief-head {
    grid-template-columns: 1fr;
    padding: 18px;
  }
  .brief-headline {
    font-size: 21px;
  }
  .brief-kpis {
    grid-template-columns: 1fr 1fr;
  }
  .brief-kpi:last-child:nth-child(odd) {
    grid-column: span 2;
  }
}
</style>
