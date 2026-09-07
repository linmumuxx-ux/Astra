<template><div ref="chartRef" class="trend-chart" role="img" aria-label="近七日任务趋势图" /></template>

<script setup lang="ts">
import * as echarts from 'echarts/core'
import { chartTypography, loadChartFonts } from '@/utils/typography'
import { LineChart } from 'echarts/charts'
import { GridComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { useResizeObserver } from '@vueuse/core'

echarts.use([LineChart, GridComponent, TooltipComponent, CanvasRenderer])
const chartRef = ref<HTMLElement | null>(null)
let chart: echarts.ECharts | null = null

onMounted(async () => {
  await loadChartFonts()

  if (!chartRef.value) return
  chart = echarts.init(chartRef.value)
  const typography = chartTypography()
  chart.setOption({
    textStyle: typography,
    backgroundColor: 'transparent',
    grid: { top: 18, right: 14, bottom: 24, left: 30 },
    tooltip: { trigger: 'axis', backgroundColor: '#101c2e', borderColor: '#273c59', textStyle: { ...typography, color: '#dce9fa' } },
    xAxis: { type: 'category', boundaryGap: false, data: ['08/21', '08/22', '08/23', '08/24', '08/25', '08/26', '今日'], axisLine: { lineStyle: { color: '#21334c' } }, axisLabel: { ...typography, color: '#70839c', fontSize: typography.fontSize } },
    yAxis: { type: 'value', splitNumber: 3, axisLabel: { ...typography, color: '#70839c', fontSize: typography.fontSize }, splitLine: { lineStyle: { color: '#17263a' } } },
    series: [
      { name: '创建', type: 'line', smooth: true, symbol: 'none', data: [4, 7, 5, 9, 8, 12, 6], lineStyle: { color: '#4c8dff', width: 2 }, areaStyle: { color: 'rgba(76,141,255,.08)' } },
      { name: '完成', type: 'line', smooth: true, symbol: 'none', data: [3, 5, 6, 7, 8, 10, 2], lineStyle: { color: '#32d69b', width: 2 } },
      { name: '失败', type: 'line', smooth: true, symbol: 'none', data: [1, 0, 1, 1, 0, 1, 0], lineStyle: { color: '#ff6f7d', width: 1.5, type: 'dashed' } },
    ],
  })
})
useResizeObserver(chartRef, () => chart?.resize())
onBeforeUnmount(() => chart?.dispose())
</script>
