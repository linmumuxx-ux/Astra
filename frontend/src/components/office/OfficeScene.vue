<template>
  <section
    ref="sceneElement"
    class="office-scene"
    data-testid="digital-office-scene"
    aria-label="连续数字办公室"
    :data-query="query"
    :data-selected-id="selectedId"
    :data-employee-count="employees.length"
    :data-team-count="teams.length"
  >
    <div class="office-scene__backdrop" aria-hidden="true">
      <span class="office-scene__sunbeam" />
      <span class="office-scene__ambient office-scene__ambient--one" />
      <span class="office-scene__ambient office-scene__ambient--two" />
    </div>

    <div class="office-scene__teams">
      <TeamZone
        v-for="(team, index) in teams"
        :key="team.id"
        :team="team"
        :zone-index="index"
        :focused="focusedTeamId === team.id"
        :selected-id="selectedId"
        :query="query"
        :matched-ids="matchedIds"
        :bubble-modes="bubbleModes"
        @select="emit('select', $event)"
        @focus="emit('focus', $event)"
      />
    </div>

    <div class="office-scene__clock">
      <time :datetime="now.toISOString()"><strong>{{ timeText }}</strong><span>{{ dateText }}</span></time>
    </div>

    <div class="office-scene__principle" aria-hidden="true">
      <strong>协 同</strong><span>让优秀更出色</span><small>Together We Go Further</small>
    </div>

    <div class="office-scene__minimap" aria-label="楼层选择">
      <div aria-hidden="true"><i v-for="index in 12" :key="index" :class="{ active: index === 3 }" /></div>
      <button type="button"><span /><strong>1F 办公室</strong><ChevronDown :size="14" /></button>
    </div>

    <div v-if="!employees.length" class="office-scene__message">
      <strong>数字办公室还没有员工</strong>
      <span>创建员工后，他们会进入对应团队的固定工位。</span>
      <RouterLink class="button button--primary" to="/settings?create=1">创建数字员工</RouterLink>
    </div>
    <div v-else-if="query && !matchedIds.size" class="office-scene__message">
      <strong>没有找到“{{ query }}”</strong><span>可搜索员工姓名、编号、岗位或当前任务。</span>
    </div>
  </section>
</template>

<script setup lang="ts">
import { ChevronDown } from 'lucide-vue-next'
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'
import TeamZone from '@/components/office/TeamZone.vue'
import type { OfficeTeam } from '@/features/office/officeLayout'
import { workspaceEmployeeMatches, type WorkspaceEmployee } from '@/features/workspace/eventAdapter'

type BubbleMode = 'alert'
const props = withDefaults(defineProps<{ teams: OfficeTeam[]; employees: WorkspaceEmployee[]; selectedId?: string; query?: string; focusedTeamId?: string }>(), { selectedId: '', query: '', focusedTeamId: '' })
const emit = defineEmits<{ select: [id: string]; focus: [teamId: string] }>()
const sceneElement = ref<HTMLElement | null>(null)
const now = ref(new Date())
let clockTimer = 0

const normalizedQuery = computed(() => props.query.trim())
const matchedIds = computed(() => new Set(props.employees
  .filter((employee) => workspaceEmployeeMatches(employee, normalizedQuery.value))
  .map((employee) => employee.id)))
