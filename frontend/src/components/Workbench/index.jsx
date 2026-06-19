import { useState, useEffect, useCallback, useRef } from "react"
import LogPanel from "../LogPanel"
import KnowledgeGraphView from "../KnowledgeGraphView"
import { API_BASE } from "../../constants"
import Toolbar from "./Toolbar"
import ProjectSidebar from "./ProjectSidebar"
import SidebarTabs from "./SidebarTabs"
import ChapterEditor from "./ChapterEditor"
import OutlineEditor from "./OutlineEditor"
import AssistantPanel from "./AssistantPanel"
import Modals from "./Modals"
import { useApp } from "../../context/AppContext"
import { useProjectContext } from "../../context/ProjectContext"
import { usePresetContext } from "../../context/PresetContext"
import { formatTime } from "@/utils/format"

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
  setShowWorkspaceSettings, setShowPresetSidebar, showPresetSidebar,
  showNotification,
  agentCatalog,
}) {
  const { t, language } = useApp()
  const projectV2 = useProjectContext()
  const { presets, defaultPreset } = usePresetContext()

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
    isRunning, setIsRunning, runningStage,
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
  const engineActionLock = useRef({})  // 防止 handleEngineAction 重入

  // ---- Volume (分卷) 展开/折叠 ----
  // volumes: [{ num, name, startChapter, endChapter }]
  const [volumes, setVolumes] = useState([])
  const [expandedVolumes, setExpandedVolumes] = useState({})  // { volNum: true/false }

  // 从 L1 大纲解析分卷信息；解析失败则按每 30 章自动分组
  useEffect(() => {
    if (!activeProject?.name || !getFile) {
      setVolumes([])
      setExpandedVolumes({})
      return
    }
    let cancelled = false
    ;(async () => {
      const l1 = await getFile(activeProject.name, "outline_L1.md")
      if (cancelled) return
      const chapters = activeProject.chapters || []
      const total = activeProject.total_chapters || chapters.length || 0
      let parsed = []
      if (l1) {
        // 匹配 "### 第X卷 卷名" 块
        const volRegex = /###\s*第\s*(\d+)\s*卷\s*[：:]*\s*(.+?)(?=\n###|\n##|\n#|$)/gs
        let m
        const rawVols = []
        while ((m = volRegex.exec(l1)) !== null) {
          const num = parseInt(m[1], 10)
          const name = m[2].trim().split("\n")[0].trim()
          // 尝试提取卷总章节
          const block = m[2]
          const chMatch = block.match(/卷总章节\*{0,2}\s*[：:]*\s*\*{0,2}\s*(\d+)/)
          const chCount = chMatch ? parseInt(chMatch[1], 10) : 0
          rawVols.push({ num, name, chCount })
        }
        // 计算每卷的章节范围
        let cursor = 1
        for (const v of rawVols) {
          const cnt = v.chCount > 0 ? v.chCount : 30
          parsed.push({
            num: v.num,
            name: v.name || `第${v.num}卷`,
            startChapter: cursor,
            endChapter: cursor + cnt - 1,
          })
          cursor += cnt
        }
      }
      // 兜底：按每 30 章自动分组
      if (parsed.length === 0 && total > 0) {
        const perVol = 30
        const volCount = Math.ceil(total / perVol)
        for (let i = 0; i < volCount; i++) {
          parsed.push({
            num: i + 1,
            name: `第${i + 1}卷`,
            startChapter: i * perVol + 1,
            endChapter: Math.min((i + 1) * perVol, total),
          })
        }
      }
      if (cancelled) return
      setVolumes(parsed)
      // 默认展开第一卷和包含当前选中章节的卷
      const init = {}
      parsed.forEach(v => { init[v.num] = false })
      if (parsed.length > 0) init[parsed[0].num] = true
      setExpandedVolumes(init)
    })()
    return () => { cancelled = true }
  }, [activeProject?.name, activeProject?.total_chapters, activeProject?.chapters?.length, getFile])

  // Sync editDraft when chapterDraft changes
  useEffect(() => { setEditDraft(chapterDraft) }, [chapterDraft])
  const [outlineDraft, setOutlineDraft] = useState("")
  // ---- Create Project Modal ----
  const [showCreate, setShowCreate] = useState(false)

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
  const [editWordCountMin, setEditWordCountMin] = useState(3000)
  const [editWordCountMax, setEditWordCountMax] = useState(5000)
  const [editMaxRoundsWriting, setEditMaxRoundsWriting] = useState(10)
  const [editMaxRoundsOutline, setEditMaxRoundsOutline] = useState(8)
  const [editTotalChapters, setEditTotalChapters] = useState(20)
  const [editExtraReqs, setEditExtraReqs] = useState("")

  // ---- Elapsed timer ----
  useEffect(() => {
    if (!isRunning) { setElapsed(0); return }
    const start = Date.now()
    const timer = setInterval(() => setElapsed(Math.floor((Date.now() - start) / 1000)), 1000)
    return () => clearInterval(timer)
  }, [isRunning])

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
        showNotification && showNotification(t("aiEditDone"), "success")
      }
    } catch (e) {
      showNotification && showNotification(t("aiEditFailed") + e.message, "error")
    } finally {
      setAiLoading(false)
    }
  }, [activeProject, selectedChapterIndex, aiInstruction, showNotification, t])

  // ---- Save outline ----
  const handleSaveOutline = useCallback(async () => {
    if (!activeProject) return
    await putFile(activeProject.name, "outline.md", outlineDraft)
    showNotification && showNotification(t("outlineSaved"), "success")
  }, [activeProject, outlineDraft, putFile, showNotification, t])

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
    setEditWordCountMin(activeProject.word_count_min || 3000)
    setEditWordCountMax(activeProject.word_count_max || 5000)
    setEditMaxRoundsWriting(activeProject.max_rounds_writing || 10)
    setEditMaxRoundsOutline(activeProject.max_rounds_outline || 8)
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
          word_count_min: Number(editWordCountMin) || 3000,
          word_count_max: Number(editWordCountMax) || 5000,
          max_rounds_writing: Number(editMaxRoundsWriting) || 10,
          max_rounds_outline: Number(editMaxRoundsOutline) || 8,
        }),
      })
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
      // 保存附加要求
      if (editExtraReqs) {
        await putFile(activeProject.name, "extra_requirements.txt", editExtraReqs)
      }
      await loadProject(activeProject.name)
      showNotification && showNotification(t("projectInfoSaved"), "success")
    } catch (e) {
      showNotification && showNotification(t("saveFailed") + e.message, "error")
    }
  }, [activeProject, editProjectTitle, editProjectGenre, editTotalChapters, editExtraReqs, editWordCountMin, editWordCountMax, editMaxRoundsWriting, editMaxRoundsOutline, loadProject, showNotification, putFile, t])

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
      showNotification && showNotification(t("projectDeleted"), "success")
    } catch (e) {
      showNotification && showNotification(t("deleteFailed") + e.message, "error")
    } finally {
      setDeleting(false)
    }
  }, [confirmDeleteProject, deleting, deleteProject, showNotification, t])

  // ---- Add memory ----
  const handleAddMemory = useCallback(async (content, memType = "note") => {
    if (!activeProject) return
    await addMemory(activeProject.name, content, memType)
    showNotification && showNotification(t("memoryAdded"), "success")
  }, [activeProject, addMemory, showNotification, t])

  // ---- Stop task ----
  const handleStopTask = useCallback(async () => {
    if (activeProject && stopTask) {
      await stopTask(activeProject.name)
    }
    setIsRunning(false)
  }, [activeProject, stopTask, setIsRunning])

  // ---- Stage label ----
  const stageLabel = (s) => ({ outline: t("stageOutline"), writing: t("stageWriting"), polish: t("stagePolish"), completed: t("stageComplete") }[s] || s)

  // ---- Sidebar tabs ----
  const SIDE_TABS = [
    { key: "chapters", label: t("chaptersTab"), icon: "📖" },
    { key: "outline", label: t("outline"), icon: "📋" },
    { key: "knowledge", label: t("graph"), icon: "🕸" },
    { key: "characters", label: t("charactersShort"), icon: "👤" },
    { key: "tasks", label: t("stages"), icon: "🚀" },
    { key: "logs", label: t("logs"), icon: "📜" },
  ]

  return (
    <div className="wb-container">
      {/* ==================== Toolbar ==================== */}
      <Toolbar
        setShowWorkspaceSettings={setShowWorkspaceSettings}
        setShowPresetSidebar={setShowPresetSidebar} showPresetSidebar={showPresetSidebar}
        isRunning={isRunning} stopTask={stopTask} activeProject={activeProject}
        runLogs={runLogs} elapsed={elapsed} formatTime={formatTime}
        setShowCreate={setShowCreate}
        setActiveRightPanel={setActiveRightPanel} activeRightPanel={activeRightPanel}
      />

      {/* ==================== Body ==================== */}
      <div className="wb-body">
        {/* ---- Left Sidebar ---- */}
        <aside className="wb-sidebar">
          <ProjectSidebar
            projects={projects} loadingList={loadingList} activeProject={activeProject}
            handleSelectProject={handleSelectProject}
            handleOpenProjectConfig={handleOpenProjectConfig}
            handleDeleteProject={handleDeleteProject}
            stageLabel={stageLabel}
          />

          {/* 子模块 Tabs */}
          {activeProject && (
            <SidebarTabs
              SIDE_TABS={SIDE_TABS}
              activeSidePanel={activeSidePanel} setActiveSidePanel={setActiveSidePanel}
              handleOpenOutline={handleOpenOutline}
              setActiveRightPanel={setActiveRightPanel}
              activeProject={activeProject}
              kgData={kgData} engineState={engineState} stageLabel={stageLabel}
              isRunning={isRunning} runningStage={runningStage}
              clearRunLogsLocal={clearRunLogsLocal} runLogs={runLogs} appendRunLog={appendRunLog}
              getFile={getFile}
              engineActionLock={engineActionLock}
              volumes={volumes} expandedVolumes={expandedVolumes} setExpandedVolumes={setExpandedVolumes}
              handleSelectChapter={handleSelectChapter}
              showNotification={showNotification}
            />
          )}
          {!activeProject && (
            <div className="side-panel-empty" style={{ padding: 16, textAlign: "center" }}>
              {t("selectProjectStart")}
            </div>
          )}
        </aside>

        {/* ---- Main Editor ---- */}
        <main className="wb-main">
          {/* 图谱全屏模式 */}
          {isKnowledgeMode && activeProject?.name && (
            <div className="kg-fullscreen-wrap" style={{ width: "100%", height: "100%", display: "flex", flexDirection: "column" }}>
              <KnowledgeGraphView
                API_BASE={API_BASE}
                projectName={activeProject.name}
              />
            </div>
          )}

          {!activeProject && !isKnowledgeMode && (
            <div className="wb-main-empty">
              <div className="wb-main-empty-info">
                <div style={{ fontSize: 48, marginBottom: 12 }}>📚</div>
                <div style={{ fontSize: 18, fontWeight: 600 }}>
                  {t("selectProjectSidebar")}
                </div>
                <div style={{ opacity: 0.6, marginTop: 8 }}>
                  {t("orClickNewProject")}
                </div>
              </div>
              <div className="wb-main-empty-logs">
                <LogPanel
                  logs={runLogs}
                  isRunning={isRunning}
                  elapsed={elapsed}
                  onClear={clearRunLogsLocal}
                  emptyMessage={t("runStageHint")}
                />
              </div>
            </div>
          )}

          {/* 章节编辑器 */}
          {activeProject && !isKnowledgeMode && activeRightPanel === "chapter-editor" && (
            <ChapterEditor
              chapterTitle={chapterTitle} chapterMode={chapterMode}
              editDraft={editDraft} chapterDraft={chapterDraft}
              setChapterMode={setChapterMode} setAiMode={setAiMode} setEditDraft={setEditDraft}
              aiMode={aiMode} aiInstruction={aiInstruction} setAiInstruction={setAiInstruction}
              handleAiEdit={handleAiEdit} aiLoading={aiLoading}
              handleSaveChapter={handleSaveChapter}
              setActiveRightPanel={setActiveRightPanel}
              runLogs={runLogs} isRunning={isRunning}
              activeProject={activeProject} stageLabel={stageLabel}
            />
          )}

          {/* 大纲编辑器 */}
          {activeProject && !isKnowledgeMode && activeRightPanel === "outline-editor" && (
            <OutlineEditor
              outlineDraft={outlineDraft} setOutlineDraft={setOutlineDraft}
              handleSaveOutline={handleSaveOutline}
            />
          )}

          {/* AI 助理 */}
          {activeProject && activeRightPanel === "assistant-editor" && (
            <AssistantPanel
              assistantInput={assistantInput} setAssistantInput={setAssistantInput}
              handleAssistantSend={handleAssistantSend}
              assistantLoading={assistantLoading} assistantReply={assistantReply}
            />
          )}

          {/* 项目配置 + 模型配置 */}
          {activeProject && activeRightPanel === "modelconfig-editor" && (
            <div className="editor-wrap">
              <div className="editor-header">
                <span>⚙️ {t("projectConfig")}</span>
                <div className="flex-gap-md">
                  <button className="pc-btn primary small"
                    onClick={handleSaveProjectInfo}>
                    💾 {t("saveInfo")}
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
                    💾 {t("saveModels")}
                  </button>
                </div>
              </div>
              <div className="editor-body">
                {/* 项目基本信息 */}
                <div className="config-section-lg">
                  <div className="config-section-title-lg">{t("projectInfo")}</div>
                  <div className="editor-field">
                    <label>{t("projectName")}</label>
                    <input value={editProjectName} disabled
                      className="text-hint" />
                  </div>
                  <div className="editor-field">
                    <label>{t("novelTitle")}</label>
                    <input value={editProjectTitle} onChange={(e) => setEditProjectTitle(e.target.value)}
                      placeholder={t("novelTitle")} />
                  </div>
                  <div className="editor-field">
                    <label>{t("genre")}</label>
                    <select value={editProjectGenre} onChange={(e) => setEditProjectGenre(e.target.value)} className="wb-select wb-select-full">
                      <option value="">{t("selectGenre")}</option>
                      {GENRES.map(g => <option key={g} value={g}>{g}</option>)}
                    </select>
                  </div>
                  <div className="editor-field">
                    <label>{t("refChapters")}</label>
                    <input type="number" value={editTotalChapters} onChange={(e) => setEditTotalChapters(e.target.value)} min={1} max={999} />
                  </div>
                  <div className="editor-field">
                    <label>{t("wordsPerChapter")}</label>
                    <div className="flex-gap-md" style={{ alignItems: "center" }}>
                      <input type="number" value={editWordCountMin} onChange={(e) => setEditWordCountMin(Number(e.target.value))}
                        min={500} max={10000} step={500} className="num-input-md" />
                      <span>~</span>
                      <input type="number" value={editWordCountMax} onChange={(e) => setEditWordCountMax(Number(e.target.value))}
                        min={1000} max={15000} step={500} className="num-input-md" />
                      <span className="text-hint">{t("wordCount")}</span>
                    </div>
                  </div>
                  <div className="editor-field">
                    <label>{t("mwrMaxRounds")}</label>
                    <div className="flex-gap-md" style={{ alignItems: "center" }}>
                      <span className="text-hint-70">{t("writing")}</span>
                      <input type="number" value={editMaxRoundsWriting} onChange={(e) => setEditMaxRoundsWriting(Number(e.target.value))}
                        min={3} max={50} step={1} className="num-input-sm" />
                      <span className="text-hint-70">{t("outline")}</span>
                      <input type="number" value={editMaxRoundsOutline} onChange={(e) => setEditMaxRoundsOutline(Number(e.target.value))}
                        min={3} max={30} step={1} className="num-input-sm" />
                    </div>
                  </div>

                  {/* 附加要求 */}
                  <div className="editor-field">
                    <label>{t("extraRequirements")}</label>
                    <textarea value={editExtraReqs} onChange={(e) => setEditExtraReqs(e.target.value)}
                      placeholder={t('extraReqsPlaceholder')}
                      rows={3} className="editor-textarea" />
                  </div>
                </div>

                {/* AI 对话模型（用于人物输入等轻量对话） */}
                <div className="config-section-accent">
                  <div className="config-section-title">
                    💬 {t("aiChatModel")}
                  </div>
                  <select value={aiChatPreset} onChange={e => setAiChatPreset(e.target.value)}
                    className="wb-select wb-select-full"
                    title={t("aiChatModelHint")}>
                    <option value="">{t("defaultFirstAvailable")}</option>
                    {presets?.map((p, i) => (
                      <option key={i} value={p.name}>{p.name} ({p.model})</option>
                    ))}
                  </select>
                  <div className="preset-hint-sm" style={{ marginTop: 4 }}>
                    {t("aiChatModelDesc")}
                  </div>
                </div>

                {/* 模型配置 */}
                <div className="text-hint-70" style={{ marginBottom: 12 }}>
                  {t("rolePresetHint")}
                </div>
                {["manager", "worker", "reviewer"].map((role) => {
                  const roleLabels = { manager: "🧠 Manager", worker: "✍️ Writer", reviewer: "🔍 Reviewer" }
                  const p = projectPresets[role] || {}
                  const currentPresetName = p.name || ""
                  const handlePresetSelect = (presetName) => {
                    if (!presetName) {
                      setProjectPresets(prev => ({ ...prev, [role]: {} }))
                    } else {
                      const selected = (presets || []).find(ps => ps.name === presetName)
                      if (selected) {
                        setProjectPresets(prev => ({
                          ...prev,
                          [role]: { name: selected.name, api_key: selected.api_key, base_url: selected.base_url, model: selected.model, api_format: selected.api_format || "openai" }
                        }))
                      }
                    }
                  }
                  return (
                    <div key={role} className="config-section">
                      <div className="config-section-title">{roleLabels[role]}</div>
                      <select className="wb-select wb-select-full" value={currentPresetName} onChange={(e) => handlePresetSelect(e.target.value)}>
                        <option value="">{t("defaultFirstAvailable")}</option>
                        {presets?.map((ps, i) => (
                          <option key={i} value={ps.name}>{ps.name} ({ps.model})</option>
                        ))}
                      </select>
                      {currentPresetName && (
                        <div className="preset-hint-sm" style={{ marginTop: 4 }}>
                          {p.base_url} · {p.model}
                        </div>
                      )}
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
              onClear={clearRunLogsLocal}
              activeProject={activeProject}
            />
          )}
        </main>
      </div>

      {/* ==================== Modals ==================== */}
      <Modals
        GENRES={GENRES}
        showCreate={showCreate} setShowCreate={setShowCreate}
        confirmDeleteProject={confirmDeleteProject} setConfirmDeleteProject={setConfirmDeleteProject}
        deleting={deleting} confirmDelete={confirmDelete}
      />
    </div>
  )
}
