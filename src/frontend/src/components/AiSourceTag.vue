<script setup>
// AI 结果来源（NFR-07）：模型 / 降级 + 原因（AC-20、AC-23、AC-24、AC-25）
const props = defineProps({
  source: { type: Object, required: true },
  kind: { type: String, default: 'generate' }, // generate：A1 内容生成；filter：A2 自然语言筛选
})
</script>

<template>
  <el-alert v-if="props.source.mode === 'MODEL'" type="success" :closable="false" show-icon
            :title="props.kind === 'generate'
              ? `由 AI 生成（DeepSeek · ${props.source.model}），请核对后再保存`
              : `条件由 AI 解析（DeepSeek · ${props.source.model}）`" />
  <el-alert v-else type="warning" :closable="false" show-icon
            :title="props.kind === 'generate'
              ? `AI 服务不可用（${props.source.reason_text}），已使用模板生成，请人工核对`
              : `AI 降级（${props.source.reason_text}），条件由本地规则解析`" />
</template>
