<script setup lang="ts">
import { computed, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { mutate, principal, useResource } from '../api'
import type { Entity, Team } from '../types'
import { date } from '../format'
import ResourceState from './ResourceState.vue'
interface Actor extends Entity { name: string; kind: string; active: boolean; permissions: string[] }
interface Grant extends Entity { actor_id: string; team_id: string; project_id: string; permissions: string[]; expires_at: number }
const admin = computed(() => principal.value?.kind === 'HUMAN' && principal.value?.permissions?.includes('*'))
const actors = useResource<Actor[]>(() => admin.value ? '/actors' : '', [])
const grants = useResource<Grant[]>(() => admin.value ? '/workspace-grants' : '', [])
const teams = useResource<Team[]>('/teams', [])
const dialog = ref(''), busy = ref(false), error = ref(''), issued = ref(false)
const visible = computed({ get: () => !!dialog.value, set: value => { if (!value) dialog.value = '' } })
const editActor = ref<Actor>(), editGrant = ref<Grant>()
const human = reactive({ name: '', permissions: '', token: '' })
const grant = reactive({ actor_id: '', team_id: '', project_id: '', permissions: '', expires_at: 0 })
const member = reactive({ team_id: '', actor_id: '', role: 'MEMBER' })
const subject = computed(() => dialog.value === 'grant' ? grant : member)
const lines = (value: string) => value.split('\n').map(item => item.trim()).filter(Boolean)
function open(kind: string, record?: Actor | Grant) {
  dialog.value = kind; error.value = ''; issued.value = false
  editActor.value = kind === 'human' ? record as Actor | undefined : undefined
  editGrant.value = kind === 'grant' ? record as Grant | undefined : undefined
  if (kind === 'human') {
    const actor = editActor.value
    human.name = actor?.name || ''; human.permissions = actor?.permissions.join('\n') || ''
    human.token = actor ? '' : Array.from(crypto.getRandomValues(new Uint8Array(32)), value => value.toString(16).padStart(2, '0')).join('')
  }
  if (kind === 'grant') {
    const row = editGrant.value
    Object.assign(grant, row ? { ...row, permissions: row.permissions.join('\n') } : { actor_id: '', team_id: '', project_id: '', permissions: '', expires_at: Math.floor(Date.now() / 1000) + 86400 })
  }
  if (kind === 'member') Object.assign(member, { actor_id: '', team_id: '', role: 'MEMBER' })
}
async function save() {
  busy.value = true; error.value = ''
  try {
    if (dialog.value === 'human') {
      if (!human.name.trim()) throw new Error('请填写人员姓名')
      if (editActor.value) await mutate(`/actors/${editActor.value.id}`, { revision: editActor.value.revision, name: human.name, permissions: lines(human.permissions) }, 'PATCH')
      else {
        const hash = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(human.token))
        await mutate('/actors', { name: human.name, permissions: lines(human.permissions), credential_digest: Array.from(new Uint8Array(hash), value => value.toString(16).padStart(2, '0')).join('') })
        issued.value = true; return
      }
    } else if (dialog.value === 'grant') {
      if (!grant.actor_id || !grant.team_id || !grant.project_id.trim() || !lines(grant.permissions).length) throw new Error('请完整填写授权主体、团队、工程与具体操作')
      const payload = { permissions: lines(grant.permissions), expires_at: grant.expires_at }
      if (editGrant.value) await mutate(`/workspace-grants/${editGrant.value.id}`, { ...payload, revision: editGrant.value.revision }, 'PATCH')
      else await mutate('/workspace-grants', { ...payload, actor_id: grant.actor_id, team_id: grant.team_id, project_id: grant.project_id })
    } else {
      if (!member.team_id || !member.actor_id) throw new Error('请选择团队和人类成员')
      await mutate(`/teams/${member.team_id}/members`, { actor_id: member.actor_id, role: member.role })
    }
    dialog.value = ''; ElMessage.success('授权设置已保存')
  } catch (caught) { error.value = (caught as Error).message } finally { busy.value = false }
}
async function revoke(kind: 'actors' | 'workspace-grants', id: string) {
  try {
    await ElMessageBox.confirm('撤销后，新的请求和事件推送将重新检查权限。已经发生的外部副作用仍需核验。', '确认撤销当前授权', { confirmButtonText: '确认撤销', cancelButtonText: '保留授权' })
    await mutate(`/${kind}/${id}/revoke`); ElMessage.success('已撤销，正在刷新权威状态')
  } catch (caught) { if (caught instanceof Error) ElMessage.error(caught.message) }
}
</script>
<template>
  <template v-if="admin">
    <div class="section-title"><h2>人员与工程授权</h2><div class="action-row"><el-button @click="open('member')">加入团队</el-button><el-button @click="open('human')">建立人员身份</el-button><el-button type="primary" @click="open('grant')">授予工程权限</el-button></div></div>
    <section class="panel">
      <h3>独立登录主体</h3>
      <ResourceState :loading="actors.loading.value" :error="actors.error.value" :empty="!actors.data.value.length" @retry="actors.load">
        <el-table :data="actors.data.value"><el-table-column prop="name" label="姓名" min-width="150"/><el-table-column prop="kind" label="主体类型" width="120"/><el-table-column label="操作权限" min-width="240"><template #default="{ row }"><span class="mono">{{ row.permissions.join(', ') || '只读' }}</span></template></el-table-column><el-table-column label="登录状态" width="100"><template #default="{ row }">{{ row.active ? '有效' : '已停用' }}</template></el-table-column><el-table-column label="人员操作" min-width="150"><template #default="{ row }"><el-button v-if="row.kind === 'HUMAN'" text @click="open('human', row)">编辑授权</el-button><el-button v-if="['HUMAN','SYSTEM'].includes(row.kind) && row.active && row.id !== principal?.id" text type="danger" @click="revoke('actors', row.id)">停用</el-button></template></el-table-column></el-table>
      </ResourceState>
      <h3>Workspace Grant</h3>
      <ResourceState :loading="grants.loading.value" :error="grants.error.value" :empty="!grants.data.value.length" description="尚未授予任何具体工程操作权限" @retry="grants.load">
        <el-table :data="grants.data.value"><el-table-column label="主体" min-width="130"><template #default="{ row }">{{ actors.data.value.find(actor => actor.id === row.actor_id)?.name || row.actor_id }}</template></el-table-column><el-table-column prop="project_id" label="工程" min-width="150"/><el-table-column label="具体操作" min-width="250"><template #default="{ row }"><span class="mono">{{ row.permissions.join(', ') }}</span></template></el-table-column><el-table-column label="到期" min-width="170"><template #default="{ row }">{{ date(row.expires_at) }}</template></el-table-column><el-table-column label="授权操作" min-width="150"><template #default="{ row }"><el-button text @click="open('grant', row)">调整</el-button><el-button text type="danger" @click="revoke('workspace-grants', row.id)">撤销</el-button></template></el-table-column></el-table>
      </ResourceState>
    </section>
    <el-dialog v-model="visible" :title="dialog === 'human' ? '人员登录身份' : dialog === 'grant' ? '具体工程授权' : '人类成员加入团队'" width="580px" :close-on-click-modal="!busy" :close-on-press-escape="!busy" @closed="human.token = ''; issued = false">
      <template v-if="issued"><el-alert title="身份已创建；凭据仅本次显示，有效期为 24 小时。请通过安全渠道交付。" type="success" :closable="false"/><el-input v-model="human.token" type="password" show-password readonly aria-label="新人员一次性访问凭据"/><p class="caption">服务端只保存哈希。关闭后本页面不保留该凭据。</p><el-button type="primary" @click="dialog = ''">已安全保存，关闭</el-button></template>
      <el-form v-else label-position="top" @submit.prevent="save">
        <template v-if="dialog === 'human'"><el-form-item label="人员姓名"><el-input v-model="human.name" aria-label="人员姓名"/></el-form-item><el-form-item label="人类操作权限"><el-input v-model="human.permissions" type="textarea" :rows="4" aria-label="人类操作权限"/><span class="field-hint">每行一个已约定的 action；留空为团队内只读。加入团队与工程授权须分别配置。</span></el-form-item></template>
        <template v-else>
          <el-form-item label="授权团队"><el-select v-model="subject.team_id" filterable :disabled="!!editGrant" aria-label="授权团队"><el-option v-for="team in teams.data.value" :key="team.id" :value="team.id" :label="team.name"/></el-select></el-form-item>
          <el-form-item label="授权主体"><el-select v-model="subject.actor_id" filterable :disabled="!!editGrant" aria-label="授权主体"><el-option v-for="actor in actors.data.value.filter(actor => actor.active && (dialog === 'grant' || actor.kind === 'HUMAN'))" :key="actor.id" :value="actor.id" :label="`${actor.name} · ${actor.kind}`"/></el-select></el-form-item>
          <template v-if="dialog === 'grant'"><el-form-item label="工程标识"><el-input v-model="grant.project_id" :disabled="!!editGrant" aria-label="工程标识"/></el-form-item><el-form-item label="工程具体操作"><el-input v-model="grant.permissions" type="textarea" :rows="4" aria-label="工程具体操作"/><span class="field-hint">例如 task.create、task.dispatch、task.handoff。仍受岗位、员工范围和组织强制规则约束。</span></el-form-item><el-form-item label="授权到期 Unix 秒"><el-input-number v-model="grant.expires_at" :controls="false" aria-label="授权到期 Unix 秒"/></el-form-item></template>
        </template>
        <el-alert v-if="error" :title="error" type="error" :closable="false"/><div class="action-row"><el-button @click="dialog = ''">取消</el-button><el-button type="primary" native-type="submit" :loading="busy">保存授权设置</el-button></div>
      </el-form>
    </el-dialog>
  </template>
</template>
