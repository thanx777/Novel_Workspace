import { useState, useCallback, useEffect, useRef } from "react"
import { API_BASE } from "../constants"

/** 将 SSE 事件转换为可读日志条目 */
function formatSSEEvent(data) {
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
    review_done: "审校完成",
    done: "完成",
    error: `错误: ${data.message || data.reason || "未知错误"}`,
    info: data.message || "",
  }

  const message = STATUS_MSG[status] || data.message || data.reason || status
  // 映射 status 到日志级别
  let logStatus = "info"
  if (["error", "cycle_cancelled"].includes(status)) logStatus = "error"
  else if (["cycle_stuck", "cycle_ended"].includes(status) && !data.accepted) logStatus = "warning"
  else if (["done", "cycle_completed", "cycle_ended", "outline_done", "writing_done", "review_done", "chapter_written", "chapter_polished", "outline_layer_done"].includes(status)) logStatus = "done"
  else if (["chapter_writing", "chapter_polishing", "mwr_round"].includes(status)) logStatus = "start"

  return { status: logStatus, role, message, timestamp: ts }
}

/**
 * v2 Project Hook — SQLite 驱动的项目中心。
 * 核心功能：
 * 1. 拉取所有项目（list）/ 单个项目详情（with chapters, memory, chat）
 * 2. 创建 / 删除项目
 * 3. 阶段执行（outline / writing / polish）
 * 4. 大纲人工审核推进或驳回
 * 5. 人工编辑章节、添加记忆
 * 6. AI 助理对话
 * 7. 项目文件读写（outline / characters）
 */
