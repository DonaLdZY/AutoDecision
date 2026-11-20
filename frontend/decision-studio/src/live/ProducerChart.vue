<script setup lang="ts">
// Charts for the producer-facing report, drawn live from the report's fact file
// (producer_facts.json) instead of pre-rendered images. Plain SVG, no chart library.
import { computed, onBeforeUnmount, onMounted, ref, shallowRef } from 'vue'

const props = defineProps<{ kind: string; facts: Record<string, unknown> }>()

// Validated categorical palette (fixed order, never cycled); low-contrast slots always carry a text label.
const PALETTE = ['#2b4d8c', '#eb6834', '#1baf7a', '#eda100', '#e87ba4', '#008300']
const MUTED = '#b9b8b3'
const INK2 = '#6b7280'
const GRID = '#e3e5e8'

type Row = Record<string, unknown>
const obj = (v: unknown): Row => (v && typeof v === 'object' && !Array.isArray(v) ? (v as Row) : {})
const arr = (v: unknown): Row[] => (Array.isArray(v) ? (v as Row[]) : [])
const num = (v: unknown): number | null => (typeof v === 'number' && Number.isFinite(v) ? v : null)
const str = (v: unknown): string => (v === null || v === undefined ? '' : String(v))

const host = ref<HTMLElement | null>(null)
const width = ref(720)
let observer: ResizeObserver | undefined
onMounted(() => {
  if (!host.value) return
  width.value = host.value.clientWidth || 720
  observer = new ResizeObserver((entries) => {
    width.value = Math.max(280, entries[0]?.contentRect.width || 720)
  })
  observer.observe(host.value)
})
onBeforeUnmount(() => observer?.disconnect())

const tip = shallowRef<{ x: number; y: number; lines: string[] } | null>(null)
function showTip(event: MouseEvent | FocusEvent, lines: string[]) {
  const box = host.value?.getBoundingClientRect()
  const target = (event.currentTarget as Element | null)?.getBoundingClientRect()
  if (!box || !target) return
  const x = ('clientX' in event ? event.clientX : target.left + target.width / 2) - box.left
  const y = ('clientY' in event ? event.clientY : target.top) - box.top
  tip.value = { x: Math.min(x + 12, width.value - 220), y: y + 12, lines }
}
const hideTip = () => {
  tip.value = null
}

const facts = computed(() => props.facts)
const names = computed(() => obj(obj(facts.value['数据'])['字段显示名']))
const displayName = (key: string) => str(names.value[key]) || key

// ---------------------------------------------------------------- competition
const comp = computed(() => obj(facts.value['算法竞争']))
const familyOrder = computed(() =>
  Object.entries(obj(comp.value['方法族']))
    .filter(([, s]) => num(obj(s)['验收集最好成绩']) !== null)
    .map(([f]) => f),
)
const familyColor = (family: string) => {
  const i = familyOrder.value.indexOf(family)
  return i >= 0 && i < PALETTE.length ? PALETTE[i] : MUTED
}
const scoredRows = computed(() =>
  arr(comp.value['候选'])
    .filter((r) => num(r['验收集成绩']) !== null)
    .sort((a, b) => (num(b['验收集成绩']) ?? 0) - (num(a['验收集成绩']) ?? 0)),
)
const failedRows = computed(() => arr(comp.value['候选']).filter((r) => num(r['验收集成绩']) === null))
const baseline = computed(() => num(obj(obj(facts.value['预警效果'])['单一指标说明'])['验收集平均精度']))
const originalPick = computed(() => num(obj(comp.value['改选说明'])['系统原选方案编号']))
const reselected = computed(() => originalPick.value !== null)
const rowNote = (r: Row) => {
  if (r['编号'] === comp.value['胜出编号']) return reselected.value ? '← 交付方案' : '← 系统选中'
  if (r['编号'] === originalPick.value) return '系统原选，借用已知规则，已剔除'
  if (r['借用已知规则']) return '借用已知规则'
  return r['结果'] === '通过' ? '' : '未参与排名'
}
const compLayout = computed(() => {
  const labelW = width.value < 520 ? 104 : 132
  const noteW = width.value < 520 ? 70 : 190
  const rowH = 24
  const top = 22
  const plotW = Math.max(80, width.value - labelW - noteW - 12)
  const maxV = Math.max(100, ...scoredRows.value.map((r) => num(r['验收集成绩']) ?? 0))
  return {
    labelW,
    noteW,
    rowH,
    top,
    plotW,
    maxV,
    height: top + scoredRows.value.length * rowH + 28,
    x: (v: number) => labelW + (v / maxV) * plotW,
  }
})
const compTicks = computed(() => [0, 20, 40, 60, 80, 100].filter((t) => t <= compLayout.value.maxV))

