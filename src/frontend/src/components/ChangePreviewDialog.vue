<script setup>
// 发布后变更：修改 → 预览影响 → 确认（AC-14~18、BR-11~17）
import { reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { api, errorText } from '../api/client'
import { session } from '../store/session'
import { fmt } from '../labels'

const props = defineProps({ activity: { type: Object, required: true } })
const emit = defineEmits(['done'])
const visible = defineModel({ type: Boolean, default: false })

const FIELDS = ['capacity', 'deadline_at', 'start_at', 'end_at', 'location']
const LABELS = { capacity: '名额', deadline_at: '报名截止', start_at: '开始时间', end_at: '结束时间', location: '地点' }
const form = reactive({})
const preview = ref(null)
const busy = ref('')

// 打开时用当前值填充；表单任何改动都会使已有预览失效，必须重新预览
watch(visible, (open) => {
  if (!open) return
  FIELDS.forEach((k) => (form[k] = props.activity[k]))
  preview.value = null
})
watch(form, () => (preview.value = null), { deep: true })

function changed() {
  return Object.fromEntries(FIELDS.filter((k) => form[k] !== props.activity[k]).map((k) => [k, form[k]]))
}

async function doPreview() {
  busy.value = 'preview'
  try {
    preview.value = await api.post(`/organizer/activities/${props.activity.id}/changes/preview`, changed())
  } catch (e) {
    ElMessage.error(errorText(e))
  } finally {
    busy.value = ''
  }
}

async function doConfirm() {
  busy.value = 'confirm'
  try {
    await api.post(`/organizer/activities/${props.activity.id}/changes/confirm`,
      { ...changed(), preview_token: preview.value.preview_token })
    ElMessage.success('调整完成')
    visible.value = false
    emit('done')
  } catch (e) {
    ElMessage.error(errorText(e))
    if (e.code === 'PREVIEW_STALE') preview.value = null // 数据已变化：清空预览，要求重新预览
  } finally {
    busy.value = ''
  }
}

const names = (list) => (list.length ? list.map((s) => s.student_name).join('、') : '无')
const show = (k, v) => (k.endsWith('_at') ? fmt(v) : v)
</script>

<template>
  <el-dialog v-model="visible" title="调整名额 / 时间 / 地点" width="640px">
    <el-form label-width="90px">
      <el-form-item label="名额">
        <el-input-number v-model="form.capacity" :min="1" :max="session.meta.limits.capacity_max" />
      </el-form-item>
      <el-form-item label="开始时间">
        <el-date-picker v-model="form.start_at" type="datetime" value-format="YYYY-MM-DDTHH:mm:ssZ" format="YYYY-MM-DD HH:mm" />
      </el-form-item>
      <el-form-item label="结束时间">
        <el-date-picker v-model="form.end_at" type="datetime" value-format="YYYY-MM-DDTHH:mm:ssZ" format="YYYY-MM-DD HH:mm" />
      </el-form-item>
      <el-form-item label="报名截止">
        <el-date-picker v-model="form.deadline_at" type="datetime" value-format="YYYY-MM-DDTHH:mm:ssZ" format="YYYY-MM-DD HH:mm" />
      </el-form-item>
      <el-form-item label="地点">
        <el-input v-model="form.location" />
      </el-form-item>
    </el-form>

    <el-card v-if="preview" shadow="never">
      <template #header>预览影响（尚未修改任何数据）</template>
      <p v-for="(v, k) in preview.changes" :key="k">{{ LABELS[k] }}：{{ show(k, v.from) }} → {{ show(k, v.to) }}</p>
      <p>将退回候补：{{ names(preview.demoted) }}</p>
      <p>将被递补：{{ names(preview.promoted) }}</p>
      <p>将收到变更通知：{{ names(preview.notified) }}</p>
      <p>调整后的候补顺序：{{ names(preview.waitlist_after) }}</p>
    </el-card>

    <template #footer>
      <el-button @click="visible = false">关闭</el-button>
      <el-button :loading="busy === 'preview'" @click="doPreview">预览影响</el-button>
      <el-button type="primary" :disabled="!preview" :loading="busy === 'confirm'" @click="doConfirm">确认调整</el-button>
    </template>
  </el-dialog>
</template>
