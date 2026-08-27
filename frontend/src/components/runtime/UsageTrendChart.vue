<template><div ref="chartRef" class="usage-trend-chart" role="img" aria-label="Token 使用趋势图" /></template>

<script setup lang="ts">
import * as echarts from 'echarts/core'
import { LineChart } from 'echarts/charts'
import { GridComponent, LegendComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { useResizeObserver } from '@vueuse/core'
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import type { UsageSummary } from '@/api/types'

const props = defineProps<{ data: Array<{ date: string } & UsageSummary> }>()
const chartRef = ref<HTMLElement | null>(null)
let chart: echarts.ECharts | null = null
echarts.use([LineChart, GridComponent, LegendComponent, TooltipComponent, CanvasRenderer])

function render() {
  if (!chart) return
  chart.setOption({
    backgroundColor: 'transparent',
    grid: { top: 34, right: 14, bottom: 24, left: 48 },
    legend: { top: 0, right: 0, textStyle: { color: '#70839c', fontSize: 9 } },
    tooltip: { trigger: 'axis', backgroundColor: '#101c2e', borderColor: '#273c59', textStyle: { color: '#dce9fa' } },
    xAxis: { type: 'category', boundaryGap: false, data: props.data.map((item) => item.date.slice(5)), axisLine: { lineStyle: { color: '#21334c' } }, axisLabel: { color: '#70839c', fontSize: 9 } },
    yAxis: { type: 'value', axisLabel: { color: '#70839c', fontSize: 9 }, splitLine: { lineStyle: { color: '#17263a' } } },
    series: [
      { name: '输入', type: 'line', smooth: true, symbol: 'none', data: props.data.map((item) => item.input_tokens ?? 0), lineStyle: { color: '#4c8dff', width: 2 }, areaStyle: { color: 'rgba(76,141,255,.08)' } },
      { name: '输出', type: 'line', smooth: true, symbol: 'none', data: props.data.map((item) => item.output_tokens ?? 0), lineStyle: { color: '#32d69b', width: 2 } },
      { name: '缓存读取', type: 'line', smooth: true, symbol: 'none', data: props.data.map((item) => item.cache_read_tokens ?? 0), lineStyle: { color: '#a886ff', width: 1.5 } },
    ],
  })
}

onMounted(() => { if (chartRef.value) { chart = echarts.init(chartRef.value); render() } })
watch(() => props.data, render, { deep: true })
useResizeObserver(chartRef, () => chart?.resize())
onBeforeUnmount(() => chart?.dispose())
</script>
