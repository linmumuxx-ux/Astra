import type { WorkspaceEmployee } from '@/features/workspace/eventAdapter'
import { stableEmployeeNumber } from '@/features/workspace/characterAssets'

export interface OfficeIslandLayout {
  id: string
  capacity: 2 | 4 | 8
  employees: Array<WorkspaceEmployee | null>
}

export interface OfficeTeam {
  id: string
  name: string
  order: number
  employees: WorkspaceEmployee[]
  islands: OfficeIslandLayout[]
  working: number
  pending: number
  idle: number
  error: number
}

interface TeamIdentity { id: string; name: string; order: number }

const KNOWN_TEAMS: Array<{ identity: TeamIdentity; match: RegExp; categories: string[] }> = [
  { identity: { id: 'automation', name: '自动化工程', order: 10 }, match: /(自动化|集成|接口)/u, categories: ['automation', 'integration'] },
  { identity: { id: 'testing-platform', name: '测试平台', order: 20 }, match: /(测试平台|平台开发|平台测试)/u, categories: ['testing-platform'] },
  { identity: { id: 'defense-operation', name: '防线运营', order: 30 }, match: /(防线|质量运营|质量保障|安全运营)/u, categories: ['defense-operation', 'incident'] },
]

function fallbackTeamName(role: string): string {
  return role.replace(/(?:数字)?员工$|工程师$|专家$|专员$|开发$|测试$/u, '').trim() || '综合协作'
}

export function officeTeamIdentity(employee: WorkspaceEmployee): TeamIdentity {
  const role = employee.role.trim()
  const categoryIds = employee.employee.category_ids
  const known = KNOWN_TEAMS.find((team) => team.match.test(role))
    ?? KNOWN_TEAMS.find((team) => team.categories.some((id) => categoryIds.includes(id)))
  if (known) return known.identity
  const name = fallbackTeamName(role)
  return { id: `team-${stableEmployeeNumber(name).toString(36)}`, name, order: 100 }
}

function islandCapacities(employeeCount: number): Array<2 | 4 | 8> {
  const capacities: Array<2 | 4 | 8> = []
  let remaining = Math.max(1, employeeCount)
  while (remaining > 8) { capacities.push(8); remaining -= 8 }
  if (remaining <= 2 && capacities.length === 0) capacities.push(2)
  else if (remaining <= 4) capacities.push(4)
  else capacities.push(8)
  return capacities
}

export function composeOfficeIslands(teamId: string, employees: WorkspaceEmployee[]): OfficeIslandLayout[] {
  const ordered = [...employees].sort((left, right) =>
    left.employee.created_at.localeCompare(right.employee.created_at) || left.id.localeCompare(right.id),
  )
  let cursor = 0
  return islandCapacities(ordered.length).map((capacity, index) => {
    const islandEmployees = ordered.slice(cursor, cursor + capacity)
    cursor += capacity
    return {
      id: `${teamId}-island-${index + 1}`,
      capacity,
      employees: [...islandEmployees, ...Array<WorkspaceEmployee | null>(capacity - islandEmployees.length).fill(null)],
    }
  })
}

export function groupOfficeTeams(employees: WorkspaceEmployee[]): OfficeTeam[] {
  const groups = new Map<string, { identity: TeamIdentity; employees: WorkspaceEmployee[] }>()
  for (const team of KNOWN_TEAMS) groups.set(team.identity.id, { identity: team.identity, employees: [] })
  for (const employee of employees) {
    const identity = officeTeamIdentity(employee)
    const group = groups.get(identity.id) ?? { identity, employees: [] }
    group.employees.push(employee)
    groups.set(identity.id, group)
  }

  return [...groups.values()]
    .sort((left, right) => left.identity.order - right.identity.order || left.identity.name.localeCompare(right.identity.name, 'zh-CN'))
    .map(({ identity, employees: members }) => {
      const employees = [...members].sort((left, right) =>
        left.employee.created_at.localeCompare(right.employee.created_at) || left.id.localeCompare(right.id),
      )
      const working = employees.filter((employee) => employee.state === 'WORKING').length
      const pending = employees.filter((employee) => employee.state === 'WAITING' || employee.state === 'NEED_HUMAN').length
      const error = employees.filter((employee) => employee.state === 'ERROR').length
      return {
        ...identity,
        employees,
        islands: composeOfficeIslands(identity.id, employees),
        working,
        pending,
        error,
        idle: Math.max(0, employees.length - working - pending - error),
      }
    })
}
