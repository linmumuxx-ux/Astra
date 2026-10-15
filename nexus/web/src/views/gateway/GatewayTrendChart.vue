<template>
  <div ref="chartRef" class="gateway-trend" :class="{ 'gateway-trend--tall': tall }" role="img" :aria-label="ariaLabel" />
</template>

<script setup lang="ts">
import * as echarts from 'echarts/core'
import { LineChart } from 'echarts/charts'
import { GridComponent, LegendComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { useResizeObserver } from '@vueuse/core'
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import type { GatewayStatBucket } from '@/api/gateway'
import { chartTypography, loadChartFonts } from '@/utils/typography'

const props = withDefaults(
  defineProps<{ buckets: GatewayStatBucket[]; mode?: 'tokens' | 'requests'; tall?: boolean }>(),
  { mode: 'tokens', tall: false },
)

const chartRef = ref<HTMLElement | null>(null)
let chart: echarts.ECharts | null = null
echarts.use([LineChart, GridComponent, LegendComponent, TooltipComponent, CanvasRenderer])

const ariaLabel = computed(() => (props.mode === 'tokens' ? 'API 中转 Token 使用趋势图' : 'API 中转请求量趋势图'))

function parseTime(value: string) {
  return new Date(/[zZ]|[+-]\d{2}:?\d{2}$/.test(value) ? value : `${value}Z`)
}

function axisLabels() {
  const points = props.buckets
  if (points.length < 2) {
    return points.map((point) => parseTime(point.bucket_start).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', hour12: false }))
  }
  const stepMinutes = (parseTime(points[1].bucket_start).getTime() - parseTime(points[0].bucket_start).getTime()) / 60_000
  return points.map((point) => {
    const date = parseTime(point.bucket_start)
    if (stepMinutes <= 60) return date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', hour12: false })
    return date.toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit' })
  })
}

function render() {
  if (!chart) return
  const typography = chartTypography()
  const series = props.mode === 'tokens'
    ? [
        { name: '输入 Token', data: props.buckets.map((item) => item.input_tokens), color: '#3d8ff0' },
        { name: '输出 Token', data: props.buckets.map((item) => item.output_tokens), color: '#159d65' },
      ]
    : [
        { name: '请求数', data: props.buckets.map((item) => item.requests), color: '#159d65' },
        { name: '成功', data: props.buckets.map((item) => item.success), color: '#3d8ff0' },
        { name: '失败', data: props.buckets.map((item) => item.errors), color: '#e45d6a' },
      ]
  chart.setOption({
    textStyle: typography,
    backgroundColor: 'transparent',
    grid: { top: 34, right: 14, bottom: 26, left: 52 },
    legend: { top: 0, right: 0, textStyle: { ...typography, color: '#617771' } },
    tooltip: { trigger: 'axis', backgroundColor: '#102522', borderColor: '#102522', textStyle: { ...typography, color: '#eaf6f1' } },
    xAxis: {
      type: 'category',
      boundaryGap: false,
      data: axisLabels(),
      axisLine: { lineStyle: { color: '#d7e1dd' } },
      axisLabel: { ...typography, color: '#617771' },
    },
    yAxis: {
      type: 'value',
      splitNumber: 4,
      axisLabel: { ...typography, color: '#617771' },
      splitLine: { lineStyle: { color: '#e7eeeb' } },
    },
    series: series.map((item, index) => ({
      name: item.name,
      type: 'line',
      smooth: true,
      symbol: 'none',
      data: item.data,
      lineStyle: { color: item.color, width: 2 },
      areaStyle: index === 0 ? { color: `${item.color}14` } : undefined,
    })),
  })
}

onMounted(async () => {
  await loadChartFonts()
  if (chartRef.value) {
    chart = echarts.init(chartRef.value)
    render()
  }
})
watch(() => [props.buckets, props.mode], render, { deep: true })
useResizeObserver(chartRef, () => chart?.resize())
onBeforeUnmount(() => chart?.dispose())
</script>

<style scoped>
.gateway-trend { width: 100%; height: 200px; }
.gateway-trend--tall { height: 240px; }
</style>