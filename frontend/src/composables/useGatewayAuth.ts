import { computed, ref } from 'vue'
import {
  clearGatewayToken,
  gatewayApi,
  getGatewayToken,
  setGatewayToken,
  type GatewayPermissions,
} from '@/api/gateway'

// 控制面凭据会话为单例：所有页面共享同一份已校验身份，凭据只存 sessionStorage 或内存。
const permissions = ref<GatewayPermissions | null>(null)
const connecting = ref(false)
const checking = ref(false)
const authError = ref('')
let loadedToken = ''

export function useGatewayAuth() {
  const authorized = computed(() => permissions.value !== null)
  const actor = computed(() => permissions.value?.actor ?? '')
  const roles = computed(() => permissions.value?.roles ?? [])

  async function connect(rawToken: string): Promise<boolean> {
    const token = rawToken.trim()
    if (!token) {
      authError.value = '请输入管理凭据'
      return false
    }
    connecting.value = true
    authError.value = ''
    try {
      setGatewayToken(token)
      permissions.value = await gatewayApi.permissions()
      loadedToken = token
      return true
    } catch (error) {
      clearGatewayToken()
      permissions.value = null
      loadedToken = ''
      authError.value = error instanceof Error ? error.message : '凭据校验失败'
      return false
    } finally {
      connecting.value = false
    }
  }

  async function ensureLoaded(): Promise<void> {
    const token = getGatewayToken()
    if (!token) {
      permissions.value = null
      return
    }
    if (permissions.value && loadedToken === token) return
    checking.value = true
    try {
      permissions.value = await gatewayApi.permissions()
      loadedToken = token
      authError.value = ''
    } catch (error) {
      permissions.value = null
      loadedToken = ''
      authError.value = error instanceof Error ? error.message : '凭据已失效，请重新输入'
    } finally {
      checking.value = false
    }
  }

  function disconnect(): void {
    clearGatewayToken()
    permissions.value = null
    loadedToken = ''
    authError.value = ''
  }

  function hasRole(role: string): boolean {
    const current = permissions.value
    if (!current) return false
    return current.roles.includes(role) || current.roles.includes('system')
  }

  return {
    permissions,
    authorized,
    actor,
    roles,
    connecting,
    checking,
    authError,
    connect,
    ensureLoaded,
    disconnect,
    hasRole,
  }
}