// ---------------------------------------------------------------- capture
const warn = computed(() => obj(facts.value['预警效果']))
const captureKs = computed(() => Object.keys(obj(warn.value['模型'])))
const totalFailures = computed(() => num(warn.value['其中真实故障次数']) ?? 0)
const captureLayout = computed(() => {
  const left = 40,
    right = 12,
    top = 18,
    bottom = 44,
    height = 260
  const plotW = width.value - left - right
  const plotH = height - top - bottom
  const maxV = Math.max(totalFailures.value, 1) * 1.08
  const group = plotW / Math.max(1, captureKs.value.length)
  const bar = Math.min(54, group * 0.32)
  return { left, top, height, plotH, group, bar, y: (v: number) => top + plotH - (v / maxV) * plotH }
})
const captureSeries = computed(() => [
  { key: '模型', label: '工智寻优模型', color: PALETTE[0] },
  {
    key: '单一指标',
    label: `只按「${displayName(str(obj(warn.value['单一指标说明'])['指标']))}」排序`,
    color: PALETTE[1],
  },
])

// ---------------------------------------------------------------- effects
const found = computed(() => obj(facts.value['发现']))
const importanceKey = computed(() => Object.keys(found.value).find((k) => k.startsWith('打乱某个指标')) ?? '')
const topFeatures = computed(() => Object.keys(obj(found.value[importanceKey.value])).slice(0, 4))
const baseRisk = computed(() => num(found.value['平均风险百分比']) ?? 0)
const panelW = computed(() => (width.value >= 600 ? (width.value - 16) / 2 : width.value))
const panelH = 190
function panel(feature: string) {
  const single = obj(obj(found.value['单因素'])[feature])
  const curve = arr(single['模型推演_取值与风险百分比']).map((p) => ({
    x: num(p['取值']) ?? 0,
    y: num(p['风险百分比']) ?? 0,
  }))
  const raw = arr(single['原始数据_分段故障率']).map((r) => {
    const [lo, hi] = str(r['区间']).split('～').map(Number)
    return {
      x: (lo + hi) / 2,
      y: num(r['故障率百分比']) ?? 0,
      range: str(r['区间']),
      n: num(r['记录数']) ?? 0,
      k: num(r['故障数']) ?? 0,
    }
  })
  const xs = [...curve.map((p) => p.x), ...raw.map((p) => p.x)]
  const ys = [...curve.map((p) => p.y), ...raw.map((p) => p.y), baseRisk.value]
  const x0 = Math.min(...xs),
    x1 = Math.max(...xs)
  const y1 = Math.max(...ys) * 1.1 || 1
  const left = 36,
    right = 10,
    top = 26,
    bottom = 24
  const w = panelW.value,
    plotW = w - left - right,
    plotH = panelH - top - bottom
  const sx = (v: number) => left + ((v - x0) / (x1 - x0 || 1)) * plotW
  const sy = (v: number) => top + plotH - (v / y1) * plotH
  return {
    feature,
    title: displayName(feature),
    w,
    sx,
    sy,
    top,
    plotH,
    left,
    right,
    x0,
    x1,
    y1,
    path: curve.map((p, i) => `${i ? 'L' : 'M'}${sx(p.x).toFixed(1)},${sy(p.y).toFixed(1)}`).join(' '),
    curve,
    raw,
  }
}
const panels = computed(() => topFeatures.value.map(panel))
const fmt = (v: number) => (Math.abs(v) >= 100 ? v.toFixed(0) : v.toFixed(1))
</script>

