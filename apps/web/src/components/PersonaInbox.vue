<script setup lang="ts">
import { useResource } from '../api'
import type { Detail } from '../types'
import { date } from '../format'
import ResourceState from './ResourceState.vue'
const props = defineProps<{ employeeId: string }>()
const inbox = useResource<Detail[]>(() => `/employees/${props.employeeId}/inbox`, [])
const turns = useResource<Detail[]>(() => `/employees/${props.employeeId}/turns`, [])
const dispositions: Record<string,string> = { HANDLED: '已处理', NO_ACTION: '无需操作，已记档', DEFERRED: '已延后', REVOKED: '来源授权已撤销，停止处理' }
</script>
<template>
  <h3>工作收件箱</h3><ResourceState :loading="inbox.loading.value" :error="inbox.error.value" :empty="!inbox.data.value.length" description="暂无已投递事项" @retry="inbox.load">
    <div v-for="item in inbox.data.value.slice().reverse()" :key="String(item.id)" class="mini-card"><strong>{{ item.reason }}</strong><p class="caption">事件 {{ item.source_event_id }}</p><small>{{ item.observed_at ? `已观察 · ${date(item.observed_at)}` : '已投递，尚未观察' }}</small><small>{{ item.disposition ? dispositions[String(item.disposition)] || item.disposition : '尚无处理结论' }}</small></div>
  </ResourceState><div class="divider"></div><h3>短决策回合</h3>
  <ResourceState :loading="turns.loading.value" :error="turns.error.value" :empty="!turns.data.value.length" description="尚无原生决策回合" @retry="turns.load"><div v-for="item in turns.data.value.slice().reverse().slice(0,20)" :key="String(item.id)" class="mini-card"><strong>{{ item.status }}</strong><small>{{ date(item.created_at) }}</small><p class="caption">原生会话 {{ item.native_session_id || '尚未绑定' }}</p><p class="caption">回合 {{ item.fence }}</p></div></ResourceState>
</template>
