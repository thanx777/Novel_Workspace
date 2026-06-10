import { useState, useEffect, useCallback } from "react"
import LogPanel from "./LogPanel"
import CharacterPanel from "./CharacterPanel"
import OutlinePanel from "./OutlinePanel"
import KnowledgeGraphView from "./KnowledgeGraphView"
import { API_BASE } from "../constants"
import useProjectV2 from "../hooks/useProjectV2"
import useNovelReader from "../hooks/useNovelReader"
import TaskDetailModal from "./TaskDetailModal"

export default function Workbench({
  t, language,
  isDark, setIsDark, setLanguage, setShowWorkspaceSettings, setShowPresetSidebar, showPresetSidebar,
  presets, showNotification,
  isRunning, setIsRunning,
  agentCatalog,
  projectV2,
}) {
  // ---- Project V2 State ----
  const {
    projects, activeProject, loadingList, loadingDetail,
    createProject, deleteProject, loadProject,
    runStage, confirmOutline, rejectOutline, stopTask,
    updateChapter, addMemory, assistantChat, aiAddCharacter, deleteCharacter,
    putFile, getFile, loadProjectPresets, saveProjectPresets,
    fetchProjects,
  } = projectV2 || {}

  // 锁定判断：进入写作/审校/完成阶段后，大纲和人物不能改
  const lockedStages = ["writing", "polish", "done", "completed"]
  const isOutlineLocked = activeProject && lockedStages.includes(activeProject.current_stage)
  const isCharacterLocked = activeProject && lockedStages.includes(activeProject.current_stage)
  const lockedReason = isOutlineLocked
    ? (language === "zh"
        ? `已进入「${activeProject.current_stage === "writing" ? "写作" : activeProject.current_stage === "polish" ? "审校" : "完成"}」阶段，大纲和人物设定已锁定`
        : `Outline and characters are locked in ${activeProject.current_stage} stage.`)
    : ""

  // ---- Task/Chapter State (legacy) ----
  const [tasks, setTasks] = useState([])
  const [activeTaskFolder, setActiveTaskFolder] = useState("")
  const [selectedTask, setSelectedTask] = useState(null)
  const [taskDetail, setTaskDetail] = useState(null)

  // ---- Editor State ----
  const [logs, setLogs] = useState([])
  const [elapsed, setElapsed] = useState(0)

  // ---- Sidebar State ----
  const [activeSidePanel, setActiveSidePanel] = useState("chapters")
  const [activeRightPanel, setActiveRightPanel] = useState("chapter-editor")

  // 知识图谱为全屏模式（占主区域）
  const isKnowledgeMode = activeSidePanel === "knowledge"

  // ---- Run Logs (for the log panel) ----
  const [runLogs, setRunLogs] = useState([])
  const appendRunLog = useCallback((event) => {
    setRunLogs(prev => {
      const next = [...prev, event]
      // 限制最多保留 500 条
      return next.length > 500 ? next.slice(-500) : next
    })
  }, [])
  const clearRunLogs = useCallback(() => setRunLogs([]), [])

  // ---- Editor Content State ----
  const [chapterDraft, setChapterDraft] = useState("")
  const [chapterTitle, setChapterTitle] = useState("")
  const [chapterSummary, setChapterSummary] = useState("")
  const [chapterMode, setChapterMode] = useState("read") // "read" or "edit"
  const [editDraft, setEditDraft] = useState("") // editable copy
  const [selectedChapterIndex, setSelectedChapterIndex] = useState(null)

  // Sync editDraft when chapterDraft changes
  useEffect(() => { setEditDraft(chapterDraft) }, [chapterDraft])
  const [outlineDraft, setOutlineDraft] = useState("")
  const [charactersDraft, setCharactersDraft] = useState("")

  // ---- Create Project Modal ----
  const [showCreate, setShowCreate] = useState(false)
  const [newName, setNewName] = useState("")
  const [newTitle, setNewTitle] = useState("")
  const [newGenre, setNewGenre] = useState("")
  const [newChapterCount, setNewChapterCount] = useState(20)
  const [newWritingMode, setNewWritingMode] = useState("lite")
  const [newOutlineReviewMode, setNewOutlineReviewMode] = useState("auto")
  const [newOutlineLayers, setNewOutlineLayers] = useState({ L1: true, L2: true, L3: true })
  const [newManagerIdx, setNewManagerIdx] = useState(-1)
  const [newWorkerIdx, setNewWorkerIdx] = useState(-1)
  const [newReviewerIdx, setNewReviewerIdx] = useState(-1)
  const [newChatPreset, setNewChatPreset] = useState("")  // AI 对话模型（用于人物输入等）
  const [newExtraReqs, setNewExtraReqs] = useState("")

  const GENRES_ZH = ["玄幻", "都市", "言情", "仙侠", "科幻", "历史", "武侠", "悬疑", "恐怖", "喜剧", "都市爽文", "系统流"]
  const GENRES_EN = ["Fantasy", "Urban", "Romance", "Xianxia", "Sci-Fi", "Historical", "Martial Arts", "Suspense", "Horror", "Comedy", "Urban Fantasy", "System Flow"]
  const GENRES = language === "zh" ? GENRES_ZH : GENRES_EN

  // ---- Stage Modal ----
  const [showStageModal, setShowStageModal] = useState(false)
  const [selectedStage, setSelectedStage] = useState("outline")
  const [taskInput, setTaskInput] = useState("")
  const [outlineReviewMode, setOutlineReviewMode] = useState("auto")
  const [executionMode, setExecutionMode] = useState("standard")

  // ---- Assistant ----
  const [assistantInput, setAssistantInput] = useState("")
  const [assistantReply, setAssistantReply] = useState("")
  const [assistantLoading, setAssistantLoading] = useState(false)

  // ---- Model Config ----
  const [projectPresets, setProjectPresets] = useState({ manager: {}, worker: {}, reviewer: {} })
  const [aiChatPreset, setAiChatPreset] = useState("")  // AI 对话模型预设名
  const [aiCharInput, setAiCharInput] = useState("")    // AI 人物输入框内容
  const [aiCharLoading, setAiCharLoading] = useState(false)  // AI 添加人物 loading

  // ---- Project Config Editing ----
  const [editProjectName, setEditProjectName] = useState("")
  const [editProjectTitle, setEditProjectTitle] = useState("")
  const [editProjectGenre, setEditProjectGenre] = useState("")
  const [editTotalChapters, setEditTotalChapters] = useState(20)
  const [editExecutionMode, setEditExecutionMode] = useState("lite")
  const [editOutlineReviewMode, setEditOutlineReviewMode] = useState("auto")
  const [editExtraReqs, setEditExtraReqs] = useState("")

  // ---- Novel Reader (for legacy task) ----
  const {
    chapters: legacyChapters, fileContent,
    activeFile, loadFiles, loadChapter, saveFile
  } = useNovelReader(activeTaskFolder)

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

  // ---- Load tasks (legacy) ----
  const loadTasks = useCallback(async () => {
    try {
      const resp = await fetch(`${API_BASE}/tasks`)
      if (resp.ok) { const data = await resp.json(); setTasks(data.tasks || []) }
    } catch (e) { console.error("Failed to load tasks:", e) }
  }, [])
  useEffect(() => { loadTasks() }, [loadTasks])

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
    setCharactersDraft("")
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
    await updateChapter(activeProject.name, selectedChapterIndex, {
      title: chapterTitle,
      summary: chapterSummary,
      content: contentToSave,
      status: "draft",
    })
    setChapterDraft(contentToSave)
    setChapterMode("read")
  }, [activeProject, chapterMode, editDraft, chapterTitle, chapterSummary, chapterDraft, selectedChapterIndex, updateChapter])

  // ---- Save outline ----
  const handleSaveOutline = useCallback(async () => {
    if (!activeProject) return
    await putFile(activeProject.name, "outline.md", outlineDraft)
    showNotification && showNotification("大纲已保存", "success")
  }, [activeProject, outlineDraft, putFile, showNotification])

  // ---- Save characters ----
  const handleSaveCharacters = useCallback(async () => {
    if (!activeProject) return
    await putFile(activeProject.name, "characters.md", charactersDraft)
    showNotification && showNotification("人物设定已保存", "success")
  }, [activeProject, charactersDraft, putFile, showNotification])

  // ---- Open outline editor ----
  const handleOpenOutline = useCallback(async () => {
    if (!activeProject) return
    const content = await getFile(activeProject.name, "outline.md")
    setOutlineDraft(content || "")
    setActiveSidePanel("outline")
    setActiveRightPanel("outline-editor")
  }, [activeProject, getFile])

  // ---- Auto-load outline content (for sidebar preview) ----
  const handleShowOutlinePanel = useCallback(async () => {
    if (!activeProject) return
    setActiveSidePanel("outline")
    // 自动加载大纲内容以显示在侧边面板
    if (!outlineDraft) {
      const content = await getFile(activeProject.name, "outline.md")
      setOutlineDraft(content || "")
    }
  }, [activeProject, getFile, outlineDraft])

  // ---- Open characters editor ----
  const handleOpenCharacters = useCallback(async () => {
    if (!activeProject) return
    const content = await getFile(activeProject.name, "characters.md")
    setCharactersDraft(content || "")
    setActiveSidePanel("characters")
    setActiveRightPanel("characters-editor")
  }, [activeProject, getFile])

  // ---- Open project config ----
  const handleOpenProjectConfig = useCallback(() => {
    if (!activeProject) return
    setEditProjectName(activeProject.name || "")
    setEditProjectTitle(activeProject.title || "")
    setEditProjectGenre(activeProject.genre || "")
    setEditTotalChapters(activeProject.total_chapters || 20)
    setEditExecutionMode(activeProject.execution_mode || "lite")
    setEditOutlineReviewMode(activeProject.outline_review_mode || "auto")
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
          total_chapters: Number(editTotalChapters) || 20,
          execution_mode: editExecutionMode,
          outline_review_mode: editOutlineReviewMode,
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
  }, [activeProject, editProjectTitle, editProjectGenre, editTotalChapters, editExecutionMode, editOutlineReviewMode, editExtraReqs, loadProject, showNotification, putFile])

  // ---- Create project ----
  const handleCreateProject = useCallback(async () => {
    if (!newName.trim()) {
      showNotification && showNotification("请输入项目名称", "error")
      return
    }
    const rolePresets = {}
    if (newManagerIdx >= 0 && presets?.[newManagerIdx]) rolePresets.manager = presets[newManagerIdx]
    if (newWorkerIdx >= 0 && presets?.[newWorkerIdx]) rolePresets.worker = presets[newWorkerIdx]
    if (newReviewerIdx >= 0 && presets?.[newReviewerIdx]) rolePresets.reviewer = presets[newReviewerIdx]
    // AI 对话模型：按名字查找预设对象
    if (newChatPreset && presets) {
      const found = presets.find(p => p.name === newChatPreset)
      if (found) rolePresets.chat = found
    }
    const result = await createProject({
      name: newName.trim(),
      title: newTitle.trim(),
      genre: newGenre,
      total_chapters: Number(newChapterCount) || 20,
      execution_mode: newWritingMode,
      outline_review_mode: newOutlineReviewMode,
      outline_layers: newOutlineLayers,
      extra_requirements: newExtraReqs.trim(),
      role_presets: rolePresets,
    })
    if (result) {
      setNewName(""); setNewTitle(""); setNewGenre(""); setNewChapterCount(20)
      setNewWritingMode("lite"); setNewOutlineReviewMode("auto")
      setNewOutlineLayers({ L1: true, L2: true, L3: true })
      setNewManagerIdx(-1); setNewWorkerIdx(-1); setNewReviewerIdx(-1)
      setNewChatPreset("")
      setNewExtraReqs("")
      setShowCreate(false)
    }
  }, [newName, newTitle, newGenre, newChapterCount, newWritingMode, newOutlineReviewMode, newOutlineLayers, newManagerIdx, newWorkerIdx, newReviewerIdx, newChatPreset, newExtraReqs, createProject, showNotification, presets])

  // ---- Start stage ----
  const handleStartStage = useCallback(async () => {
    if (!activeProject || !runStage) {
      showNotification && showNotification("请先选择项目", "error")
      return
    }
    setShowStageModal(false)
    // 清空之前的日志并切换到日志面板
    clearRunLogs()
    appendRunLog({
      status: "info", role: "系统",
      message: `准备启动 ${selectedStage} 阶段...`,
      timestamp: Date.now(),
    })
    setActiveRightPanel("logs")
    await runStage({
      projectName: activeProject.name,
      stage: selectedStage,
      task: taskInput,
      executionMode,
      outlineReviewMode,
      onLogEvent: appendRunLog,
    })
  }, [activeProject, selectedStage, taskInput, executionMode, outlineReviewMode, runStage, showNotification, clearRunLogs, appendRunLog])

  // ---- Assistant chat ----
  const handleAssistantSend = useCallback(async () => {
    if (!activeProject || !assistantInput.trim()) return
    setAssistantLoading(true)
    const reply = await assistantChat(activeProject.name, assistantInput.trim())
    setAssistantReply(reply || "(无回复)")
    setAssistantLoading(false)
    setAssistantInput("")
  }, [activeProject, assistantInput, assistantChat])

  // ---- AI 添加人物 ----
  const handleAiAddCharacter = useCallback(async () => {
    if (!activeProject || !aiCharInput.trim() || aiCharLoading || isCharacterLocked) return
    setAiCharLoading(true)
    try {
      const result = await aiAddCharacter(activeProject.name, aiCharInput.trim(), aiChatPreset)
      if (result?.success) {
        // 刷新人物文件 + 角色面板
        const content = await getFile(activeProject.name, "characters.md")
        setCharactersDraft(content || "")
        setAiCharInput("")
      }
    } finally {
      setAiCharLoading(false)
    }
  }, [activeProject, aiCharInput, aiCharLoading, isCharacterLocked, aiAddCharacter, aiChatPreset, getFile])

  // ---- 删除单个角色 ----
  const handleDeleteCharacter = useCallback(async (charName) => {
    if (!activeProject || isCharacterLocked) {
      showNotification && showNotification("人物已锁定，无法删除", "error")
      return { success: false }
    }
    return await deleteCharacter(activeProject.name, charName)
  }, [activeProject, isCharacterLocked, deleteCharacter, showNotification])

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

  // ---- Resume task (legacy) ----
  const handleResumeTask = useCallback(async (folder) => {
    setActiveTaskFolder(folder)
    try {
      const resp = await fetch(`${API_BASE}/tasks/${encodeURIComponent(folder)}/resume`, {
        method: "POST", headers: { "Content-Type": "application/json" }
      })
      if (resp.ok) {
        setIsRunning(true)
        const reader = resp.body.getReader()
        const decoder = new TextDecoder()
        while (true) {
          const { done, value } = await reader.read()
          if (done) break
          for (const line of decoder.decode(value).split("\n")) {
            if (line.startsWith("data: ")) {
              try {
                const data = JSON.parse(line.replace("data: ", ""))
                setLogs(prev => [...prev, data])
                if (data.status === "done") { showNotification && showNotification(t("taskCompleted"), "success"); setIsRunning(false) }
                if (data.status === "paused") { showNotification && showNotification(data.message || t("taskPaused"), "info"); setIsRunning(false) }
              } catch (e) {}
            }
          }
        }
        loadFiles(); loadTasks()
      }
    } catch (e) { setIsRunning(false) }
  }, [showNotification, t, setIsRunning, loadFiles, loadTasks])

  // ---- Stop task ----
  const handleStopTask = useCallback(async () => {
    try { await fetch(`${API_BASE}/stop-task`, { method: "POST" }).catch(() => {}) } catch (e) {}
    setIsRunning(false); showNotification && showNotification(t("taskStopped"), "info"); loadTasks()
  }, [showNotification, t, setIsRunning, loadTasks])

  // ---- Task click ----
  const handleTaskClick = useCallback(async (folder) => {
    setActiveTaskFolder(folder)
    try {
      const resp = await fetch(`${API_BASE}/tasks/${encodeURIComponent(folder)}`)
      if (resp.ok) {
        const data = await resp.json()
        setTaskDetail(data)
        setSelectedTask(folder)
      }
    } catch (e) { console.error("Failed to load task detail:", e) }
  }, [])

  // ---- Delete task ----
  const handleDeleteTask = useCallback(async (folder) => {
    if (!confirm(t("deleteConfirm"))) return
    try {
      await fetch(`${API_BASE}/tasks/${encodeURIComponent(folder)}`, { method: "DELETE" })
      showNotification && showNotification(t("taskDeleted"), "success")
      if (activeTaskFolder === folder) setActiveTaskFolder("")
      loadTasks()
    } catch (e) { showNotification && showNotification("Delete failed: " + e.message, "error") }
  }, [t, activeTaskFolder, loadTasks, showNotification])

  // ---- Stage label ----
  const stageLabel = (s) => ({ outline: "大纲制作", writing: "正文写作", polish: "润色审校", completed: "已完成" }[s] || s)

  // ---- Sidebar tabs ----
  const SIDE_TABS = [
    { key: "chapters", label: language === "zh" ? "章节" : "Chapters", icon: "📖" },
    { key: "outline", label: language === "zh" ? "大纲" : "Outline", icon: "📋" },
    { key: "knowledge", label: language === "zh" ? "知识图谱" : "Knowledge", icon: "🕸" },
    { key: "characters", label: language === "zh" ? "人物" : "Chars", icon: "👤" },
    { key: "memory", label: language === "zh" ? "记忆" : "Memory", icon: "🧠" },
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
              <button className="wb-btn" onClick={() => { setSelectedStage(activeProject?.current_stage || "outline"); setShowStageModal(true) }}>
                ▶ {language === "zh" ? "启动阶段" : "Run Stage"}
              </button>
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
              {activeProject.chapters_done || 0}/{activeProject.total_chapters || "?"} {language === "zh" ? "章" : "ch"}
            </span>
          )}
          <select value={executionMode} onChange={e => setExecutionMode(e.target.value)} className="wb-select">
            <option value="lite">{language === "zh" ? "精简" : "Lite"}</option>
            <option value="standard">{language === "zh" ? "标准" : "Standard"}</option>
            <option value="pro">{language === "zh" ? "完整" : "Full"}</option>
          </select>
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
                      <span>{p.chapters_done || 0}/{p.total_chapters || "?"} 章</span>
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
                          handleOpenCharacters()
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
                  {/* 知识图谱 - 在主区域全屏渲染，这里只显示提示 */}
                  {activeSidePanel === "knowledge" && (
                    <div className="side-panel" style={{ padding: 16 }}>
                      <div className="side-panel-header">🕸 {language === "zh" ? "知识图谱" : "Knowledge Graph"}</div>
                      <div className="side-panel-body">
                        <div className="side-panel-empty" style={{ padding: 16, fontSize: 12, opacity: 0.8 }}>
                          <div style={{ fontSize: 32, marginBottom: 8 }}>🕸️</div>
                          <div style={{ fontWeight: 600, marginBottom: 4 }}>
                            {language === "zh" ? "知识图谱已展开" : "Graph view is open"}
                          </div>
                          <div>
                            {language === "zh" ? "请在右侧主区域查看完整图谱" : "View the full graph on the right"}
                          </div>
                        </div>
                      </div>
                    </div>
                  )}
                  {/* 人物 */}
                  {activeSidePanel === "characters" && (
                    <div className="side-panel">
                      <div className="side-panel-header">👤 {language === "zh" ? "人物设定" : "Characters"}</div>
                      <div className="side-panel-body">
                        <button className="wb-btn" style={{ width: "100%", marginBottom: 8 }}
                          onClick={handleOpenCharacters}>
                          ✏️ {language === "zh" ? "编辑人物" : "Edit Characters"}
                        </button>

                        {/* AI 添加角色 - 分隔区 */}
                        <div className={`ai-char-section ${isCharacterLocked ? "locked" : ""}`}>
                          <div className="ai-char-section-title">
                            🤖 {language === "zh" ? "AI 添加角色" : "AI Add Character"}
                            {isCharacterLocked && (
                              <span className="ai-char-locked-pill">🔒 {language === "zh" ? "已锁定" : "Locked"}</span>
                            )}
                          </div>
                          <div className="ai-char-model">
                            {language === "zh" ? "模型：" : "Model: "}
                            <span className="ai-char-model-name">
                              {aiChatPreset
                                ? aiChatPreset
                                : (presets?.[0]?.name || (language === "zh" ? "未配置" : "Not configured"))}
                            </span>
                          </div>
                          <textarea
                            className="ai-char-textarea"
                            value={aiCharInput}
                            onChange={(e) => setAiCharInput(e.target.value)}
                            placeholder={isCharacterLocked
                              ? (language === "zh" ? "已锁定：开始写作后无法再添加角色" : "Locked: cannot add characters after writing starts")
                              : (language === "zh"
                                  ? "用自然语言描述新角色：\n姓名、性格、说话习惯、动机、关系……\nAI 会自动按格式写入 characters.md"
                                  : "Describe a new character in natural language:\nname, personality, speech, motivation, relations…\nAI will auto-format and append to characters.md")}
                            rows={4}
                            disabled={aiCharLoading || isCharacterLocked}
                            onKeyDown={(e) => {
                              if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
                                e.preventDefault()
                                handleAiAddCharacter()
                              }
                            }}
                          />
                          <button className="ai-char-btn"
                            onClick={handleAiAddCharacter}
                            disabled={!aiCharInput.trim() || aiCharLoading || isCharacterLocked}>
                            {aiCharLoading
                              ? (language === "zh" ? "⏳ AI 正在生成..." : "⏳ Generating...")
                              : isCharacterLocked
                                ? (language === "zh" ? "🔒 已锁定" : "🔒 Locked")
                                : (language === "zh" ? "🤖 AI 添加角色" : "🤖 AI Add Character")}
                          </button>
                          <div className="ai-char-hint">
                            {isCharacterLocked
                              ? (language === "zh" ? lockedReason : "Locked")
                              : (language === "zh" ? "Ctrl/⌘+Enter 快速提交" : "Ctrl/⌘+Enter to submit")}
                          </div>
                        </div>
                      </div>
                    </div>
                  )}
                  {/* 记忆 */}
                  {activeSidePanel === "memory" && (
                    <div className="side-panel">
                      <div className="side-panel-header">🧠 {language === "zh" ? "记忆" : "Memory"}</div>
                      <div className="side-panel-body">
                        <div className="memory-add-row">
                          <input type="text" placeholder={language === "zh" ? "添加记忆..." : "Add memory..."}
                            className="wb-input"
                            onKeyDown={(e) => {
                              if (e.key === "Enter" && e.target.value.trim()) {
                                handleAddMemory(e.target.value.trim())
                                e.target.value = ""
                              }
                            }}
                          />
                        </div>
                        {(activeProject.memory || []).slice(-10).reverse().map((m, i) => (
                          <div key={i} className="wb-memory-item">
                            <span className="wb-mem-type">{m.type}</span>
                            <span className="wb-mem-content">{m.content}</span>
                          </div>
                        ))}
                        {(!activeProject.memory || activeProject.memory.length === 0) && (
                          <div className="side-panel-empty">{language === "zh" ? "暂无记忆" : "No memory"}</div>
                        )}
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
                            <span className={`stage-badge stage-${activeProject.current_stage || "outline"}`}>
                              {stageLabel(activeProject.current_stage || "outline")}
                            </span>
                            <span style={{ fontSize: 11, opacity: 0.7 }}>
                              {activeProject.chapters_done || 0}/{activeProject.total_chapters || 0} {language === "zh" ? "章" : "chapters"}
                            </span>
                          </div>
                        </div>

                        {/* 阶段列表 */}
                        {(() => {
                          const stageOrder = { outline: 0, writing: 1, polish: 2, done: 3, completed: 3 }
                          const curIdx = stageOrder[activeProject.current_stage] ?? 0
                          return [
                            { key: "outline", label: "📖 " + (language === "zh" ? "大纲阶段" : "Outline"), desc: language === "zh" ? "生成小说大纲" : "Generate novel outline" },
                            { key: "writing", label: "✍️ " + (language === "zh" ? "写作阶段" : "Writing"), desc: language === "zh" ? "根据大纲写作" : "Write based on outline" },
                            { key: "polish", label: "🔍 " + (language === "zh" ? "审校阶段" : "Polish"), desc: language === "zh" ? "润色与审校" : "Polish and review" },
                          ].map((stage) => {
                            const stageIdx = stageOrder[stage.key] ?? 0
                            const isCurrent = activeProject.current_stage === stage.key
                            const isCompleted = stageIdx < curIdx
                            return (
                              <div key={stage.key} className={`wb-stage-item ${isCurrent ? "current" : ""} ${isCompleted ? "done" : ""}`}>
                                <div className="wb-stage-header">
                                  <span className="wb-stage-label">{stage.label}</span>
                                  {isCurrent && <span className="wb-stage-badge">{language === "zh" ? "进行中" : "Running"}</span>}
                                  {isCompleted && <span className="wb-stage-badge done">{language === "zh" ? "已完成" : "Done"}</span>}
                                </div>
                                <div className="wb-stage-desc">{stage.desc}</div>
                                <button
                                  className="wb-btn"
                                  style={{ marginTop: 6, width: "100%", fontSize: 11 }}
                                  onClick={() => { setSelectedStage(stage.key); setShowStageModal(true) }}
                                  disabled={isRunning}
                                >
                                  {isCurrent
                                    ? (language === "zh" ? "继续生成" : "Continue")
                                    : isCompleted
                                      ? (language === "zh" ? "重新生成" : "Re-run")
                                      : (language === "zh" ? "启动" : "Start")}
                                </button>
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
                          onClick={clearRunLogs}>
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
          {/* 知识图谱全屏模式 */}
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
                  onClear={clearRunLogs}
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
                    <button className="ce-btn ce-btn-edit" onClick={() => setChapterMode("edit")} disabled={!chapterDraft}>
                      {language === "zh" ? "编辑" : "Edit"}
                    </button>
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
                            {activeProject.chapters_done || 0}/{activeProject.total_chapters || "?"} {language === "zh" ? "章" : "ch"}
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
                  {isOutlineLocked && (
                    <span className="char-locked-badge" title={lockedReason} style={{ fontSize: 11 }}>
                      🔒 {language === "zh" ? "已锁定" : "Locked"}
                    </span>
                  )}
                  <button className="pc-btn primary small" onClick={handleSaveOutline}
                    disabled={isOutlineLocked}
                    title={isOutlineLocked ? lockedReason : ""}>
                    💾 {language === "zh" ? "保存" : "Save"}
                  </button>
                </div>
              </div>
              {isOutlineLocked && (
                <div className="char-locked-banner">
                  🔒 {lockedReason}
                </div>
              )}
              <div className="editor-body">
                <textarea value={outlineDraft}
                  onChange={(e) => setOutlineDraft(e.target.value)}
                  placeholder="# Outline\n\n1. Chapter 1 ..."
                  rows={25} className="editor-textarea"
                  readOnly={isOutlineLocked} />
              </div>
            </div>
          )}

          {/* 人物编辑器 */}
          {activeProject && activeRightPanel === "characters-editor" && (
            <CharacterPanel
              markdown={charactersDraft}
              language={language}
              onSave={handleSaveCharacters}
              onDeleteCharacter={handleDeleteCharacter}
              locked={isCharacterLocked}
              lockedReason={lockedReason}
            />
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

                  {/* 写作模式 */}
                  <div className="editor-field">
                    <label>{language === "zh" ? "写作模式" : "Writing Mode"}</label>
                    <div style={{ display: "flex", gap: 8 }}>
                      {[
                        { key: "lite", label: language === "zh" ? "标准" : "Standard", desc: language === "zh" ? "精简提示词" : "Compact" },
                        { key: "pro", label: language === "zh" ? "兼容" : "Compatible", desc: language === "zh" ? "详细提示词" : "Detailed" },
                        { key: "pro_polish", label: language === "zh" ? "完整" : "Full", desc: language === "zh" ? "润色循环" : "Polish loop" },
                      ].map(m => (
                        <div key={m.key}
                          onClick={() => setEditExecutionMode(m.key)}
                          style={{ flex: 1, padding: "6px 8px", border: editExecutionMode === m.key ? "2px solid var(--accent)" : "1px solid var(--border)", borderRadius: 6, cursor: "pointer", textAlign: "center", fontSize: 12 }}>
                          <div style={{ fontWeight: 600 }}>{m.label}</div>
                          <div style={{ fontSize: 10, opacity: 0.6 }}>{m.desc}</div>
                        </div>
                      ))}
                    </div>
                  </div>

                  {/* 大纲审核模式 */}
                  <div className="editor-field">
                    <label>{language === "zh" ? "大纲审核" : "Outline Review"}</label>
                    <div style={{ display: "flex", gap: 8 }}>
                      {[
                        { key: "auto", label: language === "zh" ? "AI 自动审核" : "AI Auto Review" },
                        { key: "manual", label: language === "zh" ? "人工确认" : "Manual Confirm" },
                      ].map(m => (
                        <div key={m.key}
                          onClick={() => setEditOutlineReviewMode(m.key)}
                          style={{ flex: 1, padding: "6px 8px", border: editOutlineReviewMode === m.key ? "2px solid var(--accent)" : "1px solid var(--border)", borderRadius: 6, cursor: "pointer", textAlign: "center", fontSize: 12 }}>
                          <div style={{ fontWeight: 600 }}>{m.label}</div>
                        </div>
                      ))}
                    </div>
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
              onClear={clearRunLogs}
              activeProject={activeProject}
            />
          )}
        </main>
      </div>

      {/* ==================== Modals ==================== */}
      {/* 新建项目 Modal */}
      {showCreate && (
        <div className="modal-overlay" onClick={() => setShowCreate(false)}>
          <div className="modal-box" onClick={(e) => e.stopPropagation()} style={{ maxWidth: 560, maxHeight: "90vh", overflowY: "auto" }}>
            <div className="modal-title">{language === "zh" ? "新建项目" : "New Project"}</div>
            <div className="modal-body">
              <div className="editor-field">
                <label>{language === "zh" ? "项目名称 *" : "Project Name *"}</label>
                <input value={newName} onChange={(e) => setNewName(e.target.value)}
                  placeholder="e.g. my_novel" />
              </div>
              <div className="editor-field">
                <label>{language === "zh" ? "小说标题" : "Novel Title"}</label>
                <input value={newTitle} onChange={(e) => setNewTitle(e.target.value)}
                  placeholder={language === "zh" ? "例如：星际大海" : "e.g. Star Chronicles"} />
              </div>
              <div className="editor-field">
                <label>{language === "zh" ? "题材" : "Genre"}</label>
                <select value={newGenre} onChange={(e) => setNewGenre(e.target.value)} className="wb-select" style={{ width: "100%" }}>
                  <option value="">{language === "zh" ? "选择题材（可选）" : "Select genre (optional)"}</option>
                  {GENRES.map(g => <option key={g} value={g}>{g}</option>)}
                </select>
              </div>
              <div className="editor-field">
                <label>{language === "zh" ? "预计章节数" : "Estimated Chapters"}</label>
                <input type="number" value={newChapterCount} onChange={(e) => setNewChapterCount(e.target.value)} min={1} max={999} />
              </div>

              {/* Writing mode */}
              <div className="editor-field">
                <label>{language === "zh" ? "写作模式" : "Writing Mode"}</label>
                <div style={{ display: "flex", gap: 8 }}>
                  {[
                    { key: "lite", label: language === "zh" ? "标准" : "Standard", desc: language === "zh" ? "精简提示词" : "Compact" },
                    { key: "pro", label: language === "zh" ? "兼容" : "Compatible", desc: language === "zh" ? "详细提示词" : "Detailed" },
                    { key: "pro_polish", label: language === "zh" ? "完整" : "Full", desc: language === "zh" ? "润色循环" : "Polish loop" },
                  ].map(m => (
                    <div key={m.key}
                      onClick={() => setNewWritingMode(m.key)}
                      style={{ flex: 1, padding: "8px 10px", border: newWritingMode === m.key ? "2px solid var(--accent)" : "1px solid var(--border)", borderRadius: 6, cursor: "pointer", textAlign: "center" }}>
                      <div style={{ fontWeight: 600, fontSize: 13 }}>{m.label}</div>
                      <div style={{ fontSize: 10, opacity: 0.6 }}>{m.desc}</div>
                    </div>
                  ))}
                </div>
              </div>

              {/* Outline review mode */}
              <div className="editor-field">
                <label>{language === "zh" ? "大纲审核" : "Outline Review"}</label>
                <div style={{ display: "flex", gap: 8 }}>
                  {[
                    { key: "auto", label: language === "zh" ? "AI 自动审核" : "AI Auto Review" },
                    { key: "manual", label: language === "zh" ? "人工确认" : "Manual Confirm" },
                  ].map(m => (
                    <div key={m.key}
                      onClick={() => setNewOutlineReviewMode(m.key)}
                      style={{ flex: 1, padding: "8px 10px", border: newOutlineReviewMode === m.key ? "2px solid var(--accent)" : "1px solid var(--border)", borderRadius: 6, cursor: "pointer", textAlign: "center" }}>
                      <div style={{ fontWeight: 600, fontSize: 13 }}>{m.label}</div>
                    </div>
                  ))}
                </div>
              </div>

              {/* 3 层大纲开关 */}
              <div className="editor-field">
                <label>{language === "zh" ? "三层大纲（三个同时进行）" : "3-Layer Outline (parallel)"}</label>
                <div style={{ display: "flex", gap: 8 }}>
                  {[
                    { key: "L1", icon: "📚", label: "L1", desc: language === "zh" ? "完整版" : "Full", color: "#1c1917" },
                    { key: "L2", icon: "🚀", label: "L2", desc: language === "zh" ? "网文版" : "Web", color: "#c2410c" },
                    { key: "L3", icon: "📝", label: "L3", desc: language === "zh" ? "单章细纲" : "Detail", color: "#0c4a6e" },
                  ].map(layer => {
                    const enabled = newOutlineLayers[layer.key]
                    const disabled = layer.key === "L1" ? false : (!newOutlineLayers.L1)
                    return (
                      <div key={layer.key}
                        onClick={() => {
                          if (disabled) return
                          if (layer.key === "L1") {
                            // L1 关闭时强制关闭 L2/L3
                            setNewOutlineLayers({
                              L1: !enabled,
                              L2: !enabled ? newOutlineLayers.L2 : false,
                              L3: !enabled ? newOutlineLayers.L3 : false,
                            })
                          } else {
                            setNewOutlineLayers({ ...newOutlineLayers, [layer.key]: !enabled })
                          }
                        }}
                        className="outline-layer-card"
                        style={{
                          flex: 1, padding: "10px 8px",
                          border: enabled ? `2px solid ${layer.color}` : "1px solid var(--border)",
                          borderRadius: 8, cursor: disabled ? "not-allowed" : "pointer",
                          textAlign: "center", opacity: disabled ? 0.4 : 1,
                          background: enabled ? `${layer.color}15` : "transparent",
                        }}>
                        <div style={{ fontSize: 22, marginBottom: 2 }}>{layer.icon}</div>
                        <div style={{ fontWeight: 700, fontSize: 13, color: enabled ? layer.color : "var(--text)" }}>{layer.label}</div>
                        <div style={{ fontSize: 10, opacity: 0.7 }}>{layer.desc}</div>
                        <div style={{ fontSize: 10, marginTop: 2, color: enabled ? layer.color : "var(--text-muted)" }}>
                          {enabled ? "✓ ON" : "○ OFF"}
                        </div>
                      </div>
                    )
                  })}
                </div>
                <div style={{ fontSize: 10, opacity: 0.6, marginTop: 4 }}>
                  {language === "zh" ? "关闭 L1 将自动级联关闭 L2/L3" : "Turning off L1 cascades to L2/L3"}
                </div>
              </div>

              {/* Per-role model assignment */}
              <div className="editor-field">
                <label>{language === "zh" ? "AI 模型分配" : "AI Model Assignment"}</label>
                {!presets || presets.length === 0 ? (
                  <div style={{ opacity: 0.6, fontSize: 12, padding: 8, background: "var(--bg-surface)", borderRadius: 6 }}>
                    {language === "zh" ? "请先配置 API 预设" : "Please configure an API preset first"}
                  </div>
                ) : (
                  <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                    {[
                      { role: "manager", label: language === "zh" ? "🧠 管理者 (Manager)" : "🧠 Manager", idx: newManagerIdx, setIdx: setNewManagerIdx },
                      { role: "worker", label: language === "zh" ? "✍️ 写手 (Worker)" : "✍️ Worker", idx: newWorkerIdx, setIdx: setNewWorkerIdx },
                      { role: "reviewer", label: language === "zh" ? "🔍 审校 (Reviewer)" : "🔍 Reviewer", idx: newReviewerIdx, setIdx: setNewReviewerIdx },
                    ].map(r => (
                      <div key={r.role} style={{ display: "flex", alignItems: "center", gap: 8 }}>
                        <span style={{ minWidth: 120, fontSize: 12 }}>{r.label}</span>
                        <select value={r.idx} onChange={e => r.setIdx(parseInt(e.target.value))}
                          className="wb-select" style={{ flex: 1 }}>
                          <option value={-1}>{language === "zh" ? "— 选择模型 —" : "— Select model —"}</option>
                          {presets.map((p, i) => (
                            <option key={i} value={i}>{p.name} ({p.model})</option>
                          ))}
                        </select>
                      </div>
                    ))}
                    {/* AI 对话模型（用于人物添加等轻量对话） */}
                    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                      <span style={{ minWidth: 120, fontSize: 12 }}>
                        💬 {language === "zh" ? "AI 对话模型" : "AI Chat Model"}
                      </span>
                      <select value={newChatPreset} onChange={e => setNewChatPreset(e.target.value)}
                        className="wb-select" style={{ flex: 1 }}
                        title={language === "zh" ? "用于侧边栏 AI 人物添加等轻量对话" : "For sidebar AI character input and other lightweight chat"}>
                        <option value="">{language === "zh" ? "— 选择模型 —" : "— Select model —"}</option>
                        {presets.map((p, i) => (
                          <option key={i} value={p.name}>{p.name} ({p.model})</option>
                        ))}
                      </select>
                    </div>
                  </div>
                )}
              </div>

              {/* Extra requirements */}
              <div className="editor-field">
                <label>{language === "zh" ? "附加要求（可选）" : "Extra Requirements (optional)"}</label>
                <textarea value={newExtraReqs} onChange={(e) => setNewExtraReqs(e.target.value)}
                  placeholder={language === "zh" ? "例如：节奏要快，要有爽点" : "e.g., Fast pacing, exciting moments"}
                  rows={3} className="editor-textarea" />
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

      {/* 启动阶段 Modal */}
      {showStageModal && activeProject && (
        <div className="modal-overlay" onClick={() => setShowStageModal(false)}>
          <div className="modal-box" onClick={(e) => e.stopPropagation()}>
            <div className="modal-title">▶ {language === "zh" ? "启动阶段" : "Run Stage"}</div>
            <div className="modal-body">
              <div className="editor-field">
                <label>{language === "zh" ? "阶段" : "Stage"}</label>
                <select value={selectedStage} onChange={(e) => setSelectedStage(e.target.value)}>
                  <option value="outline">{language === "zh" ? "大纲制作" : "Outline"}</option>
                  <option value="writing">{language === "zh" ? "正文写作" : "Writing"}</option>
                  <option value="polish">{language === "zh" ? "润色审校" : "Polish"}</option>
                </select>
              </div>
              <div className="editor-field">
                <label>{language === "zh" ? "附加指令（可选）" : "Additional Instructions (optional)"}</label>
                <textarea value={taskInput} onChange={(e) => setTaskInput(e.target.value)}
                  placeholder={language === "zh" ? "例：第3章需要重点描写战斗场景" : "e.g. Chapter 5 should focus on battle scenes"}
                  rows={3} />
              </div>
              <div className="editor-field">
                <label>{language === "zh" ? "大纲审核模式" : "Outline Review Mode"}</label>
                <select value={outlineReviewMode} onChange={(e) => setOutlineReviewMode(e.target.value)}>
                  <option value="auto">{language === "zh" ? "自动通过" : "Auto Pass"}</option>
                  <option value="manual">{language === "zh" ? "人工确认" : "Manual Review"}</option>
                </select>
              </div>
              <div className="modal-actions">
                <button className="pc-btn" onClick={() => setShowStageModal(false)}>
                  {language === "zh" ? "取消" : "Cancel"}
                </button>
                <button className="pc-btn primary" onClick={handleStartStage}>
                  ▶ {language === "zh" ? "启动" : "Run"}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Task Detail Modal (legacy) */}
      {selectedTask && taskDetail && (
        <TaskDetailModal
          t={t} language={language} presets={presets}
          taskFolder={selectedTask} taskDetail={taskDetail}
          onClose={() => { setSelectedTask(null); setTaskDetail(null) }}
          onResume={() => { setSelectedTask(null); setTaskDetail(null); handleResumeTask(selectedTask) }}
          isRunning={isRunning} showNotification={showNotification}
        />
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

