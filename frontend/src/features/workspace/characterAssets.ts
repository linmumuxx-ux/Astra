import type { CharacterPose } from '@/features/workspace/sceneLayout'

const CHARACTER_COLUMNS = 4
const CHARACTER_ROWS = 3
const CHARACTER_COUNT = CHARACTER_COLUMNS * CHARACTER_ROWS

export function stableEmployeeNumber(id: string): number {
  return [...id].reduce((total, character) => ((total * 31) + character.charCodeAt(0)) >>> 0, 7)
}

export function employeeCharacterIndex(id: string): number {
  return stableEmployeeNumber(id) % CHARACTER_COUNT
}

export function employeeCharacterStyle(id: string, pose: CharacterPose): Record<string, string> {
  const index = employeeCharacterIndex(id)
  const column = index % CHARACTER_COLUMNS
  const row = Math.floor(index / CHARACTER_COLUMNS)
  return {
    '--character-atlas': `url('/assets/characters/nexus-team-${pose}-v3.png')`,
    '--sprite-x': `${(column / (CHARACTER_COLUMNS - 1)) * 100}%`,
    '--sprite-y': `${(row / (CHARACTER_ROWS - 1)) * 100}%`,
  }
}
