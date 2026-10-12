// 当前身份与公共配置：简单的 reactive 对象，不引入 Pinia（03 §3.3）
import { reactive } from 'vue'

export const session = reactive({
  userId: Number(localStorage.getItem('userId')) || null,
  users: [],
  meta: null,
  unread: 0, // 学生的未读通知数，用于导航角标
  get user() {
    return this.users.find((u) => u.id === this.userId) || null
  },
  get role() {
    return this.user ? this.user.role : null
  },
})

export function setUser(id) {
  session.userId = id
  localStorage.setItem('userId', String(id))
}
