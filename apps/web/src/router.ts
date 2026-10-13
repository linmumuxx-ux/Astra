import { createRouter, createWebHistory } from 'vue-router'
export const router = createRouter({ history: createWebHistory(), routes: [
  { path: '/', redirect: '/space' },
  { path: '/space', component: () => import('./views/SpaceView.vue'), meta: { title: '数字空间' } },
  { path: '/employees/:id?', component: () => import('./views/EmployeeView.vue'), meta: { title: '员工工作空间' } },
  { path: '/channels', component: () => import('./views/ChannelsView.vue'), meta: { title: '团队协作' } },
  { path: '/tasks/:id?', component: () => import('./views/TasksView.vue'), meta: { title: '工作中心' } },
  { path: '/attention', component: () => import('./views/AttentionView.vue'), meta: { title: '需要我处理' } },
  { path: '/organization', component: () => import('./views/OrganizationView.vue'), meta: { title: '数字团队与岗位' } },
  { path: '/library', component: () => import('./views/LibraryView.vue'), meta: { title: '数字图书馆' } },
  { path: '/resources', component: () => import('./views/ResourcesView.vue'), meta: { title: '资源与 API' } },
  { path: '/governance', component: () => import('./views/GovernanceView.vue'), meta: { title: '履职与治理' } },
  { path: '/:pathMatch(.*)*', redirect: '/space' },
] })
router.afterEach(to => { document.title = `${String(to.meta.title || '数字团队')} · Astra 1.0` })
