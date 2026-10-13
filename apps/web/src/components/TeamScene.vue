<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import * as THREE from 'three'
import { BookOpen, Boxes, Leaf, Monitor, MoveUpRight } from 'lucide-vue-next'
import type { Employee, Role, Task } from '../types'
import { label } from '../format'
const props = defineProps<{ employees: Employee[]; roles: Role[]; tasks: Task[] }>()
const router = useRouter()
const host = ref<HTMLElement>()
const fallback = ref(sessionStorage.getItem('astra.scene.2d') === 'true')
const motion = ref(!matchMedia('(prefers-reduced-motion: reduce)').matches && sessionStorage.getItem('astra.scene.motion') !== 'false')
const supported = ref(true)
const anchors = ref<Record<string, { left: string; top: string }>>({})
const active = computed(() => props.employees.filter(employee => employee.lifecycle === 'ACTIVE').length)
let renderer: THREE.WebGLRenderer | undefined
let scene: THREE.Scene
let camera: THREE.OrthographicCamera
let team: THREE.Group
let observer: ResizeObserver | undefined
let visibility: IntersectionObserver | undefined
let frame = 0
let visible = true
let lastRender = 0
const worldPositions = new Map<string, THREE.Vector3>()
function material(color: number, opacity = 1) { return new THREE.MeshStandardMaterial({ color, roughness: 0.66, transparent: opacity < 1, opacity }) }
function box(w: number, h: number, d: number, color: number, x: number, y: number, z: number, parent: THREE.Object3D = scene) {
  const mesh = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), material(color)); mesh.position.set(x, y, z); mesh.castShadow = true; mesh.receiveShadow = true; parent.add(mesh); return mesh
}
function cylinder(top: number, bottom: number, h: number, color: number, x: number, y: number, z: number, parent: THREE.Object3D = scene) {
  const mesh = new THREE.Mesh(new THREE.CylinderGeometry(top, bottom, h, 16), material(color)); mesh.position.set(x, y, z); mesh.castShadow = true; parent.add(mesh); return mesh
}
function disposeObject(object: THREE.Object3D) { object.traverse(child => { if (child instanceof THREE.Mesh) { child.geometry.dispose(); const materials = Array.isArray(child.material) ? child.material : [child.material]; materials.forEach(value => value.dispose()) } }) }
function layout() {
  if (!renderer || !host.value) return
  const width = host.value.clientWidth, height = host.value.clientHeight
  renderer.setSize(width, height, false)
  const aspect = width / height
  camera.left = -9 * aspect; camera.right = 9 * aspect; camera.top = 9; camera.bottom = -9; camera.updateProjectionMatrix()
  const result: Record<string, { left: string; top: string }> = {}
  const labelWidth = width < 500 ? 123 : 150
  const placements: { id: string; x: number; y: number }[] = []
  worldPositions.forEach((position, id) => { const projected = position.clone().project(camera); placements.push({ id, x: Math.max(labelWidth / 2 + 10, Math.min(width - labelWidth / 2 - 10, (projected.x + 1) / 2 * width)), y: (-projected.y + 1) / 2 * height }) })
  placements.sort((left, right) => left.y - right.y)
  const placed: typeof placements = []
  for (const placement of placements) {
    for (let pass = 0; pass < placed.length; pass++) {
      const collision = placed.find(other => Math.abs(other.x - placement.x) < labelWidth + 8 && Math.abs(other.y - placement.y) < 82)
      if (!collision) break
      placement.y = collision.y + 82
    }
    result[placement.id] = { left: `${placement.x / width * 100}%`, top: `${Math.min(height - 20, placement.y) / height * 100}%` }
    placed.push(placement)
  }
  anchors.value = result
  renderer.render(scene, camera)
}
function rebuild() {
  if (!scene) return
  if (team) { scene.remove(team); disposeObject(team) }
  team = new THREE.Group(); scene.add(team); worldPositions.clear()
  const count = props.employees.length
  const columns = Math.max(2, Math.ceil(Math.sqrt(count)))
  const rows = Math.ceil(count / columns)
  const spacing = Math.min(3.3, 11 / columns)
  props.employees.forEach((employee, index) => {
    const x = (index % columns - (columns - 1) / 2) * spacing
    const z = (Math.floor(index / columns) - (rows - 1) / 2) * spacing
    const color = employee.lifecycle === 'ACTIVE' ? 0x159d65 : employee.lifecycle === 'PAUSED' ? 0xe9b564 : 0x8fa49b
    const group = new THREE.Group(); group.position.set(x, 0.28, z); team.add(group)
    cylinder(1.12, 1.2, 0.15, 0xeaf5ee, 0, 0, 0, group)
    box(1.7, 0.12, 0.78, 0xffffff, 0, 1.05, -0.25, group)
    box(0.09, 0.9, 0.09, 0xc4d9cf, -0.67, 0.55, -0.25, group); box(0.09, 0.9, 0.09, 0xc4d9cf, 0.67, 0.55, -0.25, group)
    box(0.7, 0.44, 0.07, 0x30544a, 0.22, 1.38, -0.48, group); box(0.62, 0.36, 0.08, 0xb4e6d2, 0.22, 1.38, -0.47, group)
    box(0.38, 0.035, 0.25, 0xd4e5dc, 0.2, 1.13, -0.06, group)
    cylinder(0.31, 0.38, 0.76, color, -0.28, 1.12, 0.4, group)
    const head = new THREE.Mesh(new THREE.SphereGeometry(0.27, 16, 12), material(0xf2dbc6)); head.position.set(-0.28, 1.77, 0.4); group.add(head)
    const hair = new THREE.Mesh(new THREE.SphereGeometry(0.285, 16, 12, 0, Math.PI * 2, 0, Math.PI * 0.52), material(0x364f48)); hair.position.copy(head.position); group.add(hair)
    cylinder(0.3, 0.3, 0.08, 0xc7ddd1, -0.28, 0.69, 0.45, group)
    worldPositions.set(employee.id, new THREE.Vector3(x, 2.5, z))
  })
  layout()
}
function animate(time = 0) {
  frame = requestAnimationFrame(animate)
  if (!visible || !motion.value || fallback.value || time - lastRender < 65 || !renderer) return
  lastRender = time
  // 仅环境光缓慢变化，与员工业务活动无关。
  const light = scene.getObjectByName('ambient-glow') as THREE.PointLight
  if (light) light.intensity = 18 + Math.sin(time / 5000) * 2
  renderer.render(scene, camera)
}
onMounted(async () => {
  await nextTick()
  if (!host.value) return
  try {
    renderer = new THREE.WebGLRenderer({ alpha: true, antialias: true, powerPreference: 'low-power' })
    renderer.setPixelRatio(Math.min(devicePixelRatio, 1.7)); renderer.shadowMap.enabled = true; renderer.shadowMap.type = THREE.PCFSoftShadowMap; renderer.setClearColor(0xffffff, 0)
    host.value.prepend(renderer.domElement); renderer.domElement.setAttribute('aria-hidden', 'true')
    renderer.domElement.addEventListener('webglcontextlost', () => { supported.value = false })
    scene = new THREE.Scene()
    camera = new THREE.OrthographicCamera(-10, 10, 9, -9, 0.1, 100); camera.position.set(14, 15, 18); camera.lookAt(0, 0, 0)
    scene.add(new THREE.AmbientLight(0xf3fff8, 2.4))
    const sun = new THREE.DirectionalLight(0xffffff, 3.4); sun.position.set(-7, 15, 8); sun.castShadow = true; sun.shadow.mapSize.set(1024, 1024); sun.shadow.camera.left = -12; sun.shadow.camera.right = 12; sun.shadow.camera.top = 12; sun.shadow.camera.bottom = -12; scene.add(sun)
    const glow = new THREE.PointLight(0x79e5b5, 18, 24); glow.name = 'ambient-glow'; glow.position.set(-5, 4, -5); scene.add(glow)
    cylinder(7.5, 7.8, 0.35, 0xe5f1e9, 0, -0.03, 0)
    const ring = new THREE.Mesh(new THREE.TorusGeometry(7.4, 0.025, 8, 100), material(0x8bcdb0)); ring.rotation.x = Math.PI / 2; ring.position.y = 0.18; scene.add(ring)
    const floorGrid = new THREE.GridHelper(12, 12, 0xc6dfd1, 0xd8e9de); floorGrid.position.y = 0.16; scene.add(floorGrid)
    for (let i = 0; i < 5; i++) { const height = 2.3 + i % 3; box(0.12, height, 0.12, 0xb9dace, -6 + i * 3, height / 2, -6) }
    box(12, 0.12, 0.16, 0xc1dfd2, 0, 4.2, -6)
    for (const x of [-6.1, 6.1]) { cylinder(0.45, 0.35, 0.65, 0xffffff, x, 0.48, 2); const crown = new THREE.Mesh(new THREE.IcosahedronGeometry(0.68, 1), material(0x7cbca0)); crown.position.set(x, 1.4, 2); scene.add(crown) }
    rebuild(); observer = new ResizeObserver(layout); observer.observe(host.value)
    visibility = new IntersectionObserver(entries => { visible = entries[0]?.isIntersecting ?? true }); visibility.observe(host.value)
    animate()
  } catch { supported.value = false }
})
watch(() => props.employees, rebuild, { deep: true })
watch([fallback, motion], () => { sessionStorage.setItem('astra.scene.2d', String(fallback.value)); sessionStorage.setItem('astra.scene.motion', String(motion.value)); nextTick(layout) })
onBeforeUnmount(() => { cancelAnimationFrame(frame); observer?.disconnect(); visibility?.disconnect(); if (scene) disposeObject(scene); renderer?.dispose() })
function taskCount(id: string) { return props.tasks.filter(task => task.owner_employee_id === id && !['COMPLETED','CANCELLED'].includes(task.status)).length }
</script>

