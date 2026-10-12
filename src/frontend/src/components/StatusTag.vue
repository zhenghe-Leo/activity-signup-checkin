<script setup>
// 活动阶段（phase）或报名展示状态（registration）的彩色标签
import { computed } from 'vue'
import { DISPLAY_STATUS, PHASE, statusText } from '../labels'

const props = defineProps({ phase: String, registration: Object })

const tag = computed(() => {
  if (props.phase) return PHASE[props.phase] || [props.phase, 'info']
  if (!props.registration) return ['未报名', 'info']
  const [, type] = DISPLAY_STATUS[props.registration.display_status] || ['', 'info']
  return [statusText(props.registration), type]
})
</script>

<template>
  <el-tag :type="tag[1]" disable-transitions>{{ tag[0] }}</el-tag>
</template>
