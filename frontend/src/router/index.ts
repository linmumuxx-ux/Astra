import { createRouter, createWebHistory, type LocationQueryRaw, type RouteLocationGeneric } from 'vue-router'
const MainLayout = () => import('@/layouts/MainLayout.vue')
const DashboardView = () => import('@/views/DashboardView.vue')
const EmployeeListView = () => import('@/views/EmployeeListView.vue')
const EmployeeDetailView = () => import('@/views/EmployeeDetailView.vue')
const TaskListView = () => import('@/views/TaskListView.vue')
const TaskDetailView = () => import('@/views/TaskDetailView.vue')
const DigitalLibraryView = () => import('@/views/DigitalLibraryView.vue')
const GatewayView = () => import('@/views/gateway/GatewayView.vue')
const GatewayNodeDetailView = () => import('@/views/gateway/GatewayNodeDetailView.vue')
const GatewayOverview = () => import('@/views/gateway/GatewayOverview.vue')
const GatewayNodes = () => import('@/views/gateway/GatewayNodes.vue')
const GatewayPoolsRoutes = () => import('@/views/gateway/GatewayPoolsRoutes.vue')
const GatewayKeys = () => import('@/views/gateway/GatewayKeys.vue')
const GatewayRequests = () => import('@/views/gateway/GatewayRequests.vue')
const GatewayVersions = () => import('@/views/gateway/GatewayVersions.vue')
const GatewaySelfUsage = () => import('@/views/gateway/GatewaySelfUsage.vue')
const InterventionView = () => import('@/views/InterventionView.vue')
const SettingsView = () => import('@/views/SettingsView.vue')

// 旧 ?tab= 链接（如 /gateway?tab=nodes）无损转向对应的新子路径。
const gatewayTabSegments: Record<string, string> = {
  overview: 'overview',
  nodes: 'nodes',
  routes: 'routes',
  keys: 'keys',
  logs: 'logs',
  versions: 'versions',
  self: 'self',
}

function gatewayIndexRedirect(to: RouteLocationGeneric) {
  const tab = typeof to.query.tab === 'string' ? to.query.tab : ''
  const segment = gatewayTabSegments[tab] ?? 'overview'
  const { tab: _tab, ...rest } = to.query
  return { path: `/gateway/${segment}`, query: rest as LocationQueryRaw }
}

export default createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/',
      component: MainLayout,
      children: [
        { path: '', name: 'dashboard', component: DashboardView, meta: { title: '总览' } },
        { path: 'employees', name: 'employees', component: EmployeeListView, meta: { title: '数字员工' } },
        { path: 'employees/:id', name: 'employee-detail', component: EmployeeDetailView, meta: { title: '员工详情' } },
        { path: 'tasks', name: 'tasks', component: TaskListView, meta: { title: '任务管理' } },
        { path: 'tasks/:id', name: 'task-detail', component: TaskDetailView, meta: { title: '任务详情' } },
        { path: 'library', name: 'digital-library', component: DigitalLibraryView, meta: { title: '数字图书馆' } },
        {
          path: 'gateway',
          component: GatewayView,
          meta: { title: 'API 中转' },
          children: [
            { path: '', name: 'gateway', redirect: gatewayIndexRedirect },
            { path: 'overview', name: 'gateway-overview', component: GatewayOverview, meta: { title: '运行总览' } },
            { path: 'nodes', name: 'gateway-nodes', component: GatewayNodes, meta: { title: '下游节点' } },
            { path: 'routes', name: 'gateway-routes', component: GatewayPoolsRoutes, meta: { title: '资源池与路由' } },
            { path: 'keys', name: 'gateway-keys', component: GatewayKeys, meta: { title: 'API Key 管理' } },
            { path: 'logs', name: 'gateway-logs', component: GatewayRequests, meta: { title: '调用日志' } },
            { path: 'versions', name: 'gateway-versions', component: GatewayVersions, meta: { title: '配置版本' } },
            { path: 'self', name: 'gateway-self', component: GatewaySelfUsage, meta: { title: '自助用量' } },
          ],
        },
        { path: 'gateway/nodes/:id', name: 'gateway-node-detail', component: GatewayNodeDetailView, meta: { title: '节点详情' } },
        { path: 'settings', name: 'settings', component: SettingsView, meta: { title: '配置中心' } },
        { path: 'interventions', name: 'interventions', component: InterventionView, meta: { title: '待处理' } },
      ],
    },
  ],
})
