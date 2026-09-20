#!/usr/bin/env node
import { spawnSync } from "node:child_process"
import { fileURLToPath } from "node:url"
import path from "node:path"

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..")
const workspace = path.join(root, "workspace-ui")
const action = process.argv[2]
if (!["install", "build", "type-check"].includes(action)) {
  console.error("Usage: node scripts/workspace_ui.mjs <install|build|type-check>")
  process.exit(2)
}

const windows = process.platform === "win32"
const candidates = windows
  ? [
      { command: "pnpm.cmd", prefix: [] },
      { command: "corepack.cmd", prefix: ["pnpm"] },
      { command: "bun.exe", prefix: [] },
      { command: "bun.cmd", prefix: [] },
    ]
  : [
      { command: "pnpm", prefix: [] },
      { command: "corepack", prefix: ["pnpm"] },
      { command: "bun", prefix: [] },
    ]

function run(candidate, args, options = {}) {
  return spawnSync(candidate.command, [...candidate.prefix, ...args], {
    cwd: workspace,
    stdio: options.stdio ?? "inherit",
    shell: windows,
    env: process.env,
  })
}

let manager = null
for (const candidate of candidates) {
  const probe = run(candidate, ["--version"], { stdio: "ignore" })
  if (probe.status === 0) {
    manager = candidate
    break
  }
}
if (!manager) {
  console.error("workspace-ui requires pnpm (preferred) or bun")
  process.exit(1)
}

const isBun = manager.command.startsWith("bun")
const args =
  action === "install"
    ? ["install"]
    : isBun
      ? ["run", action]
      : ["run", action]

console.log(`[workspace-ui] ${manager.command} ${[...manager.prefix, ...args].join(" ")}`)
const result = run(manager, args)
process.exit(result.status ?? 1)
