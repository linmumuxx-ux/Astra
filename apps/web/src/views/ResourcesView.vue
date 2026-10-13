<script setup lang="ts">
import { computed, ref } from 'vue'
import { Activity, Boxes, Cable, Cpu, Plus, Server } from 'lucide-vue-next'
import { ElMessage } from 'element-plus'
import { mutate, useResource } from '../api'
import type { Detail, Worker } from '../types'
import { date, json } from '../format'
import PageTitle from '../components/PageTitle.vue'
import ResourceState from '../components/ResourceState.vue'
import StatusTag from '../components/StatusTag.vue'
import EntityForm from '../components/EntityForm.vue'
const workers = useResource<Worker[]>('/workers', []), leases = useResource<Detail[]>('/worker-leases', []), metrics = useResource<Detail>('/resource-metrics', {})
const tab = ref('workers'), creating = ref(false), probing = ref('')
const slots = computed(() => workers.data.value.reduce((total, worker) => total + worker.concurrent_slots, 0))
async function probe(worker: Worker) { probing.value = worker.id; try { await mutate(`/workers/${worker.id}/probe`); ElMessage.success('真实 Runtime 检查已返回，正在刷新状态') } catch (caught) { ElMessage.error((caught as Error).message) } finally { probing.value = '' } }
</script>
<template>
  <PageTitle title="Worker 与 API 资源中心" subtitle="运行资源独立于员工，按工程授权与租约服务于工作；健康状态来自实际基础设施。" eyebrow="INFRASTRUCTURE / BEHIND THE WORK"><el-button :icon="Plus" @click="creating = true">注册 Worker</el-button></PageTitle>
  <el-tabs v-model="tab"><el-tab-pane label="Worker 资源池" name="workers"/><el-tab-pane label="API 中转站" name="gateway"/><el-tab-pane label="执行租约" name="leases"/><el-tab-pane label="资源观测" name="metrics"/></el-tabs>
  <template v-if="tab === 'workers'"><div class="resource-summary"><div class="panel"><Server :size="20"/><div><strong>{{ workers.data.value.length }}</strong><span>注册 Worker</span></div></div><div class="panel"><Boxes :size="20"/><div><strong>{{ slots }}</strong><span>配置并发容量</span></div></div><div class="panel"><Cpu :size="20"/><div><strong>{{ leases.error.value ? '—' : leases.data.value.length }}</strong><span>可见租约记录</span></div></div></div><ResourceState :loading="workers.loading.value" :error="workers.error.value" :empty="!workers.data.value.length" description="尚未注册执行资源。员工身份与 Worker 分别配置。" @retry="workers.load"><div class="card-grid"><article v-for="worker in workers.data.value" :key="worker.id" class="panel worker-card"><div class="spread"><span class="avatar"><Server :size="22"/></span><StatusTag :value="worker.health"/></div><h2>{{ worker.name }}</h2><p class="mono">{{ worker.base_url }}</p><dl class="detail-list"><dt>OpenCode 版本</dt><dd>{{ worker.runtime_version || '尚未探测' }}</dd><dt>并发槽位</dt><dd>{{ worker.concurrent_slots }}</dd></dl><h3>执行能力</h3><div class="tag-wrap"><el-tag v-for="capability in worker.capabilities" :key="capability" type="info">{{ capability }}</el-tag></div><h3>授权工程</h3><div class="tag-wrap"><el-tag v-for="project in worker.allowed_projects" :key="project">{{ project }}</el-tag></div><h3>工作区边界</h3><p v-for="root in worker.workspace_roots" :key="root" class="mono">{{ root }}</p><div class="action-row"><el-button :loading="probing === worker.id" @click="probe(worker)">检查真实 Runtime</el-button><span class="caption">{{ worker.last_seen_at ? date(worker.last_seen_at) : '尚未检查' }}</span></div></article></div></ResourceState></template>
  <section v-else-if="tab === 'gateway'" class="panel gateway-empty"><Cable :size="40" :stroke-width="1.2"/><h2>API 网关尚未接入</h2><p>当前服务尚未提供 Provider、路由、凭据引用与额度的管理接口。</p><p class="caption">此页面不会将注册 Worker 或模型配置视为网关健康证据。正式接入后，由后端提供配额、延迟、成本和故障数据。</p></section>
  <section v-else-if="tab === 'leases'" class="panel"><ResourceState :loading="leases.loading.value" :error="leases.error.value" :empty="!leases.data.value.length" description="暂无可见执行租约" @retry="leases.load"><el-table :data="leases.data.value"><el-table-column prop="worker_id" label="Worker" min-width="160"/><el-table-column label="关联工作" min-width="160"><template #default="{ row }"><RouterLink v-if="row.task_id" :to="`/tasks/${row.task_id}`" class="text-link">{{ row.task_id }}</RouterLink><span v-else>{{ row.owner_ref || '—' }}</span></template></el-table-column><el-table-column prop="state" label="状态" min-width="100"/><el-table-column prop="fence" label="Fencing" min-width="90"/><el-table-column label="到期时间" min-width="170"><template #default="{ row }">{{ date(row.expires_at) }}</template></el-table-column></el-table></ResourceState></section>
  <section v-else class="panel metrics-detail"><div class="panel-heading"><h2><Activity :size="19"/>资源权威观测</h2></div><ResourceState :loading="metrics.loading.value" :error="metrics.error.value" :empty="!Object.keys(metrics.data.value).length" description="尚无资源观测数据" @retry="metrics.load"><dl class="metric-dictionary"><template v-for="(value,key) in metrics.data.value" :key="key"><dt>{{ key }}</dt><dd>{{ typeof value === 'object' ? json(value) : value }}</dd></template></dl></ResourceState></section>
  <EntityForm v-model="creating" kind="worker"/>
</template>
