/** 将 SSE 事件转换为可读日志条目 */
export function formatSSEEvent(data) {
  const ts = data.timestamp || Date.now()
  const status = data.status || "info"
  const role = data.role || ""

  // 人类可读的 status 映射
  const STATUS_MSG = {
    mwr_round: `MWR 第 ${data.round}/${data.max_rounds || 5} 轮`,
    manager_decided: `Manager 决策: ${data.action === "write" ? "撰写" : data.action === "polish" ? "润色" : data.action === "review" ? "审校" : data.action}`,
    chapter_writing: `正在撰写第 ${data.chapter} 章`,
    chapter_written: `第 ${data.chapter} 章撰写完成`,
    chapter_polishing: `正在润色第 ${data.chapter} 章 (第 ${data.polish_round} 轮)`,
    chapter_polished: `第 ${data.chapter} 章润色完成`,
    writer_done: `Writer 完成第 ${data.round} 轮`,
    reviewer_done: `Reviewer 评分: ${data.score}/10${data.issues?.length ? " — " + data.issues.slice(0, 3).join("; ") : ""}`,
    cycle_completed: `MWR 循环通过 (评分 ${data.score})`,
    cycle_stuck: `连续相同问题未解决，提前退出`,
    cycle_ended: data.accepted ? "MWR 循环通过" : `MWR 循环结束: ${data.reason || "未通过"}`,
    cycle_cancelled: "已取消",
    outline_layer_done: `${data.layer} 大纲完成`,
    outline_layer_start: `开始 ${data.layer} 大纲`,
    outline_done: "大纲生成完成",
    writing_done: "写作完成",
    reviewing: `正在审校第 ${data.chapter} 章 - ${data.dimension_name || data.dimension}`,
    review_dim_done: data.message || `第 ${data.chapter} 章 ${data.dimension_name || data.dimension} 审校完成`,
    review_done: "审校完成",
    review_cancelled: `审校已暂停: 第 ${data.chapter || ""}章`,
    done: "完成",
    error: `错误: ${data.message || data.reason || "未知错误"}`,
    info: data.message || "",
  }

  const message = STATUS_MSG[status] || data.message || data.reason || status
  // 映射 status 到日志级别
  let logStatus = "info"
  if (["error", "cycle_cancelled"].includes(status)) logStatus = "error"
  else if (["cycle_stuck", "cycle_ended"].includes(status) && !data.accepted) logStatus = "warning"
  else if (["done", "cycle_completed", "cycle_ended", "outline_done", "writing_done", "review_done", "review_dim_done", "chapter_written", "chapter_polished", "outline_layer_done", "reviewer_done", "writer_done"].includes(status)) logStatus = "done"
  else if (["chapter_writing", "chapter_polishing", "mwr_round", "reviewing"].includes(status)) logStatus = "start"

  return { status: logStatus, role, message, timestamp: ts }
}

/**
 * 带心跳检测的 SSE 流读取。
 * 浏览器节流后台标签页时 reader.read() 会挂起，此函数通过检测
 * 长时间无事件来识别连接断开，而非静默丢失后续事件。
 *
 * @param {ReadableStreamDefaultReader} reader
 * @param {Object} opts
 * @param {Function} opts.onData       - 收到 data: 行时的回调 (parsed JSON)
 * @param {Function} opts.onTimeout    - 心跳超时回调（30秒无任何数据）
 * @param {number}   opts.timeoutMs    - 超时阈值，默认 30000
 */
export async function readSSEStream(reader, { onData, onTimeout, timeoutMs = 30000 }) {
  const decoder = new TextDecoder()
  let lastEventTime = Date.now()
  let timer = null
  let stopped = false

  const checkHeartbeat = () => {
    if (stopped) return
    if (Date.now() - lastEventTime > timeoutMs) {
      stopped = true
      clearInterval(timer)
      try { reader.cancel() } catch {}
      onTimeout()
    }
  }

  timer = setInterval(checkHeartbeat, 5000)

  try {
    let buffer = ''
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      lastEventTime = Date.now()
      buffer += decoder.decode(value, { stream: true })
      // 按双换行分割 SSE 事件（兼容 \r\n 和 \n）
      const parts = buffer.split(/\r?\n\r?\n/)
      // 最后一段可能不完整，保留在 buffer
      buffer = parts.pop() || ''
      for (const part of parts) {
        for (const line of part.split(/\r?\n/)) {
          if (line.startsWith('data: ')) {
            try {
              const data = JSON.parse(line.slice(6))
              onData(data)
            } catch (e) {
              console.warn('[SSE] JSON parse error:', e)
            }
          }
        }
      }
    }
  } finally {
    stopped = true
    clearInterval(timer)
  }
}
