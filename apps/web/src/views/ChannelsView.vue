<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Hash, Plus } from 'lucide-vue-next'
import { useResource } from '../api'
import type { Channel, Employee, Handoff, Task } from '../types'
import PageTitle from '../components/PageTitle.vue'
import ResourceState from '../components/ResourceState.vue'
import StatusTag from '../components/StatusTag.vue'
import EntityForm from '../components/EntityForm.vue'
import ChatThread from '../components/ChatThread.vue'
const route = useRoute(), router = useRouter()
const channels = useResource<Channel[]>('/channels', [])
const employees = useResource<Employee[]>('/employees', [])
const tasks = useResource<Task[]>('/tasks', [])
const handoffs = useResource<Handoff[]>('/handoffs', [])
const creating = ref(false)
const channel = computed(() => channels.data.value.find(item => item.id === route.query.channel) || channels.data.value[0])
const relatedTasks = computed(() => tasks.data.value.filter(task => task.team_id === channel.value?.team_id))
const members = useResource<{ id: string; name: string; kind: string }[]>(() => channel.value ? `/channels/${channel.value.id}/members` : '', [])
const channelEmployees = computed(() => employees.data.value.filter(employee => members.data.value.some(member => member.id === employee.id)))
watch(() => channel.value?.id, id => { if (id && id !== route.query.channel) router.replace({ query: { channel: id } }) })
</script>
<template>
  <PageTitle title="团队协作" subtitle="人和数字员工共同讨论，正式交接有主责、有签收、有证据。" eyebrow="TEAM / HUMAN + DIGITAL EMPLOYEE"><el-button type="primary" :icon="Plus" @click="creating = true">新建讨论</el-button></PageTitle>
  <div class="workspace-layout"><aside class="panel roster"><div class="panel-heading"><h2>交流空间</h2><el-tag round>{{ channels.data.value.length }}</el-tag></div><ResourceState :loading="channels.loading.value" :error="channels.error.value" :empty="!channels.data.value.length" description="尚未加入交流空间" @retry="channels.load"><button v-for="item in channels.data.value" :key="item.id" class="roster-item" :class="{ selected: item.id === channel?.id }" @click="router.replace({ query: { channel: item.id } })"><span class="avatar"><Hash :size="18"/></span><div><strong>{{ item.name }}</strong><small>{{ item.kind === 'DM' ? '私人对话' : '团队讨论' }}</small></div></button></ResourceState></aside>
    <article v-if="channel" class="panel conversation"><div class="chat-heading"><span class="avatar"><Hash :size="20"/></span><div><h2>{{ channel.name }}</h2><p>{{ channel.kind === 'DM' ? '对话仅对有权参与者可见' : '围绕共同目标讨论，@ 员工产生优先关注' }}</p></div><el-tag type="info">{{ channel.kind }}</el-tag></div><ChatThread :channel-id="channel.id" :employees="channelEmployees" :participants="members.data.value" :group="channel.kind !== 'DM'"/></article><article v-else class="panel empty-conversation"><el-empty description="创建或选择交流空间"/></article>
    <aside v-if="channel" class="panel employee-aside"><div class="aside-body"><h3>频道成员</h3><ResourceState :loading="members.loading.value" :error="members.error.value" :empty="!members.data.value.length" description="没有可见成员" @retry="members.load"><div class="member-list"><div v-for="member in members.data.value" :key="member.id"><span class="avatar avatar-small">{{ member.name.slice(0,1) }}</span><RouterLink v-if="member.kind === 'EMPLOYEE'" :to="`/employees/${member.id}`">{{ member.name }}</RouterLink><span v-else>{{ member.name }}</span></div></div></ResourceState><div class="divider"></div><h3>团队关联工作</h3><ResourceState :loading="tasks.loading.value" :error="tasks.error.value" :empty="!relatedTasks.length" description="暂无关联工作" @retry="tasks.load"><RouterLink v-for="task in relatedTasks.slice(0,6)" :key="task.id" :to="`/tasks/${task.id}`" class="mini-card"><strong>{{ task.title }}</strong><StatusTag :value="task.status"/></RouterLink></ResourceState><div class="divider"></div><h3>正式交接</h3><ResourceState :loading="handoffs.loading.value" :error="handoffs.error.value" :empty="!handoffs.data.value.filter(item => relatedTasks.some(task => task.id === item.task_id)).length" description="暂无相关交接" @retry="handoffs.load"><RouterLink v-for="handoff in handoffs.data.value.filter(item => relatedTasks.some(task => task.id === item.task_id))" :key="handoff.id" :to="`/tasks/${handoff.task_id}`" class="mini-card"><strong>{{ handoff.reason }}</strong><StatusTag :value="handoff.status"/></RouterLink></ResourceState><div class="soft-note"><p>发消息不会改变任务主责。交接由接收员工签收后生效，群聊成员资格不授予工程写权限。</p></div></div></aside>
  </div><EntityForm v-model="creating" kind="channel"/>
</template>
