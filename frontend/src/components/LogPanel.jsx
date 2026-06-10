import { useState, useEffect, useRef } from "react"

/**
 * LogPanel — 运行日志面板
 * 实时显示阶段执行过程中的 SSE 事件流，支持自动滚动
 */
export default function LogPanel({
  logs = [],
  isRunning = false,
  elapsed = 0,
  language = "zh",
  onClear = null,
  activeProject = null,
  emptyMessage = null,
}) {
  const listRef = useRef(null)
  const [autoScroll, setAutoScroll] = useState(true)

  useEffect(() => {
    if (autoScroll && listRef.current) {
      listRef.current.scrollTop = listRef.current.scrollHeight
    }
  }, [logs, autoScroll])

  const handleScroll = (e) => {
    const el = e.target
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 30
    setAutoScroll(atBottom)
  }

  const formatTime = (s) => {
    const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60
    return h > 0 ? `${h}h ${m}m ${sec}s` : `${m}m ${sec}s`
  }

  const statusIcon = (status) => {
    switch (status) {
      case "start": return "▶"
      case "done": case "finished": return "✅"
      case "paused": return "⏸"
      case "error": return "❌"
      case "warning": return "⚠"
      case "info": return "ℹ"
      default: return "•"
    }
  }

  const defaultEmpty = language === "zh"
    ? "在左侧项目阶段标签点击「启动」按钮，或在工具栏点击「启动阶段」后，AI 生成过程会实时显示在这里。"
    : "Click 'Start' on a stage in the sidebar or 'Run Stage' in the toolbar. AI generation progress will appear here in real time."

  return (
    <div className="log-panel">
      <div className="log-panel-header">
        <div className="log-panel-title">
          <span style={{ fontSize: 16 }}>📜</span>
          <span>{language === "zh" ? "运行日志" : "Run Logs"}</span>
          {isRunning && (
            <span className="log-panel-running">
              <span className="running-dot" /> {language === "zh" ? "运行中" : "Running"}
            </span>
          )}
          {isRunning && (
            <span className="log-panel-timer">⏱ {formatTime(elapsed)}</span>
          )}
        </div>
        <div className="log-panel-actions">
          <span style={{ fontSize: 11, opacity: 0.6 }}>
            {language === "zh" ? `共 ${logs.length} 条` : `${logs.length} entries`}
          </span>
          {!autoScroll && (
            <button className="wb-btn-sm" onClick={() => { setAutoScroll(true); if (listRef.current) listRef.current.scrollTop = listRef.current.scrollHeight }}
              title={language === "zh" ? "跳到底部" : "Jump to bottom"}>
              ⬇
            </button>
          )}
          {onClear && (
            <button className="wb-btn-sm" onClick={onClear}
              title={language === "zh" ? "清空" : "Clear"}>
              🗑
            </button>
          )}
        </div>
      </div>

      <div className="log-panel-list" ref={listRef} onScroll={handleScroll}>
        {logs.length === 0 ? (
          <div className="log-panel-empty">
            <div style={{ fontSize: 48, marginBottom: 12, opacity: 0.3 }}>📜</div>
            <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 6 }}>
              {language === "zh" ? "暂无日志" : "No logs yet"}
            </div>
            <div style={{ fontSize: 12, opacity: 0.6, maxWidth: 320, lineHeight: 1.6 }}>
              {emptyMessage || defaultEmpty}
            </div>
            {activeProject && (
              <div style={{ marginTop: 16, fontSize: 11, opacity: 0.5 }}>
                {language === "zh" ? "当前项目：" : "Project: "} <strong>{activeProject.title || activeProject.name}</strong>
              </div>
            )}
          </div>
        ) : (
          logs.map((log, i) => (
            <div key={i} className={`log-panel-row log-status-${log.status || "info"}`}>
              <span className="log-panel-icon">{statusIcon(log.status)}</span>
              <span className="log-panel-time">
                {new Date(log.timestamp || Date.now()).toLocaleTimeString("zh-CN", { hour12: false })}
              </span>
              {log.role && <span className="log-panel-role">{log.role}</span>}
              <span className="log-panel-msg">{log.message || JSON.stringify(log)}</span>
            </div>
          ))
        )}
      </div>

      {logs.length > 0 && (
        <div className="log-panel-footer">
          <span>
            {language === "zh" ? "最后状态：" : "Last: "}
            <strong className={`log-status-${logs[logs.length - 1].status || "info"}`}>
              {logs[logs.length - 1].status}
            </strong>
          </span>
          <span style={{ opacity: 0.5 }}>
            {isRunning
              ? (language === "zh" ? "正在接收事件..." : "Receiving events...")
              : (language === "zh" ? "已停止" : "Stopped")}
          </span>
        </div>
      )}
    </div>
  )
}
