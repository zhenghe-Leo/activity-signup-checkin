<script setup>
// 外壳：顶部身份切换（预置账号，无密码，01-spec §2）+ 按角色显示的导航
import { onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api, errorText } from './api/client'
import { session, setUser } from './store/session'

const router = useRouter()
const ready = ref(false)

// 学生的未读通知数：切换身份或页面时刷新；「我的报名」标记已读后由该页清零
async function refreshUnread() {
  if (session.role !== 'student') return (session.unread = 0)
  try {
    const rows = await api.get('/me/registrations')
    session.unread = rows.filter((r) => r.registration.notify_status === 'UNREAD').length
  } catch {
    session.unread = 0
  }
}
// 「我的报名」页自己负责清零；在那里刷新会和「标记已读」请求竞争，可能把角标写回旧值
router.afterEach((to) => { if (session.user && to.path !== '/me') refreshUnread() })
watch(() => session.userId, refreshUnread)

onMounted(async () => {
  try {
    const [users, meta] = await Promise.all([api.get('/users'), api.get('/meta')])
    session.users = users
    session.meta = meta
    if (!session.user) setUser(users.find((u) => u.role === 'student')?.id ?? users[0].id)
    refreshUnread()
  } catch (e) {
    ElMessage.error(errorText(e))
  } finally {
    ready.value = true
  }
})

function onSwitch(id) {
  // 身份之间相互隔离：切换时关闭上一个身份留下的提示和确认框
  // （全局提示不随页面卸载；鼠标悬停时还会暂停倒计时，否则会在新身份的画面里停留很久）
  ElMessage.closeAll()
  ElMessageBox.close()
  setUser(id)
  router.push(session.role === 'organizer' ? '/organizer' : '/activities')
}
</script>

<template>
  <el-container class="layout">
    <el-header class="header">
      <strong class="title">校园活动报名与签到</strong>
      <nav v-if="session.role === 'student'">
        <router-link to="/activities">活动列表</router-link>
        <router-link to="/me">
          <el-badge :value="session.unread" :hidden="!session.unread" :offset="[8, 0]">我的报名</el-badge>
        </router-link>
      </nav>
      <nav v-else-if="session.role === 'organizer'">
        <router-link to="/organizer">活动管理</router-link>
        <router-link to="/organizer/new">新建活动</router-link>
      </nav>
      <span class="spacer" />
      <el-tag v-if="session.meta" :type="session.meta.ai_enabled ? 'success' : 'warning'" size="small">
        {{ session.meta.ai_enabled ? 'AI 已配置' : 'AI 未配置（将使用降级）' }}
      </el-tag>
      <span class="muted">当前身份</span>
      <el-select :model-value="session.userId" style="width: 180px" @change="onSwitch">
        <el-option v-for="u in session.users" :key="u.id" :value="u.id"
                   :label="`${u.name}（${u.role === 'organizer' ? '组织者' : '学生'}）`" />
      </el-select>
    </el-header>
    <el-main>
      <router-view v-if="ready && session.user" :key="`${session.userId}-${$route.fullPath}`" />
    </el-main>
  </el-container>
</template>

<style>
body { margin: 0; font-family: system-ui, "Microsoft YaHei", sans-serif; background: #f5f7fa; }
.layout { min-height: 100vh; }
.header { display: flex; align-items: center; gap: 16px; background: #fff; border-bottom: 1px solid #e4e7ed; }
.header nav a { margin-right: 12px; color: #409eff; text-decoration: none; }
.header nav a.router-link-active { font-weight: bold; }
.title { font-size: 18px; }
.spacer { flex: 1; }
.page { max-width: 1200px; margin: 0 auto; }
.row { display: flex; gap: 12px; align-items: center; flex-wrap: wrap; }
.mt { margin-top: 16px; }
.muted { color: #909399; font-size: 13px; }
</style>
