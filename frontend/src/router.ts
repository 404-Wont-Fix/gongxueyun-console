import { createRouter, createWebHistory } from 'vue-router'
import { getToken } from './api'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/login',
      name: 'login',
      component: () => import('./views/LoginView.vue'),
      meta: { blank: true, title: '登录' },
    },
    {
      path: '/',
      name: 'dashboard',
      component: () => import('./views/DashboardView.vue'),
      meta: { title: '总览', subtitle: '今天的打卡与账号状态一目了然' },
    },
    {
      path: '/accounts',
      name: 'accounts',
      component: () => import('./views/AccountsView.vue'),
      meta: { title: '账号管理', subtitle: '托管工学云账号、设置打卡时间与地点' },
    },
    {
      path: '/calendar',
      name: 'calendar',
      component: () => import('./views/CalendarView.vue'),
      meta: { title: '打卡日历', subtitle: '放假调休自动同步，每日安排与记录一处查看' },
    },
    {
      path: '/records',
      name: 'records',
      component: () => import('./views/RecordsView.vue'),
      meta: { title: '考勤记录', subtitle: '以服务端记录为准，核对真实打卡结果' },
    },
    {
      path: '/reports',
      name: 'reports',
      component: () => import('./views/ReportsView.vue'),
      meta: { title: '实习报告', subtitle: '生成草稿、确认内容后提交日报 / 周报 / 月报' },
    },
    {
      path: '/verifications',
      name: 'verifications',
      component: () => import('./views/VerificationsView.vue'),
      meta: { title: '验证中心', subtitle: '需要本人完成的验证、点选验证码与续提' },
    },
    {
      path: '/logs',
      name: 'logs',
      component: () => import('./views/LogsView.vue'),
      meta: { title: '执行日志', subtitle: '每一次请求的结果、耗时与响应摘要' },
    },
    {
      path: '/settings',
      name: 'settings',
      component: () => import('./views/SettingsView.vue'),
      meta: { title: '设置', subtitle: '账号安全、通知通道与系统能力' },
    },
    { path: '/:pathMatch(.*)*', redirect: '/' },
  ],
})

router.beforeEach((to) => {
  if (to.meta.blank) return true
  if (!getToken()) return { name: 'login', query: { next: to.fullPath } }
  return true
})

router.afterEach((to) => {
  document.title = `${(to.meta.title as string) || '工学云'} · GongXueYun Console`
})

export default router
