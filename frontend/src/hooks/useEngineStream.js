import { useState, useCallback, useRef, useEffect } from "react"
import { API_BASE } from "../constants"
import { formatSSEEvent, readSSEStream } from "../utils/sse"

export function useEngineStream(showNotification, loadProject, fetchProjects, t) {
  const [isRunning, setIsRunning] = useState(false)
  const [runningStage, setRunningStage] = useState(null)  // "outline" | "writing" | "review"
  const [kgRefreshKey, setKgRefreshKey] = useState(0)  // 递增触发 KG 刷新

  const engineAbortRef = useRef(null)  // 当前正在跑的 SSE 请求，可被 stopTask 取消
  const logPollTimerRef = useRef(null)  // 超时后轮询日志的定时器

  // 停止日志轮询
  const stopLogPolling = useCallback(() => {
    if (logPollTimerRef.current) {
      clearInterval(logPollTimerRef.current)
      logPollTimerRef.current = null
    }
  }, [])

  // SSE 超时后自动拉取最新日志并持续轮询
  const startLogPolling = useCallback((name, onLogEvent) => {
    stopLogPolling()
    const fetchLatest = async () => {
      try {
        const resp = await fetch(`${API_BASE}/v2/projects/${encodeURIComponent(name)}/logs?limit=100`)
        if (!resp.ok) return
        const data = await resp.json()
        const logs = (data.logs || []).map(evt => formatSSEEvent({ ...evt, timestamp: evt.timestamp || Date.now() }))
        if (logs.length > 0 && onLogEvent) {
          // 用最新日志替换（由调用方决定如何处理）
          onLogEvent({ type: "replace", logs })
        }
        // 检查引擎是否还在跑
        const stateResp = await fetch(`${API_BASE}/v2/projects/${encodeURIComponent(name)}/engine/state`)
        if (stateResp.ok) {
          const state = await stateResp.json()
          const writing = state?.writing || {}
          if (writing.status === "completed" || writing.status === "failed" || writing.status === "cancelled") {
            stopLogPolling()
            return
          }
        }
      } catch {}
    }
    fetchLatest()
    logPollTimerRef.current = setInterval(fetchLatest, 5000)
  }, [stopLogPolling])

  const stopTask = useCallback(async (name) => {
    try {
      // 停止新引擎
      await fetch(`${API_BASE}/v2/projects/${encodeURIComponent(name)}/engine/stop`, { method: "POST" }).catch(() => {})
      // 中断前端 SSE 请求
      if (engineAbortRef.current) { try { engineAbortRef.current.abort() } catch (e) {} }
      stopLogPolling()
      setIsRunning(false)
      setRunningStage(null)
      showNotification && showNotification(t?.("taskStopped") || "已停止", "info")
      await loadProject(name)
    } catch (e) {
      showNotification && showNotification("停止失败: " + e.message, "error")
    }
  }, [showNotification, loadProject, t, stopLogPolling])

  // ---------- 引擎：通用 SSE 启动流（三个阶段共享） ----------
  const _startEngineStream = useCallback(async (name, {
    stage, url, body, doneMessage, errorPrefix, abortMessage, onLogEvent = null, onDataExtra = null,
  }) => {
    // 先 abort 残留的旧请求
    if (engineAbortRef.current) { try { engineAbortRef.current.abort() } catch (e) {} }
    setIsRunning(true)
    setRunningStage(stage)
    const abortCtrl = new AbortController()
    engineAbortRef.current = abortCtrl
    try {
      const resp = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: body ? JSON.stringify(body) : undefined,
        signal: abortCtrl.signal,
      })
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
      const reader = resp.body?.getReader()
      if (!reader) throw new Error("No stream reader")
      let timedOut = false
      await readSSEStream(reader, {
        onData(data) {
          if (onLogEvent) onLogEvent(formatSSEEvent({ ...data, timestamp: Date.now() }))
          if (data.status === "done") showNotification && showNotification(doneMessage, "success")
          if (data.status === "error") showNotification && showNotification(data.message || `${errorPrefix}出错`, "error")
          if (onDataExtra) onDataExtra(data, name)
        },
        onTimeout() { timedOut = true },
      })
      if (timedOut) {
        showNotification && showNotification("SSE 连接超时，正在自动拉取最新日志", "info")
        startLogPolling(name, onLogEvent)
      }
      await loadProject(name)
      await fetchProjects()
    } catch (e) {
      if (e?.name === "AbortError") {
        if (onLogEvent) onLogEvent({ status: "info", role: "系统", message: abortMessage, timestamp: Date.now() })
      } else {
        showNotification && showNotification(`${errorPrefix}: ${e.message}`, "error")
      }
    } finally {
      if (engineAbortRef.current === abortCtrl) engineAbortRef.current = null
      stopLogPolling()
      setIsRunning(false)
      setRunningStage(null)
    }
  }, [showNotification, loadProject, fetchProjects, stopLogPolling, startLogPolling])

  // ---------- 引擎：启动大纲生成（SSE 流式） ----------
  const engineOutlineGenerate = useCallback(async (name, { layer = "", requirements = "", onLogEvent = null } = {}) => {
    await _startEngineStream(name, {
      stage: "outline",
      url: `${API_BASE}/v2/projects/${encodeURIComponent(name)}/outline/generate/stream`,
      body: { layer, requirements },
      doneMessage: "大纲生成完成",
      errorPrefix: "大纲生成",
      abortMessage: "已停止大纲生成",
      onLogEvent,
      onDataExtra(data, projName) {
        if (data.status === "outline_layer_done" || data.status === "done") { loadProject(projName); fetchProjects() }
        if (data.status === "outline_layer_done" || data.status === "done") setKgRefreshKey(k => k + 1)
      },
    })
  }, [_startEngineStream, loadProject, fetchProjects])

  // ---------- 引擎：启动写作（SSE 流式） ----------
  const engineWritingStart = useCallback(async (name, { startChapter = 1, totalChapters = 0, onLogEvent = null } = {}) => {
    await _startEngineStream(name, {
      stage: "writing",
      url: `${API_BASE}/v2/projects/${encodeURIComponent(name)}/writing/start/stream`,
      body: { start_chapter: startChapter, total_chapters: totalChapters },
      doneMessage: "写作完成",
      errorPrefix: "写作",
      abortMessage: "已停止写作",
      onLogEvent,
      onDataExtra(data, projName) {
        if (data.status === "chapter_written" || data.status === "chapter_completed" || data.status === "done") { loadProject(projName); fetchProjects() }
        if (data.status === "chapter_completed" || data.status === "kg_ingested") setKgRefreshKey(k => k + 1)
      },
    })
  }, [_startEngineStream, loadProject, fetchProjects])

  // ---------- 引擎：启动全局审校（SSE 流式） ----------
  const engineReviewStart = useCallback(async (name, { onLogEvent = null } = {}) => {
    await _startEngineStream(name, {
      stage: "review",
      url: `${API_BASE}/v2/projects/${encodeURIComponent(name)}/review/start/stream`,
      body: null,
      doneMessage: "全局审校完成",
      errorPrefix: "审校",
      abortMessage: "已停止审校",
      onLogEvent,
      onDataExtra(data) {
        if (data.status === "reviewing") setRunningStage(`review:${data.dimension}`)
        if (data.status === "review_cancelled") showNotification && showNotification("审校已暂停，可继续", "info")
      },
    })
  }, [_startEngineStream, showNotification])

  // 切换项目时停止日志轮询
  useEffect(() => {
    stopLogPolling()
  }, [stopLogPolling]) // activeProject?.name handled by parent

  // 组件卸载时 abort 所有 SSE 请求并停止日志轮询，防止内存泄漏与僵尸连接
  useEffect(() => {
    return () => {
      if (engineAbortRef.current) {
        try { engineAbortRef.current.abort() } catch {}
        engineAbortRef.current = null
      }
      if (logPollTimerRef.current) {
        clearInterval(logPollTimerRef.current)
        logPollTimerRef.current = null
      }
    }
  }, [])

  return {
    isRunning, setIsRunning, runningStage, kgRefreshKey,
    engineAbortRef, logPollTimerRef,
    stopTask, stopLogPolling, startLogPolling,
    engineOutlineGenerate, engineWritingStart, engineReviewStart,
  }
}
