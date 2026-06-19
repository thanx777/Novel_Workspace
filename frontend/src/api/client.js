/**
 * API Client — 封装 fetch，自动注入 JWT header
 * 为未来 exe 打包启用认证铺路
 */

const TOKEN_KEY = 'novel_workspace_token'

export function getToken() {
  return localStorage.getItem(TOKEN_KEY)
}

export function setToken(token) {
  localStorage.setItem(TOKEN_KEY, token)
}

export function clearToken() {
  localStorage.removeItem(TOKEN_KEY)
}

function getBaseUrl() {
  // 优先使用环境变量，否则用相对路径（走 vite proxy）
  return import.meta.env.VITE_API_BASE || ''
}

function buildHeaders(options = {}) {
  const headers = { ...options.headers }
  // 不设置 Content-Type 对于 FormData 的情况
  if (options.body && !(options.body instanceof FormData)) {
    headers['Content-Type'] = headers['Content-Type'] || 'application/json'
  }
  const token = getToken()
  if (token) {
    headers['Authorization'] = `Bearer ${token}`
  }
  return headers
}

/**
 * 基础 fetch 封装
 * @param {string} path — API 路径，如 /api/v2/projects
 * @param {object} options — fetch options
 * @returns {Promise<Response>}
 */
export async function apiFetch(path, options = {}) {
  const url = getBaseUrl() + path
  const headers = buildHeaders(options)
  const { headers: _, ...rest } = options
  const response = await fetch(url, { ...rest, headers })
  if (response.status === 401) {
    clearToken()
    // 不自动跳转，让调用方处理
  }
  return response
}

/** GET 请求 */
export async function apiGet(path) {
  const res = await apiFetch(path)
  if (!res.ok) throw new Error(`API GET ${path} failed: ${res.status}`)
  return res.json()
}

/** POST 请求 */
export async function apiPost(path, body) {
  const res = await apiFetch(path, {
    method: 'POST',
    body: body instanceof FormData ? body : JSON.stringify(body),
  })
  if (!res.ok) {
    const text = await res.text().catch(() => '')
    throw new Error(`API POST ${path} failed: ${res.status} ${text}`)
  }
  return res.json()
}

/** PUT 请求 */
export async function apiPut(path, body) {
  const res = await apiFetch(path, {
    method: 'PUT',
    body: JSON.stringify(body),
  })
  if (!res.ok) throw new Error(`API PUT ${path} failed: ${res.status}`)
  return res.json()
}

/** DELETE 请求 */
export async function apiDelete(path) {
  const res = await apiFetch(path, { method: 'DELETE' })
  if (!res.ok) throw new Error(`API DELETE ${path} failed: ${res.status}`)
  return res.json()
}

/** SSE 流请求 — 返回 Response 供 ReadableStream 读取 */
export async function apiSSE(path, body) {
  const res = await apiFetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'Accept': 'text/event-stream' },
    body: JSON.stringify(body),
  })
  if (!res.ok) throw new Error(`API SSE ${path} failed: ${res.status}`)
  return res
}
