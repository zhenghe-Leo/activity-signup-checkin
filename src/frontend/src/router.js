// 使用 hash 路由：刷新任意页面都由 index.html 承接，后端不需要额外的回退规则
import { createRouter, createWebHashHistory } from 'vue-router'
import ActivityList from './views/student/ActivityList.vue'
import ActivityDetail from './views/student/ActivityDetail.vue'
import MyRegistrations from './views/student/MyRegistrations.vue'
import Dashboard from './views/organizer/Dashboard.vue'
import ActivityForm from './views/organizer/ActivityForm.vue'
import ActivityManage from './views/organizer/ActivityManage.vue'

export const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    { path: '/', redirect: '/activities' },
    { path: '/activities', component: ActivityList },
    { path: '/activities/:id', component: ActivityDetail, props: true },
    { path: '/me', component: MyRegistrations },
    { path: '/organizer', component: Dashboard },
    { path: '/organizer/new', component: ActivityForm },
    { path: '/organizer/activities/:id/edit', component: ActivityForm, props: true },
    { path: '/organizer/activities/:id', component: ActivityManage, props: true },
  ],
})
