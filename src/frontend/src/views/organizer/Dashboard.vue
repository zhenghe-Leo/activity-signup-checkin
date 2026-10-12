<script setup>
// 组织者汇总表：全部活动（含草稿、已取消）及各自统计（AC-28）
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { api, errorText } from '../../api/client'
import { fmt } from '../../labels'
import StatusTag from '../../components/StatusTag.vue'

const rows = ref([])
const loading = ref(true)

onMounted(async () => {
  try {
    rows.value = await api.get('/organizer/activities')
  } catch (e) {
    ElMessage.error(errorText(e))
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <div class="page">
    <div class="row">
      <h3 style="margin: 0">全部活动</h3>
      <span class="spacer" />
      <router-link to="/organizer/new"><el-button type="primary">新建活动</el-button></router-link>
    </div>
    <el-card shadow="never" class="mt">
      <el-table :data="rows" v-loading="loading" empty-text="还没有活动">
        <el-table-column label="活动" min-width="220">
          <template #default="{ row }">
            <router-link :to="`/organizer/activities/${row.id}`">{{ row.title }}</router-link>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="90">
          <template #default="{ row }"><StatusTag :phase="row.phase" /></template>
        </el-table-column>
        <el-table-column label="开始时间" width="150">
          <template #default="{ row }">{{ fmt(row.start_at) }}</template>
        </el-table-column>
        <el-table-column prop="capacity" label="名额" width="70" />
        <el-table-column prop="stats.registered" label="已报名" width="75" />
        <el-table-column prop="stats.waitlisted" label="候补中" width="75" />
        <el-table-column prop="stats.checked_in" label="已签到" width="75" />
        <el-table-column prop="stats.cancelled" label="已取消" width="75" />
        <el-table-column label="签到率" width="80">
          <template #default="{ row }">{{ Math.round(row.stats.checkin_rate * 100) }}%</template>
        </el-table-column>
        <el-table-column prop="stats.promoted_count" label="递补人次" width="85" />
      </el-table>
    </el-card>
  </div>
</template>
