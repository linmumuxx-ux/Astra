import { describe, expect, test } from "bun:test"
import { configureWorkspaceCapabilities, workspaceCapabilities } from "./workspace-capabilities"

describe("workspace capabilities", () => {
  test("defaults to session management enabled", () => {
    expect(workspaceCapabilities.sessionManagementEnabled).toBe(true)
    expect(workspaceCapabilities.humanReplyEnabled).toBe(true)
  })

  test("disables session management and can be reset", () => {
    configureWorkspaceCapabilities({ sessionManagementEnabled: false })
    expect(workspaceCapabilities.sessionManagementEnabled).toBe(false)

    configureWorkspaceCapabilities({ sessionManagementEnabled: true })
    expect(workspaceCapabilities.sessionManagementEnabled).toBe(true)
  })
})