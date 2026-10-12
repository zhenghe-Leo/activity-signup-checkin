<script setup>
// 组织者活动详情：统计、名单、签到口令、操作记录、发布 / 取消活动（AC-03、AC-10、AC-13、AC-28、AC-30）
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api, errorText } from '../../api/client'
import { ACTION, fmt, NOTIFY } from '../../labels'
import StatusTag from '../../components/StatusTag.vue'
import ChangePreviewDialog from '../../components/ChangePreviewDialog.vue'

const props = defineProps({ id: String })
const act = ref(null)
const roster = ref([])
const logs = ref([])
const busy = ref('')
const issues = ref([])
const changing = ref(false)

const base = computed(() => `/organizer/activities/${props.id}`)
const editable = computed(() => act.value && !['ENDED', 'CANCELLED'].includes(act.value.phase))
const canCode = computed(() => act.value && ['OPEN', 'CLOSED', 'ONGOING'].includes(act.value.phase))
// 发布后调整只在签到窗口开放前可用；是否已开放以后端校验为准（CHANGE_LOCKED）
const canChange = computed(() => act.value && ['OPEN', 'CLOSED'].includes(act.value.phase))

async function load() {
  try {
    ;[act.value, roster.value, logs.value] = await Promise.all([
      api.get(base.value), api.get(`${base.value}/registrations`), api.get(`${base.value}/logs`),
    ])
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
    if (e.code === 'CONTENT_INVALID') issues.value = e.details
    ElMessage.error(errorText(e))
  } finally {
    busy.value = ''
  }
}

const publish = () => run('publish', async () => {
  issues.value = []
  await api.post(`${base.value}/publish`)
  ElMessage.success('已发布')
})

const resetCode = () => run('code', async () => {
  await api.post(`${base.value}/checkin-code`)
  ElMessage.success('已生成新口令，旧口令立即失效')
})

async function cancelActivity() {
  try {
    await ElMessageBox.confirm('取消后，所有已报名和候补的学生都会被取消并收到通知，且不可恢复。确定取消活动吗？',
      '取消活动', { type: 'warning' })
  } catch {
    return
  }
  await run('cancel', async () => {
    const r = await api.post(`${base.value}/cancel`)
    ElMessage.success(`活动已取消，联动取消 ${r.cancelled_registrations} 条报名`)
  })
}

onMounted(load)
</script>

<template>
  <div class="page" v-if="act">
    <el-card shadow="never">
      <template #header>
        <div class="row">
          <strong>{{ act.title }}</strong>
          <StatusTag :phase="act.phase" />
          <span class="spacer" />
          <router-link v-if="editable" :to="`${base}/edit`"><el-button>编辑</el-button></router-link>
          <el-button v-if="act.status === 'DRAFT'" type="primary" :loading="busy === 'publish'" @click="publish">发布</el-button>
          <el-button v-if="canChange" @click="changing = true">调整名额 / 时间 / 地点</el-button>
          <el-button v-if="act.status === 'PUBLISHED'" type="danger" plain :loading="busy === 'cancel'"
                     @click="cancelActivity">取消活动</el-button>
        </div>
      </template>
      <el-alert v-for="(i, k) in issues" :key="k" type="error" :closable="false" style="margin-bottom: 6px"
                :title="`${i.message}（原文：${i.text || '—'}）`" />
      <el-descriptions :column="2" border>
        <el-descriptions-item label="时间">{{ fmt(act.start_at) }} – {{ fmt(act.end_at).slice(11) }}</el-descriptions-item>
        <el-descriptions-item label="地点">{{ act.location }}</el-descriptions-item>
        <el-descriptions-item label="报名截止">{{ fmt(act.deadline_at) }}</el-descriptions-item>
        <el-descriptions-item label="标签">{{ act.tags.join('、') || '（未选择）' }}</el-descriptions-item>
        <el-descriptions-item label="简介" :span="2">
          <span style="white-space: pre-wrap">{{ act.summary || '（暂无）' }}</span>
        </el-descriptions-item>
      </el-descriptions>
    </el-card>

    <el-card v-if="act.status !== 'DRAFT'" shadow="never" class="mt">
      <template #header>统计与签到口令</template>
      <div class="row" style="gap: 40px">
        <el-statistic title="已报名" :value="act.stats.registered" />
        <el-statistic title="候补中" :value="act.stats.waitlisted" />
        <el-statistic title="已签到" :value="act.stats.checked_in" />
        <el-statistic title="已取消" :value="act.stats.cancelled" />
        <el-statistic title="签到率(%)" :value="Math.round(act.stats.checkin_rate * 100)" />
        <el-statistic title="递补人次" :value="act.stats.promoted_count" />
        <span class="spacer" />
        <div v-if="canCode" style="text-align: center">
          <div class="muted">当前签到口令</div>
          <div style="font-size: 40px; font-weight: bold; letter-spacing: 6px">{{ act.checkin_code || '——' }}</div>
          <el-button size="small" :loading="busy === 'code'" @click="resetCode">
            {{ act.checkin_code ? '重新生成' : '生成口令' }}
          </el-button>
        </div>
      </div>
    </el-card>

    <el-card v-if="act.status !== 'DRAFT'" shadow="never" class="mt">
      <template #header>报名名单</template>
      <el-table :data="roster" empty-text="暂无报名">
        <el-table-column prop="student_name" label="学生" width="120" />
        <el-table-column label="状态" width="200">
          <template #default="{ row }"><StatusTag :registration="row" /></template>
        </el-table-column>
        <el-table-column label="签到时间" width="160">
          <template #default="{ row }">{{ fmt(row.checked_in_at) }}</template>
        </el-table-column>
        <el-table-column label="通知状态" width="90">
          <template #default="{ row }">{{ NOTIFY[row.notify_status] }}</template>
        </el-table-column>
        <el-table-column prop="notify_message" label="最近通知" min-width="240" />
      </el-table>
    </el-card>

    <el-card shadow="never" class="mt">
      <template #header>操作记录</template>
      <el-table :data="logs" empty-text="暂无记录" max-height="360">
        <el-table-column label="时间" width="160">
          <template #default="{ row }">{{ fmt(row.occurred_at) }}</template>
        </el-table-column>
        <el-table-column prop="actor_name" label="操作人" width="120" />
        <el-table-column label="动作" width="100">
          <template #default="{ row }">{{ ACTION[row.action] || row.action }}</template>
        </el-table-column>
        <el-table-column prop="target_student_name" label="涉及学生" width="120" />
        <el-table-column label="详情" min-width="200">
          <template #default="{ row }">{{ Object.keys(row.detail).length ? JSON.stringify(row.detail) : '' }}</template>
        </el-table-column>
      </el-table>
    </el-card>
    <ChangePreviewDialog v-model="changing" :activity="act" @done="load" />
  </div>
</template>
