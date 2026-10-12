<script setup>
// 新建 / 编辑活动：AI 生成 → 人工修改 → 保存 → 发布（AC-19~23）
// 草稿全部字段可改；已发布只能改标题、简介、标签、注意事项（BR-11），其余字段在活动管理页「预览 → 确认」调整
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { api, errorText } from '../../api/client'
import { session } from '../../store/session'
import AiSourceTag from '../../components/AiSourceTag.vue'

const props = defineProps({ id: String })
const router = useRouter()
const limits = computed(() => session.meta.limits)

const form = reactive({
  title: '', location: '', start_at: null, end_at: null, deadline_at: null,
  capacity: 50, tags: [], summary: '', notes: [],
})
const status = ref('DRAFT')
const locked = computed(() => status.value !== 'DRAFT') // 已发布：时间、地点、名额、截止时间不可直接改
const aiCallId = ref(null)
const description = ref('')
const ai = ref(null) // 最近一次 AI 生成的返回（来源、预检问题）
const issues = ref([]) // 发布或保存时 CONTENT_INVALID 的逐条问题
const busy = ref('')

onMounted(async () => {
  if (!props.id) return
  try {
    const act = await api.get(`/organizer/activities/${props.id}`)
    Object.keys(form).forEach((k) => (form[k] = act[k]))
    status.value = act.status
    aiCallId.value = act.ai_call_id
  } catch (e) {
    ElMessage.error(errorText(e))
  }
})

async function generate() {
  const missing = ['title', 'location', 'start_at', 'end_at'].filter((k) => !form[k])
  if (missing.length || !description.value.trim()) {
    return ElMessage.warning('请先填写标题、时间、地点、名额和一句话描述')
  }
  busy.value = 'ai'
  try {
    const r = await api.post('/organizer/ai/generate', {
      title: form.title, location: form.location, start_at: form.start_at, end_at: form.end_at,
      capacity: form.capacity, description: description.value.trim(),
    })
    form.summary = r.summary
    form.tags = r.tags
    form.notes = r.notes
    aiCallId.value = r.ai_call_id
    ai.value = r
    ElMessage.success('已填入表单，请核对修改后再保存')
  } catch (e) {
    ElMessage.error(errorText(e))
  } finally {
    busy.value = ''
  }
}

function payload() {
  const display = { title: form.title, summary: form.summary, tags: form.tags, notes: form.notes.filter((n) => n.trim()) }
  if (locked.value) return display
  return { ...display, location: form.location, start_at: form.start_at, end_at: form.end_at,
           deadline_at: form.deadline_at, capacity: form.capacity, ai_call_id: aiCallId.value }
}

async function save() {
  issues.value = []
  const act = props.id
    ? await api.put(`/organizer/activities/${props.id}`, payload())
    : await api.post('/organizer/activities', payload())
  return act.id
}

async function submit(publish) {
  busy.value = publish ? 'publish' : 'save'
  try {
    const id = await save()
    if (publish) {
      await api.post(`/organizer/activities/${id}/publish`)
      ElMessage.success('已发布')
    } else {
      ElMessage.success('已保存')
    }
    router.push(`/organizer/activities/${id}`)
  } catch (e) {
    if (e.code === 'CONTENT_INVALID') {
      issues.value = e.details
      ElMessage.error('内容校验未通过，请按提示修改')
    } else {
      ElMessage.error(errorText(e))
    }
  } finally {
    busy.value = ''
  }
}
</script>