<template>
  <figure ref="host" class="pchart" @mouseleave="hideTip">
    <!-- 方案竞争 -->
    <template v-if="kind === 'competition'">
      <figcaption>{{ str(comp['候选总数']) }} 个方案同台比较（统一复算，越长越好）</figcaption>
      <div class="legend">
        <span v-for="f in familyOrder" :key="f"><i :style="{ background: familyColor(f) }"></i>{{ f }}</span>
        <span v-if="reselected"><i class="faded"></i>借用已知规则（已剔除）</span>
      </div>
      <svg
        :width="width"
        :height="compLayout.height"
        role="img"
        :aria-label="`${scoredRows.length} 个有成绩方案的验收集平均精度`"
      >
        <g v-for="t in compTicks" :key="t">
          <line
            :x1="compLayout.x(t)"
            :x2="compLayout.x(t)"
            :y1="compLayout.top - 4"
            :y2="compLayout.height - 22"
            :stroke="GRID"
          />
          <text :x="compLayout.x(t)" :y="compLayout.height - 8" text-anchor="middle" class="tick">
            {{ t }}
          </text>
        </g>
        <g
          v-for="(r, i) in scoredRows"
          :key="str(r['编号'])"
          class="hit"
          tabindex="0"
          @mousemove="
            showTip($event, [
              `#${r['编号']} ${r['方法类型']}`,
              `来源：${r['来源编号'] ? `由 #${r['来源编号']} ${r['产生方式']}` : '首稿'}`,
              `验收集成绩：${r['验收集成绩']}`,
              `系统自报验证成绩：${r['自报验证成绩'] ?? '—'}`,
              rowNote(r) || str(r['结果']),
            ])
          "
          @focus="showTip($event, [`#${r['编号']} ${r['方法类型']}`, `验收集成绩：${r['验收集成绩']}`])"
          @blur="hideTip"
        >
          <rect
            :x="0"
            :y="compLayout.top + i * compLayout.rowH"
            :width="width"
            :height="compLayout.rowH"
            fill="transparent"
          />
          <text
            :x="compLayout.labelW - 6"
            :y="compLayout.top + i * compLayout.rowH + 16"
            text-anchor="end"
            class="label"
          >
            #{{ r['编号'] }} {{ r['方法类型'] }}
          </text>
          <rect
            :x="compLayout.labelW"
            :y="compLayout.top + i * compLayout.rowH + 5"
            :height="compLayout.rowH - 10"
            rx="3"
            :width="Math.max(2, compLayout.x(num(r['验收集成绩']) ?? 0) - compLayout.labelW)"
            :fill="familyColor(str(r['方法类型']))"
            :opacity="r['借用已知规则'] || r['结果'] !== '通过' ? 0.38 : 1"
          />
          <text
            :x="compLayout.x(num(r['验收集成绩']) ?? 0) + 5"
            :y="compLayout.top + i * compLayout.rowH + 16"
            class="value"
          >
            {{ r['验收集成绩'] }}
            <tspan v-if="rowNote(r)" :class="{ strong: r['编号'] === comp['胜出编号'] }" dx="6">
              {{ rowNote(r) }}
            </tspan>
          </text>
        </g>
        <g v-if="baseline !== null">
          <line
            :x1="compLayout.x(baseline)"
            :x2="compLayout.x(baseline)"
            :y1="compLayout.top - 6"
            :y2="compLayout.height - 22"
            :stroke="INK2"
            stroke-dasharray="4 4"
          />
          <text :x="compLayout.x(baseline)" :y="12" text-anchor="middle" class="tick">
            对照：单一指标排序 {{ baseline }}
          </text>
        </g>
      </svg>
      <p v-if="failedRows.length" class="note">
        另有 {{ failedRows.length }} 个方案运行失败出局：{{
          failedRows.map((r) => `#${r['编号']} ${r['方法类型']}`).join('、')
        }}。
      </p>
    </template>

    <!-- 预警效果 -->
    <template v-else-if="kind === 'capture'">
      <figcaption>
        预警效果：在
        {{ str(warn['待评估加工次数']) }} 次待评估加工中，按风险从高到低检查能抓到多少真实故障（共
        {{ totalFailures }} 次）
      </figcaption>
      <div class="legend">
        <span v-for="s in captureSeries" :key="s.key"
          ><i :style="{ background: s.color }"></i>{{ s.label }}</span
        >
      </div>
      <svg
        :width="width"
        :height="captureLayout.height"
        role="img"
        aria-label="不同检查范围下抓到的真实故障数"
      >
        <line
          :x1="captureLayout.left"
          :x2="width - 12"
          :y1="captureLayout.y(totalFailures)"
          :y2="captureLayout.y(totalFailures)"
          :stroke="INK2"
          stroke-dasharray="4 4"
        />
        <text :x="width - 14" :y="captureLayout.y(totalFailures) - 5" text-anchor="end" class="tick">
          全部故障 {{ totalFailures }}
        </text>
        <line
          :x1="captureLayout.left"
          :x2="width - 12"
          :y1="captureLayout.y(0)"
          :y2="captureLayout.y(0)"
          :stroke="GRID"
        />
        <g v-for="(k, gi) in captureKs" :key="k">
          <g
            v-for="(s, si) in captureSeries"
            :key="s.key"
            class="hit"
            tabindex="0"
            @mousemove="
              showTip($event, [`检查风险最高的 ${k} 次`, `${s.label}：抓到 ${obj(warn[s.key])[k]} 次故障`])
            "
            @blur="hideTip"
          >
            <rect
              :x="
                captureLayout.left +
                gi * captureLayout.group +
                captureLayout.group / 2 +
                (si - 1) * (captureLayout.bar + 2)
              "
              :y="captureLayout.y(num(obj(warn[s.key])[k]) ?? 0)"
              :width="captureLayout.bar"
              :height="captureLayout.y(0) - captureLayout.y(num(obj(warn[s.key])[k]) ?? 0)"
              rx="3"
              :fill="s.color"
            />
            <text
              :x="
                captureLayout.left +
                gi * captureLayout.group +
                captureLayout.group / 2 +
                (si - 1) * (captureLayout.bar + 2) +
                captureLayout.bar / 2
              "
              :y="captureLayout.y(num(obj(warn[s.key])[k]) ?? 0) - 5"
              text-anchor="middle"
              class="value"
            >
              {{ obj(warn[s.key])[k] }}
            </text>
          </g>
          <text
            :x="captureLayout.left + gi * captureLayout.group + captureLayout.group / 2"
            :y="captureLayout.height - 20"
            text-anchor="middle"
            class="label"
          >
            检查风险最高的 {{ k }} 次
          </text>
        </g>
      </svg>
    </template>

    <!-- 工况与风险 -->
    <template v-else-if="kind === 'effects'">
      <figcaption>
        故障风险（%）随单个工况指标的变化：线为模型推演（其余指标保持实际值），圈为原始记录分段故障率，虚线为平均风险
      </figcaption>
      <div class="legend">
        <span><i :style="{ background: PALETTE[0] }"></i>模型推演</span>
        <span><i class="ring" :style="{ borderColor: PALETTE[1] }"></i>原始故障率</span>
      </div>
      <div class="panels">
        <svg
          v-for="p in panels"
          :key="p.feature"
          :width="p.w"
          :height="panelH"
          role="img"
          :aria-label="`${p.title} 与故障风险`"
        >
          <text x="2" y="14" class="label strong">{{ p.title }}</text>
          <line :x1="p.left" :x2="p.w - p.right" :y1="p.sy(0)" :y2="p.sy(0)" :stroke="GRID" />
          <line
            :x1="p.left"
            :x2="p.w - p.right"
            :y1="p.sy(baseRisk)"
            :y2="p.sy(baseRisk)"
            :stroke="INK2"
            stroke-dasharray="4 4"
          />
          <text :x="p.left - 4" :y="p.sy(p.y1 / 1.1) + 4" text-anchor="end" class="tick">
            {{ fmt(p.y1 / 1.1) }}
          </text>
          <text :x="p.left - 4" :y="p.sy(0) + 4" text-anchor="end" class="tick">0</text>
          <text :x="p.left" :y="panelH - 6" class="tick">{{ fmt(p.x0) }}</text>
          <text :x="p.w - p.right" :y="panelH - 6" text-anchor="end" class="tick">{{ fmt(p.x1) }}</text>
          <path :d="p.path" fill="none" :stroke="PALETTE[0]" stroke-width="2" />
          <circle
            v-for="pt in p.curve"
            :key="`c${pt.x}`"
            :cx="p.sx(pt.x)"
            :cy="p.sy(pt.y)"
            r="4"
            :fill="PALETTE[0]"
            class="hit"
            @mousemove="showTip($event, [p.title, `取值 ${pt.x}`, `模型推演风险 ${pt.y}%`])"
          />
          <circle
            v-for="pt in p.raw"
            :key="`r${pt.range}`"
            :cx="p.sx(pt.x)"
            :cy="p.sy(pt.y)"
            r="4.5"
            fill="#fff"
            :stroke="PALETTE[1]"
            stroke-width="2"
            class="hit"
            @mousemove="
              showTip($event, [p.title, `区间 ${pt.range}`, `原始故障率 ${pt.y}%（${pt.k}/${pt.n}）`])
            "
          />
        </svg>
      </div>
    </template>

    <p v-else class="note">未知图表：{{ kind }}</p>

    <div v-if="tip" class="tip" :style="{ left: `${tip.x}px`, top: `${tip.y}px` }">
      <div v-for="(line, i) in tip.lines" :key="i" :class="{ strong: i === 0 }">{{ line }}</div>
    </div>
  </figure>