<template>
  <section class="scene-stage" :class="{ 'scene-flat': fallback || !supported }" aria-label="数字员工空间">
    <div class="scene-top"><span class="scene-eyebrow">DIGITAL TEAM · WORKING SPACE</span><span class="caption">在岗 {{ active }} / {{ employees.length }}</span></div>
    <div ref="host" class="scene-canvas" :class="{ 'hide-canvas': fallback || !supported }">
      <div class="scene-labels" :class="{ 'flat-labels': fallback || !supported }">
        <button v-for="employee in employees" :key="employee.id" class="employee-hotspot" :style="fallback || !supported ? undefined : anchors[employee.id]" @click="router.push(`/employees/${employee.id}`)">
          <span class="presence" :class="employee.lifecycle.toLowerCase()"></span><strong>{{ employee.name }}</strong><small>{{ roles.find(role => role.id === employee.role_id)?.name || '岗位待配置' }}</small><span class="hotspot-detail">{{ label(employee.lifecycle) }} · {{ taskCount(employee.id) }} 项工作 <MoveUpRight :size="11"/></span>
        </button>
      </div>
      <div v-if="!employees.length" class="scene-empty"><Leaf :size="38" :stroke-width="1"/><strong>这里，等待你的团队</strong><p>建立岗位与员工后，空间会随团队自然生长。</p><RouterLink to="/organization"><el-button type="primary" plain>建立数字团队</el-button></RouterLink></div>
    </div>
    <div class="scene-portals"><RouterLink to="/library"><BookOpen :size="15"/>数字图书馆</RouterLink><RouterLink to="/tasks"><Boxes :size="15"/>工作中心</RouterLink><RouterLink to="/resources"><Monitor :size="15"/>资源与 API</RouterLink></div>
    <div class="scene-settings"><el-switch v-model="fallback" active-text="二维空间" aria-label="使用二维空间"/><el-switch v-if="supported && !fallback" v-model="motion" active-text="环境动态" aria-label="环境动态"/><span v-if="!supported" class="caption">当前设备使用二维空间</span></div>
  </section>
</template>
