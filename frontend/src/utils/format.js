/**
 * formatTime — 将秒数格式化为可读的时长字符串
 * @param {number} s - 秒数
 * @returns {string} 如 "1h 2m 3s" 或 "5m 30s"
 */
export function formatTime(s) {
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const sec = s % 60
  return h > 0 ? `${h}h ${m}m ${sec}s` : `${m}m ${sec}s`
}

/**
 * formatTimestamp — 将时间戳格式化为可读的时间字符串
 * @param {number} timestamp - 毫秒时间戳（若为秒级会自动乘 1000）
 * @param {object} [options] - 可选参数
 * @param {boolean} [options.short=false] - 是否截取前 8 位（HH:MM:SS）
 * @returns {string} 如 "14:30:05" 或 "14:30:05"
 */
export function formatTimestamp(timestamp, { short = false } = {}) {
  const ts = timestamp || Date.now()
  // 如果时间戳小于 1e12，视为秒级
  const ms = ts < 1e12 ? ts * 1000 : ts
  const str = new Date(ms).toLocaleTimeString("zh-CN", { hour12: false })
  return short ? str.slice(0, 8) : str
}
