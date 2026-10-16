<template>
  <span class="astra-form-label">
    <label v-if="forId" :for="forId">{{ label }}</label>
    <span v-else>{{ label }}</span>
    <button
      v-if="help"
      ref="trigger"
      type="button"
      class="astra-form-help"
      :aria-label="`${label}说明`"
      :aria-describedby="visible ? tooltipId : undefined"
      @mouseenter="show"
      @mouseleave="hide"
      @focus="show"
      @blur="hide"
      @keydown.esc.stop="hide"
      @click.prevent.stop
    ><Info :size="14" aria-hidden="true" /></button>
    <Teleport to="body">
      <div v-if="visible && help" :id="tooltipId" ref="tooltip" role="tooltip" class="astra-form-tooltip" :style="position">
        {{ help }}
      </div>
    </Teleport>
  </span>
</template>

<script setup lang="ts">
import { Info } from 'lucide-vue-next'
import { nextTick, onBeforeUnmount, ref, useId } from 'vue'

defineProps<{ label: string; help?: string; forId?: string }>()
const tooltipId = `form-help-${useId()}`
const trigger = ref<HTMLElement | null>(null)
const tooltip = ref<HTMLElement | null>(null)
const visible = ref(false)
const position = ref({ left: '0px', top: '0px', visibility: 'hidden' as 'hidden' | 'visible' })
async function show() {
  visible.value = true
  position.value.visibility = 'hidden'
  await nextTick()
  if (!visible.value || !trigger.value || !tooltip.value) return
  reposition()
  window.addEventListener('scroll', reposition, true)
  window.addEventListener('resize', reposition)
}
function reposition() {
  if (!visible.value || !trigger.value || !tooltip.value) return
  const anchor = trigger.value.getBoundingClientRect()
  if (anchor.bottom < 0 || anchor.top > window.innerHeight) { hide(); return }
  const box = tooltip.value.getBoundingClientRect()
  const left = Math.max(8, Math.min(anchor.left, window.innerWidth - box.width - 8))
  const below = anchor.bottom + 8
  const top = below + box.height <= window.innerHeight - 8 ? below : Math.max(8, anchor.top - box.height - 8)
  position.value = { left: `${left}px`, top: `${top}px`, visibility: 'visible' }
}
function hide() {
  visible.value = false
  window.removeEventListener('scroll', reposition, true)
  window.removeEventListener('resize', reposition)
}
onBeforeUnmount(hide)
</script>

<style scoped>
.astra-form-label { display: inline-flex; align-items: center; gap: 5px; min-width: 0; min-height: 18px; line-height: 18px; }
.astra-form-label > label, .astra-form-label > span { display: inline; margin: 0; padding: 0; color: inherit; font: inherit; }
.astra-form-label > .astra-form-help { display: inline-flex; align-items: center; justify-content: center; flex: none; width: 18px; height: 18px; min-height: 0; margin: 0; padding: 0; color: var(--astra-text-muted); border: 0; border-radius: 3px; background: transparent; cursor: help; line-height: 1; }
.astra-form-help:hover, .astra-form-help:focus-visible { color: var(--astra-primary); }
.astra-form-help:focus-visible { outline: 2px solid var(--astra-primary-border); outline-offset: 2px; }
.astra-form-tooltip { position: fixed; z-index: 2000; width: max-content; max-width: min(360px, calc(100vw - 16px)); max-height: calc(100vh - 16px); padding: 10px 12px; color: var(--astra-text-primary); border: 1px solid var(--astra-border); border-radius: 8px; background: var(--astra-bg-panel); box-shadow: var(--astra-shadow-panel); font: var(--astra-weight-regular) var(--astra-font-body)/1.6 var(--astra-font-family); white-space: pre-wrap; overflow-wrap: anywhere; pointer-events: none; }
</style>
