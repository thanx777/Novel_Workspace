import { useState, useEffect, useRef } from "react"
import LogPanel from "./LogPanel"

/**
 * ProjectCenter — 项目中心首页，替换原来的 NovelWorkspace。
 * 功能：
 * 1. 左侧：项目列表 + 新建 / 删除
 * 2. 中间：当前项目详情（章节列表、记忆、大纲、阶段控制）
 * 3. 右侧：章节编辑器 / 大纲编辑 / 模型配置
 *
 * 简化版：用最小改动，不引入外部库。
 */
export default function ProjectCenter({
  t, language, projectV2, showNotification,
  presets, currentView, setCurrentView,
}) {
  const {
    projects, activeProject, loadingList, loadingDetail,
    createProject, deleteProject, loadProject,
    confirmOutline, rejectOutline, confirmWriting, confirmReview, stopTask, isRunning,
    updateChapter, addMemory, assistantChat,
    // 新引擎 API
    getEngineState,
    engineOutlineGenerate, engineOutlineChat, getOutlineState,
    engineWritingStart, engineWritingChat, getWritingState,
    engineReviewStart, getReviewState,
    putFile, getFile, migrateOld,
    loadProjectPresets, saveProjectPresets,
  } = projectV2

  // 创建项目表单
  const [showCreate, setShowCreate] = useState(false)
  const [newName, setNewName] = useState("")
  const [newTitle, setNewTitle] = useState("")
  const [newGenre, setNewGenre] = useState("")

  // 当前所选章节 / 面板
  const [selectedChapterIndex, setSelectedChapterIndex] = useState(null)
  const [rightPanel, setRightPanel] = useState("chapter") // chapter | outline | characters | assistant | modelConfig

  // 项目模型预设（三角色）
  const [projectPresets, setProjectPresets] = useState({ manager: {}, worker: {}, reviewer: {} })

  // 编辑内容
  const [chapterDraft, setChapterDraft] = useState("")
  const [chapterTitle, setChapterTitle] = useState("")
  const [chapterSummary, setChapterSummary] = useState("")
  const [outlineDraft, setOutlineDraft] = useState("")
  const [charactersDraft, setCharactersDraft] = useState("")

  // 助理对话
  const [assistantInput, setAssistantInput] = useState("")
  const [assistantReply, setAssistantReply] = useState("")
  const [assistantLoading, setAssistantLoading] = useState(false)

  // 阶段启动参数
  const [showStageModal, setShowStageModal] = useState(false)
  const [selectedStage, setSelectedStage] = useState("outline")

  // 引擎状态轮询
  const [engineState, setEngineState] = useState(null)
  useEffect(() => {
    if (!activeProject) { setEngineState(null); return }
    let timer
    const poll = async () => {
      const state = await getEngineState(activeProject.name)
      if (state) setEngineState(state)
    }
    poll()
    timer = setInterval(poll, 5000) // 5 秒轮询
    return () => clearInterval(timer)
  }, [activeProject?.name])
  const [taskInput, setTaskInput] = useState("")

  // 日志面板状态
  const [runLogs, setRunLogs] = useState([])
  const [elapsed, setElapsed] = useState(0)
  const elapsedTimerRef = useRef(null)
  const startedAtRef = useRef(null)

  const appendRunLog = (event) => {
    if (event?.type === "replace") {
      setRunLogs(event.logs || [])
      return
    }
    setRunLogs(prev => {
      const next = [...prev, { ...event, timestamp: event.timestamp || Date.now() }]
      return next.length > 100 ? next.slice(-100) : next
    })
  }
  const clearRunLogs = () => setRunLogs([])

  // 计时器：isRunning 期间累加 elapsed
  useEffect(() => {
    if (isRunning) {
      if (!startedAtRef.current) startedAtRef.current = Date.now()
      setElapsed(0)
      elapsedTimerRef.current = setInterval(() => {
        if (startedAtRef.current) {
          setElapsed(Math.floor((Date.now() - startedAtRef.current) / 1000))
        }
      }, 1000)
    } else {
      if (elapsedTimerRef.current) {
        clearInterval(elapsedTimerRef.current)
        elapsedTimerRef.current = null
      }
      startedAtRef.current = null
    }
    return () => {
      if (elapsedTimerRef.current) {
        clearInterval(elapsedTimerRef.current)
        elapsedTimerRef.current = null
      }
    }
  }, [isRunning])

  // ============ 创建项目 ============
  const handleCreate = async () => {
    if (!newName.trim()) {
      showNotification && showNotification("请输入项目名称", "error")
      return
    }
    const result = await createProject({
      name: newName.trim(),
      title: newTitle.trim(),
      genre: newGenre.trim(),
      total_chapters: 0,
    })
    if (result) {
      setNewName(""); setNewTitle(""); setNewGenre("");
      setShowCreate(false)
    }
  }

  // ============ 选择项目并加载详情 ============
  const handleSelect = async (name) => {
    setSelectedChapterIndex(null)
    setRightPanel("chapter")
    await loadProject(name)
  }

  // 项目切换时，加载模型预设
  useEffect(() => {
    if (!activeProject?.name) return
    ;(async () => {
      const data = await loadProjectPresets(activeProject.name)
      setProjectPresets(data || { manager: {}, worker: {}, reviewer: {} })
    })()
  }, [activeProject?.name])

  // ============ 选择章节 ============
  const handleSelectChapter = async (chap) => {
    setSelectedChapterIndex(chap.chapter_index)
    setChapterTitle(chap.title || "")
    setChapterSummary(chap.summary || "")
    // 从 v2 API 拉取正文
    if (activeProject) {
      const content = await getFile(activeProject.name, `chapters/第${chap.chapter_index}章.txt`)
      // 只在文件存在时才更新草稿；不存在时不覆盖现有输入
      if (content) {
        setChapterDraft(content)
      }
    }
    setRightPanel("chapter")
  }

  // ============ 保存章节 ============
  const handleSaveChapter = async () => {
    if (!activeProject || selectedChapterIndex == null) return
    await updateChapter(activeProject.name, selectedChapterIndex, {
      title: chapterTitle,
      summary: chapterSummary,
      content: chapterDraft,
      status: "draft",
    })
  }

  // ============ 大纲 / 人物设定 ============
  const handleOpenOutline = async () => {
    if (!activeProject) return
    const content = await getFile(activeProject.name, "outline.md")
    setOutlineDraft(content || "")
    setRightPanel("outline")
  }

  const handleOpenCharacters = async () => {
    if (!activeProject) return
    const content = await getFile(activeProject.name, "characters.md")
    setCharactersDraft(content || "")
    setRightPanel("characters")
  }

  const handleSaveOutline = async () => {
    if (!activeProject) return
    await putFile(activeProject.name, "outline.md", outlineDraft)
  }

  const handleSaveCharacters = async () => {
    if (!activeProject) return
    await putFile(activeProject.name, "characters.md", charactersDraft)
  }

  // ============ 直接启动写作（不弹模态框；点按钮 = 确认大纲） ============
  const handleStartWritingDirectly = async () => {
    if (!activeProject) return
    // 1) 先把项目状态推进到 writing（如果还在 outline）
    if (activeProject.current_stage === "outline") {
      try {
        await confirmOutline(activeProject.name)
      } catch (e) {
        // 忽略：可能项目已经在 writing 状态
      }
    }
    // 2) 清空日志、跑写作
    clearRunLogs()
    appendRunLog({
      status: "info", role: "系统",
      message: `▶ 准备启动 正文写作 阶段（已确认大纲）...`,
    })
    setRightPanel("logs")
    await engineWritingStart(activeProject.name, {
      startChapter: 1,
      totalChapters: activeProject.total_chapters || 0,
      onLogEvent: appendRunLog,
    })
  }

  // ============ 启动阶段 ============
  const handleStartStage = async () => {
    if (!activeProject) return
    setShowStageModal(false)
    // 切换到日志面板并清空之前日志
    clearRunLogs()
    const stageLabels = { outline: "大纲", writing: "正文", polish: "润色", done: "完成" }
    appendRunLog({
      status: "info", role: "系统",
      message: `准备启动 ${stageLabels[selectedStage] || selectedStage} 阶段...`,
    })
    setRightPanel("logs")
    // 根据阶段调用对应的新引擎函数
    if (selectedStage === "outline") {
      await engineOutlineGenerate(activeProject.name, {
        layer: "",
        requirements: taskInput,
        onLogEvent: appendRunLog,
      })
    } else if (selectedStage === "writing") {
      await engineWritingStart(activeProject.name, {
        startChapter: 1,
        totalChapters: activeProject.total_chapters || 0,
        onLogEvent: appendRunLog,
      })
    } else if (selectedStage === "polish" || selectedStage === "review") {
      await engineReviewStart(activeProject.name, {
        onLogEvent: appendRunLog,
      })
    }
  }

  // ============ AI 助理 ============
  const handleAssistantSend = async () => {
    if (!activeProject || !assistantInput.trim()) return
    setAssistantLoading(true)
    const reply = await assistantChat(activeProject.name, assistantInput.trim())
    setAssistantReply(reply || "(无回复)")
    setAssistantLoading(false)
    setAssistantInput("")
  }

  // ============ 辅助：状态文字 ============
  const stageLabel = (s) => ({
    outline: "大纲制作",
    writing: "正文写作",
    polish: "润色审校",
    completed: "已完成",
  }[s] || s)

  // ============ 渲染 ============
  return (
    <div className="project-center">
      {/* 顶部：项目标题栏 */}
      <div className="project-topbar">
        <div className="project-topbar-left">
          <span className="project-topbar-title">📚 项目中心</span>
          <span className="project-topbar-sub">
            {activeProject
              ? `当前: ${activeProject.name} ${activeProject.title ? ` · ${activeProject.title}` : ""}`
              : "未选择项目"}
          </span>
          {/* 视图切换按钮 */}
          <span style={{ marginLeft: 12, display: "inline-flex", gap: 4 }}>
            <button
              onClick={() => setCurrentView?.("project-center")}
              className="pc-btn small"
              style={{
                background: "var(--accent)", color: "var(--bg-base)",
                fontSize: 12, padding: "2px 8px", cursor: "default", opacity: 1,
              }}
            >📚 项目中心</button>
            <button
              onClick={() => setCurrentView?.("workbench")}
              className="pc-btn small"
              style={{
                background: "var(--bg-surface)", color: "var(--text)",
                fontSize: 12, padding: "2px 8px",
              }}
            >⚙️ Workbench</button>
          </span>
        </div>
        <div className="project-topbar-right">
          <button className="pc-btn" onClick={() => setShowCreate(true)}>➕ 新建项目</button>
          <button className="pc-btn secondary" onClick={migrateOld}>🔄 导入旧项目</button>
          {activeProject && (
            <>
              <button className="pc-btn danger" onClick={() => {
                if (confirm(`确定删除项目 "${activeProject.name}" 吗？`)) deleteProject(activeProject.name)
              }}>🗑 删除</button>
              <button className={`pc-btn ${rightPanel === "logs" ? "primary" : ""}`} onClick={() => setRightPanel("logs")}>
                📜 日志
                {runLogs.length > 0 && (
                  <span style={{ marginLeft: 4, padding: "0 5px", borderRadius: 8, background: "var(--accent)", color: "#fff", fontSize: 9, fontWeight: 700, minWidth: 14, display: "inline-block", textAlign: "center" }}>
                    {runLogs.length > 99 ? "99+" : runLogs.length}
                  </span>
                )}
                {isRunning && <span style={{ marginLeft: 4, color: "#3fb950" }}>●</span>}
              </button>
              <button className="pc-btn primary" onClick={() => setShowStageModal(true)}>
                ▶ 启动阶段
              </button>
              {isRunning && (
                <button className="pc-btn" onClick={() => stopTask(activeProject.name)}>⏹ 停止</button>
              )}
            </>
          )}
        </div>
      </div>

      <div className="project-body">
        {/* 左：项目列表 */}
        <aside className="project-sidebar">
          <div className="pc-section-title">项目列表 ({projects.length})</div>
          {loadingList && <div className="pc-empty">加载中...</div>}
          {!loadingList && projects.length === 0 && (
            <div className="pc-empty">暂无项目，点击"新建项目"开始</div>
          )}
          <div className="project-list">
            {projects.map((p) => {
              const active = activeProject?.name === p.name
              const stageTxt = stageLabel(p.current_stage || "outline")
              const done = p.total_chapters > 0
                ? `${p.chapters_done || 0} / ${p.total_chapters}`
                : `${p.chapters_done || 0} / 待定`
              return (
                <div
                  key={p.name}
                  className={`project-item ${active ? "active" : ""}`}
                  onClick={() => handleSelect(p.name)}
                >
                  <div className="project-item-title">{p.title || p.name}</div>
                  <div className="project-item-meta">
                    <span className={`stage-badge stage-${p.current_stage || "outline"}`}>{stageTxt}</span>
                    <span>{done} 章</span>
                    {p.genre && <span className="pc-genre">{p.genre}</span>}
                  </div>
                </div>
              )
            })}
          </div>

          {/* 项目详情：章节 / 记忆 */}
          {activeProject && (
            <div className="project-details">
              <div className="pc-section-title">📖 章节 ({activeProject.chapters?.length || 0})</div>
              <div className="chapter-list">
                {(activeProject.chapters || []).map((c) => (
                  <div
                    key={c.chapter_index}
                    className={`chapter-item ${selectedChapterIndex === c.chapter_index ? "active" : ""}`}
                    onClick={() => handleSelectChapter(c)}
                  >
                    <div className="chapter-idx">第 {c.chapter_index} 章</div>
                    <div className="chapter-name">{c.title || "(未命名)"}</div>
                    <div className="chapter-sub">{c.summary || ""}</div>
                  </div>
                ))}
                {activeProject.chapters?.length === 0 && (
                  <div className="pc-empty">无章节</div>
                )}
              </div>

              <div className="pc-section-title" style={{ marginTop: 12 }}>💡 快捷面板</div>
              <div className="quick-panel">
                <button className="pc-btn small" onClick={handleOpenOutline}>📋 大纲</button>
                <button className="pc-btn small" onClick={handleOpenCharacters}>🧑 人物</button>
                <button className="pc-btn small" onClick={() => setRightPanel("assistant")}>🤖 AI 助理</button>
                <button className="pc-btn small" onClick={() => setRightPanel("modelConfig")}>⚙️ 模型配置</button>
              </div>

              <div className="pc-section-title" style={{ marginTop: 12 }}>🧠 记忆 ({activeProject.memory?.length || 0})</div>
              <div className="memory-list">
                {(activeProject.memory || []).slice(-8).reverse().map((m, i) => (
                  <div key={i} className="memory-item">
                    <span className="mem-type">{m.type}</span>
                    <span className="mem-content">{m.content}</span>
                  </div>
                ))}
                {(!activeProject.memory || activeProject.memory.length === 0) && (
                  <div className="pc-empty">暂无记忆</div>
                )}
              </div>
            </div>
          )}
        </aside>

        {/* 中：主编辑区 */}
        <main className="project-main">
          {loadingDetail && <div className="pc-empty">加载详情...</div>}
          {!activeProject && !loadingDetail && (
            <div className="project-main-empty">
              <div className="project-main-empty-info">
                <div style={{ fontSize: 48, marginBottom: 12 }}>📚</div>
                <div style={{ fontSize: 18, fontWeight: 600 }}>请选择一个项目开始</div>
                <div style={{ opacity: 0.6, marginTop: 8 }}>或点击右上角"新建项目"</div>
              </div>
              <div className="project-main-empty-logs">
                <LogPanel
                  logs={runLogs}
                  isRunning={isRunning}
                  elapsed={elapsed}
                  language="zh"
                  onClear={clearRunLogs}
                  emptyMessage={
                    activeProject
                      ? null
                      : "启动一个项目阶段后，AI 生成过程会实时显示在这里。你可以先在左侧项目卡片上点击「启动阶段」按钮试试。"
                  }
                />
              </div>
            </div>
          )}

          {activeProject && rightPanel === "logs" && (
            <div className="editor-wrap" style={{ display: "flex", flexDirection: "column" }}>
              <div className="editor-header">
                <span>📜 运行日志</span>
                {activeProject && (
                  <span style={{ marginLeft: 8, opacity: 0.6, fontSize: 11 }}>
                    {activeProject.title || activeProject.name}
                  </span>
                )}
              </div>
              <div style={{ flex: 1, minHeight: 0, padding: 8, display: "flex" }}>
                <div style={{ flex: 1, minHeight: 0 }}>
                  <LogPanel
                    logs={runLogs}
                    isRunning={isRunning}
                    elapsed={elapsed}
                    language="zh"
                    onClear={clearRunLogs}
                    activeProject={activeProject}
                  />
                </div>
              </div>
            </div>
          )}

          {activeProject && rightPanel === "chapter" && (
            <div className="editor-wrap">
              <div className="editor-header">
                <span>✏️ 章节编辑</span>
                {selectedChapterIndex != null && (
                  <button className="pc-btn primary small" onClick={handleSaveChapter}>保存</button>
                )}
              </div>
              {selectedChapterIndex == null ? (
                <div className="pc-empty">从左侧选择一个章节开始编辑</div>
              ) : (
                <div className="editor-body">
                  <div className="editor-field">
                    <label>第 {selectedChapterIndex} 章 · 标题</label>
                    <input
                      type="text"
                      value={chapterTitle}
                      onChange={(e) => setChapterTitle(e.target.value)}
                      placeholder="章节标题"
                    />
                  </div>
                  <div className="editor-field">
                    <label>本章摘要</label>
                    <textarea
                      value={chapterSummary}
                      onChange={(e) => setChapterSummary(e.target.value)}
                      placeholder="本章核心情节..."
                      rows={2}
                    />
                  </div>
                  <div className="editor-field">
                    <label>正文</label>
                    <textarea
                      value={chapterDraft}
                      onChange={(e) => setChapterDraft(e.target.value)}
                      placeholder="章节正文..."
                      rows={18}
                      className="editor-textarea"
                    />
                  </div>
                </div>
              )}
            </div>
          )}

          {activeProject && rightPanel === "outline" && (
            <div className="editor-wrap">
              <div className="editor-header">
                <span>📋 大纲编辑</span>
                <button className="pc-btn primary small" onClick={handleSaveOutline}>保存</button>
              </div>
              <div className="editor-body">
                <textarea
                  value={outlineDraft}
                  onChange={(e) => setOutlineDraft(e.target.value)}
                  placeholder="# 大纲\n\n1. 第1章 ..."
                  rows={25}
                  className="editor-textarea"
                />
              </div>
            </div>
          )}

          {activeProject && rightPanel === "characters" && (
            <div className="editor-wrap">
              <div className="editor-header">
                <span>🧑 人物设定</span>
                <button className="pc-btn primary small" onClick={handleSaveCharacters}>保存</button>
              </div>
              <div className="editor-body">
                <textarea
                  value={charactersDraft}
                  onChange={(e) => setCharactersDraft(e.target.value)}
                  placeholder="# 人物设定\n\n**主角**：..."
                  rows={25}
                  className="editor-textarea"
                />
              </div>
            </div>
          )}

          {activeProject && rightPanel === "assistant" && (
            <div className="editor-wrap">
              <div className="editor-header">
                <span>🤖 项目 AI 助理</span>
              </div>
              <div className="assistant-body">
                <div className="assistant-input-row">
                  <input
                    type="text"
                    value={assistantInput}
                    onChange={(e) => setAssistantInput(e.target.value)}
                    placeholder="对 AI 说点什么...（例：我现在第5章，后面该怎么推进？）"
                    onKeyDown={(e) => { if (e.key === "Enter") handleAssistantSend() }}
                  />
                  <button className="pc-btn primary" onClick={handleAssistantSend} disabled={assistantLoading}>
                    {assistantLoading ? "思考中..." : "发送"}
                  </button>
                </div>
                <div className="assistant-reply">
                  {assistantReply || "（还没有对话，问点什么吧）"}
                </div>
                <div className="assistant-history">
                  <div className="assistant-history-title">最近对话</div>
                  {(activeProject.chat || []).slice(-5).reverse().map((c, i) => (
                    <div key={i} className="chat-line">
                      <b>[{c.role || "?"}]</b> {String(c.content || "").slice(0, 120)}
                    </div>
                  ))}
                </div>
              </div>
            </div>
          )}

          {activeProject && rightPanel === "modelConfig" && (
            <div className="editor-wrap">
              <div className="editor-header">
                <span>⚙️ 项目模型配置</span>
                <button
                  className="pc-btn primary small"
                  onClick={() => saveProjectPresets(activeProject.name, projectPresets)}
                >
                  保存到项目
                </button>
              </div>
              <div className="editor-body">
                <div className="mc-hint">
                  你可以为每个角色（经理/作者/审稿）指定不同的模型配置。保存后下次运行该项目时将自动使用这些配置。
                </div>
                {["manager", "worker", "reviewer"].map((role) => {
                  const roleLabels = { manager: "🎯 经理角色", worker: "⚡ 作者角色", reviewer: "🔍 审稿角色" }
                  const roleDescs = {
                    manager: "负责总体规划、章节结构、质量把控",
                    worker: "负责实际撰写章节正文",
                    reviewer: "负责审查章节内容，提出修改意见",
                  }
                  const p = projectPresets[role] || {}
                  const setField = (key, value) => {
                    setProjectPresets((prev) => ({
                      ...prev,
                      [role]: { ...(prev[role] || {}), [key]: value },
                    }))
                  }
                  return (
                    <div className="mc-card" key={role}>
                      <div className="mc-card-title">{roleLabels[role]}</div>
                      <div className="mc-card-desc">{roleDescs[role]}</div>
                      <div className="editor-field">
                        <label>预设名称</label>
                        <input
                          value={p.name || ""}
                          onChange={(e) => setField("name", e.target.value)}
                          placeholder="例：my-gpt"
                        />
                      </div>
                      <div className="editor-field">
                        <label>Base URL</label>
                        <input
                          value={p.base_url || ""}
                          onChange={(e) => setField("base_url", e.target.value)}
                          placeholder="https://api.example.com/v1"
                        />
                      </div>
                      <div className="editor-field">
                        <label>API Key</label>
                        <input
                          type="password"
                          value={p.api_key || ""}
                          onChange={(e) => setField("api_key", e.target.value)}
                          placeholder="sk-..."
                        />
                      </div>
                      <div className="editor-field">
                        <label>模型名称</label>
                        <input
                          value={p.model || ""}
                          onChange={(e) => setField("model", e.target.value)}
                          placeholder="gpt-4o-mini / claude-sonnet-4-20250514 / 其它模型名"
                        />
                      </div>
                      <div className="editor-field">
                        <label>API Format</label>
                        <select
                          value={p.api_format || "openai"}
                          onChange={(e) => setField("api_format", e.target.value)}
                        >
                          <option value="openai">OpenAI 兼容</option>
                          <option value="claude">Anthropic Claude</option>
                        </select>
                      </div>
                      <div className="mc-quick-row">
                        <span style={{ opacity: 0.7, fontSize: 12 }}>快速填充：</span>
                        {presets && presets.length > 0 ? (
                          presets.slice(0, 5).map((ps, i) => (
                            <button
                              key={i}
                              className="pc-btn tiny"
                              onClick={() => {
                                setProjectPresets((prev) => ({
                                  ...prev,
                                  [role]: {
                                    name: ps.name || "",
                                    api_key: ps.api_key || "",
                                    base_url: ps.base_url || "",
                                    model: ps.model || "",
                                    api_format: ps.api_format || "openai",
                                    chat_template_kwargs: ps.chat_template_kwargs || null,
                                  },
                                }))
                              }}
                            >
                              {ps.name}
                            </button>
                          ))
                        ) : (
                          <span style={{ fontSize: 12, opacity: 0.5 }}>（当前无全局预设）</span>
                        )}
                      </div>
                    </div>
                  )
                })}
              </div>
            </div>
          )}
        </main>

        {/* 右：大纲审核提示条（当处于 outline 阶段且需要人工审核时） */}
        <aside className="project-rightbar">
          <div className="stage-card">
            <div className="stage-card-title">🎯 当前阶段</div>
            <div className="stage-card-main">
              {engineState ? stageLabel(engineState.current_stage || "outline") : (activeProject ? stageLabel(activeProject.current_stage || "outline") : "—")}
            </div>
            {activeProject && (
              <>
                <div className="stage-card-sub">
                  {engineState && (
                    <>
                      {engineState.current_stage === "outline" && (
                        <div>大纲：{engineState.outline?.status || "pending"} · 已完成：{(engineState.outline?.completed_layers || []).join(", ") || "—"}</div>
                      )}
                      {engineState.current_stage === "writing" && (
                        <div>写作进度：{engineState.writing?.progress || "0/0"}</div>
                      )}
                      {engineState.current_stage === "review" && (
                        <div>审校：{engineState.review?.status || "pending"} · 已完成维度：{(engineState.review?.dimensions_done || []).join(", ") || "—"}</div>
                      )}
                    </>
                  )}
                  <div>章节进度：{activeProject.chapters_done || 0} / {activeProject.total_chapters || "待定"}</div>
                  <div>总字数：{activeProject.total_words || 0}</div>
                </div>
                <div className="stage-actions">
                  <button className="pc-btn small" disabled={isRunning} onClick={async () => {
                    if (!activeProject) return
                    clearRunLogs()
                    appendRunLog({ status: "info", role: "系统", message: "▶ 准备启动大纲阶段...", timestamp: Date.now() })
                    setRightPanel("logs")
                    await engineOutlineGenerate(activeProject.name, { onLogEvent: appendRunLog })
                  }}>生成大纲</button>
                  <button className="pc-btn small primary" disabled={isRunning} onClick={async () => {
                    if (!activeProject) return
                    clearRunLogs()
                    appendRunLog({ status: "info", role: "系统", message: "▶ 准备启动写作阶段...", timestamp: Date.now() })
                    setRightPanel("logs")
                    await engineWritingStart(activeProject.name, {
                      startChapter: 1,
                      totalChapters: activeProject.total_chapters || 100,
                      onLogEvent: appendRunLog,
                    })
                  }}>开始写作 ▶</button>
                  <button className="pc-btn small" disabled={isRunning} onClick={async () => {
                    if (!activeProject) return
                    clearRunLogs()
                    appendRunLog({ status: "info", role: "系统", message: "▶ 准备启动审校阶段...", timestamp: Date.now() })
                    setRightPanel("logs")
                    await engineReviewStart(activeProject.name, { onLogEvent: appendRunLog })
                  }}>全局审校</button>
                </div>
              </>
            )}
          </div>
          {isRunning && (
            <div className="running-card">
              <div className="running-dot"></div>
              <div>执行中...</div>
            </div>
          )}
        </aside>
      </div>

      {/* ========== 新建项目 Modal ========== */}
      {showCreate && (
        <div className="modal-overlay" onClick={() => setShowCreate(false)}>
          <div className="modal-box" onClick={(e) => e.stopPropagation()}>
            <div className="modal-title">➕ 新建项目</div>
            <div className="modal-body">
              <div className="editor-field">
                <label>项目名称 *</label>
                <input value={newName} onChange={(e) => setNewName(e.target.value)} placeholder="例：my_novel" />
              </div>
              <div className="editor-field">
                <label>小说标题</label>
                <input value={newTitle} onChange={(e) => setNewTitle(e.target.value)} placeholder="例：星辰大海" />
              </div>
              <div className="editor-field">
                <label>题材</label>
                <input value={newGenre} onChange={(e) => setNewGenre(e.target.value)} placeholder="例：玄幻 / 科幻 / 都市" />
              </div>
              <div className="editor-field" style={{color: '#888', fontSize: '12px'}}>
                章节数由大纲生成时自动确定
              </div>
            </div>
            <div className="modal-actions">
              <button className="pc-btn" onClick={() => setShowCreate(false)}>取消</button>
              <button className="pc-btn primary" onClick={handleCreate}>创建</button>
            </div>
          </div>
        </div>
      )}

      {/* ========== 启动阶段 Modal ========== */}
      {showStageModal && (
        <div className="modal-overlay" onClick={() => setShowStageModal(false)}>
          <div className="modal-box" onClick={(e) => e.stopPropagation()}>
            <div className="modal-title">▶ 启动 {stageLabel(selectedStage)} 阶段</div>
            <div className="modal-body">
              <div className="editor-field">
                <label>阶段</label>
                <select value={selectedStage} onChange={(e) => setSelectedStage(e.target.value)}>
                  <option value="outline">大纲制作</option>
                  <option value="writing">正文写作</option>
                  <option value="polish">润色审校</option>
                </select>
              </div>
              <div className="editor-field">
                <label>任务补充说明（可选）</label>
                <textarea
                  value={taskInput}
                  onChange={(e) => setTaskInput(e.target.value)}
                  placeholder="例：主角性格坚毅，成长线要清晰..."
                  rows={3}
                />
              </div>
            </div>
            <div className="modal-actions">
              <button className="pc-btn" onClick={() => setShowStageModal(false)}>取消</button>
              <button className="pc-btn primary" onClick={handleStartStage}>开始 {stageLabel(selectedStage)}</button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
