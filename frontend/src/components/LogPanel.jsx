import { useState, useEffect, useRef } from "react"
import { useApp } from "../context/AppContext"
import { formatTime, formatTimestamp } from "@/utils/format"

/**
 * LogPanel — 运行日志面板
 * 实时显示阶段执行过程中的 SSE 事件流，支持自动滚动
 */
export default function LogPanel({
  logs = [],
  isRunning = false,
  elapsed = 0,
  onClear = null,
  activeProject = null,
  emptyMessage = null,
}) {
  const { t, language } = useApp()
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

  const defaultEmpty = t('logPanelDefaultEmpty')

  return (
    <div className="log-panel">
      <div className="log-panel-header">
        <div className="log-panel-title">
          <span style={{ fontSize: 16 }}>📜</span>
          <span>{t('runLogs')}</span>
          {isRunning && (
            <span className="log-panel-running">
              <span className="running-dot" /> {t('running')}
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
              title={t('jumpToBottom')}>
              ⬇
            </button>
          )}
          {onClear && (
            <button className="wb-btn-sm" onClick={onClear}
              title={t('clear')}>
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
              {t('noLogsYet')}
            </div>
            <div style={{ fontSize: 12, opacity: 0.6, maxWidth: 320, lineHeight: 1.6 }}>
              {emptyMessage || defaultEmpty}
            </div>
            {activeProject && (
              <div style={{ marginTop: 16, fontSize: 11, opacity: 0.5 }}>
                {t('currentProjectLabel')} <strong>{activeProject.title || activeProject.name}</strong>
              </div>
            )}
          </div>
        ) : (
          logs.map((log, i) => (
            <div key={i} className={`log-panel-row log-status-${log.status || "info"}`}>
              <span className="log-panel-icon">{statusIcon(log.status)}</span>
              <span className="log-panel-time">
                {formatTimestamp(log.timestamp)}
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
            {t('lastStatus')}
            <strong className={`log-status-${logs[logs.length - 1].status || "info"}`}>
              {logs[logs.length - 1].status}
            </strong>
          </span>
          <span style={{ opacity: 0.5 }}>
            {isRunning
              ? (t('receivingEvents'))
              : (t('stopped'))}
          </span>
        </div>
      )}
    </div>
  )
}
