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

/** Give each employee a distinct portrait until the complete atlas is in use. */
export function assignEmployeeCharacterIndices(ids: string[]): Map<string, number> {
  const result = new Map<string, number>()
  const claimed = new Set<number>()
  const orderedIds = [...new Set(ids)].sort((left, right) =>
    stableEmployeeNumber(left) - stableEmployeeNumber(right) || left.localeCompare(right),
  )

  for (const id of orderedIds) {
    const preferred = employeeCharacterIndex(id)
    let index = preferred
    if (claimed.size < CHARACTER_COUNT) {
      while (claimed.has(index)) index = (index + 1) % CHARACTER_COUNT
      claimed.add(index)
    }
    result.set(id, index)
  }
  return result
}

export function employeeCharacterStyle(id: string, pose: CharacterPose, assignedIndex?: number): Record<string, string> {
  const index = assignedIndex ?? employeeCharacterIndex(id)
  const column = index % CHARACTER_COLUMNS
  const row = Math.floor(index / CHARACTER_COLUMNS)
  return {
    '--character-atlas': `url('/assets/characters/nexus-team-${pose}-${pose === 'seated' ? 'v4' : 'v3'}.png')`,
    '--sprite-x': `${(column / (CHARACTER_COLUMNS - 1)) * 100}%`,
    '--sprite-y': `${(row / (CHARACTER_ROWS - 1)) * 100}%`,
  }
}