</template>

<style scoped>
.pchart {
  position: relative;
  margin: 1.2em 0;
  min-width: 0;
}
figcaption {
  margin-bottom: 6px;
  color: #1f2328;
  font-size: 13px;
  font-weight: 600;
}
.legend {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 16px;
  margin-bottom: 6px;
  color: #6b7280;
  font-size: 12px;
}
.legend span {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.legend i {
  display: inline-block;
  width: 12px;
  height: 12px;
  border-radius: 3px;
}
.legend i.faded {
  background: #2b4d8c;
  opacity: 0.38;
}
.legend i.ring {
  width: 9px;
  height: 9px;
  border: 2px solid;
  border-radius: 50%;
  background: #fff;
}
svg {
  display: block;
  overflow: visible;
}
.panels {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 16px;
}
.label {
  fill: #1f2328;
  font-size: 12px;
}
.value {
  fill: #1f2328;
  font-size: 11px;
}
.tick {
  fill: #6b7280;
  font-size: 10.5px;
}
.strong {
  font-weight: 600;
}
.hit {
  cursor: default;
  outline: none;
}
.hit:focus-visible rect {
  stroke: #1f2328;
  stroke-width: 1;
}
.note {
  margin: 6px 0 0;
  color: #6b7280;
  font-size: 12px;
}
.tip {
  position: absolute;
  z-index: 5;
  pointer-events: none;
  min-width: 140px;
  max-width: 220px;
  border: 1px solid #e3e5e8;
  border-radius: 6px;
  padding: 6px 9px;
  background: #fff;
  box-shadow: 0 4px 14px rgba(31, 35, 40, 0.12);
  color: #1f2328;
  font-size: 12px;
  line-height: 1.5;
}
</style>
