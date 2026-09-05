<template>
  <div class="biz-card" :class="`biz-card--${card.card_type ?? 'generic'}`">
    <header class="biz-card__head">
      <component :is="icon" :size="15" class="biz-card__icon" />
      <div class="biz-card__title">
        <strong>{{ card.title }}</strong>
        <small v-if="card.id">{{ card.id }}</small>
      </div>
      <span class="biz-card__status" :class="`status--${(card.status || '').toLowerCase()}`">
        {{ card.status_label || card.status }}
      </span>
    </header>
    <dl class="biz-card__fields">
      <div v-for="field in card.fields ?? []" :key="field.label">
        <dt>{{ field.label }}</dt>
        <dd>{{ field.value }}</dd>
      </div>
    </dl>
    <footer v-if="card.actions?.length" class="biz-card__actions">
      <template v-for="action in card.actions" :key="action.label">
        <RouterLink
          v-if="action.type === 'navigate' && action.target"
          class="biz-card__action"
          :to="action.target"
        >{{ action.label }}</RouterLink>
        <button
          v-else-if="action.type === 'assistant_operation'"
          class="biz-card__action biz-card__action--op"
          type="button"
          @click="emit('operation', action, card)"
        >{{ action.label }}</button>
      </template>
    </footer>
  </div>
</template>

<script setup lang="ts">
import { Bot, ClipboardList, FileText, History } from 'lucide-vue-next'
import { computed } from 'vue'
import { RouterLink } from 'vue-router'
import type { AssistantCardAction, AssistantCardPayload } from '../types'

const props = defineProps<{ card: AssistantCardPayload }>()
const emit = defineEmits<{ operation: [action: AssistantCardAction, card: AssistantCardPayload] }>()

const icon = computed(() =>
  props.card.card_type === 'task'
    ? ClipboardList
    : props.card.card_type === 'employee'
      ? Bot
      : props.card.card_type === 'run'
        ? History
        : FileText,
)
</script>

<style scoped>
.biz-card {
  border: 1px solid var(--astra-border);
  border-radius: 12px;
  background: var(--astra-bg-card);
  padding: 12px 14px;
  display: grid;
  gap: 10px;
  max-width: 340px;
}
.biz-card__head {
  display: flex;
  align-items: center;
  gap: 8px;
}
.biz-card__icon { color: var(--astra-primary); flex-shrink: 0; }
.biz-card__title { min-width: 0; flex: 1; }
.biz-card__title strong {
  display: block;
  font-size: var(--astra-font-emphasis);
  color: var(--astra-text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.biz-card__title small { color: var(--astra-text-muted); font-size: var(--astra-font-helper); }
.biz-card__status {
  font-size: var(--astra-font-helper);
  padding: 2px 8px;
  border-radius: 999px;
  background: var(--astra-primary-soft);
  color: var(--astra-primary-bright);
  white-space: nowrap;
}
.biz-card__status.status--failed,
.biz-card__status.status--execution_error,
.biz-card__status.status--cancelled,
.biz-card__status.status--error {
  background: var(--astra-danger-soft);
  color: var(--astra-danger);
}
.biz-card__status.status--wait_human,
.biz-card__status.status--suspended,
.biz-card__status.status--paused {
  background: var(--astra-warning-soft);
  color: var(--astra-warning);
}
.biz-card__fields {
  display: grid;
  gap: 4px;
  margin: 0;
}
.biz-card__fields div {
  display: grid;
  grid-template-columns: 72px 1fr;
  gap: 8px;
  font-size: var(--astra-font-body);
}
.biz-card__fields dt { color: var(--astra-text-muted); }
.biz-card__fields dd {
  margin: 0;
  color: var(--astra-text-secondary);
  word-break: break-all;
}
.biz-card__actions { display: flex; flex-wrap: wrap; gap: 8px; }
.biz-card__action {
  font-size: var(--astra-font-control);
  padding: 4px 12px;
  border-radius: 8px;
  border: 1px solid var(--astra-primary-border);
  color: var(--astra-primary-bright);
  background: var(--astra-primary-soft);
  text-decoration: none;
  cursor: pointer;
}
.biz-card__action--op {
  border-color: var(--astra-border);
  color: var(--astra-text-secondary);
  background: transparent;
}
.biz-card__action:hover { border-color: var(--astra-border-hover); }
</style>
