import { createRouter, createWebHistory } from 'vue-router'
const DashboardView = () => import('@/views/DashboardView.vue')
const EmployeeListView = () => import('@/views/EmployeeListView.vue')
const EmployeeDetailView = () => import('@/views/EmployeeDetailView.vue')
const TaskListView = () => import('@/views/TaskListView.vue')
const TaskDetailView = () => import('@/views/TaskDetailView.vue')
const RunListView = () => import('@/views/RunListView.vue')
const RunDetailView = () => import('@/views/RunDetailView.vue')
const InterventionView = () => import('@/views/InterventionView.vue')
const SettingsView = () => import('@/views/SettingsView.vue')

export default createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'dashboard', component: DashboardView, meta: { title: '运行总览', eyebrow: 'CONTROL CENTER' } },
    { path: '/employees', name: 'employees', component: EmployeeListView, meta: { title: '数字员工', eyebrow: 'DIGITAL EMPLOYEES' } },
    { path: '/employees/:id', name: 'employee-detail', component: EmployeeDetailView, meta: { title: '员工详情', eyebrow: 'EMPLOYEE PROFILE' } },
    { path: '/tasks', name: 'tasks', component: TaskListView, meta: { title: '任务中心', eyebrow: 'TASK OPERATIONS' } },
    { path: '/tasks/:id', name: 'task-detail', component: TaskDetailView, meta: { title: '任务详情', eyebrow: 'TASK RUNTIME' } },
    { path: '/runs', name: 'runs', component: RunListView, meta: { title: '运行记录', eyebrow: 'RUN HISTORY' } },
    { path: '/runs/:id', name: 'run-detail', component: RunDetailView, meta: { title: '运行详情', eyebrow: 'RUN EVIDENCE' } },
    { path: '/interventions', name: 'interventions', component: InterventionView, meta: { title: '人工介入', eyebrow: 'HUMAN IN THE LOOP' } },
    { path: '/settings', name: 'settings', component: SettingsView, meta: { title: '配置中心', eyebrow: 'SYSTEM CONFIG' } },
  ],
})
