<script setup lang="ts">
import { computed } from 'vue'
import BriefHeader from './BriefHeader.vue'
import CheckRules from './CheckRules.vue'
import ProducerChart from './ProducerChart.vue'
const props = defineProps<{
  facts: Record<string, unknown>
  text: Record<string, unknown>
  reuse?: Record<string, unknown>
}>()
defineEmits<{ 'open-report': []; 'open-package': [] }>()
type Row = Record<string, unknown>
const obj = (v: unknown): Row => (v && typeof v === 'object' && !Array.isArray(v) ? (v as Row) : {})
const arr = (v: unknown): Row[] => (Array.isArray(v) ? (v as Row[]) : [])
const num = (v: unknown): number | null => (typeof v === 'number' && Number.isFinite(v) ? v : null)
const str = (v: unknown): string => (v === null || v === undefined ? '' : String(v))
const plain = (name: string) => name.replace(/（[^）]*）/g, '').trim()

// 看板只放精简层（text.brief）的短句；长结论和依据收进折叠，完整内容在工作汇报里。
const brief = computed(() => obj(props.text['brief']))
const names = computed(() => obj(obj(props.facts['数据'])['字段显示名']))
const single = computed(() => obj(obj(props.facts['发现'])['单因素']))
const avgRisk = computed(() => num(obj(props.facts['发现'])['平均风险百分比']))
function factorOf(finding: Row): string {
  // 取长标题里最先出现的工况因素；标题里没有再看结论。
  for (const words of [str(finding['title']), str(finding['conclusion'])]) {
    const hits = Object.keys(single.value)
      .map((key) => ({ key, at: words.indexOf(plain(str(names.value[key]) || key)) }))
      .filter((hit) => hit.at >= 0)
      .sort((a, b) => a.at - b.at)
    if (hits.length) return hits[0].key
  }
  return ''
}
const findings = computed(() => {
  const short = arr(brief.value['findings'])
  return arr(props.text['findings']).map((finding, i) => ({
    title: str(short[i]?.['title']) || str(finding['title']),
    advice: str(short[i]?.['advice']) || str(finding['advice']),
    conclusion: str(finding['conclusion']),
    evidence: arr(finding['evidence']).map(str).filter(Boolean),
    chart: spark(factorOf(finding)),
  }))
})
// 单因素推演的小曲线：横轴是取值，纵轴是模型推演的故障风险，虚线是平均风险。
const SW = 250
const SH = 110
const SP = 18
function spark(key: string) {
  if (!key) return null
  const points = arr(obj(single.value[key])['模型推演_取值与风险百分比'])
    .map((p) => ({ x: num(p['取值']), y: num(p['风险百分比']) }))
    .filter((p): p is { x: number; y: number } => p.x !== null && p.y !== null)
  if (points.length < 2) return null
  const xs = points.map((p) => p.x)
  const x0 = Math.min(...xs)
  const x1 = Math.max(...xs)
  const peak = Math.max(...points.map((p) => p.y))
  const top = Math.max(peak, avgRisk.value || 0, 10)
  const X = (v: number) => SP + ((SW - 2 * SP) * (v - x0)) / (x1 - x0 || 1)
  const Y = (v: number) => SH - SP - ((SH - 2 * SP) * v) / top
  return {
    name: plain(str(names.value[key]) || key),
    line: points.map((p) => `${X(p.x)},${Y(p.y)}`).join(' '),
    dots: points.map((p) => ({ cx: X(p.x), cy: Y(p.y) })),
    avg: avgRisk.value === null ? null : Y(avgRisk.value),
    x0,
    x1,
    peak: Math.round(peak),
  }
}
const competition = computed(() => obj(props.facts['算法竞争']))
const candidates = computed(() => arr(competition.value['候选']))
const families = computed(() =>
  Object.entries(obj(competition.value['方法族']))
    .map(([name, row]) => ({ name, best: num(obj(row)['验收集最好成绩']) }))
    .sort((a, b) => (b.best ?? -1) - (a.best ?? -1)),
)
const funnel = computed(() => {
  const total = num(competition.value['候选总数'])
  const winner = num(competition.value['胜出编号'])
  if (total === null || winner === null) return []
  const passed = candidates.value.filter((c) => c['结果'] === '通过')
  const tainted = passed.filter((c) => c['借用已知规则'] === true).length
  const steps: { value: string; label: string; tone?: string }[] = [
    { value: String(total), label: `候选 · ${families.value.length} 类算法` },
    { value: String(passed.length), label: '跑通' },
  ]
  if (tainted) steps.push({ value: String(tainted), label: '抄公开答案，剔除', tone: 'cut' })
  steps.push({ value: String(passed.length - tainted), label: '参与比拼' })
  steps.push({ value: `#${winner}`, label: str(competition.value['胜出方法']), tone: 'win' })
  return steps
})
const winnerFamily = computed(() => str(competition.value['胜出方法']))
const steps = computed(() => {
  const short = arr(brief.value['steps'])
  return arr(props.text['next_steps']).map((step, i) => ({
    title: str(short[i]?.['title']),
    action: str(short[i]?.['action']) || str(step),
  }))
})
const trust = computed(() => {
  const items: { ok: boolean; title: string; detail: string }[] = []
  const rows = num(obj(props.facts['数据'])['待评估记录数'])
  if (rows !== null) items.push({ ok: true, title: '统一打分', detail: `${rows} 条未见数据` })
  const prior = obj(props.facts['先验知识检查'])
  const flagged = num(prior['引用了已知名称或阈值的方案数'])
  if (flagged !== null)
    items.push({
      ok: true,
      title: '防背答案',
      detail: flagged ? '抄公开阈值的方案已剔除' : '未发现抄公开答案',
    })
  const mechanisms = Object.values(obj(props.facts['已知机理核对'])).map((row) => ({
    caught: num(obj(row)['其中落在模型风险最高前100条里的次数']),
    total: num(obj(row)['这类故障在待预测数据中的次数']),
  }))
  const matched = mechanisms.filter((m) => m.caught !== null && m.total && m.caught / m.total >= 0.9)
  if (matched.length)
    items.push({
      ok: true,
      title: '机理吻合',
      detail: matched.map((m) => `${m.caught}/${m.total}`).join(' · '),
    })
  const blind = str(brief.value['blind_spot'])
  if (blind) items.push({ ok: false, title: '盲区', detail: blind })
  return items
})
</script>
<template>
  <div class="brief">
    <BriefHeader :facts="facts" :text="text" />

    <section v-if="funnel.length" class="brief-block">
      <h3>{{ funnel[0].value }} 个方案竞争</h3>
      <div class="live-panel">
        <div class="brief-funnel">
          <div v-for="step in funnel" :key="step.label" :class="step.tone">
            <strong>{{ step.value }}</strong
            ><span>{{ step.label }}</span>
          </div>
        </div>
        <div class="brief-families">
          <template v-for="family in families" :key="family.name">
            <span>{{ family.name }}</span>
            <span class="brief-bar"
              ><i
                :class="{ win: family.name === winnerFamily }"
                :style="{ width: `${family.best ?? 0}%` }"
              ></i
            ></span>
            <b>{{ family.best ?? '—' }}</b>
          </template>
        </div>
        <details class="brief-fold">
          <summary>全部方案</summary>
          <ProducerChart kind="competition" :facts="facts" />
        </details>
      </div>
    </section>

    <section v-if="findings.length" class="brief-block">
      <h3>主要发现</h3>
      <article v-for="(finding, index) in findings" :key="index" class="live-panel brief-finding">
        <div class="brief-finding-main">
          <h4>{{ index + 1 }}. {{ finding.title }}</h4>
          <p v-if="finding.advice" class="brief-advice"><b>建议</b>{{ finding.advice }}</p>
          <details v-if="finding.conclusion || finding.evidence.length" class="brief-fold">
            <summary>依据</summary>
            <p v-if="finding.conclusion">{{ finding.conclusion }}</p>
            <ul v-if="finding.evidence.length">
              <li v-for="(line, lineIndex) in finding.evidence" :key="lineIndex">{{ line }}</li>
            </ul>
          </details>
        </div>
        <figure v-if="finding.chart" class="brief-spark">
          <figcaption>{{ finding.chart.name }} → 风险</figcaption>
          <svg :viewBox="`0 0 ${SW} ${SH}`" role="img" :aria-label="`${finding.chart.name}与故障风险`">
            <line
              v-if="finding.chart.avg !== null"
              :x1="SP"
              :x2="SW - SP"
              :y1="finding.chart.avg"
              :y2="finding.chart.avg"
              class="spark-avg"
            />
            <polyline :points="finding.chart.line" class="spark-line" />
            <circle v-for="(dot, i) in finding.chart.dots" :key="i" :cx="dot.cx" :cy="dot.cy" r="2.6" />
            <text :x="SP" y="11">最高 {{ finding.chart.peak }}%</text>
            <text :x="SP" :y="SH - 3">{{ finding.chart.x0 }}</text>
            <text :x="SW - SP" :y="SH - 3" text-anchor="end">{{ finding.chart.x1 }}</text>
          </svg>
        </figure>
      </article>
    </section>

    <CheckRules :facts="facts" :text="text" />

    <section v-if="steps.length" class="brief-block">
      <h3>下一步</h3>
      <ol class="brief-steps">
        <li v-for="(step, index) in steps" :key="index" class="live-panel">
          <span class="brief-step-index">{{ index + 1 }}</span>
          <strong v-if="step.title">{{ step.title }}</strong>
          <p>{{ step.action }}</p>
        </li>
      </ol>
    </section>

    <section v-if="trust.length" class="brief-block">
      <h3>可信度</h3>
      <ul class="brief-trust">
        <li v-for="item in trust" :key="item.title" class="live-panel" :class="{ note: !item.ok }">
          <span class="brief-mark" aria-hidden="true">{{ item.ok ? '✓' : '!' }}</span>
          <strong>{{ item.title }}</strong>
          <p>{{ item.detail }}</p>
        </li>
      </ul>
    </section>

    <div class="brief-actions">
      <button class="btn primary small" @click="$emit('open-report')">工作汇报</button>
      <button class="btn secondary small" @click="$emit('open-package')">交付的算法包</button>
    </div>
  </div>
