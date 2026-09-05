<template>
  <section
    :id="`team-${team.id}`"
    class="team-zone"
    :class="[`team-zone--${team.id}`, { 'team-zone--active': focused || (selectedId && team.employees.some((employee) => employee.id === selectedId)) }]"
    :style="{ '--zone-index': zoneIndex }"
    :data-testid="`team-zone-${team.id}`"
    :aria-label="`${team.name}团队办公区`"
  >
    <button class="team-zone__marker" type="button" :aria-label="`${team.name}，${team.employees.length} 人`" @click="emit('focus', team.id)">
      <span class="team-zone__icon"><component :is="teamIcon" :size="19" /></span>
      <span><strong>{{ team.name }}</strong><small>{{ team.employees.length }} 人 · {{ Math.max(1, team.islands.length) }} 组</small></span>
      <em v-if="team.error" data-tone="danger"><i />{{ team.error }} 异常</em>
      <em v-else-if="team.pending" data-tone="warning"><i />{{ team.pending }} 待处理</em>
      <em v-else><i />{{ team.working }} 工作中</em>
    </button>

    <div class="team-zone__islands">
      <OfficeIsland
        v-for="island in team.islands"
        :key="island.id"
        :island="island"
        :selected-id="selectedId"
        :query="query"
        :matched-ids="matchedIds"
        :bubble-modes="bubbleModes"
        @select="emit('select', $event)"
      />
    </div>
    <span v-if="hiddenCount" class="team-zone__more">+{{ hiddenCount }}</span>
  </section>
</template>

<script setup lang="ts">
import { Blocks, ChartNoAxesCombined, ShieldCheck } from 'lucide-vue-next'
import { computed } from 'vue'
import OfficeIsland from '@/components/office/OfficeIsland.vue'
import type { OfficeTeam } from '@/features/office/officeLayout'

type BubbleMode = 'alert'
const props = withDefaults(defineProps<{
  team: OfficeTeam
  zoneIndex?: number
  focused?: boolean
  selectedId?: string
  query?: string
  matchedIds: Set<string>
  bubbleModes: Map<string, BubbleMode>
}>(), { zoneIndex: 0, focused: false, selectedId: '', query: '' })
const emit = defineEmits<{ select: [id: string]; focus: [teamId: string] }>()
const teamIcon = computed(() => props.team.id === 'automation'
  ? ChartNoAxesCombined
  : props.team.id === 'defense-operation' ? ShieldCheck : Blocks)
const hiddenCount = computed(() => Math.max(0, props.team.employees.length - 6))
</script>

<style scoped>
.team-zone{position:absolute;z-index:4;width:36%;height:29%;transition:filter .22s ease,transform .22s ease}.team-zone--automation{top:21%;left:6%;width:39%}.team-zone--testing-platform{top:54%;left:5%;width:36%}.team-zone--defense-operation{top:44%;right:7%;width:35%}.team-zone:not(.team-zone--automation):not(.team-zone--testing-platform):not(.team-zone--defense-operation){top:calc(18% + var(--zone-index) * 9%);left:calc(42% + var(--zone-index) * 2%);width:28%}.team-zone--active{z-index:12;filter:drop-shadow(0 8px 18px rgba(23,163,105,.22));transform:translateY(-3px)}
.team-zone__marker{position:absolute;z-index:40;top:-3px;left:0;display:inline-flex;align-items:center;gap:9px;min-width:162px;min-height:56px;padding:8px 12px 8px 8px;color:#fff;text-align:left;border:1px solid rgba(255,255,255,.62);border-radius:11px;background:linear-gradient(135deg,rgba(55,186,151,.8),rgba(94,198,171,.7));box-shadow:0 8px 22px rgba(40,137,108,.14),inset 0 1px rgba(255,255,255,.42);backdrop-filter:blur(8px);cursor:pointer;transition:transform .18s ease,box-shadow .18s ease}.team-zone__marker:hover{box-shadow:0 11px 28px rgba(40,137,108,.2),inset 0 1px rgba(255,255,255,.45);transform:translateY(-2px)}.team-zone__marker:focus-visible{outline:3px solid rgba(255,255,255,.95);outline-offset:2px}.team-zone__icon{display:grid;place-items:center;width:35px;height:35px;border-radius:9px;background:rgba(255,255,255,.16)}.team-zone__marker>span:nth-child(2){display:grid;min-width:84px}.team-zone__marker strong{font-size:14px;line-height:1.15}.team-zone__marker small{margin-top:3px;color:rgba(255,255,255,.85);font-size:9px}.team-zone__marker em{position:absolute;top:calc(100% + 9px);left:calc(100% + 20px);display:flex;align-items:center;gap:5px;width:max-content;padding:6px 9px;color:#237c5f;border:1px solid rgba(211,228,221,.9);border-radius:8px;background:rgba(255,255,255,.94);box-shadow:0 7px 18px rgba(43,80,66,.11);font-size:8px;font-style:normal}.team-zone__marker em i{width:6px;height:6px;border-radius:50%;background:#24b886}.team-zone__marker em[data-tone='warning']{color:#a36a22}.team-zone__marker em[data-tone='warning'] i{background:#f2a12a}.team-zone__marker em[data-tone='danger']{color:#c44950}.team-zone__marker em[data-tone='danger'] i{background:#ef4f57}
.team-zone__islands{position:absolute;inset:23% 0 0 12%;display:flex;align-items:flex-end;gap:2px}.team-zone__islands :deep(.office-island:nth-child(n+2)){position:absolute;width:0;height:0;overflow:visible}.team-zone__islands :deep(.office-island:nth-child(n+2) .employee-seat){display:none}.team-zone__more{position:absolute;z-index:30;right:4%;bottom:10%;display:grid;place-items:center;min-width:31px;height:31px;padding:0 8px;color:#14855e;border:2px solid rgba(255,255,255,.9);border-radius:17px;background:rgba(231,248,240,.94);box-shadow:0 7px 16px rgba(38,92,71,.13);font-size:10px;font-weight:800}
.team-zone--testing-platform .team-zone__marker{top:6%;left:0}.team-zone--defense-operation .team-zone__marker{top:2%;left:50%;transform:translateX(-18%)}.team-zone--defense-operation .team-zone__islands{inset:23% 4% 0 0}.team-zone--defense-operation .team-zone__more{right:-1%}
@media(max-width:1120px){.team-zone{width:44%}.team-zone--automation{top:20%;left:1%;width:46%}.team-zone--testing-platform{top:56%;left:1%;width:44%}.team-zone--defense-operation{top:44%;right:1%;width:44%}.team-zone__marker{transform:scale(.84);transform-origin:left top}.team-zone--defense-operation .team-zone__marker{transform:translateX(-18%) scale(.84)}}
@media(max-width:720px){.team-zone__marker{min-width:142px;transform:scale(.74);transform-origin:left top}.team-zone--automation{top:21%;left:-3%;width:55%}.team-zone--testing-platform{top:57%;left:-4%;width:57%}.team-zone--defense-operation{top:42%;right:-5%;width:56%}.team-zone--defense-operation .team-zone__marker{left:42%;transform:translateX(-18%) scale(.74)}.team-zone__marker em{display:none}.team-zone__more{transform:scale(.8)}}
</style>