const bubbleModes = computed(() => {
  const visible = props.employees
    .filter((employee) => employee.hasError || employee.needHuman)
    .sort((left, right) => Number(right.hasError) - Number(left.hasError)
      || (right.lastActiveAt ?? '').localeCompare(left.lastActiveAt ?? ''))
    .slice(0, 5)
  return new Map<string, BubbleMode>(visible.map((employee) => [employee.id, 'alert']))
})
const timeText = computed(() => now.value.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false }))
const dateText = computed(() => now.value.toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit', weekday: 'short' }).replaceAll('/', '月').replace(' ', '日 '))

onMounted(() => { clockTimer = window.setInterval(() => { now.value = new Date() }, 1_000) })
onBeforeUnmount(() => window.clearInterval(clockTimer))

defineExpose({ element: sceneElement })
</script>

<style scoped>
.office-scene{position:relative;width:100%;height:100%;min-height:610px;overflow:hidden;border-bottom:1px solid #c8ddd4;background:#eaf2ed;isolation:isolate}
.office-scene__backdrop{position:absolute;z-index:-3;inset:0;background:url('/assets/workspace/nexus-office-reference-clean-v1.png') center/cover no-repeat;transform:scale(1.006);transform-origin:center;animation:office-breathe 18s ease-in-out infinite alternate}
.office-scene__backdrop::after{position:absolute;inset:0;background:linear-gradient(180deg,rgba(249,253,252,.08),transparent 21% 80%,rgba(216,239,232,.08)),radial-gradient(circle at 52% 36%,transparent 0 42%,rgba(216,239,233,.025) 78%);content:''}
.office-scene__sunbeam{position:absolute;top:-35%;left:3%;width:52%;height:130%;background:linear-gradient(112deg,rgba(255,255,255,.3),rgba(255,255,255,0) 48%);filter:blur(9px);opacity:.55;transform:skewX(-12deg);animation:sunbeam-drift 12s ease-in-out infinite alternate}
.office-scene__ambient{position:absolute;width:9px;height:9px;border-radius:50%;background:#36c692;box-shadow:0 0 0 7px rgba(54,198,146,.1),0 0 24px rgba(54,198,146,.45);animation:ambient-pulse 2.8s ease-in-out infinite}.office-scene__ambient--one{top:67%;left:28%}.office-scene__ambient--two{top:47%;right:18%;animation-delay:-1.1s}
.office-scene__teams{position:absolute;z-index:4;inset:0}
.office-scene__clock{position:absolute;z-index:18;top:17px;right:2.2%;display:grid;place-items:center;width:106px;min-height:66px;padding:8px;border:1px solid rgba(255,255,255,.9);border-radius:13px;background:rgba(251,253,252,.9);box-shadow:0 12px 28px rgba(48,79,67,.08);backdrop-filter:blur(12px)}.office-scene__clock time{display:grid;color:#26483f;text-align:center}.office-scene__clock strong{font-size: var(--astra-font-subtitle);font-variant-numeric:tabular-nums;letter-spacing:-.02em}.office-scene__clock span{margin-top:2px;color:#73867f;font-size: var(--astra-font-micro)}
.office-scene__principle{position:absolute;z-index:6;top:47%;left:55.4%;display:grid;color:#3d6358;text-shadow:0 1px rgba(255,255,255,.8);transform:rotate(-1deg)}.office-scene__principle strong{font-size: var(--astra-font-label);letter-spacing:.25em}.office-scene__principle span{font-size: var(--astra-font-body)}.office-scene__principle small{color:#69847a;font-size:var(--astra-font-size-7);font-style:italic}
.office-scene__minimap{position:absolute;z-index:18;right:1.2%;bottom:16px;width:132px;padding:9px;border:1px solid rgba(255,255,255,.9);border-radius:13px;background:rgba(252,254,253,.91);box-shadow:0 13px 30px rgba(42,76,63,.12);backdrop-filter:blur(13px)}.office-scene__minimap>div{display:grid;grid-template-columns:repeat(4,1fr);gap:7px;padding:5px 8px 9px}.office-scene__minimap i{width:5px;height:5px;border-radius:50%;background:#42c59a;opacity:.65}.office-scene__minimap i.active{width:9px;height:9px;margin:-2px;background:#10a96c;box-shadow:0 0 0 5px rgba(16,169,108,.12)}.office-scene__minimap button{display:flex;align-items:center;width:100%;height:32px;padding:0 8px;color:#294d42;border:0;border-radius:8px;background:#f8fbf9;font-size: var(--astra-font-helper);cursor:pointer}.office-scene__minimap button>span{width:7px;height:7px;margin-right:8px;border-radius:50%;background:#12ae70}.office-scene__minimap button strong{margin-right:auto}
.office-scene__message{position:absolute;z-index:100;top:55%;left:50%;display:grid;place-items:center;gap:6px;min-width:280px;padding:18px;color:#627970;border:1px solid rgba(192,216,205,.9);border-radius:14px;background:rgba(255,255,255,.96);box-shadow:0 16px 38px rgba(35,72,58,.14);font-size: var(--astra-font-control);text-align:center;transform:translate(-50%,-50%)}.office-scene__message strong{color:#183f35;font-size: var(--astra-font-emphasis)}.office-scene__message .button{margin-top:5px}
@keyframes office-breathe{to{transform:scale(1.014) translate3d(-.1%,.06%,0)}}
@keyframes sunbeam-drift{to{opacity:.32;transform:translateX(4%) skewX(-12deg)}}
@keyframes ambient-pulse{50%{opacity:.45;transform:scale(.74)}}
@media(max-width:1120px){.office-scene__backdrop{background-size:cover;background-position:center}.office-scene__principle{display:none}}
@media(max-width:720px){.office-scene{min-height:680px}.office-scene__clock{top:12px;right:12px;width:96px;min-height:58px}.office-scene__minimap{right:10px;bottom:56px}.office-scene__backdrop{background-size:auto 100%;background-position:43% center}.office-scene__sunbeam{display:none}}
@media(prefers-reduced-motion:reduce){.office-scene__backdrop,.office-scene__sunbeam,.office-scene__ambient{animation:none!important}}
</style>
