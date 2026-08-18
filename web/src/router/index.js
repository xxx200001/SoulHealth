import { createRouter, createWebHistory } from 'vue-router'

// 信息架构：登录 → 档案 → 四诊采集 → 分析 → 报告 / 问答 / 我的
// 底栏四项：首页 · 档案 · 分析 · 我的；采集页从首页或档案进入。
const routes = [
  { path: '/login', component: () => import('../pages/LoginPage.vue'),
    meta: { public: true, bare: true } },

  { path: '/', component: () => import('../pages/HomePage.vue'),
    meta: { title: 'SoulHealth', nav: 'home' } },

  { path: '/archive', component: () => import('../pages/ArchivePage.vue'),
    meta: { title: '健康档案', nav: 'archive' } },
  { path: '/archive/:pid', component: () => import('../pages/PatientPage.vue'),
    meta: { title: '档案详情', nav: 'archive', back: '/archive' } },

  { path: '/collect/profile', component: () => import('../pages/ProfilePage.vue'),
    meta: { title: '基础信息', nav: 'home', back: '/' , needPatient: true } },
  { path: '/collect/lab', component: () => import('../pages/LabPage.vue'),
    meta: { title: '体检指标', nav: 'home', back: '/', needPatient: true } },
  { path: '/collect/exam', component: () => import('../pages/ExamPage.vue'),
    meta: { title: '舌诊 · 面诊', nav: 'home', back: '/', needPatient: true } },
  { path: '/collect/inquiry', component: () => import('../pages/InquiryPage.vue'),
    meta: { title: '症状问诊', nav: 'home', back: '/', needPatient: true } },

  { path: '/analysis', component: () => import('../pages/AnalysisPage.vue'),
    meta: { title: '智能分析', nav: 'analysis', needPatient: true } },
  { path: '/analysis/:aid', component: () => import('../pages/AnalysisPage.vue'),
    meta: { title: '分析结果', nav: 'analysis', back: '/analysis', needPatient: true } },
  { path: '/reports', component: () => import('../pages/ReportPage.vue'),
    meta: { title: '我的报告', nav: 'analysis', back: '/analysis', needPatient: true } },
  { path: '/qa', component: () => import('../pages/QAPage.vue'),
    meta: { title: '健康问答', nav: 'analysis', back: '/analysis', needPatient: true } },

  { path: '/me', component: () => import('../pages/MePage.vue'),
    meta: { title: '我的', nav: 'me' } },
  { path: '/me/admin', component: () => import('../pages/AdminPage.vue'),
    meta: { title: '用户管理', nav: 'me', back: '/me' } },

  { path: '/:pathMatch(.*)*', redirect: '/' },
]

const router = createRouter({ history: createWebHistory(), routes })

router.beforeEach((to) => {
  const hasToken = !!localStorage.getItem('sh_token')
  if (!to.meta.public && !hasToken) return { path: '/login', query: { r: to.fullPath } }
  if (to.path === '/login' && hasToken) return { path: '/' }
  // 采集与分析都必须先选定档案，否则数据无处可落
  if (to.meta.needPatient && !localStorage.getItem('sh_pid')) {
    return { path: '/archive', query: { need: '1' } }
  }
  return true
})

export default router
