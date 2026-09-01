export const WORKSPACE_AREA_IDS = [
  'development',
  'collaboration',
  'pantry',
  'integration',
  'meeting',
  'special',
] as const

export type WorkspaceAreaId = (typeof WORKSPACE_AREA_IDS)[number]
export type CharacterPose = 'standing' | 'seated'

export interface SceneSlot {
  id: string
  x: number
  y: number
  scale: number
  depth: number
  pose: CharacterPose
  minSceneWidth?: number
}

export interface WorkspaceArea {
  id: WorkspaceAreaId
  name: string
  shortName: string
  labelX: number
  labelY: number
  aggregateX: number
  aggregateY: number
  slots: SceneSlot[]
}

export const workspaceAreas: WorkspaceArea[] = [
  {
    id: 'development', name: '开发办公区', shortName: '开发办公区', labelX: 15, labelY: 18, aggregateX: 29, aggregateY: 20,
    slots: [
      { id: 'dev-1', x: 13, y: 44, scale: 9.4, depth: 42, pose: 'seated' },
      { id: 'dev-2', x: 28, y: 49, scale: 9.8, depth: 48, pose: 'seated' },
      { id: 'dev-3', x: 20, y: 54, scale: 9.8, depth: 53, pose: 'standing' },
      { id: 'dev-4', x: 35, y: 43, scale: 8.9, depth: 41, pose: 'standing' },
      { id: 'dev-5', x: 7.5, y: 51, scale: 8.8, depth: 50, pose: 'standing', minSceneWidth: 980 },
    ],
  },
  {
    id: 'collaboration', name: '协作讨论区', shortName: '协作讨论区', labelX: 43, labelY: 14, aggregateX: 53, aggregateY: 12,
    slots: [
      { id: 'collab-1', x: 36.5, y: 32, scale: 9.1, depth: 31, pose: 'standing' },
      { id: 'collab-2', x: 46, y: 37, scale: 9.4, depth: 36, pose: 'seated' },
      { id: 'collab-3', x: 54, y: 30, scale: 8.8, depth: 29, pose: 'standing', minSceneWidth: 960 },
    ],
  },
  {
    id: 'pantry', name: '茶水间', shortName: '茶水间', labelX: 70, labelY: 11, aggregateX: 85, aggregateY: 14,
    slots: [
      { id: 'pantry-1', x: 69, y: 34, scale: 9.2, depth: 33, pose: 'standing' },
      { id: 'pantry-2', x: 84, y: 31, scale: 8.8, depth: 30, pose: 'standing', minSceneWidth: 940 },
    ],
  },
  {
    id: 'integration', name: '集成区', shortName: '集成区', labelX: 11, labelY: 59, aggregateX: 21, aggregateY: 61,
    slots: [
      { id: 'integration-1', x: 14, y: 80, scale: 10, depth: 79, pose: 'seated' },
      { id: 'integration-2', x: 27, y: 71, scale: 9.1, depth: 70, pose: 'standing' },
      { id: 'integration-3', x: 7, y: 72, scale: 8.7, depth: 71, pose: 'standing', minSceneWidth: 1080 },
    ],
  },
  {
    id: 'meeting', name: '会议室', shortName: '会议室', labelX: 49, labelY: 52, aggregateX: 60, aggregateY: 55,
    slots: [
      { id: 'meeting-1', x: 45, y: 84, scale: 9.7, depth: 83, pose: 'seated' },
      { id: 'meeting-2', x: 58.5, y: 84, scale: 9.7, depth: 83, pose: 'seated' },
      { id: 'meeting-3', x: 53, y: 69, scale: 8.8, depth: 68, pose: 'standing' },
      { id: 'meeting-4', x: 63, y: 76, scale: 8.8, depth: 75, pose: 'standing', minSceneWidth: 1080 },
    ],
  },
  {
    id: 'special', name: '专项处理区', shortName: '专项处理区', labelX: 68, labelY: 38, aggregateX: 88, aggregateY: 40,
    slots: [
      { id: 'special-1', x: 70, y: 57, scale: 9.5, depth: 56, pose: 'seated' },
      { id: 'special-2', x: 84, y: 59, scale: 9.7, depth: 58, pose: 'seated' },
      { id: 'special-3', x: 91, y: 57, scale: 8.9, depth: 56, pose: 'standing', minSceneWidth: 950 },
    ],
  },
]

export const workspaceAreaMap = new Map(workspaceAreas.map((area) => [area.id, area]))

export function isWorkspaceAreaId(value: string | null | undefined): value is WorkspaceAreaId {
  return WORKSPACE_AREA_IDS.includes(value as WorkspaceAreaId)
}

export function availableAreaSlots(area: WorkspaceArea, sceneWidth: number): SceneSlot[] {
  return area.slots.filter((slot) => sceneWidth >= (slot.minSceneWidth ?? 0))
}
