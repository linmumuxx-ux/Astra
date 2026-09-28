import { createRouter, createWebHistory } from 'vue-router'
const MainLayout = () => import('@/layouts/MainLayout.vue')
const DashboardView = () => import('@/views/DashboardView.vue')
const EmployeeListView = () => import('@/views/EmployeeListView.vue')
const EmployeeDetailView = () => import('@/views/EmployeeDetailView.vue')
const TaskListView = () => import('@/views/TaskListView.vue')
const TaskDetailView = () => import('@/views/TaskDetailView.vue')
const DigitalLibraryView = () => import('@/views/DigitalLibraryView.vue')
const GatewayView = () => import('@/views/gateway/GatewayView.vue')
const GatewayNodeDetailView = () => import('@/views/gateway/GatewayNodeDetailView.vue')
const InterventionView = () => import('@/views/InterventionView.vue')
const SettingsView = () => import('@/views/SettingsView.vue')

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
        { path: 'gateway', name: 'gateway', component: GatewayView, meta: { title: 'API 中转' } },
        { path: 'gateway/nodes/:id', name: 'gateway-node-detail', component: GatewayNodeDetailView, meta: { title: '节点详情' } },
        { path: 'settings', name: 'settings', component: SettingsView, meta: { title: '配置中心' } },
        { path: 'interventions', name: 'interventions', component: InterventionView, meta: { title: '待处理' } },
      ],
    },
  ],
})
