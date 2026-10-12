<script setup>
// 学生活动列表：手动筛选（AC-27）+ 自然语言筛选（AC-24、AC-25）
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { api, errorText } from '../../api/client'
import { session } from '../../store/session'
import { fmt } from '../../labels'
import StatusTag from '../../components/StatusTag.vue'
import AiSourceTag from '../../components/AiSourceTag.vue'

const filters = reactive({ keyword: '', tags: [], dates: null, has_seats: false })
const items = ref([])
const loading = ref(false)

const nlQuery = ref('')
const nl = ref(null) // 自然语言筛选的完整返回；为 null 时显示手动筛选结果
const nlLoading = ref(false)

async function search() {
  loading.value = true
  try {
    items.value = await api.get('/activities', {
      keyword: filters.keyword.trim(),
      tags: filters.tags.join(','),
      date_from: filters.dates?.[0],
      date_to: filters.dates?.[1],
      has_seats: filters.has_seats,
    })
    nl.value = null
  } catch (e) {
    ElMessage.error(errorText(e))
  } finally {
    loading.value = false
  }
}

function reset() {
  Object.assign(filters, { keyword: '', tags: [], dates: null, has_seats: false })
  search()
}

async function nlSearch() {
  if (!nlQuery.value.trim()) return ElMessage.warning('请输入想找的活动')
  nlLoading.value = true
  try {
    nl.value = await api.post('/ai/nl-filter', { query: nlQuery.value.trim() })
  } catch (e) {
    ElMessage.error(errorText(e))
  } finally {
    nlLoading.value = false
  }
}

// 解析出的条件 → 中文描述
function conditionText(c) {
  const parts = []
  if (c.keyword) parts.push(`关键词 = ${c.keyword}`)
  if (c.tags.length) parts.push(`标签 = ${c.tags.join('、')}`)
  if (c.date_from || c.date_to) parts.push(`开始日期 = ${c.date_from ?? '不限'}–${c.date_to ?? '不限'}`)
  if (c.location) parts.push(`地点包含 ${c.location}`)
  if (c.has_seats) parts.push('仅看有余量')
  return parts.join('；') || '（无）'
}

onMounted(search)
</script>

<template>
  <div class="page">
    <el-card shadow="never">
      <template #header>一句话找活动</template>
      <div class="row">
        <el-input v-model="nlQuery" placeholder="例如：这周还有名额的讲座" maxlength="200" style="width: 420px"
                  clearable @keyup.enter="nlSearch" />
        <el-button type="primary" :loading="nlLoading" @click="nlSearch">智能筛选</el-button>
        <el-button v-if="nl" @click="nl = null">返回手动筛选结果</el-button>
      </div>
      <div v-if="nl" class="mt">
        <AiSourceTag :source="nl.source" kind="filter" />
        <p>解析出的条件：{{ conditionText(nl.conditions) }}</p>
        <p>本次使用字段：{{ nl.used_fields.length ? nl.used_fields.join('、') : '（无）' }}</p>
        <p class="muted">{{ nl.message }}</p>
      </div>
    </el-card>

    <el-card shadow="never" class="mt">
      <div class="row">
        <el-input v-model="filters.keyword" placeholder="关键词（标题或简介）" style="width: 200px" clearable />
        <el-select v-model="filters.tags" multiple placeholder="标签" style="width: 220px" clearable>
          <el-option v-for="t in session.meta?.tag_library || []" :key="t" :value="t" :label="t" />
        </el-select>
        <el-date-picker v-model="filters.dates" type="daterange" value-format="YYYY-MM-DD"
                        start-placeholder="开始日期" end-placeholder="结束日期" style="width: 260px" />
        <el-checkbox v-model="filters.has_seats">仅看有余量</el-checkbox>
        <el-button type="primary" :loading="loading" @click="search">查询</el-button>
        <el-button @click="reset">清空条件</el-button>
      </div>
    </el-card>

    <el-card shadow="never" class="mt">
      <el-table :data="nl ? nl.items : items" v-loading="loading || nlLoading" empty-text="没有符合条件的活动">
        <el-table-column label="活动" min-width="220">
          <template #default="{ row }">
            <router-link :to="`/activities/${row.id}`">{{ row.title }}</router-link>
          </template>
        </el-table-column>
        <el-table-column label="开始时间" width="160">
          <template #default="{ row }">{{ fmt(row.start_at) }}</template>
        </el-table-column>
        <el-table-column prop="location" label="地点" min-width="140" />
        <el-table-column label="标签" min-width="140">
          <template #default="{ row }">{{ row.tags.join('、') }}</template>
        </el-table-column>
        <el-table-column label="已报名 / 名额" width="120">
          <template #default="{ row }">{{ row.registered_count }} / {{ row.capacity }}</template>
        </el-table-column>
        <el-table-column prop="remaining" label="剩余" width="80" />
        <el-table-column label="状态" width="100">
          <template #default="{ row }"><StatusTag :phase="row.phase" /></template>
        </el-table-column>
      </el-table>
    </el-card>
  </div>
</template>
