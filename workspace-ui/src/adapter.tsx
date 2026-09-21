import { render } from 'solid-js/web'
import { HashRouter } from '@solidjs/router'
import {
  AppBaseProviders,
  AppInterface,
  configureWorkspaceCapabilities,
  PlatformProvider,
  ServerConnection,
  type Platform,
} from '@opencode-ai/app'
import { base64Encode } from '@opencode-ai/core/util/encode'

// Only binding belongs here. Conversation, tools, files, diff, composer and theme are upstream;
// Astra must not restyle the OpenCode surface.
const taskID = new URLSearchParams(location.search).get('task')
const selected = new URLSearchParams(location.search).get('session')
const root = document.getElementById('root')!

async function boot() {
  if (!taskID) throw new Error('缺少 Task ID')
  const response = await fetch(`/api/tasks/${encodeURIComponent(taskID)}/workspace${selected ? `?session_id=${encodeURIComponent(selected)}` : ""}`)
  const binding = await response.json()
  if (!response.ok) throw new Error(binding.detail)
  const sessionID = selected || binding.runtime.session_id
  if (!sessionID) throw new Error('任务尚未绑定 OpenCode Session')
  if (!binding.sessions.some((session: { id: string }) => session.id === sessionID)) throw new Error('Session 不属于此任务')
  const endpoint = `${location.origin}${binding.runtime.server}/${encodeURIComponent(sessionID)}`
  const server: ServerConnection.Http = { type: 'http', http: { url: endpoint } }
  location.hash = `/${base64Encode(binding.runtime.workspace)}/session/${sessionID}`
  const platform: Platform = {
    platform: 'web', version: '1.18.31',
    fetch: (input, init) => {
      const url = new URL(input instanceof Request ? input.url : String(input), location.origin)
      // Upstream probes absolute health URLs; keep them within the task-bound transport.
      if (url.origin === location.origin && ['/global/health', '/api/health'].includes(url.pathname)) {
        return fetch(endpoint + '/global/health', init)
      }
      return fetch(input, init)
    },
    openExternal: url => { window.open(url, '_blank', 'noopener,noreferrer') },
    restart: async () => location.reload(),
    notify: async () => {},
    // Isolate persisted upstream preferences and server selection per task.
    storage: name => ({
      getItem: key => localStorage.getItem(`${taskID}:${name}:${key}`),
      setItem: (key, value) => localStorage.setItem(`${taskID}:${name}:${key}`, value),
      removeItem: key => localStorage.removeItem(`${taskID}:${name}:${key}`),
    }),
  }
  // Astra owns session creation and lifecycle: the embedded workspace only shows the bound session.
  configureWorkspaceCapabilities({ sessionManagementEnabled: false })
  render(() => <PlatformProvider value={platform}><AppBaseProviders><AppInterface
    defaultServer={ServerConnection.Key.make(endpoint)} servers={[server]} router={HashRouter}
  ></AppInterface></AppBaseProviders></PlatformProvider>, root)
}
boot().catch(error => { root.textContent = String(error.message || error) })
