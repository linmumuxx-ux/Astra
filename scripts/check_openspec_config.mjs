#!/usr/bin/env node
// Guards openspec/config.yaml against the two failure modes that are invisible
// in review:
//
//   1. a top-level key the bundled CLI never reads (it is dropped silently), and
//   2. a `rules` key that is not a valid artifact ID of the configured schema
//      (the CLI only prints a warning and ignores it).
//
// Both produce a config that looks correct in the diff but constrains nothing.
// The check drives the real CLI rather than re-implementing its parser, so it
// tracks whatever bundle is committed in .opencode/tools/openspec.mjs.

import { spawnSync } from "node:child_process"
import { readFileSync, rmSync } from "node:fs"
import path from "node:path"
import { fileURLToPath } from "node:url"

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..")
const cli = path.join(root, ".opencode", "tools", "openspec.mjs")

// Mirrors the bundled CLI's ProjectConfigSchema.
const SUPPORTED_KEYS = ["schema", "context", "rules"]

const run = (args) => {
  const result = spawnSync(process.execPath, [cli, ...args], {
    cwd: root,
    encoding: "utf8",
  })
  if (result.status !== 0) {
    console.error(`openspec CLI failed: ${args.join(" ")}`)
    process.stderr.write(result.stderr || "")
    process.exit(1)
  }
  return result.stdout
}

const probeName = "config-check-probe"
const probeDir = path.join(root, "openspec", "changes", probeName)

// Clear first: a previous aborted run must not make this check fail with a
// "change already exists" error that hides the real config problem.
rmSync(probeDir, { recursive: true, force: true })
run(["new", "change", probeName])

const status = JSON.parse(run(["status", "--change", probeName, "--json"]))
const schemaName = status.schemaName

// The instructions payload is how the CLI surfaces a parsed `context`, so a
// missing field here means the whole file failed to load.
const template = JSON.parse(
  run(["instructions", "proposal", "--change", probeName, "--json"]),
)
if (template.context === undefined || template.context === null) {
  console.error("openspec/config.yaml: CLI did not pick up a `context` field")
  process.exit(1)
}

const raw = readFileSync(path.join(root, "openspec", "config.yaml"), "utf8")
const topLevelKeys = raw
  .split("\n")
  .filter((line) => /^[A-Za-z_][\w-]*\s*:/.test(line))
  .map((line) => line.match(/^([A-Za-z_][\w-]*)/)[1])
const unknown = topLevelKeys.filter((key) => !SUPPORTED_KEYS.includes(key))
if (unknown.length) {
  console.error(
    `openspec/config.yaml: unsupported top-level key(s) the bundled CLI ignores: ${unknown.join(", ")}`,
  )
  process.exit(1)
}

// Artifact ID audit: an unknown `rules` key only produces a CLI warning.
const ruleKeys = raw
  .split("\n")
  .map((line) => line.match(/^ {2}([A-Za-z_][\w-]*)\s*:\s*$/))
  .filter(Boolean)
  .map((match) => match[1])
const validIds = new Set(status.artifacts.map((artifact) => artifact.id))
const badIds = ruleKeys.filter((key) => !validIds.has(key))
if (badIds.length) {
  console.error(
    `openspec/config.yaml: rules key(s) not an artifact of schema "${schemaName}": ` +
      `${badIds.join(", ")} (valid: ${[...validIds].sort().join(", ")})`,
  )
  process.exit(1)
}

for (const artifactId of validIds) {
  const instructions = JSON.parse(
    run(["instructions", artifactId, "--change", probeName, "--json"]),
  )
  const rules = instructions.rules || []
  for (const rule of rules) {
    if (typeof rule !== "string" || rule.trim() === "") {
      console.error(`openspec/config.yaml: rules.${artifactId} contains a non-string or empty rule`)
      process.exit(1)
    }
  }
}

rmSync(probeDir, { recursive: true, force: true })

console.log(`ok: openspec/config.yaml applies to schema "${schemaName}" (${ruleKeys.length} rule groups)`)
