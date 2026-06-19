import { useApp } from "../../context/AppContext"
import { useProjectContext } from "../../context/ProjectContext"
import { API_BASE } from "../../constants"
import OutlinePanel from "../OutlinePanel"
import ChapterTree from "./ChapterTree"
import { formatTimestamp } from "@/utils/format"

export default function SidebarTabs({
  SIDE_TABS, activeSidePanel, setActiveSidePanel,
  handleOpenOutline, setActiveRightPanel,
  activeProject, kgData, engineState, stageLabel,
  isRunning, runningStage, clearRunLogsLocal, runLogs, appendRunLog,
  getFile, engineActionLock,
  volumes, expandedVolumes, setExpandedVolumes, handleSelectChapter,
  showNotification,
}) {
  const { t, language } = useApp()
  const {
    engineOutlineGenerate, engineWritingStart, engineReviewStart,
    confirmOutline, confirmWriting, confirmReview, stopTask,
  } = useProjectContext()
  return (
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
        {/* 章节列表 — 按分卷展开/折叠 */}
        {activeSidePanel === "chapters" && (
          <ChapterTree
            activeProject={activeProject}
            volumes={volumes}
            expandedVolumes={expandedVolumes}
            setExpandedVolumes={setExpandedVolumes}
            handleSelectChapter={handleSelectChapter}
          />
        )}
        {/* 大纲 - V2 三层 Tab + 多视图 */}
        {activeSidePanel === "outline" && (
          <OutlinePanel
            projectName={activeProject?.name}
            API_BASE={API_BASE}
            showNotification={showNotification}
          />
        )}
        {/* 图谱 — KG 实体 + 人物介绍 */}
        {activeSidePanel === "knowledge" && (
          <div className="side-panel">
            <div className="side-panel-header">🕸 {t("graph")}</div>
            <div className="side-panel-body">
              {/* KG 实体摘要 */}
              {kgData && (() => {
                const nodes = kgData.nodes || []
                const byType = {}
                nodes.forEach(n => { (byType[n.type] = byType[n.type] || []).push(n) })
                const typeLabels = {
                  character: { label: t("kgCharacters"), color: "#6ee7b7" },
                  foreshadowing: { label: t("kgForeshadowing"), color: "#fbbf24" },
                  scene: { label: t("kgScenes"), color: "#93c5fd" },
                  world_fact: { label: t("kgWorld"), color: "#c4b5fd" },
                  plot_thread: { label: t("kgPlotThreads"), color: "#fca5a5" },
                  chapter: { label: t("kgChapters"), color: "#67e8f9" },
                  outline_node: { label: t("kgOutline"), color: "#d1d5db" },
                  genre_rule: { label: t("kgGenreRules"), color: "#f87171" },
                  strand_tag: { label: t("kgStrandTags"), color: "#2dd4bf" },
                  coolpoint: { label: t("kgCoolpoints"), color: "#fbbf24" },
                  hook: { label: t("kgHooks"), color: "#a78bfa" },
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
                  {t("noGraphData")}
                </div>
              )}

              {/* 人物介绍 — 从 KG 角色节点实时读取 */}
              <div style={{ borderTop: "1px solid var(--border)", paddingTop: 8, marginTop: 8 }}>
                <div style={{ fontSize: 11, fontWeight: 600, marginBottom: 6, opacity: 0.7 }}>
                  👤 {t("characterProfiles")}
                </div>
                {(() => {
                  const kgChars = (kgData?.nodes || []).filter(n => n.type === "character")
                  if (kgChars.length === 0) {
                    return <div style={{ fontSize: 10, opacity: 0.5 }}>{t("noCharactersYet")}</div>
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
            <div className="side-panel-header">👤 {t("characters")}</div>
            <div className="side-panel-body">
              {/* KG 角色列表 — 实时从知识图谱读取 */}
              {(() => {
                const kgChars = (kgData?.nodes || []).filter(n => n.type === "character")
                if (kgChars.length === 0) {
                  return <div style={{ fontSize: 10, opacity: 0.5, padding: 8 }}>
                    {t("noCharactersAutoExtract")}
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
            <div className="side-panel-header">📋 {t("stages")}</div>
            <div className="side-panel-body">
              {/* 当前阶段状态 */}
              <div style={{ marginBottom: 12, padding: 8, background: "var(--bg-surface)", borderRadius: 6 }}>
                <div style={{ fontSize: 11, opacity: 0.6, marginBottom: 4 }}>
                  {t("currentStage")}
                </div>
                <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                  <span className={`stage-badge stage-${activeProject.current_stage || engineState?.current_stage || "outline"}`}>
                    {stageLabel(activeProject.current_stage || engineState?.current_stage || "outline")}
                  </span>
                  <span style={{ fontSize: 11, opacity: 0.7 }}>
                    {activeProject.chapters_done || 0}/{activeProject.total_chapters || t('tbd')} {t("chapters")}
                  </span>
                </div>
                {/* 引擎状态详情 */}
                {engineState && (
                  <div style={{ marginTop: 6, fontSize: 10, opacity: 0.7 }}>
                    {(() => {
                      const _s = activeProject.current_stage || engineState?.current_stage || "outline"
                      if (_s === "outline") return <div>{t("outline")}：{engineState.outline?.status || "pending"} · {t("layersDone")}：{(engineState.outline?.completed_layers || []).join(", ") || "—"}</div>
                      if (_s === "writing") return <div>{t("writingProgress")}：{engineState.writing?.progress || "0/0"}</div>
                      if (_s === "review" || _s === "polish") return <div>{t("reviewStage")}：{engineState.review?.status || "pending"}</div>
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
                  { key: "outline", label: "📖 " + t("outlineStage"), desc: t("outlineStageDesc"), btnLabel: t("generateOutline"), confirmLabel: t("confirmOutline") },
                  { key: "writing", label: "✍️ " + t("writingStage"), desc: t("writingStageDesc"), btnLabel: t("startWriting"), confirmLabel: t("confirmWriting") },
                  { key: "review", label: "🔍 " + t("reviewStageLabel"), desc: t("reviewStageDesc"), btnLabel: t("globalReview"), confirmLabel: t("confirmDone") },
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
                      // 正在运行 → 停止（不受 lock 限制，因为启动的 await 期间需要能停止）
                      try { await stopTask(activeProject.name) } catch {}
                      return
                    }
                    if (engineActionLock.current[stage.key]) return  // 防止同阶段重入（仅限启动）
                    engineActionLock.current[stage.key] = true
                    try {
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
                    } finally {
                      engineActionLock.current[stage.key] = false
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
                        {isCurrent && !isRunning && <span className="wb-stage-badge">{t("current")}</span>}
                        {isCurrent && isRunning && <span className="wb-stage-badge">{t("running")}</span>}
                        {isCompleted && <span className="wb-stage-badge done">{t("done")}</span>}
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
                            ? (t('stopBtn'))
                            : isCurrent
                              ? t("continueGen")
                              : isCompleted
                                ? t("rerun")
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
              📜 {t("runLogs")}
              <button className="wb-btn-sm" title={t("clear")}
                onClick={clearRunLogsLocal}>
                🗑
              </button>
            </div>
            <div className="side-panel-body">
              {runLogs.length === 0 ? (
                <div className="side-panel-empty">
                  {t("noLogsHint")}
                </div>
              ) : (
                <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                  {runLogs.slice(-15).reverse().map((log, i) => (
                    <div key={i} className={`wb-log-row log-${log.status || "info"}`}>
                      <span className="wb-log-time">
                        {formatTimestamp(log.timestamp, { short: true })}
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
                {t("viewFullLogs")}
              </button>
            </div>
          </div>
        )}
      </div>
    </>
  )
}
