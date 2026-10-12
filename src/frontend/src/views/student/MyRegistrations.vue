<script setup>
// 我的报名：状态、候补位次、通知；页面展示后把未读通知置为已读（AC-03、BR-29）
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { api, errorText } from '../../api/client'
import { fmt, NOTIFY } from '../../labels'
import { session } from '../../store/session'
import StatusTag from '../../components/StatusTag.vue'

const rows = ref([])
const loading = ref(true)
const markedRead = ref(0)

onMounted(async () => {
  try {
    rows.value = await api.get('/me/registrations')
    // 先按「未读」展示本次看到的通知，再标记为已读（下次打开即为已读）
    if (rows.value.some((r) => r.registration.notify_status === 'UNREAD')) {
      markedRead.value = (await api.post('/me/notifications/read')).updated
      session.unread = 0
    }
  } catch (e) {
    ElMessage.error(errorText(e))
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <div class="page">
    <el-alert v-if="markedRead" type="info" :closable="false" show-icon
              :title="`有 ${markedRead} 条新通知（下方高亮），已标记为已读`" />
    <el-card shadow="never" class="mt">
      <el-table :data="rows" v-loading="loading" empty-text="还没有报名记录"
                :row-class-name="({ row }) => row.registration.notify_status === 'UNREAD' ? 'unread' : ''">
        <el-table-column label="活动" min-width="200">
          <template #default="{ row }">
            <router-link :to="`/activities/${row.activity.id}`">{{ row.activity.title }}</router-link>
          </template>
        </el-table-column>
        <el-table-column label="开始时间" width="160">
          <template #default="{ row }">{{ fmt(row.activity.start_at) }}</template>
        </el-table-column>
        <el-table-column label="活动状态" width="100">
          <template #default="{ row }"><StatusTag :phase="row.activity.phase" /></template>
        </el-table-column>
        <el-table-column label="我的状态" width="200">
          <template #default="{ row }"><StatusTag :registration="row.registration" /></template>
        </el-table-column>
        <el-table-column label="通知" min-width="280">
          <template #default="{ row }">
            <span v-if="row.registration.notify_message">
              【{{ NOTIFY[row.registration.notify_status] }}】{{ row.registration.notify_message }}
            </span>
            <span v-else class="muted">—</span>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
  </div>
</template>

<style>
.el-table .unread { --el-table-tr-bg-color: #fdf6ec; font-weight: bold; }
</style>
