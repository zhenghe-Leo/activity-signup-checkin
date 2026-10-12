// API 客户端：附加 X-User-Id；统一处理错误（03 §3.2「前端 api 客户端」）。
// 后端错误统一为 {code, message, details?}，message 已是中文；这里只补充网络异常等前端情况的中文提示。
import { session } from '../store/session'

export class ApiError extends Error {
  constructor(code, message, details, status) {
    super(message)
    this.code = code
    this.details = details
    this.status = status
  }
}

async function request(method, path, body) {
  const headers = { 'Content-Type': 'application/json' }
  if (session.userId) headers['X-User-Id'] = String(session.userId)
  let resp
  try {
    resp = await fetch(`/api${path}`, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
    })
  } catch {
    throw new ApiError('NETWORK_ERROR', '网络异常，请稍后重试')
  }
  const data = await resp.json().catch(() => null)
  if (!resp.ok) {
    if (data && data.code) throw new ApiError(data.code, data.message, data.details, resp.status)
    throw new ApiError('HTTP_ERROR', `请求失败（${resp.status}）`, null, resp.status)
  }
  return data
}

function query(params) {
  if (!params) return ''
  const pairs = Object.entries(params).filter(([, v]) => v !== '' && v != null && v !== false)
  return pairs.length ? '?' + new URLSearchParams(pairs).toString() : ''
}

export const api = {
  get: (path, params) => request('GET', path + query(params)),
  post: (path, body) => request('POST', path, body),
  put: (path, body) => request('PUT', path, body),
  del: (path) => request('DELETE', path),
}

// 把错误转成可展示的中文：VALIDATION_ERROR 附字段名；CONTENT_INVALID 的明细由页面逐条展示
export function errorText(err) {
  if (!(err instanceof ApiError)) return '操作失败，请稍后重试'
  if (err.code === 'VALIDATION_ERROR' && Array.isArray(err.details) && err.details.length) {
    return `${err.message}：${err.details.map((d) => d.field.replace(/^body\./, '')).join('、')}`
  }
  return err.message
}
