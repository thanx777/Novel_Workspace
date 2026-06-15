import { useState, useEffect, useCallback } from "react"
import LogPanel from "./LogPanel"
import OutlinePanel from "./OutlinePanel"
import KnowledgeGraphView from "./KnowledgeGraphView"
import { API_BASE } from "../constants"
import useProjectV2 from "../hooks/useProjectV2"

/** 从章节内容中提取标题（与后端 _extract_chapter_title 逻辑一致） */
function extractTitleFromContent(content) {
  if (!content) return ""
  for (const raw of content.trim().split("\n")) {
    const line = raw.trim()
    if (!line) continue
    if (line.startsWith("---PREV:") || line.startsWith("---CAST:") || line.startsWith("---")) continue
    let m = line.match(/^#+\s*第[一二三四五六七八九十百千\d]+章\s*(.*)/)
    if (m && m[1].trim()) return m[1].trim()
    m = line.match(/^第[一二三四五六七八九十百千\d]+章\s+(.*)/)
    if (m && m[1].trim()) return m[1].trim()
    m = line.match(/^#+\s*(.+)/)
    if (m && m[1].trim()) {
      let title = m[1].trim().replace(/^第[一二三四五六七八九十百千\d]+章\s*/, "")
      return title.trim() || ""
    }
    continue
  }
  return ""
}

export default function Workbench({
  t, language,
  isDark, setIsDark, setLanguage, setShowWorkspaceSettings, setShowPresetSidebar, showPresetSidebar,
  presets, defaultPreset, showNotification,
  isRunning, setIsRunning, runningStage,
  agentCatalog,
  projectV2,
}) {
  // ---- Project V2 State ----
  const {
    projects, activeProject, loadingList, loadingDetail,
    createProject, deleteProject, loadProject,
    confirmOutline, rejectOutline, confirmWriting, confirmReview, stopTask,
    updateChapter, addMemory, assistantChat,
    putFile, getFile, loadProjectPresets, saveProjectPresets,
    fetchProjects,
    // 新引擎 API
    getEngineState,
    loadRunLogs, clearRunLogs,
    engineOutlineGenerate, engineOutlineChat, getOutlineState,
    engineWritingStart, engineWritingChat, getWritingState,
    engineReviewStart, getReviewState,
    kgRefreshKey,
  } = projectV2 || {}

  // ---- Editor State ----
  const [elapsed, setElapsed] = useState(0)

  // ---- Sidebar State ----
  const [activeSidePanel, setActiveSidePanel] = useState("chapters")
  const [activeRightPanel, setActiveRightPanel] = useState("chapter-editor")

  // 图谱为全屏模式（占主区域）
  const isKnowledgeMode = activeSidePanel === "knowledge"

  // ---- Run Logs (for the log panel) ----
  const [runLogs, setRunLogs] = useState([])
  const appendRunLog = useCallback((event) => {
    if (event?.type === "replace") {
      setRunLogs(event.logs || [])
      return
    }
    setRunLogs(prev => {
      const next = [...prev, event]
      // 限制最多保留 100 条
      return next.length > 100 ? next.slice(-100) : next
    })
  }, [])
  const clearRunLogsLocal = useCallback(() => {
    setRunLogs([])
    if (activeProject?.name && clearRunLogs) {
      clearRunLogs(activeProject.name)
    }
  }, [activeProject?.name, clearRunLogs])

  // 切换项目时加载历史日志
  useEffect(() => {
    if (!activeProject?.name || !loadRunLogs) { setRunLogs([]); return }
    loadRunLogs(activeProject.name).then(logs => setRunLogs(logs))
  }, [activeProject?.name])

  // ---- Editor Content State ----
  const [chapterDraft, setChapterDraft] = useState("")
  const [chapterTitle, setChapterTitle] = useState("")
  const [chapterSummary, setChapterSummary] = useState("")
  const [chapterMode, setChapterMode] = useState("read") // "read" or "edit"
  const [editDraft, setEditDraft] = useState("") // editable copy
  const [selectedChapterIndex, setSelectedChapterIndex] = useState(null)
  const [aiMode, setAiMode] = useState(false)
  const [aiInstruction, setAiInstruction] = useState("")
  const [aiLoading, setAiLoading] = useState(false)

  // Sync editDraft when chapterDraft changes
  useEffect(() => { setEditDraft(chapterDraft) }, [chapterDraft])
  const [outlineDraft, setOutlineDraft] = useState("")
  // ---- Create Project Modal ----
  const [showCreate, setShowCreate] = useState(false)
  const [newName, setNewName] = useState("")
  const [newGenre, setNewGenre] = useState("")
  const [newExtraReqs, setNewExtraReqs] = useState("")
  const [newManagerIdx, setNewManagerIdx] = useState(-1)
  const [newWorkerIdx, setNewWorkerIdx] = useState(-1)
  const [newReviewerIdx, setNewReviewerIdx] = useState(-1)
  const [newChatPreset, setNewChatPreset] = useState("")  // AI 对话模型（用于人物输入等）
  const [showModelConfig, setShowModelConfig] = useState(false)  // 模型配置折叠

  const GENRES_ZH = ["玄幻", "都市", "言情", "仙侠", "科幻", "历史", "武侠", "悬疑", "恐怖", "喜剧", "都市爽文", "系统流"]
  const GENRES_EN = ["Fantasy", "Urban", "Romance", "Xianxia", "Sci-Fi", "Historical", "Martial Arts", "Suspense", "Horror", "Comedy", "Urban Fantasy", "System Flow"]
  const GENRES = language === "zh" ? GENRES_ZH : GENRES_EN

  // ---- 引擎状态轮询 ----
  const [engineState, setEngineState] = useState(null)
  const [kgData, setKgData] = useState(null)
  useEffect(() => {
    if (!activeProject?.name || !getEngineState) { setEngineState(null); return }
    let timer
    const poll = async () => {
      const state = await getEngineState(activeProject.name)
      if (state) setEngineState(state)
    }
    poll()
    timer = setInterval(poll, 5000)
    return () => clearInterval(timer)
  }, [activeProject?.name])

  // KG 数据轮询 + kgRefreshKey 触发即时刷新
  useEffect(() => {
    if (!activeProject?.name) { setKgData(null); return }
    let timer
    const fetchKg = async () => {
      try {
        const r = await fetch(`${API_BASE}/v2/projects/${encodeURIComponent(activeProject.name)}/graph`)
        if (r.ok) { const d = await r.json(); setKgData(d) }
      } catch {}
    }
    fetchKg()
    timer = setInterval(fetchKg, 15000)
    return () => clearInterval(timer)
  }, [activeProject?.name, kgRefreshKey])

  // ---- Assistant ----
  const [assistantInput, setAssistantInput] = useState("")
  const [assistantReply, setAssistantReply] = useState("")
  const [assistantLoading, setAssistantLoading] = useState(false)

  // ---- Model Config ----
  const [projectPresets, setProjectPresets] = useState({ manager: {}, worker: {}, reviewer: {} })
  const [aiChatPreset, setAiChatPreset] = useState("")  // AI 对话模型预设名

  // ---- Project Config Editing ----
  const [editProjectName, setEditProjectName] = useState("")
  const [editProjectTitle, setEditProjectTitle] = useState("")
  const [editProjectGenre, setEditProjectGenre] = useState("")
  const [editTotalChapters, setEditTotalChapters] = useState(20)
  const [editExtraReqs, setEditExtraReqs] = useState("")

  // ---- Elapsed timer ----
  useEffect(() => {
    if (!isRunning) { setElapsed(0); return }
    const start = Date.now()
    const timer = setInterval(() => setElapsed(Math.floor((Date.now() - start) / 1000)), 1000)
    return () => clearInterval(timer)
  }, [isRunning])

  const formatTime = (s) => {
    const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60
    return h > 0 ? `${h}h ${m}m ${sec}s` : `${m}m ${sec}s`
  }

  // ---- Load project presets ----
  useEffect(() => {
    if (!activeProject?.name || !loadProjectPresets) return
    ;(async () => {
      const data = await loadProjectPresets(activeProject.name)
      const p = data || { manager: {}, worker: {}, reviewer: {}, chat: {} }
      setProjectPresets({
        manager: p.manager || {},
        worker: p.worker || {},
        reviewer: p.reviewer || {},
      })
      setAiChatPreset((p.chat && p.chat.name) || "")
    })()
  }, [activeProject?.name, loadProjectPresets])

  // ---- Handle select project ----
  const handleSelectProject = useCallback(async (name) => {
    setActiveSidePanel("chapters")
    setActiveRightPanel("chapter-editor")
    setOutlineDraft("")
    setChapterDraft("")
    setChapterTitle("")
    setChapterSummary("")
    setSelectedChapterIndex(null)
    await loadProject(name)
  }, [loadProject])

  // ---- Handle select chapter ----
  const handleSelectChapter = useCallback(async (chap) => {
    if (!activeProject) return
    setChapterMode("read")
    setChapterTitle(chap.title || "")
    setChapterSummary(chap.summary || "")
    setSelectedChapterIndex(chap.chapter_index)
    const content = await getFile(activeProject.name, `chapters/第${chap.chapter_index}章.txt`)
    setChapterDraft(content || "")
    setActiveRightPanel("chapter-editor")
  }, [activeProject, getFile])

  // ---- Save chapter ----
  const handleSaveChapter = useCallback(async () => {
    if (!activeProject) return
    const contentToSave = chapterMode === "edit" ? editDraft : chapterDraft
    // 从内容提取标题
    const newTitle = extractTitleFromContent(contentToSave)
    const finalTitle = newTitle || chapterTitle
    await updateChapter(activeProject.name, selectedChapterIndex, {
      title: finalTitle,
      summary: chapterSummary,
      content: contentToSave,
      status: "draft",
    })
    setChapterDraft(contentToSave)
    setChapterMode("read")
    // 更新侧边栏标题
    if (newTitle && activeProject.chapters) {
      setActiveProject(prev => ({
        ...prev,
        chapters: prev.chapters.map(c =>
          c.chapter_index === selectedChapterIndex
            ? { ...c, title: newTitle }
            : c
        )
      }))
    }
  }, [activeProject, chapterMode, editDraft, chapterTitle, chapterSummary, chapterDraft, selectedChapterIndex, updateChapter])

  // ---- AI Edit chapter ----
  const handleAiEdit = useCallback(async () => {
    if (!activeProject?.name || !selectedChapterIndex || !aiInstruction.trim()) return
    setAiLoading(true)
    try {
      const resp = await fetch(`${API_BASE}/v2/projects/${encodeURIComponent(activeProject.name)}/chapters/${selectedChapterIndex}/ai-edit`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ instruction: aiInstruction.trim() })
      })
      if (!resp.ok) {
        const err = await resp.json().catch(() => ({}))
        throw new Error(err.detail || err.error || `HTTP ${resp.status}`)
      }
      const data = await resp.json()
      if (data.error) {
        showNotification && showNotification(data.error, "error")
        return
      }
      if (data.content) {
        setEditDraft(data.content)
        setChapterDraft(data.content)
        setChapterMode("edit")
        setAiMode(false)
        setAiInstruction("")
        // 更新侧边栏标题
        const newTitle = extractTitleFromContent(data.content)
        if (newTitle && activeProject.chapters) {
          setActiveProject(prev => ({
            ...prev,
            chapters: prev.chapters.map(c =>
              c.chapter_index === selectedChapterIndex
                ? { ...c, title: newTitle }
                : c
            )
          }))
        }
        showNotification && showNotification(language === "zh" ? "AI修改完成，请确认后保存" : "AI edit done, please confirm and save", "success")
      }
    } catch (e) {
      showNotification && showNotification((language === "zh" ? "AI修改失败: " : "AI edit failed: ") + e.message, "error")
    } finally {
      setAiLoading(false)
    }
  }, [activeProject, selectedChapterIndex, aiInstruction, showNotification, language])

  // ---- Save outline ----
  const handleSaveOutline = useCallback(async () => {
    if (!activeProject) return
    await putFile(activeProject.name, "outline.md", outlineDraft)
    showNotification && showNotification("大纲已保存", "success")
  }, [activeProject, outlineDraft, putFile, showNotification])

  // ---- Open outline editor ----
  const handleOpenOutline = useCallback(async () => {
    if (!activeProject) return
    // 读取三层大纲合并显示
    const [l1, l2, l3] = await Promise.all([
      getFile(activeProject.name, "outline_L1.md"),
      getFile(activeProject.name, "outline_L2.md"),
      getFile(activeProject.name, "outline_L3.md"),
    ])
    const parts = []
    if (l1) parts.push(l1.startsWith("#") ? l1 : "# L1 完整版大纲\n\n" + l1)
    if (l2) parts.push(l2.startsWith("#") ? l2 : "# L2 网文版大纲\n\n" + l2)
    if (l3) parts.push(l3.startsWith("#") ? l3 : "# L3 单章细纲\n\n" + l3)
    setOutlineDraft(parts.join("\n\n---\n\n") || "")
    setActiveSidePanel("outline")
    setActiveRightPanel("outline-editor")
  }, [activeProject, getFile])

  // ---- Auto-load outline content (for sidebar preview) ----
  const handleShowOutlinePanel = useCallback(async () => {
    if (!activeProject) return
    setActiveSidePanel("outline")
    // 自动加载大纲内容以显示在侧边面板
    if (!outlineDraft) {
      const [l1, l2, l3] = await Promise.all([
        getFile(activeProject.name, "outline_L1.md"),
        getFile(activeProject.name, "outline_L2.md"),
        getFile(activeProject.name, "outline_L3.md"),
      ])
      const parts = []
      if (l1) parts.push(l1.startsWith("#") ? l1 : "# L1 完整版大纲\n\n" + l1)
      if (l2) parts.push(l2.startsWith("#") ? l2 : "# L2 网文版大纲\n\n" + l2)
      if (l3) parts.push(l3.startsWith("#") ? l3 : "# L3 单章细纲\n\n" + l3)
      setOutlineDraft(parts.join("\n\n---\n\n") || "")
    }
  }, [activeProject, getFile, outlineDraft])

  // ---- Open project config ----
  const handleOpenProjectConfig = useCallback(() => {
    if (!activeProject) return
    setEditProjectName(activeProject.name || "")
    setEditProjectTitle(activeProject.title || "")
    setEditProjectGenre(activeProject.genre || "")
    setEditTotalChapters(activeProject.total_chapters || 0)
    // 加载附加要求
    getFile(activeProject.name, "extra_requirements.txt").then(content => {
      setEditExtraReqs(content || "")
    })
    setActiveRightPanel("modelconfig-editor")
  }, [activeProject, getFile])

  // ---- Save project info ----
  const handleSaveProjectInfo = useCallback(async () => {
    if (!activeProject) return
    try {
      const resp = await fetch(`${API_BASE}/v2/projects/${encodeURIComponent(activeProject.name)}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          title: editProjectTitle,
          genre: editProjectGenre,
          total_chapters: Number(editTotalChapters) || 0,
        }),
      })
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
      // 保存附加要求
      if (editExtraReqs) {
        await putFile(activeProject.name, "extra_requirements.txt", editExtraReqs)
      }
      await loadProject(activeProject.name)
      showNotification && showNotification("项目信息已保存", "success")
    } catch (e) {
      showNotification && showNotification("保存失败: " + e.message, "error")
    }
  }, [activeProject, editProjectTitle, editProjectGenre, editTotalChapters, editExtraReqs, loadProject, showNotification, putFile])

  // ---- Create project ----
  const handleCreateProject = useCallback(async () => {
    if (!newName.trim()) {
      showNotification && showNotification("请输入项目名称", "error")
      return
    }
    const rolePresets = {}
    // 如果有默认预设，自动应用到所有角色
    const defaultPresetObj = defaultPreset ? presets?.find(p => p.name === defaultPreset) : null
    if (newManagerIdx >= 0 && presets?.[newManagerIdx]) rolePresets.manager = presets[newManagerIdx]
    else if (defaultPresetObj) rolePresets.manager = defaultPresetObj
    if (newWorkerIdx >= 0 && presets?.[newWorkerIdx]) rolePresets.worker = presets[newWorkerIdx]
    else if (defaultPresetObj) rolePresets.worker = defaultPresetObj
    if (newReviewerIdx >= 0 && presets?.[newReviewerIdx]) rolePresets.reviewer = presets[newReviewerIdx]
    else if (defaultPresetObj) rolePresets.reviewer = defaultPresetObj
    // AI 对话模型：按名字查找预设对象
    if (newChatPreset && presets) {
      const found = presets.find(p => p.name === newChatPreset)
      if (found) rolePresets.chat = found
    } else if (defaultPresetObj) {
      rolePresets.chat = defaultPresetObj
    }
    const result = await createProject({
      name: newName.trim(),
      title: "",  // 标题由大纲生成阶段产生
      genre: newGenre,
      total_chapters: 0,
      outline_layers: { L1: true, L2: true },
      extra_requirements: newExtraReqs.trim(),
      role_presets: rolePresets,
    })
    if (result) {
      setNewName("")
      setNewGenre("")
      setNewExtraReqs("")
      setNewManagerIdx(-1); setNewWorkerIdx(-1); setNewReviewerIdx(-1)
      setNewChatPreset("")
      setShowModelConfig(false)
      setShowCreate(false)
    }
  }, [newName, newGenre, newExtraReqs, newManagerIdx, newWorkerIdx, newReviewerIdx, newChatPreset, createProject, showNotification, presets, defaultPreset])

  // ---- Assistant chat ----
  const handleAssistantSend = useCallback(async () => {
    if (!activeProject || !assistantInput.trim()) return
    setAssistantLoading(true)
    const reply = await assistantChat(activeProject.name, assistantInput.trim())
    setAssistantReply(reply || "(无回复)")
    setAssistantLoading(false)
    setAssistantInput("")
  }, [activeProject, assistantInput, assistantChat])

  // ---- Delete project (with confirmation modal) ----
  const [confirmDeleteProject, setConfirmDeleteProject] = useState(null)
  const [deleting, setDeleting] = useState(false)
  const handleDeleteProject = useCallback((name) => {
    setConfirmDeleteProject(name)
  }, [])
  const confirmDelete = useCallback(async () => {
    if (!confirmDeleteProject || deleting) return
    setDeleting(true)
    try {
      await deleteProject(confirmDeleteProject)
      setConfirmDeleteProject(null)
      showNotification && showNotification("项目已删除", "success")
    } catch (e) {
      showNotification && showNotification("删除失败: " + e.message, "error")
    } finally {
      setDeleting(false)
    }
  }, [confirmDeleteProject, deleting, deleteProject, showNotification])

  // ---- Add memory ----
  const handleAddMemory = useCallback(async (content, memType = "note") => {
    if (!activeProject) return
    await addMemory(activeProject.name, content, memType)
    showNotification && showNotification("记忆已添加", "success")
  }, [activeProject, addMemory, showNotification])

  // ---- Stop task ----
  const handleStopTask = useCallback(async () => {
    if (activeProject && stopTask) {
      await stopTask(activeProject.name)
    }
    setIsRunning(false)
  }, [activeProject, stopTask, setIsRunning])

  // ---- Stage label ----
  const stageLabel = (s) => ({ outline: "大纲制作", writing: "正文写作", polish: "润色审校", completed: "已完成" }[s] || s)

  // ---- Sidebar tabs ----
  const SIDE_TABS = [
    { key: "chapters", label: language === "zh" ? "章节" : "Chapters", icon: "📖" },
    { key: "outline", label: language === "zh" ? "大纲" : "Outline", icon: "📋" },
    { key: "knowledge", label: language === "zh" ? "图谱" : "Graph", icon: "🕸" },
    { key: "characters", label: language === "zh" ? "人物" : "Chars", icon: "👤" },
    { key: "tasks", label: language === "zh" ? "阶段" : "Stages", icon: "🚀" },
    { key: "logs", label: language === "zh" ? "日志" : "Logs", icon: "📜" },
  ]

    return (
    <div className="wb-container">
      {/* ==================== Toolbar ==================== */}
      <div className="wb-toolbar">
        <div className="wb-toolbar-left">
          <div className="toolbar-brand">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
              <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/>
              <path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/>
              <line x1="8" y1="7" x2="16" y2="7"/>
              <line x1="8" y1="11" x2="14" y2="11"/>
            </svg>
            <span>{language === "zh" ? "小说工坊" : "Novel Forge"}</span>
          </div>
          <div className="toolbar-divider" />
          <button className={`toolbar-btn ${showPresetSidebar ? "active" : ""}`} onClick={() => setShowPresetSidebar(!showPresetSidebar)} title={t("presets")}>
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"/><line x1="3" y1="9" x2="21" y2="9"/><line x1="9" y1="21" x2="9" y2="9"/></svg>
            {t("presets")}
          </button>
          <button className="toolbar-btn" onClick={() => setShowWorkspaceSettings(true)} title={t("settings")}>
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>
            {t("settings")}
          </button>
          <div className="toolbar-divider" />
          <button className="wb-btn wb-btn-new" onClick={() => setShowCreate(true)} disabled={isRunning}>
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
            {language === "zh" ? "新项目" : "New Project"}
          </button>
          {activeProject && (
            <>
              <button className={`wb-btn ${activeRightPanel === "logs" ? "active" : ""}`}
                onClick={() => setActiveRightPanel(activeRightPanel === "logs" ? "chapter-editor" : "logs")}
                title={language === "zh" ? "运行日志" : "Run Logs"}>
                📜 {language === "zh" ? "日志" : "Logs"}
                {runLogs.length > 0 && (
                  <span style={{ marginLeft: 4, padding: "0 5px", borderRadius: 8, background: "var(--accent)", color: "#fff", fontSize: 9, fontWeight: 700, minWidth: 14, display: "inline-block", textAlign: "center" }}>
                    {runLogs.length > 99 ? "99+" : runLogs.length}
                  </span>
                )}
              </button>
              {isRunning && (
                <button className="wb-btn wb-btn-stop" onClick={() => stopTask(activeProject?.name)}>
                  ⏹ {language === "zh" ? "停止" : "Stop"}
                </button>
              )}
            </>
          )}
        </div>
        <div className="wb-toolbar-right">
          {isRunning && <span className="wb-timer">⏱ {formatTime(elapsed)}</span>}
          {activeProject && (
            <span className="wb-progress">
              {activeProject.chapters_done || 0}/{activeProject.total_chapters || "待定"} {language === "zh" ? "章" : "ch"}
            </span>
          )}
          <div className="toolbar-divider" />
          <button className="toolbar-btn lang-toggle" onClick={() => setLanguage(l => l === "zh" ? "en" : "zh")}>
            {language === "en" ? "中文" : "EN"}
          </button>
          <button className="toolbar-btn theme-toggle" onClick={() => setIsDark(!isDark)}>
            {isDark ? (
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="5"/><path d="M12 1v2m0 18v2M21 12h2M1 12h2m16.95-6.95l1.414 1.414M2.636 21.364l1.414-1.414M4.636 4.636l1.414 1.414M17.95 19.364l1.414-1.414"/></svg>
            ) : (
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M21 12.79A9 9 0 1111.21 3 7 7 0 0021 12.79z"/></svg>
            )}
          </button>
        </div>
      </div>

      {/* ==================== Body ==================== */}
      <div className="wb-body">
        {/* ---- Left Sidebar ---- */}
        <aside className="wb-sidebar">
          {/* 项目列表 */}
          <div className="wb-sidebar-tabs" style={{ borderBottom: "1px solid var(--border)" }}>
            <div className="project-list-header">
              <span style={{ fontSize: 11, fontWeight: 600, opacity: 0.7 }}>
                📚 {language === "zh" ? "项目" : "Projects"} ({projects?.length || 0})
              </span>
            </div>
          </div>
          <div className="wb-sidebar-content" style={{ padding: 0 }}>
            {/* 项目列表 */}
            <div className="project-list-scroll">
              {loadingList && <div className="side-panel-empty">加载中...</div>}
              {!loadingList && (!projects || projects.length === 0) && (
                <div className="side-panel-empty" style={{ fontSize: 11 }}>
                  {language === "zh" ? "暂无项目，点击上方「新项目」" : "No projects yet"}
                </div>
              )}
              {projects?.map((p) => {
                const active = activeProject?.name === p.name
                return (
                  <div key={p.name} className={`wb-project-item ${active ? "active" : ""}`}
                    onClick={() => handleSelectProject(p.name)}>
                    <div className="wb-project-title">{p.title || p.name}</div>
                    <div className="wb-project-meta">
                      <span className={`stage-badge stage-${p.current_stage || "outline"}`}>
                        {stageLabel(p.current_stage || "outline")}
                      </span>
                      <span>{p.genre || ""}</span>
                      <span>{p.chapters_done || 0}/{p.total_chapters || "待定"} 章</span>
                    </div>
                    {active && (
                      <div style={{ position: "absolute", right: 4, top: 4, display: "flex", gap: 2 }}>
                        <button className="wb-btn-sm"
                          onClick={(e) => { e.stopPropagation(); handleOpenProjectConfig() }}
                          title={language === "zh" ? "项目配置" : "Project Config"}
                          style={{ opacity: 0.6, background: "none", border: "none", cursor: "pointer", padding: 2 }}>
                          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>
                        </button>
                        <button className="wb-btn-sm wb-btn-delete"
                          onClick={(e) => { e.stopPropagation(); handleDeleteProject(p.name) }}
                          title={t("delete")}>
                          <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14H6L5 6"/></svg>
                        </button>
                      </div>
                    )}
                  </div>
                )
              })}
            </div>

            {/* 子模块 Tabs */}
            {activeProject && (
              <>
                <div className="wb-sidebar-tabs" style={{ borderTop: "1px solid var(--border)", borderBottom: "1px solid var(--border)" }}>
                  {SIDE_TABS.map(tab => (
                    <button key={tab.key}
                      className={`wb-sidebar-tab ${activeSidePanel === tab.key ? "active" : ""}`}
                      onClick={() => {
                        if (tab.key === "outline") {
                          handleOpenOutline()
                        } else if (tab.key === "characters") {
                          setActiveSidePanel(tab.key)
                        } else if (tab.key === "logs") {
                          setActiveSidePanel(tab.key)
                          setActiveRightPanel("logs")
                        } else {
                          setActiveSidePanel(tab.key)
                        }
                      }}>
                      <span className="wb-tab-icon">{tab.icon}</span>
                      <span className="wb-tab-label">{tab.label}</span>
                    </button>
                  ))}
                </div>
                <div className="wb-sidebar-content" style={{ flex: 1, overflowY: "auto" }}>
                  {/* 章节列表 */}
                  {activeSidePanel === "chapters" && (
                    <div className="chapter-items">
                      {(activeProject.chapters || []).map((c) => (
                        <div key={c.chapter_index} className="chapter-item"
                          onClick={() => handleSelectChapter(c)}>
                          <div className="chapter-item-num">{c.chapter_index}</div>
                          <div className="chapter-item-name">{c.title || (language === "zh" ? "(未命名)" : "(Untitled)")}</div>
                        </div>
                      ))}
                      {activeProject.chapters?.length === 0 && (
                        <div className="chapter-list-empty">{language === "zh" ? "无章节" : "No chapters"}</div>
                      )}
                    </div>
                  )}
                  {/* 大纲 - V2 三层 Tab + 多视图 */}
                  {activeSidePanel === "outline" && (
                    <OutlinePanel
                      t={t} language={language}
                      projectName={activeProject?.name}
                      API_BASE={API_BASE}
                      showNotification={showNotification}
                    />
                  )}
                  {/* 图谱 — KG 实体 + 人物介绍 */}
                  {activeSidePanel === "knowledge" && (
                    <div className="side-panel">
                      <div className="side-panel-header">🕸 {language === "zh" ? "图谱" : "Graph"}</div>
                      <div className="side-panel-body">
                        {/* KG 实体摘要 */}
                        {kgData && (() => {
                          const nodes = kgData.nodes || []
                          const byType = {}
                          nodes.forEach(n => { (byType[n.type] = byType[n.type] || []).push(n) })
                          const typeLabels = {
                            character: { label: language === "zh" ? "👤 角色" : "👤 Characters", color: "#6ee7b7" },
                            foreshadowing: { label: language === "zh" ? "🔮 伏笔" : "🔮 Foreshadowing", color: "#fbbf24" },
                            scene: { label: language === "zh" ? "🏞 场景" : "🏞 Scenes", color: "#93c5fd" },
                            world_fact: { label: language === "zh" ? "🌐 世界观" : "🌐 World", color: "#c4b5fd" },
                            plot_thread: { label: language === "zh" ? "🧵 剧情线" : "🧵 Plot Threads", color: "#fca5a5" },
                            chapter: { label: language === "zh" ? "📖 章节" : "📖 Chapters", color: "#67e8f9" },
                            outline_node: { label: language === "zh" ? "📋 大纲" : "📋 Outline", color: "#d1d5db" },
                            genre_rule: { label: language === "zh" ? "📕 体裁规则" : "📕 Genre Rules", color: "#f87171" },
                            strand_tag: { label: language === "zh" ? "🎯 节奏标签" : "🎯 Strand Tags", color: "#2dd4bf" },
                            coolpoint: { label: language === "zh" ? "⚡ 爽点" : "⚡ Coolpoints", color: "#fbbf24" },
                            hook: { label: language === "zh" ? "🪝 钩子" : "🪝 Hooks", color: "#a78bfa" },
                          }
                          const totalEdges = (kgData.edges || []).length
                          return (
                            <div style={{ marginBottom: 12 }}>
                              <div style={{ fontSize: 11, opacity: 0.6, marginBottom: 6 }}>
                                {language === "zh" ? `图谱 · ${nodes.length} 节点 · ${totalEdges} 关系` : `Graph · ${nodes.length} nodes · ${totalEdges} edges`}
                              </div>
                              {Object.entries(typeLabels).map(([type, { label, color }]) => {
                                const items = byType[type]
                                if (!items || items.length === 0) return null
                                return (
                                  <div key={type} style={{ marginBottom: 8 }}>
                                    <div style={{ fontSize: 11, fontWeight: 600, color, marginBottom: 2 }}>{label}（{items.length}）</div>
                                    <div style={{ paddingLeft: 8 }}>
                                      {items.slice(0, 8).map(n => (
                                        <div key={n.id} style={{ fontSize: 10, opacity: 0.85, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                                          {n.label}{n.summary && n.summary !== n.label ? `：${n.summary.slice(0, 30)}` : ""}
                                        </div>
                                      ))}
                                      {items.length > 8 && <div style={{ fontSize: 10, opacity: 0.5 }}>+{items.length - 8} ...</div>}
                                    </div>
                                  </div>
                                )
                              })}
                            </div>
                          )
                        })()}
                        {!kgData && (
                          <div className="side-panel-empty" style={{ fontSize: 11, padding: 16 }}>
                            {language === "zh" ? "暂无图谱数据，生成大纲或写作后自动构建" : "No graph data yet. Auto-built after outline or writing."}
                          </div>
                        )}

                        {/* 人物介绍 — 从 KG 角色节点实时读取 */}
                        <div style={{ borderTop: "1px solid var(--border)", paddingTop: 8, marginTop: 8 }}>
                          <div style={{ fontSize: 11, fontWeight: 600, marginBottom: 6, opacity: 0.7 }}>
                            👤 {language === "zh" ? "人物介绍" : "Character Profiles"}
                          </div>
                          {(() => {
                            const kgChars = (kgData?.nodes || []).filter(n => n.type === "character")
                            if (kgChars.length === 0) {
                              return <div style={{ fontSize: 10, opacity: 0.5 }}>{language === "zh" ? "暂无角色" : "No characters yet"}</div>
                            }
                            return kgChars.slice(0, 10).map(c => (
                              <div key={c.id} style={{ marginBottom: 6, padding: "4px 6px", background: "var(--bg-surface)", borderRadius: 4 }}>
                                <div style={{ fontSize: 11, fontWeight: 600, color: "#6ee7b7" }}>{c.label}</div>
                                {c.summary && c.summary !== c.label && (
                                  <div style={{ fontSize: 9, opacity: 0.7, marginTop: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                                    {c.summary.slice(0, 80)}
                                  </div>
                                )}
                              </div>
                            ))
                          })()}
                        </div>
                      </div>
                    </div>
                  )}
                  {/* 人物 — 从 KG 角色节点自动生成 */}
                  {activeSidePanel === "characters" && (
                    <div className="side-panel">
                      <div className="side-panel-header">👤 {language === "zh" ? "人物" : "Characters"}</div>
                      <div className="side-panel-body">
                        {/* KG 角色列表 — 实时从知识图谱读取 */}
                        {(() => {
                          const kgChars = (kgData?.nodes || []).filter(n => n.type === "character")
                          if (kgChars.length === 0) {
                            return <div style={{ fontSize: 10, opacity: 0.5, padding: 8 }}>
                              {language === "zh" ? "暂无角色，生成大纲或写作后自动提取" : "No characters yet. Auto-extracted from outline/writing."}
                            </div>
                          }
                          return kgChars.map(c => (
                            <div key={c.id} style={{ marginBottom: 6, padding: "6px 8px", background: "var(--bg-surface)", borderRadius: 4 }}>
                              <div style={{ fontSize: 11, fontWeight: 600, color: "#6ee7b7" }}>
                                {c.label}
                              </div>
                              {c.summary && c.summary !== c.label && (
                                <div style={{ fontSize: 9, opacity: 0.7, marginTop: 2, lineHeight: 1.4 }}>
                                  {c.summary.slice(0, 120)}
                                </div>
                              )}
                              {c.attrs && Object.entries(c.attrs).map(([k, v]) => (
                                <div key={k} style={{ fontSize: 9, opacity: 0.6, marginTop: 1 }}>
                                  <span style={{ fontWeight: 500 }}>{k}：</span>{String(v).slice(0, 60)}
                                </div>
                              ))}
                            </div>
                          ))
                        })()}
                      </div>
                    </div>
                  )}
                  {/* 项目阶段 */}
                  {activeSidePanel === "tasks" && (
                    <div className="side-panel">
                      <div className="side-panel-header">📋 {language === "zh" ? "项目阶段" : "Stages"}</div>
                      <div className="side-panel-body">
                        {/* 当前阶段状态 */}
                        <div style={{ marginBottom: 12, padding: 8, background: "var(--bg-surface)", borderRadius: 6 }}>
                          <div style={{ fontSize: 11, opacity: 0.6, marginBottom: 4 }}>
                            {language === "zh" ? "当前阶段" : "Current Stage"}
                          </div>
                          <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                            <span className={`stage-badge stage-${activeProject.current_stage || engineState?.current_stage || "outline"}`}>
                              {stageLabel(activeProject.current_stage || engineState?.current_stage || "outline")}
                            </span>
                            <span style={{ fontSize: 11, opacity: 0.7 }}>
                              {activeProject.chapters_done || 0}/{activeProject.total_chapters || "待定"} {language === "zh" ? "章" : "chapters"}
                            </span>
                          </div>
                          {/* 引擎状态详情 */}
                          {engineState && (
                            <div style={{ marginTop: 6, fontSize: 10, opacity: 0.7 }}>
                              {(() => {
                                const _s = activeProject.current_stage || engineState?.current_stage || "outline"
                                if (_s === "outline") return <div>{language === "zh" ? "大纲" : "Outline"}：{engineState.outline?.status || "pending"} · {language === "zh" ? "已完成层" : "Layers done"}：{(engineState.outline?.completed_layers || []).join(", ") || "—"}</div>
                                if (_s === "writing") return <div>{language === "zh" ? "写作进度" : "Writing progress"}：{engineState.writing?.progress || "0/0"}</div>
                                if (_s === "review" || _s === "polish") return <div>{language === "zh" ? "审校" : "Review"}：{engineState.review?.status || "pending"} · {language === "zh" ? "已完成维度" : "Dims done"}：{(engineState.review?.dimensions_done || []).join(", ") || "—"}</div>
                                return null
                              })()}
                            </div>
                          )}
                        </div>

                        {/* 阶段列表 — 使用新引擎 SSE 流式 API */}
                        {(() => {
                          const curStage = activeProject.current_stage || engineState?.current_stage || "outline"
                          const stageOrder = { outline: 0, writing: 1, review: 2, polish: 2, done: 3, completed: 3 }
                          const curIdx = stageOrder[curStage] ?? 0
                          return [
                            { key: "outline", label: "📖 " + (language === "zh" ? "大纲阶段" : "Outline"), desc: language === "zh" ? "MWR 循环生成大纲" : "MWR cycle outline generation", btnLabel: language === "zh" ? "生成大纲" : "Generate Outline", confirmLabel: language === "zh" ? "确认大纲" : "Confirm Outline" },
                            { key: "writing", label: "✍️ " + (language === "zh" ? "写作阶段" : "Writing"), desc: language === "zh" ? "逐章 MWR 写作+润色" : "Per-chapter MWR write+polish", btnLabel: language === "zh" ? "开始写作" : "Start Writing", confirmLabel: language === "zh" ? "确认写作" : "Confirm Writing" },
                            { key: "review", label: "🔍 " + (language === "zh" ? "审校阶段" : "Review"), desc: language === "zh" ? "按维度全局审校" : "Dimension-based global review", btnLabel: language === "zh" ? "全局审校" : "Global Review", confirmLabel: language === "zh" ? "确认完成" : "Confirm Done" },
                          ].map((stage) => {
                            const stageIdx = stageOrder[stage.key] ?? 0
                            const isCurrent = curStage === stage.key || (curStage === "polish" && stage.key === "review")
                            const isCompleted = stageIdx < curIdx
                            const isDone = curStage === "done" || curStage === "completed"
                            const isRunningThisStage = isRunning && (runningStage === stage.key || runningStage?.startsWith(stage.key + ":"))
                            // 是否可以操作此阶段（当前阶段或已完成阶段可重新运行）
                            const canOperate = isCurrent || isCompleted

                            const handleEngineAction = async () => {
                              if (!activeProject) return
                              if (isRunningThisStage) {
                                // 正在运行 → 停止
                                await stopTask(activeProject.name)
                                return
                              }
                              // 清空日志并切换到日志面板
                              clearRunLogsLocal()
                              appendRunLog({
                                status: "info", role: "系统",
                                message: `▶ 准备启动 ${stage.label} 阶段...`,
                                timestamp: Date.now(),
                              })
                              setActiveRightPanel("logs")
                              if (stage.key === "outline" && engineOutlineGenerate) {
                                // 读取项目要求传给大纲生成
                                const reqs = await getFile(activeProject.name, "extra_requirements.txt")
                                await engineOutlineGenerate(activeProject.name, { requirements: reqs || "", onLogEvent: appendRunLog })
                              } else if (stage.key === "writing" && engineWritingStart) {
                                await engineWritingStart(activeProject.name, {
                                  startChapter: 1,
                                  totalChapters: activeProject.total_chapters || 0,
                                  onLogEvent: appendRunLog,
                                })
                              } else if (stage.key === "review" && engineReviewStart) {
                                await engineReviewStart(activeProject.name, { onLogEvent: appendRunLog })
                              }
                            }

                            const handleConfirm = async () => {
                              if (!activeProject) return
                              if (stage.key === "outline") {
                                await confirmOutline(activeProject.name)
                              } else if (stage.key === "writing") {
                                await confirmWriting(activeProject.name)
                              } else if (stage.key === "review") {
                                await confirmReview(activeProject.name)
                              }
                            }

                            return (
                              <div key={stage.key} className={`wb-stage-item ${isCurrent ? "current" : ""} ${isCompleted ? "done" : ""}`}>
                                <div className="wb-stage-header">
                                  <span className="wb-stage-label">{stage.label}</span>
                                  {isCurrent && !isRunning && <span className="wb-stage-badge">{language === "zh" ? "当前" : "Current"}</span>}
                                  {isCurrent && isRunning && <span className="wb-stage-badge">{language === "zh" ? "进行中" : "Running"}</span>}
                                  {isCompleted && <span className="wb-stage-badge done">{language === "zh" ? "已完成" : "Done"}</span>}
                                </div>
                                <div className="wb-stage-desc">{stage.desc}</div>
                                <div style={{ display: "flex", gap: 4, marginTop: 6 }}>
                                  <button
                                    className={`wb-btn ${isRunningThisStage ? "wb-btn-stop" : ""}`}
                                    style={{ flex: 1, fontSize: 11 }}
                                    onClick={handleEngineAction}
                                    disabled={isRunning && !isRunningThisStage}
                                  >
                                    {isRunningThisStage
                                      ? (language === "zh" ? "⏹ 停止" : "⏹ Stop")
                                      : isCurrent
                                        ? (language === "zh" ? "▶ 继续生成" : "▶ Continue")
                                        : isCompleted
                                          ? (language === "zh" ? "🔄 重新生成" : "🔄 Re-run")
                                          : stage.btnLabel}
                                  </button>
                                  {isCurrent && !isRunning && (
                                    <button
                                      className="wb-btn"
                                      style={{ flex: 1, fontSize: 11, background: "var(--accent, #4f8cff)", color: "#fff" }}
                                      onClick={handleConfirm}
                                    >
                                      ✓ {stage.confirmLabel}
                                    </button>
                                  )}
                                </div>
                              </div>
                            )
                          })
                        })()}
                      </div>
                    </div>
                  )}
                  {/* 日志侧栏预览 */}
                  {activeSidePanel === "logs" && (
                    <div className="side-panel">
                      <div className="side-panel-header">
                        📜 {language === "zh" ? "运行日志" : "Run Logs"}
                        <button className="wb-btn-sm" title={language === "zh" ? "清空" : "Clear"}
                          onClick={clearRunLogsLocal}>
                          🗑
                        </button>
                      </div>
                      <div className="side-panel-body">
                        {runLogs.length === 0 ? (
                          <div className="side-panel-empty">
                            {language === "zh" ? "暂无日志，启动一个阶段后会在此显示进度" : "No logs yet. Run a stage to see progress."}
                          </div>
                        ) : (
                          <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                            {runLogs.slice(-15).reverse().map((log, i) => (
                              <div key={i} className={`wb-log-row log-${log.status || "info"}`}>
                                <span className="wb-log-time">
                                  {new Date(log.timestamp || Date.now()).toLocaleTimeString("zh-CN", { hour12: false }).slice(0, 8)}
                                </span>
                                <span className="wb-log-msg">{log.message || log.status}</span>
                              </div>
                            ))}
                            {runLogs.length > 15 && (
                              <div style={{ fontSize: 10, opacity: 0.5, textAlign: "center", padding: 4 }}>
                                {language === "zh" ? `还有 ${runLogs.length - 15} 条更早的日志` : `${runLogs.length - 15} earlier logs hidden`}
                              </div>
                            )}
                          </div>
                        )}
                        <button className="wb-btn" style={{ width: "100%", marginTop: 8 }}
                          onClick={() => setActiveRightPanel("logs")}>
                          {language === "zh" ? "在主区域查看完整日志 →" : "View full logs in main →"}
                        </button>
                      </div>
                    </div>
                  )}
                </div>
              </>
            )}
            {!activeProject && (
              <div className="side-panel-empty" style={{ padding: 16, textAlign: "center", opacity: 0.5 }}>
                {language === "zh" ? "← 选择左侧项目开始" : "← Select a project to start"}
              </div>
            )}
          </div>
        </aside>

        {/* ---- Main Editor ---- */}
        <main className="wb-main">
          {/* 图谱全屏模式 */}
          {isKnowledgeMode && activeProject?.name && (
            <div className="kg-fullscreen-wrap" style={{ width: "100%", height: "100%", display: "flex", flexDirection: "column" }}>
              <KnowledgeGraphView
                API_BASE={API_BASE}
                projectName={activeProject.name}
                language={language}
              />
            </div>
          )}

          {!activeProject && !isKnowledgeMode && (
            <div className="wb-main-empty">
              <div className="wb-main-empty-info">
                <div style={{ fontSize: 48, marginBottom: 12 }}>📚</div>
                <div style={{ fontSize: 18, fontWeight: 600 }}>
                  {language === "zh" ? "请选择左侧项目开始" : "Select a project from the sidebar"}
                </div>
                <div style={{ opacity: 0.6, marginTop: 8 }}>
                  {language === "zh" ? "或点击「新项目」创建新项目" : "Or click 'New Project' to create one"}
                </div>
              </div>
              <div className="wb-main-empty-logs">
                <LogPanel
                  logs={runLogs}
                  isRunning={isRunning}
                  elapsed={elapsed}
                  language={language}
                  onClear={clearRunLogsLocal}
                  emptyMessage={
                    language === "zh"
                      ? "启动一个项目阶段后，AI 生成过程会实时显示在这里。"
                      : "After running a stage, AI generation progress will appear here in real time."
                  }
                />
              </div>
            </div>
          )}

          {/* 章节编辑器 */}
          {activeProject && !isKnowledgeMode && activeRightPanel === "chapter-editor" && (
            <div className="chapter-editor">
              {/* Toolbar */}
              <div className="chapter-editor-toolbar">
                <div className="chapter-editor-info">
                  {chapterTitle ? (
                    <>
                      <span className="ce-filename">{chapterTitle}</span>
                      <span className={`ce-badge ${chapterMode === "read" ? "ce-badge-read" : "ce-badge-edit"}`}>
                        {chapterMode === "read" ? (language === "zh" ? "阅读" : "Read") : (language === "zh" ? "编辑中" : "Editing")}
                      </span>
                      <span className="ce-badge"> {(editDraft || chapterDraft).length.toLocaleString()} {language === "zh" ? "字" : "chars"}</span>
                    </>
                  ) : (
                    <span style={{ opacity: 0.5 }}>{language === "zh" ? "未选择章节" : "No chapter selected"}</span>
                  )}
                </div>
                <div className="chapter-editor-actions">
                  {chapterMode === "read" ? (
                    <>
                      <button className="ce-btn ce-btn-edit" onClick={() => setChapterMode("edit")} disabled={!chapterDraft}>
                        {language === "zh" ? "编辑" : "Edit"}
                      </button>
                      <button className="ce-btn ce-btn-ai" onClick={() => setAiMode(true)} disabled={!chapterDraft}>
                        AI {language === "zh" ? "修改" : "Edit"}
                      </button>
                    </>
                  ) : (
                    <>
                      <button className="ce-btn ce-btn-cancel" onClick={() => { setEditDraft(chapterDraft); setChapterMode("read") }}>
                        Esc {language === "zh" ? "取消" : "Cancel"}
                      </button>
                      <button className="ce-btn ce-btn-save" onClick={handleSaveChapter}>
                        Ctrl+S {language === "zh" ? "保存" : "Save"}
                      </button>
                    </>
                  )}
                </div>
              </div>

              {/* AI Edit Input Bar */}
              {aiMode && (
                <div className="ce-ai-input-bar">
                  <input
                    type="text"
                    className="ce-ai-input"
                    value={aiInstruction}
                    onChange={e => setAiInstruction(e.target.value)}
                    placeholder={language === "zh" ? "输入修改要求，如：把第三段的对话改得更紧张..." : "Enter edit instruction..."}
                    onKeyDown={e => { if (e.key === "Enter" && aiInstruction.trim()) handleAiEdit() }}
                    disabled={aiLoading}
                    autoFocus
                  />
                  <button className="ce-btn ce-btn-ai-submit" onClick={handleAiEdit} disabled={aiLoading || !aiInstruction.trim()}>
                    {aiLoading ? (language === "zh" ? "处理中..." : "Processing...") : (language === "zh" ? "提交" : "Submit")}
                  </button>
                  <button className="ce-btn ce-btn-ai-cancel" onClick={() => { setAiMode(false); setAiInstruction("") }} disabled={aiLoading}>
                    {language === "zh" ? "取消" : "Cancel"}
                  </button>
                </div>
              )}

              {/* Content */}
              <div className="chapter-editor-content">
                {!chapterDraft && (
                  <div className="read-empty">
                    <div className="read-empty-icon">📖</div>
                    <p>{language === "zh" ? "暂无章节内容" : "No chapter content"}</p>
                    <p className="read-empty-hint">
                      {language === "zh" ? "← 从左侧选择章节，或点击下方查看运行日志" : "← Select a chapter, or click below to view run logs"}
                    </p>
                    <div style={{ display: "flex", gap: 8, marginTop: 16 }}>
                      <button className="pc-btn primary small" onClick={() => setActiveRightPanel("logs")}>
                        📜 {language === "zh" ? "查看运行日志" : "View Run Logs"}
                        {runLogs.length > 0 && (
                          <span style={{ marginLeft: 6, padding: "1px 6px", borderRadius: 8, background: "var(--accent)", color: "#fff", fontSize: 9, fontWeight: 700 }}>
                            {runLogs.length}
                          </span>
                        )}
                      </button>
                      {isRunning && (
                        <button className="pc-btn small" onClick={() => setActiveRightPanel("logs")}>
                          ⏱ {language === "zh" ? "正在运行" : "Running..."}
                        </button>
                      )}
                    </div>
                    {activeProject && (
                      <div style={{ marginTop: 20, padding: "10px 16px", background: "var(--bg-elevated)", borderRadius: 8, fontSize: 11, opacity: 0.7, maxWidth: 400 }}>
                        <div style={{ marginBottom: 4 }}>
                          {language === "zh" ? "📚 当前项目" : "📚 Current project"}：
                          <strong>{activeProject.title || activeProject.name}</strong>
                        </div>
                        <div>
                          {language === "zh" ? "阶段" : "Stage"}：
                          <span className={`stage-badge stage-${activeProject.current_stage || "outline"}`} style={{ marginLeft: 4 }}>
                            {stageLabel(activeProject.current_stage || "outline")}
                          </span>
                          <span style={{ marginLeft: 8 }}>
                            {activeProject.chapters_done || 0}/{activeProject.total_chapters || "待定"} {language === "zh" ? "章" : "ch"}
                          </span>
                        </div>
                      </div>
                    )}
                  </div>
                )}
                {chapterDraft && chapterMode === "read" && (
                  <div className="read-view">
                    <div className="read-text">
                      {chapterDraft.split("\n").map((line, i) => {
                        if (line.startsWith("# ")) return <h2 key={i} className="read-h2">{line.replace("# ", "")}</h2>
                        if (line.startsWith("## ")) return <h3 key={i} className="read-h3">{line.replace("## ", "")}</h3>
                        if (line.trim() === "") return <br key={i} />
                        return <p key={i} className="read-p">{line}</p>
                      })}
                    </div>
                  </div>
                )}
                {chapterMode === "edit" && (
                  <textarea
                    className="edit-textarea"
                    value={editDraft}
                    onChange={(e) => setEditDraft(e.target.value)}
                    placeholder={language === "zh" ? "开始写作..." : "Start writing..."}
                    autoFocus
                  />
                )}
              </div>

              {/* Status bar */}
              <div className="chapter-editor-status">
                <span>{chapterTitle || (language === "zh" ? "未选择章节" : "No chapter selected")}</span>
                <span>{language === "zh" ? "行" : "Lines"}: {(editDraft || chapterDraft).split("\n").length} · {language === "zh" ? "字" : "Chars"}: {(editDraft || chapterDraft).length.toLocaleString()}</span>
              </div>
            </div>
          )}

          {/* 大纲编辑器 */}
          {activeProject && !isKnowledgeMode && activeRightPanel === "outline-editor" && (
            <div className="editor-wrap">
              <div className="editor-header">
                <span>📋 {language === "zh" ? "大纲编辑" : "Outline Editor"}</span>
                <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
                  <button className="pc-btn primary small" onClick={handleSaveOutline}>
                    💾 {language === "zh" ? "保存" : "Save"}
                  </button>
                </div>
              </div>
              <div className="editor-body">
                <textarea value={outlineDraft}
                  onChange={(e) => setOutlineDraft(e.target.value)}
                  placeholder="# Outline\n\n1. Chapter 1 ..."
                  rows={25} className="editor-textarea" />
              </div>
            </div>
          )}

          {/* AI 助理 */}
          {activeProject && activeRightPanel === "assistant-editor" && (
            <div className="editor-wrap">
              <div className="editor-header">
                <span>🤖 {language === "zh" ? "项目 AI 助理" : "AI Assistant"}</span>
              </div>
              <div className="assistant-body">
                <div className="assistant-input-row">
                  <input type="text" value={assistantInput}
                    onChange={(e) => setAssistantInput(e.target.value)}
                    placeholder={language === "zh" ? "对 AI 说点什么..." : "Ask AI something..."}
                    onKeyDown={(e) => { if (e.key === "Enter") handleAssistantSend() }} />
                  <button className="pc-btn primary" onClick={handleAssistantSend} disabled={assistantLoading}>
                    {assistantLoading ? (language === "zh" ? "思考中..." : "Thinking...") : (language === "zh" ? "发送" : "Send")}
                  </button>
                </div>
                {assistantReply && (
                  <div className="assistant-reply">
                    {assistantReply}
                  </div>
                )}
              </div>
            </div>
          )}

          {/* 项目配置 + 模型配置 */}
          {activeProject && activeRightPanel === "modelconfig-editor" && (
            <div className="editor-wrap">
              <div className="editor-header">
                <span>⚙️ {language === "zh" ? "项目配置" : "Project Config"}</span>
                <div style={{ display: "flex", gap: 6 }}>
                  <button className="pc-btn primary small"
                    onClick={handleSaveProjectInfo}>
                    💾 {language === "zh" ? "保存信息" : "Save Info"}
                  </button>
                  <button className="pc-btn primary small"
                    onClick={() => {
                      if (!saveProjectPresets) return
                      // 把当前 aiChatPreset 一起保存到 chat 字段
                      const chatPreset = (presets || []).find(p => p.name === aiChatPreset)
                      saveProjectPresets(activeProject.name, {
                        ...projectPresets,
                        chat: chatPreset || {},
                      })
                    }}>
                    💾 {language === "zh" ? "保存模型" : "Save Models"}
                  </button>
                </div>
              </div>
              <div className="editor-body">
                {/* 项目基本信息 */}
                <div style={{ marginBottom: 16, padding: 12, border: "1px solid var(--border)", borderRadius: 6 }}>
                  <div style={{ fontWeight: 600, marginBottom: 8 }}>{language === "zh" ? "项目信息" : "Project Info"}</div>
                  <div className="editor-field">
                    <label>{language === "zh" ? "项目名称" : "Project Name"}</label>
                    <input value={editProjectName} disabled
                      style={{ opacity: 0.6 }} />
                  </div>
                  <div className="editor-field">
                    <label>{language === "zh" ? "小说标题" : "Novel Title"}</label>
                    <input value={editProjectTitle} onChange={(e) => setEditProjectTitle(e.target.value)}
                      placeholder={language === "zh" ? "小说标题" : "Novel title"} />
                  </div>
                  <div className="editor-field">
                    <label>{language === "zh" ? "题材" : "Genre"}</label>
                    <select value={editProjectGenre} onChange={(e) => setEditProjectGenre(e.target.value)} className="wb-select" style={{ width: "100%" }}>
                      <option value="">{language === "zh" ? "选择题材" : "Select genre"}</option>
                      {GENRES.map(g => <option key={g} value={g}>{g}</option>)}
                    </select>
                  </div>
                  <div className="editor-field">
                    <label>{language === "zh" ? "预计章节数" : "Estimated Chapters"}</label>
                    <input type="number" value={editTotalChapters} onChange={(e) => setEditTotalChapters(e.target.value)} min={1} max={999} />
                  </div>

                  {/* 附加要求 */}
                  <div className="editor-field">
                    <label>{language === "zh" ? "附加要求" : "Extra Requirements"}</label>
                    <textarea value={editExtraReqs} onChange={(e) => setEditExtraReqs(e.target.value)}
                      placeholder={language === "zh" ? "例如：节奏要快，要有爽点" : "e.g., Fast pacing, exciting moments"}
                      rows={3} className="editor-textarea" />
                  </div>
                </div>

                {/* AI 对话模型（用于人物输入等轻量对话） */}
                <div style={{ marginBottom: 12, padding: 10, border: "1px solid var(--accent)", borderRadius: 6, background: "var(--bg-surface)" }}>
                  <div style={{ fontWeight: 600, marginBottom: 6, fontSize: 12 }}>
                    💬 {language === "zh" ? "AI 对话模型" : "AI Chat Model"}
                  </div>
                  <select value={aiChatPreset} onChange={e => setAiChatPreset(e.target.value)}
                    className="wb-select" style={{ width: "100%", fontSize: 12 }}
                    title={language === "zh" ? "用于侧边栏 AI 人物添加等轻量对话" : "For sidebar AI character input and other lightweight chat"}>
                    <option value="">{language === "zh" ? "— 不指定，使用第一个可用 —" : "— Default (first available) —"}</option>
                    {presets?.map((p, i) => (
                      <option key={i} value={p.name}>{p.name} ({p.model})</option>
                    ))}
                  </select>
                  <div style={{ fontSize: 10, opacity: 0.6, marginTop: 4 }}>
                    {language === "zh" ? "轻量级对话，例如人物设定添加" : "Lightweight chat, e.g. character adding"}
                  </div>
                </div>

                {/* 模型配置 */}
                <div style={{ marginBottom: 12, opacity: 0.7, fontSize: 12 }}>
                  {language === "zh" ? "为每个角色配置不同的模型预设" : "Configure different model presets for each role"}
                </div>
                {["manager", "worker", "reviewer"].map((role) => {
                  const roleLabels = { manager: "🧠 Manager", worker: "✍️ Writer", reviewer: "🔍 Reviewer" }
                  const p = projectPresets[role] || {}
                  const setField = (key, value) => setProjectPresets(prev => ({
                    ...prev, [role]: { ...(prev[role] || {}), [key]: value }
                  }))
                  return (
                    <div key={role} className="mc-card" style={{ marginBottom: 12, padding: 12, border: "1px solid var(--border)", borderRadius: 6 }}>
                      <div style={{ fontWeight: 600, marginBottom: 8 }}>{roleLabels[role]}</div>
                      <div className="editor-field">
                        <label>{language === "zh" ? "预设名称" : "Preset Name"}</label>
                        <input value={p.name || ""} onChange={(e) => setField("name", e.target.value)}
                          placeholder="e.g. my-gpt" />
                      </div>
                      <div className="editor-field">
                        <label>Base URL</label>
                        <input value={p.base_url || ""} onChange={(e) => setField("base_url", e.target.value)}
                          placeholder="https://api.example.com/v1" />
                      </div>
                      <div className="editor-field">
                        <label>API Key</label>
                        <input value={p.api_key || ""} onChange={(e) => setField("api_key", e.target.value)}
                          placeholder="sk-..." type="password" />
                      </div>
                      <div className="editor-field">
                        <label>Model</label>
                        <input value={p.model || ""} onChange={(e) => setField("model", e.target.value)}
                          placeholder="gpt-4o-mini / claude-3-5-sonnet" />
                      </div>
                      <div className="editor-field">
                        <label>API Format</label>
                        <select value={p.api_format || "openai"} onChange={(e) => setField("api_format", e.target.value)} className="wb-select" style={{ width: "100%" }}>
                          <option value="openai">OpenAI</option>
                          <option value="anthropic">Anthropic</option>
                          <option value="ollama">Ollama</option>
                        </select>
                      </div>
                      <div className="mc-quick-row">
                        {language === "zh" ? "快速填入：" : "Quick fill:"}
                        {presets?.slice(0, 3).map((ps, i) => (
                          <button key={i} className="pc-btn tiny" style={{ marginLeft: 4 }}
                            onClick={() => setProjectPresets(prev => ({
                              ...prev,
                              [role]: { name: ps.name, api_key: ps.api_key, base_url: ps.base_url, model: ps.model, api_format: ps.api_format || "openai" }
                            }))}>
                            {ps.name}
                          </button>
                        ))}
                      </div>
                    </div>
                  )
                })}
              </div>
            </div>
          )}

          {/* 日志面板（主区域全宽） */}
          {activeProject && !isKnowledgeMode && activeRightPanel === "logs" && (
            <LogPanel
              logs={runLogs}
              isRunning={isRunning}
              elapsed={elapsed}
              language={language}
              onClear={clearRunLogsLocal}
              activeProject={activeProject}
            />
          )}
        </main>
      </div>

      {/* ==================== Modals ==================== */}
      {/* 新建项目 Modal */}
      {showCreate && (
        <div className="modal-overlay" onClick={() => setShowCreate(false)}>
          <div className="modal-box" onClick={(e) => e.stopPropagation()} style={{ maxWidth: 520, maxHeight: "90vh", overflowY: "auto" }}>
            <div className="modal-title">{language === "zh" ? "新建项目" : "New Project"}</div>
            <div className="modal-body">
              <div className="editor-field">
                <label>{language === "zh" ? "项目名称 *" : "Project Name *"}</label>
                <input value={newName} onChange={(e) => setNewName(e.target.value)}
                  placeholder={language === "zh" ? "例如：my_novel" : "e.g. my_novel"} />
              </div>

              {/* 小说题材（与 InkOS 体裁系统集成） */}
              <div className="editor-field">
                <label>{language === "zh" ? "小说题材（可选）" : "Genre (optional)"}</label>
                <select value={newGenre} onChange={(e) => setNewGenre(e.target.value)} className="wb-select" style={{ width: "100%" }}>
                  <option value="">{language === "zh" ? "选择题材" : "Select genre"}</option>
                  {GENRES.map(g => <option key={g} value={g}>{g}</option>)}
                </select>
                <div style={{ fontSize: 10, opacity: 0.5, marginTop: 4 }}>
                  {language === "zh" ? "选择题材后，AI 会注入对应的体裁写作指南和审校维度" : "Genre selection injects tailored writing guides and review dimensions"}
                </div>
              </div>

              {/* 项目要求（传给大纲生成阶段） */}
              <div className="editor-field">
                <label>{language === "zh" ? "项目要求（可选）" : "Project Requirements (optional)"}</label>
                <textarea value={newExtraReqs} onChange={(e) => setNewExtraReqs(e.target.value)}
                  placeholder={language === "zh"
                    ? "描述你想写的小说类型、风格、核心设定等，AI 会据此生成大纲。\n例如：修仙题材，主角从凡人开始，节奏要快，要有爽点"
                    : "Describe the novel type, style, core settings, etc. AI will generate outline accordingly.\ne.g., Cultivation theme, MC starts as mortal, fast pacing, exciting moments"}
                  rows={5} className="editor-textarea" />
                <div style={{ fontSize: 10, opacity: 0.5, marginTop: 4 }}>
                  {language === "zh"
                    ? "小说标题和题材会在大纲生成阶段自动确定"
                    : "Novel title and genre will be determined during outline generation"}
                </div>
              </div>

              {/* 模型配置（折叠） */}
              <div style={{ borderTop: "1px solid var(--border)", paddingTop: 8, marginTop: 8 }}>
                <button className="wb-btn" style={{ width: "100%", fontSize: 12, opacity: 0.7 }}
                  onClick={() => setShowModelConfig(!showModelConfig)}>
                  {showModelConfig ? "▼" : "▶"} {language === "zh" ? "AI 模型配置（高级）" : "AI Model Config (Advanced)"}
                </button>
                {showModelConfig && (
                  <div style={{ marginTop: 8 }}>
                    {!presets || presets.length === 0 ? (
                      <div style={{ opacity: 0.6, fontSize: 12, padding: 8, background: "var(--bg-surface)", borderRadius: 6 }}>
                        {language === "zh" ? "请先在预设面板配置 API 预设" : "Please configure API presets first"}
                      </div>
                    ) : (
                      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                        {[
                          { role: "manager", label: language === "zh" ? "🧠 管理者" : "🧠 Manager", idx: newManagerIdx, setIdx: setNewManagerIdx },
                          { role: "worker", label: language === "zh" ? "✍️ 写手" : "✍️ Writer", idx: newWorkerIdx, setIdx: setNewWorkerIdx },
                          { role: "reviewer", label: language === "zh" ? "🔍 审校" : "🔍 Reviewer", idx: newReviewerIdx, setIdx: setNewReviewerIdx },
                        ].map(r => (
                          <div key={r.role} style={{ display: "flex", alignItems: "center", gap: 8 }}>
                            <span style={{ minWidth: 80, fontSize: 12 }}>{r.label}</span>
                            <select value={r.idx} onChange={e => r.setIdx(parseInt(e.target.value))}
                              className="wb-select" style={{ flex: 1 }}>
                              <option value={-1}>{language === "zh" ? "— 默认 —" : "— Default —"}</option>
                              {presets.map((p, i) => (
                                <option key={i} value={i}>{p.name} ({p.model})</option>
                              ))}
                            </select>
                          </div>
                        ))}
                        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                          <span style={{ minWidth: 80, fontSize: 12 }}>
                            💬 {language === "zh" ? "对话模型" : "Chat Model"}
                          </span>
                          <select value={newChatPreset} onChange={e => setNewChatPreset(e.target.value)}
                            className="wb-select" style={{ flex: 1 }}>
                            <option value="">{language === "zh" ? "— 默认 —" : "— Default —"}</option>
                            {presets.map((p, i) => (
                              <option key={i} value={p.name}>{p.name} ({p.model})</option>
                            ))}
                          </select>
                        </div>
                      </div>
                    )}
                  </div>
                )}
              </div>

              <div className="modal-actions">
                <button className="pc-btn" onClick={() => setShowCreate(false)}>
                  {language === "zh" ? "取消" : "Cancel"}
                </button>
                <button className="pc-btn primary" onClick={handleCreateProject}>
                  {language === "zh" ? "创建" : "Create"}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* 项目删除确认弹窗 */}
      {confirmDeleteProject && (
        <div className="modal-overlay" onClick={() => !deleting && setConfirmDeleteProject(null)}>
          <div className="pc-modal danger-modal" onClick={e => e.stopPropagation()}
            style={{ maxWidth: 440 }}>
            <div className="pc-modal-header danger">
              <span>🗑 {language === "zh" ? "删除项目" : "Delete Project"}</span>
              <button className="pc-modal-close" onClick={() => setConfirmDeleteProject(null)} disabled={deleting}>×</button>
            </div>
            <div className="pc-modal-body">
              <div className="delete-warning-icon">⚠️</div>
              <div className="delete-warning-title">
                {language === "zh" ? "确定要删除以下项目吗？" : "Are you sure you want to delete this project?"}
              </div>
              <div className="delete-project-name">{confirmDeleteProject}</div>
              <div className="delete-warning-desc">
                {language === "zh"
                  ? "此操作不可撤销！项目下的所有章节、大纲、人物设定和记忆都将永久删除。"
                  : "This action cannot be undone! All chapters, outline, characters, and memories under this project will be permanently deleted."}
              </div>
              <div className="pc-modal-actions">
                <button className="pc-btn" onClick={() => setConfirmDeleteProject(null)} disabled={deleting}>
                  {language === "zh" ? "取消" : "Cancel"}
                </button>
                <button className="pc-btn danger" onClick={confirmDelete} disabled={deleting}>
                  {deleting
                    ? (language === "zh" ? "删除中..." : "Deleting...")
                    : (language === "zh" ? "🗑 确认删除" : "🗑 Delete")}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