<template>
  <div class="page" v-if="session.meta">
    <el-card shadow="never">
      <template #header>{{ props.id ? '编辑活动' : '新建活动' }}</template>
      <el-form label-width="110px" style="max-width: 820px">
        <el-form-item label="标题" required>
          <el-input v-model="form.title" :maxlength="limits.title_max_len" show-word-limit />
        </el-form-item>
        <el-alert v-if="locked" type="info" :closable="false" style="margin-bottom: 18px"
                  title="活动已发布：名额、时间、地点、截止时间请在活动管理页点「调整名额 / 时间 / 地点」，先预览影响再确认" />
        <el-form-item label="地点" required>
          <el-input v-model="form.location" :disabled="locked" />
        </el-form-item>
        <el-form-item label="开始 / 结束" required>
          <div class="row">
            <el-date-picker v-model="form.start_at" type="datetime" value-format="YYYY-MM-DDTHH:mm:ssZ"
                            format="YYYY-MM-DD HH:mm" placeholder="开始时间" :disabled="locked" />
            <el-date-picker v-model="form.end_at" type="datetime" value-format="YYYY-MM-DDTHH:mm:ssZ"
                            format="YYYY-MM-DD HH:mm" placeholder="结束时间" :disabled="locked" />
          </div>
        </el-form-item>
        <el-form-item label="报名截止" required>
          <el-date-picker v-model="form.deadline_at" type="datetime" value-format="YYYY-MM-DDTHH:mm:ssZ"
                          format="YYYY-MM-DD HH:mm" placeholder="报名截止时间" :disabled="locked" />
        </el-form-item>
        <el-form-item label="名额" required>
          <el-input-number v-model="form.capacity" :min="1" :max="limits.capacity_max" :disabled="locked" />
        </el-form-item>

        <el-divider>AI 辅助撰写</el-divider>
        <el-form-item label="一句话描述">
          <div class="row" style="width: 100%">
            <el-input v-model="description" type="textarea" :rows="2" maxlength="500" style="flex: 1"
                      placeholder="例如：请校友讲讲大厂后端面试经验，欢迎大三大四" />
            <el-button type="primary" :loading="busy === 'ai'" @click="generate">AI 生成</el-button>
          </div>
        </el-form-item>
        <el-form-item v-if="ai" label="生成来源">
          <div style="width: 100%">
            <AiSourceTag :source="ai.source" kind="generate" />
            <el-alert v-for="(i, k) in ai.issues" :key="k" class="mt" type="error" :closable="false"
                      :title="`预检：${i.message}（${i.text}）`" />
          </div>
        </el-form-item>

        <el-form-item label="简介">
          <el-input v-model="form.summary" type="textarea" :rows="5" :maxlength="limits.summary_max_len" show-word-limit />
        </el-form-item>
        <el-form-item label="标签">
          <el-select v-model="form.tags" multiple :multiple-limit="limits.tags_max" placeholder="从标签库中选择" style="width: 100%">
            <el-option v-for="t in session.meta.tag_library" :key="t" :value="t" :label="t" />
          </el-select>
        </el-form-item>
        <el-form-item label="注意事项">
          <div style="width: 100%">
            <div v-for="(n, i) in form.notes" :key="i" class="row" style="margin-bottom: 8px">
              <el-input v-model="form.notes[i]" :maxlength="limits.note_max_len" show-word-limit style="flex: 1" />
              <el-button link type="danger" @click="form.notes.splice(i, 1)">删除</el-button>
            </div>
            <el-button v-if="form.notes.length < limits.notes_max_items" link type="primary"
                       @click="form.notes.push('')">+ 添加一条</el-button>
          </div>
        </el-form-item>

        <el-form-item v-if="issues.length" label="校验问题">
          <div style="width: 100%">
            <el-alert v-for="(i, k) in issues" :key="k" type="error" :closable="false" style="margin-bottom: 6px"
                      :title="`${i.message}（原文：${i.text || '—'}）`" />
          </div>
        </el-form-item>

        <el-form-item>
          <el-button :loading="busy === 'save'" @click="submit(false)">保存</el-button>
          <el-button v-if="status === 'DRAFT'" type="primary" :loading="busy === 'publish'" @click="submit(true)">
            保存并发布
          </el-button>
        </el-form-item>
      </el-form>
    </el-card>
  </div>
</template>
