<script setup>
// 学生活动详情：报名、取消、签到（AC-01~03、AC-05、AC-10~12）
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api, errorText } from '../../api/client'
import { fmt, NOTIFY } from '../../labels'
import { session } from '../../store/session'
import StatusTag from '../../components/StatusTag.vue'

const props = defineProps({ id: String })
const act = ref(null)
const busy = ref('')
const code = ref('')

const mine = computed(() => act.value?.my_registration)
const active = computed(() => ['REGISTERED', 'WAITLISTED'].includes(mine.value?.status))
const checkedIn = computed(() => !!mine.value?.checked_in_at)

async function load() {
  try {
    act.value = await api.get(`/activities/${props.id}`)
  } catch (e) {
    ElMessage.error(errorText(e))
  }
}

async function run(name, fn) {
  busy.value = name
  try {
    await fn()
    await load()
  } catch (e) {
    ElMessage.error(errorText(e))
  } finally {
    busy.value = ''
  }
}

const register = () => run('register', async () => {
  const r = await api.post(`/activities/${props.id}/registration`)
  if (r.status === 'REGISTERED') ElMessage.success('报名成功')
  else ElMessage.warning(`名额已满，已加入候补，当前第 ${r.waitlist_position} 位`)
})

async function cancel() {
  try {
    await ElMessageBox.confirm('确定取消报名吗？', '取消报名', { type: 'warning' })
  } catch {
    return // 用户在确认框中点了「取消」
  }
  await run('cancel', async () => {
    const r = await api.del(`/activities/${props.id}/registration`)
    ElMessage.success(r.promoted_count ? '已取消报名，空出的名额已自动递补给候补同学' : '已取消报名')
  })
}

function checkin() {
  if (!code.value.trim()) return ElMessage.warning('请输入签到口令')
  return doCheckin()
}

const doCheckin = () => run('checkin', async () => {
  const r = await api.post(`/activities/${props.id}/checkin`, { code: code.value.trim() })
  ElMessage.success(`签到成功，签到时间 ${fmt(r.checked_in_at)}`)
  code.value = ''
})

onMounted(load)
</script>

<template>
  <div class="page" v-if="act">
    <el-card shadow="never">
      <template #header>
        <div class="row">
          <strong>{{ act.title }}</strong>
          <StatusTag :phase="act.phase" />
        </div>
      </template>
      <el-descriptions :column="2" border>
        <el-descriptions-item label="时间">{{ fmt(act.start_at) }} – {{ fmt(act.end_at).slice(11) }}</el-descriptions-item>
        <el-descriptions-item label="地点">{{ act.location }}</el-descriptions-item>
        <el-descriptions-item label="报名截止">{{ fmt(act.deadline_at) }}</el-descriptions-item>
        <el-descriptions-item label="标签">{{ act.tags.join('、') }}</el-descriptions-item>
        <el-descriptions-item label="名额">已报名 {{ act.registered_count }} / {{ act.capacity }}，剩余 {{ act.remaining }}</el-descriptions-item>
        <el-descriptions-item label="候补人数">{{ act.waitlist_count }}</el-descriptions-item>
        <el-descriptions-item label="简介" :span="2">
          <span style="white-space: pre-wrap">{{ act.summary || '（暂无）' }}</span>
        </el-descriptions-item>
        <el-descriptions-item label="注意事项" :span="2">
          <ol v-if="act.notes.length" style="margin: 0; padding-left: 20px">
            <li v-for="(n, i) in act.notes" :key="i">{{ n }}</li>
          </ol>
          <span v-else>（暂无）</span>
        </el-descriptions-item>
      </el-descriptions>
    </el-card>

    <el-card shadow="never" class="mt">
      <template #header>我的报名</template>
      <div class="row">
        <span>状态：</span>
        <StatusTag :registration="mine" />
        <span v-if="checkedIn" class="muted">签到时间 {{ fmt(mine.checked_in_at) }}</span>
      </div>
      <el-alert v-if="mine?.notify_message" class="mt" :closable="false"
                :type="mine.notify_status === 'UNREAD' ? 'warning' : 'info'"
                :title="`通知（${NOTIFY[mine.notify_status]}）：${mine.notify_message}`" />
      <div class="row mt">
        <el-button v-if="!active" type="primary" :loading="busy === 'register'" @click="register">报名</el-button>
        <el-button v-if="active && !checkedIn" :loading="busy === 'cancel'" @click="cancel">取消报名</el-button>
      </div>
      <div class="row mt">
        <el-input v-model="code" placeholder="输入 6 位签到口令" maxlength="20" style="width: 200px"
                  @keyup.enter="checkin" />
        <el-button type="success" :loading="busy === 'checkin'" @click="checkin">签到</el-button>
        <span class="muted">签到时间：活动开始前 {{ session.meta?.checkin_open_before_minutes }} 分钟至结束</span>
      </div>
    </el-card>
  </div>
</template>
