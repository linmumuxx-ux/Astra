// Host capability switch for the vendored OpenCode app.
//
// Two hosts share this source tree:
//   - standalone OpenCode: session management stays enabled (default true)
//   - Astra task workspace: Astra owns session creation and lifecycle, so the
//     embedded workspace must not create, close, archive or fork sessions
//
// Keep this module the single source of truth. UI controls and commands must
// consult it instead of hiding controls with host-specific CSS.
export type WorkspaceCapabilities = {
  sessionManagementEnabled: boolean
  /** When false, question/permission docks are status-only; replies go through digital-employee chat. */
  humanReplyEnabled: boolean
}

export const workspaceCapabilities: WorkspaceCapabilities = {
  sessionManagementEnabled: true,
  humanReplyEnabled: true,
}

export function configureWorkspaceCapabilities(next: Partial<WorkspaceCapabilities>): void {
  Object.assign(workspaceCapabilities, next)
}
