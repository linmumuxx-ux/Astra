<template>
  <section class="gateway-connect" data-testid="gateway-connect">
    <div class="gateway-connect__card">
      <div class="gateway-connect__head">
        <span class="gateway-connect__icon"><LockKeyhole :size="20" /></span>
        <div>
          <strong>API 中转控制面</strong>
          <p>控制面凭据由你在当前会话输入，只保存在 sessionStorage，不写入构建产物、不内置默认管理员 Token。</p>
        </div>
      </div>
      <form @submit.prevent="submit">
        <label class="gateway-field">
          <span>管理凭据（Bearer）</span>
          <div class="gateway-token">
            <input
              v-model="input"
              :type="reveal ? 'text' : 'password'"
              autocomplete="off"
              spellcheck="false"
              placeholder="粘贴部署环境提供的管理 Token"
            />
            <button type="button" :aria-label="reveal ? '隐藏凭据' : '显示凭据'" @click="reveal = !reveal">
              <EyeOff v-if="reveal" :size="15" /><Eye v-else :size="15" />
            </button>
          </div>
        </label>
        <p v-if="authError" class="gateway-connect__error"><TriangleAlert :size="14" />{{ authError }}</p>
        <button class="button button--primary" type="submit" :disabled="connecting">
          <LoaderCircle v-if="connecting" :size="15" class="spin" />{{ connecting ? '校验中…' : '连接控制面' }}
        </button>
      </form>
      <small>需要 view 只读角色，写操作还需 node / route / key / publish 角色；system 等价于全部权限。</small>
    </div>
  </section>
</template>

<script setup lang="ts">
import { Eye, EyeOff, LoaderCircle, LockKeyhole, TriangleAlert } from 'lucide-vue-next'
import { ref } from 'vue'
import { useGatewayAuth } from '@/composables/useGatewayAuth'

const emit = defineEmits<{ connected: [] }>()
const { connect, connecting, authError } = useGatewayAuth()
const input = ref('')
const reveal = ref(false)

async function submit() {
  if (await connect(input.value)) emit('connected')
}
</script>

<style scoped>
.gateway-connect { display: grid; place-items: center; min-height: 60vh; padding: 24px 0; }
.gateway-connect__card { width: min(520px, 100%); padding: 24px; border: 1px solid var(--astra-border); border-radius: 16px; background: var(--astra-bg-card); box-shadow: var(--astra-shadow-panel); }
.gateway-connect__head { display: flex; align-items: flex-start; gap: 12px; margin-bottom: 18px; }
.gateway-connect__icon { display: grid; place-items: center; flex: none; width: 42px; height: 42px; color: var(--astra-primary-bright); border-radius: 12px; background: var(--astra-primary-soft); }
.gateway-connect__head strong { color: var(--astra-text-primary); font-size: var(--astra-font-subtitle); }
.gateway-connect__head p { margin: 5px 0 0; color: var(--astra-text-muted); font-size: var(--astra-font-helper); line-height: 1.6; }
.gateway-field { display: grid; gap: 7px; margin-bottom: 14px; color: var(--astra-text-secondary); font-size: var(--astra-font-control); }
.gateway-token { display: flex; align-items: center; gap: 8px; height: var(--astra-control-height); padding: 0 10px; border: 1px solid var(--astra-border); border-radius: 9px; background: var(--astra-bg-base); }
.gateway-token:focus-within { border-color: var(--astra-primary-border); background: #fff; }
.gateway-token input { flex: 1; min-width: 0; height: 100%; color: var(--astra-text-primary); border: 0; outline: 0; background: transparent; }
.gateway-token button { display: grid; place-items: center; width: 26px; height: 26px; color: var(--astra-text-muted); border: 0; border-radius: 6px; background: transparent; cursor: pointer; }
.gateway-token button:hover { color: var(--astra-primary-bright); background: var(--astra-primary-soft); }
.gateway-connect__error { display: flex; align-items: center; gap: 6px; margin: 0 0 12px; padding: 9px 11px; color: var(--astra-danger); border: 1px solid rgba(228, 93, 106, .2); border-radius: 8px; background: var(--astra-danger-soft); font-size: var(--astra-font-helper); }
.gateway-connect__card button[type='submit'] { width: 100%; }
.gateway-connect__card > small { display: block; margin-top: 14px; color: var(--astra-text-muted); font-size: var(--astra-font-micro); line-height: 1.6; }
</style>