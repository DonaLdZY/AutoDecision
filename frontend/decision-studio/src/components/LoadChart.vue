<script setup lang="ts">
withDefaults(defineProps<{ compact?: boolean; compose?: boolean; water?: boolean }>(), {
  compact: false,
  compose: true,
  water: false,
})
</script>
<template>
  <div class="load-chart" :class="{ compact }">
    <div class="chart-heading">
      <span
        >{{ water ? '未来 24 小时供水需求' : '未来 24 小时负荷' }}
        <small>· {{ water ? 'm³/h' : 'MW' }}</small></span
      >
      <div class="legend">
        <span><i class="legend-line pale" />{{ compose ? '原计划' : '区间上界' }}</span
        ><span><i class="legend-line" />{{ compose ? '优化后' : '预测值' }}</span>
      </div>
    </div>
    <div class="chart-plot">
      <div class="chart-y-axis">
        <span>{{ water ? '700' : '50' }}</span
        ><span>{{ water ? '500' : '40' }}</span
        ><span>{{ water ? '300' : '30' }}</span
        ><span>{{ water ? '100' : '20' }}</span>
      </div>
      <span class="chart-peak-label">{{ water ? '晚间高峰' : '尖峰电价' }}</span
      ><svg
        viewBox="0 0 650 144"
        role="img"
        :aria-label="water ? '模拟供水需求曲线' : '模拟用能负荷曲线，优化后晚间峰值降低'"
        preserveAspectRatio="none"
      >
        <defs>
          <linearGradient id="chartArea" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stop-color="#219d89" stop-opacity=".15" />
            <stop offset="100%" stop-color="#219d89" stop-opacity=".01" />
          </linearGradient>
        </defs>
        <g stroke="#edf0f1" stroke-width="1"><path d="M38 24H630M38 64H630M38 104H630M38 144H630" /></g>
        <rect x="456" y="13" width="80" height="131" fill="#f8ecd5" opacity=".5" rx="4" />
        <path
          d="M38 109 C66 109 68 113 86 110 S120 117 136 109 S160 100 181 93 S214 79 233 75 S263 65 283 67 S312 83 334 79 S365 64 383 63 S412 77 435 74 S460 61 480 67 S508 69 525 82 S554 87 573 103 S608 117 630 120 L630 144 L38 144 Z"
          fill="url(#chartArea)"
        />
        <path
          d="M38 121 C67 121 72 122 88 121 S117 124 136 118 S165 88 181 69 S213 45 233 39 S261 31 283 42 S309 72 334 70 S365 52 383 46 S413 58 435 50 S460 32 480 35 S510 38 525 60 S553 80 573 105 S609 118 630 121"
          fill="none"
          stroke="#b7c7ce"
          stroke-width="2"
          stroke-dasharray="5 4"
        />
        <path
          d="M38 109 C66 109 68 113 86 110 S120 117 136 109 S160 100 181 93 S214 79 233 75 S263 65 283 67 S312 83 334 79 S365 64 383 63 S412 77 435 74 S460 61 480 67 S508 69 525 82 S554 87 573 103 S608 117 630 120"
          fill="none"
          stroke="#198875"
          stroke-width="2.5"
        />
      </svg>
    </div>
    <div class="chart-x-axis">
      <span>00:00</span><span>06:00</span><span>12:00</span><span>18:00</span><span>24:00</span>
    </div>
  </div>
</template>
