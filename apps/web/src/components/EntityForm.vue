<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { mutate, useResource } from '../api'
import type { Employee, Role, Team } from '../types'
type Field = { key: string; label: string; type?: 'text' | 'area' | 'lines' | 'json' | 'number' | 'team' | 'role' | 'employee' | 'select'; required?: boolean; values?: string[]; hint?: string; initial?: unknown }
const props = defineProps<{ kind: string; modelValue: boolean; employeeId?: string; teamId?: string; record?: Record<string, unknown> }>()
const emit = defineEmits<{ 'update:modelValue': [boolean]; created: [unknown] }>()
const teams = useResource<Team[]>('/teams', [])
const roles = useResource<Role[]>('/roles', [])
const employees = useResource<Employee[]>('/employees', [])
const values = reactive<Record<string, string | number>>({})
const busy = ref(false)
const error = ref('')
const definitions: Record<string, { title: string; path: string; fields: Field[] }> = {
  team: { title: '建立团队', path: '/teams', fields: [{ key: 'name', label: '团队名称', required: true }] },
  role: { title: '建立岗位', path: '/roles', fields: [{ key: 'name', label: '岗位名称', required: true }, { key: 'team_id', label: '所属团队', type: 'team', required: true }, { key: 'mandate', label: '长期职责', type: 'area', required: true }, { key: 'permissions', label: '岗位权限上限', type: 'lines', hint: '每行一个已约定的 action。员工授权不能超过岗位权限。' }] },
  employee: { title: '创建数字员工', path: '/employees', fields: [{ key: 'name', label: '员工姓名', required: true }, { key: 'team_id', label: '所属团队', type: 'team', required: true }, { key: 'role_id', label: '业务岗位', type: 'role', required: true }, { key: 'scope', label: '责任范围', type: 'json', initial: '{}', required: true, hint: 'JSON 对象，明确工程、资产与业务边界。' }, { key: 'permissions', label: '自主授权', type: 'lines', hint: '每行一个 action；由后端校验授权人和岗位边界。' }, { key: 'daily_token_budget', label: '每日 Token 预算', type: 'number', initial: 100000 }] },
  goal: { title: '设定工作目标', path: '/goals', fields: [{ key: 'title', label: '目标', required: true }, { key: 'team_id', label: '团队', type: 'team', required: true }, { key: 'owner_employee_id', label: '主责员工', type: 'employee' }, { key: 'metric', label: '衡量方式', type: 'area', required: true }, { key: 'scope', label: '责任范围', type: 'json', initial: '{}' }] },
  task: { title: '交办业务工作', path: '/tasks', fields: [{ key: 'title', label: '工作标题', required: true }, { key: 'team_id', label: '团队', type: 'team', required: true }, { key: 'owner_employee_id', label: '唯一主责员工', type: 'employee', required: true }, { key: 'objective', label: '交付目标', type: 'area', required: true }, { key: 'acceptance_criteria', label: '验收标准', type: 'lines', required: true, hint: '每行一条可验证的标准。' }, { key: 'required_capabilities', label: '执行能力要求', type: 'lines' }, { key: 'asset_scope', label: '工程与资产范围', type: 'json', initial: '{}' }] },
  channel: { title: '发起团队讨论', path: '/channels', fields: [{ key: 'name', label: '讨论名称', required: true }, { key: 'team_id', label: '所属团队', type: 'team', required: true }, { key: 'member_ids', label: '参与者身份 ID', type: 'lines', hint: '每行一位已授权的人类或员工身份 ID。当前身份由后端加入。' }] },
  routine: { title: '安排持续职责', path: '/routines', fields: [{ key: 'title', label: '例程名称', required: true }, { key: 'employee_id', label: '责任员工', type: 'employee', required: true }, { key: 'kind', label: '触发方式', type: 'select', values: ['INTERVAL', 'CRON', 'EVENT'], initial: 'INTERVAL' }, { key: 'schedule', label: '执行规则', required: true, hint: 'INTERVAL 填秒数，CRON 填 Cron 表达式，EVENT 填事件类型。' }, { key: 'timezone', label: '时区', initial: 'Asia/Shanghai', required: true }] },
  worker: { title: '注册执行资源', path: '/workers', fields: [{ key: 'name', label: 'Worker 名称', required: true }, { key: 'base_url', label: 'OpenCode Server 地址', required: true, hint: '填写公司环境可达地址；注册不代表健康检查已通过。' }, { key: 'capabilities', label: '能力标签', type: 'lines', required: true }, { key: 'allowed_projects', label: '授权工程', type: 'lines', required: true }, { key: 'workspace_roots', label: '允许的工作区根目录', type: 'lines', required: true, hint: '每行一个 Worker 主机中的绝对路径。' }, { key: 'concurrent_slots', label: '并发容量', type: 'number', initial: 1 }] },
  knowledge: { title: '添加组织资料', path: '/knowledge', fields: [{ key: 'title', label: '资料标题', required: true }, { key: 'team_id', label: '共享团队', type: 'team', required: true }, { key: 'kind', label: '资料类型', type: 'select', values: ['SOURCE', 'WIKI', 'EXPERIENCE', 'SKILL'], initial: 'SOURCE' }, { key: 'content', label: '正文', type: 'area', required: true }, { key: 'source_refs', label: '来源证据引用', type: 'lines', required: true, hint: '每行一个可信 Task / Channel / 文档引用；新增资料默认未经验证。' }] },
}
const definition = computed(() => definitions[props.kind])
watch(() => props.modelValue, open => { if (open && definition.value) { Object.keys(values).forEach(key => delete values[key]); for (const field of definition.value.fields) { const current = props.record?.[field.key]; values[field.key] = current === undefined ? field.initial as string | number ?? '' : field.type === 'json' ? JSON.stringify(current, null, 2) : field.type === 'lines' ? (current as string[]).join('\n') : current as string | number } if (props.employeeId) values[props.kind === 'routine' ? 'employee_id' : 'owner_employee_id'] = props.employeeId; if (props.teamId) values.team_id = props.teamId; error.value = '' } })
function choices(field: Field) {
  const items = field.type === 'team' ? teams.data.value : field.type === 'role' ? roles.data.value : employees.data.value
  return items.filter(item => field.type === 'team' || !values.team_id || (item as Role | Employee).team_id === values.team_id)
}
async function submit() {
  error.value = ''
  const payload: Record<string, unknown> = {}
  try {
    for (const field of definition.value!.fields) {
      const raw = values[field.key]
      if (field.required && !String(raw ?? '').trim()) throw new Error(`请填写${field.label}`)
      let value: unknown = raw
      if (field.type === 'lines') value = String(raw).split('\n').map(line => line.trim()).filter(Boolean)
      if (field.type === 'json') { value = JSON.parse(String(raw || '{}')); if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error(`${field.label}必须为 JSON 对象`) }
      if (field.type === 'number') value = Number(raw)
      if (field.key === 'owner_employee_id' && !raw) value = null
      if (!(props.record && ['team_id', 'role_id', 'employee_id', 'kind'].includes(field.key))) payload[field.key] = value
    }
    if (props.kind === 'channel') payload.kind = 'GROUP'
    busy.value = true
    if (props.record) payload.revision = props.record.revision
    const result = await mutate(props.record ? `${definition.value!.path}/${props.record.id}` : definition.value!.path, payload, props.record ? 'PATCH' : 'POST')
    ElMessage.success('已保存，正在读取最新状态')
    emit('created', result); emit('update:modelValue', false)
  } catch (caught) { error.value = (caught as Error).message } finally { busy.value = false }
}
</script>
<template>
  <el-dialog :model-value="modelValue" :title="record ? '更新业务资料' : definition?.title" width="580px" :close-on-click-modal="!busy" @update:model-value="$emit('update:modelValue', $event)">
    <el-form v-if="definition" label-position="top" @submit.prevent="submit">
      <el-form-item v-for="field in definition.fields" :key="field.key" :label="field.label" :required="field.required">
        <el-select v-if="['team','role','employee'].includes(field.type || '')" v-model="values[field.key]" filterable clearable :disabled="!!record && ['team_id','role_id','employee_id'].includes(field.key)" :placeholder="`请选择${field.label}`" :aria-label="field.label"><el-option v-for="option in choices(field)" :key="option.id" :label="option.name" :value="option.id"/></el-select>
        <el-select v-else-if="field.type === 'select'" v-model="values[field.key]" :disabled="!!record && field.key === 'kind'" :aria-label="field.label"><el-option v-for="option in field.values" :key="option" :value="option" :label="option"/></el-select>
        <el-input-number v-else-if="field.type === 'number'" v-model="values[field.key] as number" :min="1" :max="2147483647" :aria-label="field.label"/>
        <el-input v-else v-model="values[field.key]" :type="['area','lines','json'].includes(field.type || '') ? 'textarea' : 'text'" :rows="field.type === 'area' ? 4 : 2" :aria-label="field.label"/>
        <span v-if="field.hint" class="field-hint">{{ field.hint }}</span>
      </el-form-item>
      <el-alert v-if="error" :title="error" type="error" :closable="false"/>
    </el-form>
    <template #footer><el-button :disabled="busy" @click="$emit('update:modelValue', false)">取消</el-button><el-button type="primary" :loading="busy" @click="submit">确认保存</el-button></template>
  </el-dialog>
</template>
