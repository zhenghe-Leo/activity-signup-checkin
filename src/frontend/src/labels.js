// 状态码 → 中文文案与标签颜色
export const PHASE = {
  DRAFT: ['草稿', 'info'],
  OPEN: ['报名中', 'success'],
  CLOSED: ['已截止', 'warning'],
  ONGOING: ['进行中', 'primary'],
  ENDED: ['已结束', 'info'],
  CANCELLED: ['已取消', 'danger'],
}

export const DISPLAY_STATUS = {
  REGISTERED: ['已报名', 'success'],
  CHECKED_IN: ['已签到', 'primary'],
  WAITLISTED: ['候补中', 'warning'],
  WAITLIST_EXPIRED: ['候补失效，活动已开始', 'info'],
  CANCELLED: ['已取消', 'danger'],
}

export const NOTIFY = { NONE: '无', UNREAD: '未读', READ: '已读' }

export const ACTION = {
  CREATE: '创建', UPDATE: '编辑', PUBLISH: '发布', CANCEL_ACTIVITY: '取消活动', CODE_RESET: '生成口令',
  REGISTER: '报名', WAITLIST: '进入候补', CANCEL: '取消报名', PROMOTE: '递补',
  DEMOTE: '退回候补', CHECKIN: '签到', CHANGE_CONFIRM: '发布后变更',
}

// 接口时间为带偏移的 ISO 8601（配置时区），只截取「YYYY-MM-DD HH:mm」展示
export function fmt(iso) {
  return iso ? iso.slice(0, 16).replace('T', ' ') : '—'
}

// 报名记录的中文状态；候补带位次，活动取消导致的取消单独说明
export function statusText(reg) {
  if (!reg) return '未报名'
  if (reg.display_status === 'CANCELLED' && reg.cancel_reason === 'BY_ACTIVITY') return '已取消（活动取消）'
  const [text] = DISPLAY_STATUS[reg.display_status] || [reg.display_status]
  return reg.display_status === 'WAITLISTED' ? `${text}（第 ${reg.waitlist_position} 位）` : text
}