</template>
<style scoped>
.brief {
  display: flex;
  flex-direction: column;
  gap: 26px;
  min-width: 0;
}
.brief :deep(.live-panel) {
  margin: 0;
}
.brief-block > h3 {
  margin: 0 0 12px;
  font-size: 17px;
}
.brief-funnel {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(110px, 1fr));
  gap: 3px;
  margin-bottom: 16px;
}
.brief-funnel > div {
  display: flex;
  flex-direction: column;
  padding: 12px 14px;
  background: #f4f6fa;
}
.brief-funnel > div:first-child {
  border-radius: 10px 0 0 10px;
}
.brief-funnel > div:last-child {
  border-radius: 0 10px 10px 0;
}
.brief-funnel strong {
  font-size: 22px;
  font-variant-numeric: tabular-nums;
}
.brief-funnel span {
  color: var(--secondary);
  font-size: 12px;
}
.brief-funnel .cut strong {
  color: #c2410c;
}
.brief-funnel .win {
  background: var(--primary-soft);
}
.brief-funnel .win strong {
  color: var(--primary);
}
.brief-families {
  display: grid;
  grid-template-columns: 110px minmax(0, 1fr) 44px;
  gap: 8px 12px;
  align-items: center;
  font-size: 13px;
}
.brief-families b {
  font-variant-numeric: tabular-nums;
}
.brief-bar {
  height: 14px;
  overflow: hidden;
  border-radius: 4px;
  background: #f4f6fa;
}
.brief-bar i {
  display: block;
  height: 100%;
  border-radius: 4px;
  background: #c9d2df;
}
.brief-bar i.win {
  background: var(--primary);
}
.brief-fold {
  margin-top: 10px;
  color: var(--secondary);
  font-size: 13px;
}
.brief-fold summary {
  color: var(--primary);
  cursor: pointer;
}
.brief-fold p {
  margin: 8px 0 0;
  line-height: 1.8;
}
.brief-fold ul {
  margin: 6px 0 0;
  padding-left: 18px;
  line-height: 1.8;
}
.brief-finding {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 250px;
  gap: 18px;
}
.brief-finding + .brief-finding {
  margin-top: 12px;
}
.brief-finding h4 {
  margin: 0 0 12px;
  font-size: 16px;
}
.brief-advice {
  margin: 0;
  padding: 9px 12px;
  border-radius: 8px;
  background: var(--primary-soft);
  color: var(--ink);
  font-size: 13px;
}
.brief-advice b {
  margin-right: 10px;
  color: var(--primary);
}
.brief-spark {
  margin: 0;
}
.brief-spark figcaption {
  color: var(--secondary);
  font-size: 12px;
}
.brief-spark svg {
  display: block;
  width: 100%;
  max-width: 320px;
  height: auto;
}
.brief-spark text {
  fill: var(--muted);
  font-size: 10px;
}
.brief-spark circle {
  fill: var(--primary);
}
.spark-line {
  fill: none;
  stroke: var(--primary);
  stroke-width: 2.2;
}
.spark-avg {
  stroke: #c9d2df;
  stroke-dasharray: 3 3;
}
.brief-steps,
.brief-trust {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: 14px;
  margin: 0;
  padding: 0;
  list-style: none;
}
.brief-step-index {
  display: grid;
  place-items: center;
  width: 26px;
  height: 26px;
  margin-bottom: 8px;
  border-radius: 50%;
  background: var(--primary);
  color: #fff;
  font-size: 13px;
  font-weight: 600;
}
.brief-steps strong,
.brief-trust strong {
  display: block;
  margin-bottom: 4px;
  font-size: 14.5px;
}
.brief-steps p,
.brief-trust p {
  margin: 0;
  color: var(--ink);
  font-size: 13.5px;
  font-variant-numeric: tabular-nums;
}
.brief-mark {
  display: grid;
  place-items: center;
  width: 22px;
  height: 22px;
  margin-bottom: 6px;
  border-radius: 50%;
  background: #1f8a5b;
  color: #fff;
  font-size: 13px;
  font-weight: 700;
}
.brief-trust .note .brief-mark {
  background: #b7791f;
}
.brief-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}
@media (max-width: 900px) {
  .brief-finding {
    grid-template-columns: 1fr;
  }
  .brief-funnel > div {
    border-radius: 8px !important;
  }
  .brief-families {
    grid-template-columns: 84px minmax(0, 1fr) 40px;
  }
}
</style>
