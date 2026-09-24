<template>
  <section class="service-status-card" :data-state="state">
    <div class="service-status-card__row">
      <div class="service-status-card__icon" :data-state="state">
        <AlertTriangle v-if="state === 'error'" :size="17" />
        <RefreshCw v-else-if="state === 'checking'" :size="17" class="spin" />
        <CircleCheck v-else :size="17" />
      </div>
      <div class="service-status-card__copy">
        <strong>{{ title }}</strong>
        <p>{{ message }}</p>
        <span v-if="detail" class="service-status-card__detail">{{ detail }}</span>
      </div>
      <div class="service-status-card__actions">
        <el-button v-if="syncable" type="warning" plain size="small" :loading="syncing" :disabled="syncing" @click="$emit('sync')">
          {{ syncing ? '同步中…' : '立即同步' }}
        </el-button>
        <el-button v-if="recheckable" size="small" :loading="checking" :disabled="checking" @click="$emit('recheck')">
          重新检测
        </el-button>
        <el-button v-if="rawError" size="small" @click="expanded = !expanded">
          {{ expanded ? '收起详情' : '查看详情' }}
        </el-button>
      </div>
    </div>
    <div v-if="expanded && rawError" class="service-status-card__error">
      <dl>
        <div v-if="endpoint"><dt>Endpoint</dt><dd>{{ endpoint }}</dd></div>
        <div v-if="httpCode"><dt>HTTP Code</dt><dd>{{ httpCode }}</dd></div>
        <div v-if="timestamp"><dt>Timestamp</dt><dd>{{ timestamp }}</dd></div>
      </dl>
      <pre>{{ rawError }}</pre>
    </div>
  </section>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { AlertTriangle, CircleCheck, RefreshCw } from 'lucide-vue-next'

defineProps<{
  title: string
  state: 'ok' | 'error' | 'checking' | 'unknown'
  message: string
  detail?: string | null
  endpoint?: string | null
  httpCode?: number | null
  rawError?: string | null
  timestamp?: string | null
  recheckable?: boolean
  syncable?: boolean
  checking?: boolean
  syncing?: boolean
}>()
const emit = defineEmits<{ (e: 'recheck'): void; (e: 'sync'): void }>()
const expanded = ref(false)
</script>

<style scoped>
.service-status-card {
  display: grid;
  gap: 12px;
  padding: 13px 14px;
  border: 1px solid var(--astra-border);
  border-radius: 10px;
  background: var(--astra-bg-panel);
}
.service-status-card[data-state='error'] { border-color: rgba(255, 111, 125, 0.26); background: var(--astra-danger-soft); }
.service-status-card[data-state='checking'] { border-color: var(--astra-primary-border); background: var(--astra-primary-soft); }
.service-status-card__row { display: flex; align-items: center; gap: 11px; }
.service-status-card__icon {
  display: grid; place-items: center; flex: none;
  width: 33px; height: 33px; border-radius: 9px;
  color: var(--astra-success); background: var(--astra-success-soft);
}
.service-status-card__icon[data-state='error'] { color: var(--astra-danger); background: var(--astra-danger-soft); }
.service-status-card__icon[data-state='checking'] { color: var(--astra-primary-bright); background: var(--astra-primary-soft); }
.service-status-card__copy { display: grid; min-width: 0; gap: 2px; margin-right: auto; }
.service-status-card__copy strong { font-size: var(--astra-font-control); }
.service-status-card__copy p { margin: 0; color: var(--astra-text-secondary); font-size: var(--astra-font-helper); }
.service-status-card__detail { color: var(--astra-text-muted); font-size: var(--astra-font-helper); }
.service-status-card__actions { display: flex; align-items: center; gap: 7px; flex-wrap: wrap; }
.service-status-card__error { padding-top: 10px; border-top: 1px solid rgba(27, 48, 73, 0.5); }
.service-status-card__error dl { display: grid; gap: 6px; margin: 0 0 8px; }
.service-status-card__error dl > div { display: flex; gap: 8px; }
.service-status-card__error dt { min-width: 86px; color: var(--astra-text-muted); font-size: var(--astra-font-helper); }
.service-status-card__error dd { margin: 0; color: var(--astra-text-secondary); font-size: var(--astra-font-helper); word-break: break-all; }
.service-status-card__error pre {
  max-height: 160px; margin: 0; padding: 10px 12px; overflow: auto;
  color: #a9c1dd; border-radius: 8px; background: #050c15;
  font: var(--astra-font-helper)/1.5 var(--astra-font-family); white-space: pre-wrap; word-break: break-word;
}
</style>