export default function useProjectV2({ showNotification, presets = [], t }) {
  const [projects, setProjects] = useState([])
  const [activeProject, setActiveProject] = useState(null)
  const [loadingList, setLoadingList] = useState(false)
  const [loadingDetail, setLoadingDetail] = useState(false)
  const [isRunning, setIsRunning] = useState(false)
  const [runningStage, setRunningStage] = useState(null)  // "outline" | "writing" | "review"
  const [kgRefreshKey, setKgRefreshKey] = useState(0)  // 递增触发 KG 刷新

  // ---------- 列表 ----------
  const fetchProjects = useCallback(async () => {
    setLoadingList(true)
    try {
      const resp = await fetch(`${API_BASE}/v2/projects`)
      if (resp.ok) {
        const data = await resp.json()
        setProjects(data.projects || [])
      }
    } catch (e) {
      console.error("[v2] fetch projects failed:", e)
    } finally {
      setLoadingList(false)
    }
  }, [])

  // ---------- 详情 ----------
  const syncChapters = useCallback(async (name) => {
    if (!name) return
    try {
      await fetch(`${API_BASE}/v2/projects/${encodeURIComponent(name)}/sync-chapters`, { method: "POST" })
    } catch (e) {
      console.error("[v2] sync chapters failed:", e)
    }
  }, [])

  const loadProject = useCallback(async (name) => {
    if (!name) return
    setLoadingDetail(true)
    try {
      // 先同步章节标题，确保数据库中的章节信息是最新的
      await syncChapters(name)

      const [projResp, chaptersResp, memoryResp, chatResp] = await Promise.all([
        fetch(`${API_BASE}/v2/projects/${encodeURIComponent(name)}`),
        fetch(`${API_BASE}/v2/projects/${encodeURIComponent(name)}/chapters`),
        fetch(`${API_BASE}/v2/projects/${encodeURIComponent(name)}/memory`),
        fetch(`${API_BASE}/v2/projects/${encodeURIComponent(name)}/chat`),
      ])

      const respData = projResp.ok ? await projResp.json() : null
      // 后端返回的是 {project, chapters, ...} 包装结构，提取 project 部分
      const project = respData && respData.project ? respData.project : respData
      const chapters = chaptersResp.ok ? (await chaptersResp.json()).chapters || [] : []
      const memory = memoryResp.ok ? (await memoryResp.json()).memory || [] : []
      const chat = chatResp.ok ? (await chatResp.json()).chat || [] : []

      setActiveProject({
        ...(project || { name }),
        chapters,
        memory,
        chat,
      })
    } catch (e) {
      console.error("[v2] load project failed:", e)
    } finally {
      setLoadingDetail(false)
    }
  }, [])

  // ---------- 创建 ----------
  const createProject = useCallback(async (payload) => {
    try {
      const resp = await fetch(`${API_BASE}/v2/projects`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      })
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
      const data = await resp.json()
      showNotification && showNotification(t?.("projectCreated") || "项目已创建", "success")
      await fetchProjects()
      return data
    } catch (e) {
      showNotification && showNotification((t?.("createFailed") || "创建失败: ") + e.message, "error")
      return null
    }
  }, [showNotification, fetchProjects, t])

  // ---------- 删除 ----------
  const deleteProject = useCallback(async (name) => {
    try {
      const resp = await fetch(`${API_BASE}/v2/projects/${encodeURIComponent(name)}`, {
        method: "DELETE",
      })
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
      showNotification && showNotification(t?.("projectDeleted") || "项目已删除", "success")
      if (activeProject?.name === name) setActiveProject(null)
      await fetchProjects()
      return true
    } catch (e) {
      showNotification && showNotification("删除失败: " + e.message, "error")
      return false
    }
  }, [showNotification, fetchProjects, activeProject, t])

  // ---------- 更新章节 ----------
  const updateChapter = useCallback(async (name, chapterIndex, body) => {
    try {
      const resp = await fetch(`${API_BASE}/v2/projects/${encodeURIComponent(name)}/chapters/${chapterIndex}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      })
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
      await loadProject(name)
      return true
    } catch (e) {
      showNotification && showNotification("更新失败: " + e.message, "error")
      return false
    }
  }, [showNotification, loadProject])

  // ---------- 添加记忆 ----------
  const addMemory = useCallback(async (name, content, memType = "note", chapterRef = 0) => {
    try {
      const resp = await fetch(`${API_BASE}/v2/projects/${encodeURIComponent(name)}/memory`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ type: memType, content, chapter_ref: chapterRef }),
      })
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
      await loadProject(name)
      return true
    } catch (e) {
      showNotification && showNotification("添加记忆失败: " + e.message, "error")
      return false
    }
  }, [showNotification, loadProject])

  // ---------- 大纲审核 ----------
  const confirmOutline = useCallback(async (name) => {
    try {
      const resp = await fetch(`${API_BASE}/v2/projects/${encodeURIComponent(name)}/confirm-outline`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
      })
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
      await loadProject(name)
      showNotification && showNotification("大纲已确认，推进至写作阶段", "success")
      return true
    } catch (e) {
      showNotification && showNotification("确认失败: " + e.message, "error")
      return false
    }
  }, [showNotification, loadProject])

  const rejectOutline = useCallback(async (name) => {
    try {
      const resp = await fetch(`${API_BASE}/v2/projects/${encodeURIComponent(name)}/reject-outline`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
      })
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
      await loadProject(name)
      showNotification && showNotification("大纲已驳回", "info")
      return true
    } catch (e) {
      showNotification && showNotification("驳回失败: " + e.message, "error")
      return false
    }
  }, [showNotification, loadProject])

  // ---------- 写作确认 ----------
  const confirmWriting = useCallback(async (name) => {
    try {
      const resp = await fetch(`${API_BASE}/v2/projects/${encodeURIComponent(name)}/confirm-writing`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
      })
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
      await loadProject(name)
      showNotification && showNotification("写作已确认，推进至审校阶段", "success")
      return true
    } catch (e) {
      showNotification && showNotification("确认失败: " + e.message, "error")
      return false
    }
  }, [showNotification, loadProject])

  // ---------- 审校确认 ----------
  const confirmReview = useCallback(async (name) => {
    try {
      const resp = await fetch(`${API_BASE}/v2/projects/${encodeURIComponent(name)}/confirm-review`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
      })
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
      await loadProject(name)
      showNotification && showNotification("审校完成，项目已标记为完成", "success")
      return true
    } catch (e) {
      showNotification && showNotification("确认失败: " + e.message, "error")
      return false
    }
  }, [showNotification, loadProject])

  // ---------- 停止 ----------
  const engineAbortRef = useRef(null)  // 当前正在跑的 SSE 请求，可被 stopTask 取消

  const stopTask = useCallback(async (name) => {
    try {
      // 停止新引擎
      await fetch(`${API_BASE}/v2/projects/${encodeURIComponent(name)}/engine/stop`, { method: "POST" }).catch(() => {})
      // 中断前端 SSE 请求
      if (engineAbortRef.current) { try { engineAbortRef.current.abort() } catch (e) {} }
      setIsRunning(false)
      setRunningStage(null)
      showNotification && showNotification(t?.("taskStopped") || "已停止", "info")
      await loadProject(name)
    } catch (e) {
      showNotification && showNotification("停止失败: " + e.message, "error")
    }
  }, [showNotification, loadProject, t])

  // ---------- AI 助理对话 ----------
  const assistantChat = useCallback(async (name, message) => {
    try {
      const presetsPayload = (presets || []).map(p => ({
        name: p.name || "", api_key: p.api_key || "",
        base_url: p.base_url || "", model: p.model || "",
        api_format: p.api_format || "openai",
        chat_template_kwargs: p.chat_template_kwargs || null,
      }))
      const resp = await fetch(`${API_BASE}/v2/projects/${encodeURIComponent(name)}/assistant/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message, presets: presetsPayload }),
      })
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
      const data = await resp.json()
      await loadProject(name)
      return data.reply || ""
    } catch (e) {
      showNotification && showNotification("AI 助理失败: " + e.message, "error")
      return ""
    }
  }, [showNotification, presets, loadProject])

  // ---------- 写入文件 ----------
  const putFile = useCallback(async (name, file, content) => {
    try {
      const resp = await fetch(`${API_BASE}/v2/projects/${encodeURIComponent(name)}/file/${encodeURIComponent(file)}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content }),
      })
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
      await loadProject(name)
      showNotification && showNotification("文件已保存", "success")
      return true
    } catch (e) {
      showNotification && showNotification("保存失败: " + e.message, "error")
      return false
    }
  }, [showNotification, loadProject])

  // ---------- 读取文件 ----------
  const getFile = useCallback(async (name, file) => {
    try {
      const resp = await fetch(`${API_BASE}/v2/projects/${encodeURIComponent(name)}/file/${encodeURIComponent(file)}`)
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
      const data = await resp.json()
      return data.content || ""
    } catch (e) {
      return ""
    }
  }, [])

  // ---------- 引擎状态 ----------
  const getEngineState = useCallback(async (name) => {
    try {
      const resp = await fetch(`${API_BASE}/v2/projects/${encodeURIComponent(name)}/engine/state`)
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
      return await resp.json()
    } catch (e) {
      return null
    }
  }, [])

  // ---------- 历史日志 ----------
  const loadRunLogs = useCallback(async (name, limit = 500) => {
    try {
      const resp = await fetch(`${API_BASE}/v2/projects/${encodeURIComponent(name)}/logs?limit=${limit}`)
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
      const data = await resp.json()
      return (data.logs || []).map(evt => formatSSEEvent({ ...evt, timestamp: evt.timestamp || Date.now() }))
    } catch (e) {
      return []
    }
  }, [])

  const clearRunLogs = useCallback(async (name) => {
    try {
      const resp = await fetch(`${API_BASE}/v2/projects/${encodeURIComponent(name)}/logs`, { method: "DELETE" })
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
      return true
    } catch (e) {
      return false
    }
  }, [])

  // ---------- 引擎：启动大纲生成（SSE 流式） ----------
  const engineOutlineGenerate = useCallback(async (name, { layer = "", requirements = "", onLogEvent = null } = {}) => {
    setIsRunning(true)
    setRunningStage("outline")
    const abortCtrl = new AbortController()
    engineAbortRef.current = abortCtrl
    try {
      const resp = await fetch(`${API_BASE}/v2/projects/${encodeURIComponent(name)}/outline/generate/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ layer, requirements }),
        signal: abortCtrl.signal,
      })
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
      const reader = resp.body?.getReader()
      if (!reader) throw new Error("No stream reader")
      const decoder = new TextDecoder()
      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        const chunk = decoder.decode(value)
        for (const line of chunk.split("\n")) {
          if (line.startsWith("data: ")) {
            try {
              const data = JSON.parse(line.slice(6))
              if (onLogEvent) onLogEvent(formatSSEEvent({ ...data, timestamp: Date.now() }))
              if (data.status === "done") showNotification && showNotification("大纲生成完成", "success")
              if (data.status === "error") showNotification && showNotification(data.message || "大纲生成出错", "error")
              // 大纲层完成时刷新项目数据
              if (data.status === "outline_layer_done" || data.status === "done") loadProject(name)
              // 大纲完成后也刷新 KG
              if (data.status === "outline_layer_done" || data.status === "done") setKgRefreshKey(k => k + 1)
            } catch (e) {}
          }
        }
      }
      await loadProject(name)
    } catch (e) {
      if (e?.name === "AbortError") {
        if (onLogEvent) onLogEvent({ status: "info", role: "系统", message: "已停止大纲生成", timestamp: Date.now() })
      } else {
        showNotification && showNotification("大纲生成失败: " + e.message, "error")
      }
    } finally {
      if (engineAbortRef.current === abortCtrl) engineAbortRef.current = null
      setIsRunning(false)
      setRunningStage(null)
    }
  }, [showNotification, loadProject])

  // ---------- 引擎：大纲 AI 对话 ----------
  const engineOutlineChat = useCallback(async (name, message, layer = "") => {
    try {
      const resp = await fetch(`${API_BASE}/v2/projects/${encodeURIComponent(name)}/outline/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message, layer }),
      })
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
      const data = await resp.json()
      return data.response || ""
    } catch (e) {
      showNotification && showNotification("大纲对话失败: " + e.message, "error")
      return ""
    }
  }, [showNotification])

  // ---------- 引擎：启动写作（SSE 流式） ----------
  const engineWritingStart = useCallback(async (name, { startChapter = 1, totalChapters = 0, onLogEvent = null } = {}) => {
    setIsRunning(true)
    setRunningStage("writing")
    const abortCtrl = new AbortController()
    engineAbortRef.current = abortCtrl
    try {
      const resp = await fetch(`${API_BASE}/v2/projects/${encodeURIComponent(name)}/writing/start/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ start_chapter: startChapter, total_chapters: totalChapters }),
        signal: abortCtrl.signal,
      })
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
      const reader = resp.body?.getReader()
      if (!reader) throw new Error("No stream reader")
      const decoder = new TextDecoder()
      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        const chunk = decoder.decode(value)
        for (const line of chunk.split("\n")) {
          if (line.startsWith("data: ")) {
            try {
              const data = JSON.parse(line.slice(6))
              if (onLogEvent) onLogEvent(formatSSEEvent({ ...data, timestamp: Date.now() }))
              if (data.status === "done") showNotification && showNotification("写作完成", "success")
              if (data.status === "error") showNotification && showNotification(data.message || "写作出错", "error")
              // 章节写完时刷新项目数据（同步章节列表和进度）
              if (data.status === "chapter_written" || data.status === "chapter_completed" || data.status === "done") loadProject(name)
              // KG 摄取完成后触发图谱刷新
              if (data.status === "chapter_completed" || data.status === "kg_ingested") setKgRefreshKey(k => k + 1)
            } catch (e) {}
          }
        }
      }
      await loadProject(name)
    } catch (e) {
      if (e?.name === "AbortError") {
        if (onLogEvent) onLogEvent({ status: "info", role: "系统", message: "已停止写作", timestamp: Date.now() })
      } else {
        showNotification && showNotification("写作失败: " + e.message, "error")
      }
    } finally {
      if (engineAbortRef.current === abortCtrl) engineAbortRef.current = null
      setIsRunning(false)
      setRunningStage(null)
    }
  }, [showNotification, loadProject])

  // ---------- 引擎：写作 AI 对话 ----------
  const engineWritingChat = useCallback(async (name, message, chapter = 0) => {
    try {
      const resp = await fetch(`${API_BASE}/v2/projects/${encodeURIComponent(name)}/writing/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message, chapter }),
      })
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
      const data = await resp.json()
      return data.response || ""
    } catch (e) {
      showNotification && showNotification("写作对话失败: " + e.message, "error")
      return ""
    }
  }, [showNotification])

  // ---------- 引擎：启动全局审校（SSE 流式） ----------
  const engineReviewStart = useCallback(async (name, { onLogEvent = null } = {}) => {
    setIsRunning(true)
    setRunningStage("review")
    const abortCtrl = new AbortController()
    engineAbortRef.current = abortCtrl
    try {
      const resp = await fetch(`${API_BASE}/v2/projects/${encodeURIComponent(name)}/review/start/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        signal: abortCtrl.signal,
      })
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
      const reader = resp.body?.getReader()
      if (!reader) throw new Error("No stream reader")
      const decoder = new TextDecoder()
      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        const chunk = decoder.decode(value)
        for (const line of chunk.split("\n")) {
          if (line.startsWith("data: ")) {
            try {
              const data = JSON.parse(line.slice(6))
              if (onLogEvent) onLogEvent(formatSSEEvent({ ...data, timestamp: Date.now() }))
              if (data.status === "done") showNotification && showNotification("全局审校完成", "success")
              if (data.status === "error") showNotification && showNotification(data.message || "审校出错", "error")
            } catch (e) {}
          }
        }
      }
      await loadProject(name)
    } catch (e) {
      if (e?.name === "AbortError") {
        if (onLogEvent) onLogEvent({ status: "info", role: "系统", message: "已停止审校", timestamp: Date.now() })
      } else {
        showNotification && showNotification("审校失败: " + e.message, "error")
      }
    } finally {
      if (engineAbortRef.current === abortCtrl) engineAbortRef.current = null
      setIsRunning(false)
      setRunningStage(null)
    }
  }, [showNotification, loadProject])

  // ---------- 引擎：获取各阶段状态 ----------
  const getOutlineState = useCallback(async (name) => {
    try {
      const resp = await fetch(`${API_BASE}/v2/projects/${encodeURIComponent(name)}/outline/state`)
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
      return await resp.json()
    } catch (e) { return null }
  }, [])

  const getWritingState = useCallback(async (name) => {
    try {
      const resp = await fetch(`${API_BASE}/v2/projects/${encodeURIComponent(name)}/writing/state`)
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
      return await resp.json()
    } catch (e) { return null }
  }, [])

  const getReviewState = useCallback(async (name) => {
    try {
      const resp = await fetch(`${API_BASE}/v2/projects/${encodeURIComponent(name)}/review/state`)
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
      return await resp.json()
    } catch (e) { return null }
  }, [])

  // ---------- 迁移旧项目 ----------
  const migrateOld = useCallback(async () => {
    try {
      const resp = await fetch(`${API_BASE}/v2/projects/migrate-old`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
      })
      const data = resp.ok ? await resp.json() : {}
      await fetchProjects()
      return data
    } catch (e) {
      return { success: false, error: e.message }
    }
  }, [fetchProjects])

  // ---------- 项目模型预设（保存到项目数据库） ----------
  const loadProjectPresets = useCallback(async (name) => {
    try {
      const resp = await fetch(`${API_BASE}/v2/projects/${encodeURIComponent(name)}/presets`)
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
      const data = await resp.json()
      return data.presets || { manager: {}, worker: {}, reviewer: {} }
    } catch (e) {
      showNotification && showNotification("加载模型预设失败: " + e.message, "error")
      return { manager: {}, worker: {}, reviewer: {} }
    }
  }, [showNotification])

  const saveProjectPresets = useCallback(async (name, { manager, worker, reviewer }) => {
    try {
      const resp = await fetch(`${API_BASE}/v2/projects/${encodeURIComponent(name)}/presets`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ manager, worker, reviewer }),
      })
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
      showNotification && showNotification("模型配置已保存到项目", "success")
      return true
    } catch (e) {
      showNotification && showNotification("保存失败: " + e.message, "error")
      return false
    }
  }, [showNotification])

  useEffect(() => {
    fetchProjects()
  }, [fetchProjects])

  return {
    // state
    projects, setProjects,
    activeProject, setActiveProject,
    loadingList, loadingDetail,
    isRunning, setIsRunning, runningStage, kgRefreshKey,

    // actions
    fetchProjects, loadProject,
    createProject, deleteProject,
    updateChapter, addMemory,
    confirmOutline, rejectOutline,
    confirmWriting, confirmReview,
    stopTask,
    assistantChat,
    putFile, getFile,
    migrateOld,
    loadProjectPresets, saveProjectPresets,
    // 新引擎 API
    getEngineState,
    loadRunLogs, clearRunLogs,
    engineOutlineGenerate, engineOutlineChat, getOutlineState,
    engineWritingStart, engineWritingChat, getWritingState,
    engineReviewStart, getReviewState,
  }
}
