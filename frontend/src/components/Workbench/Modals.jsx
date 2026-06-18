import { useApp } from "../../context/AppContext"

export default function Modals({
  GENRES,
  showCreate, setShowCreate,
  newName, setNewName, newGenre, setNewGenre, newExtraReqs, setNewExtraReqs,
  newTotalChapters, setNewTotalChapters,
  newWordCountMin, setNewWordCountMin, newWordCountMax, setNewWordCountMax,
  newMaxRoundsWriting, setNewMaxRoundsWriting, newMaxRoundsOutline, setNewMaxRoundsOutline,
  newManagerIdx, setNewManagerIdx, newWorkerIdx, setNewWorkerIdx,
  newReviewerIdx, setNewReviewerIdx, newChatPreset, setNewChatPreset,
  showModelConfig, setShowModelConfig, presets, handleCreateProject,
  confirmDeleteProject, setConfirmDeleteProject, deleting, confirmDelete,
}) {
  const { t, language } = useApp()
  return (
    <>
      {/* 新建项目 Modal */}
      {showCreate && (
        <div className="modal-overlay" onClick={() => setShowCreate(false)}>
          <div className="modal-box" onClick={(e) => e.stopPropagation()} style={{ maxWidth: 520, maxHeight: "90vh", overflowY: "auto" }}>
            <div className="modal-title">{t("newProject")}</div>
            <div className="modal-body">
              <div className="editor-field">
                <label>{t("projectNameRequired")}</label>
                <input value={newName} onChange={(e) => setNewName(e.target.value)}
                  placeholder={t('projectNameExample')} />
              </div>

              {/* 小说题材（与 InkOS 体裁系统集成） */}
              <div className="editor-field">
                <label>{t("genreOptional")}</label>
                <select value={newGenre} onChange={(e) => setNewGenre(e.target.value)} className="wb-select" style={{ width: "100%" }}>
                  <option value="">{t("selectGenre")}</option>
                  {GENRES.map(g => <option key={g} value={g}>{g}</option>)}
                </select>
                <div style={{ fontSize: 10, opacity: 0.5, marginTop: 4 }}>
                  {t("genreHint")}
                </div>
              </div>

              {/* 预计总章节数 */}
              <div className="editor-field">
                <label>{t("refTotalChapters")}</label>
                <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <input type="number" value={newTotalChapters || ""} onChange={(e) => setNewTotalChapters(Number(e.target.value))}
                    min={0} max={2000} step={10} placeholder="0" style={{ width: 100 }} />
                  <span style={{ fontSize: 12, opacity: 0.6 }}>{t("chaptersAiDecides")}</span>
                </div>
                <div style={{ fontSize: 10, opacity: 0.5, marginTop: 4 }}>
                  {t("chaptersAutoPlan")}
                </div>
              </div>

              {/* 章节字数配置 */}
              <div className="editor-field">
                <label>{t("wordsPerChapter")}</label>
                <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <input type="number" value={newWordCountMin} onChange={(e) => setNewWordCountMin(Number(e.target.value))}
                    min={500} max={10000} step={500} style={{ width: 100 }} />
                  <span>~</span>
                  <input type="number" value={newWordCountMax} onChange={(e) => setNewWordCountMax(Number(e.target.value))}
                    min={1000} max={15000} step={500} style={{ width: 100 }} />
                  <span style={{ fontSize: 12, opacity: 0.6 }}>{t("wordCount")}</span>
                </div>
                <div style={{ fontSize: 10, opacity: 0.5, marginTop: 4 }}>
                  {t("wordsPerChapterHint")}
                </div>
              </div>

              {/* MWR 最大轮次配置 */}
              <div className="editor-field">
                <label>{t("mwrMaxRounds")}</label>
                <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <span style={{ fontSize: 12, opacity: 0.7 }}>{t("writing")}</span>
                  <input type="number" value={newMaxRoundsWriting} onChange={(e) => setNewMaxRoundsWriting(Number(e.target.value))}
                    min={3} max={50} step={1} style={{ width: 70 }} />
                  <span style={{ fontSize: 12, opacity: 0.7 }}>{t("outline")}</span>
                  <input type="number" value={newMaxRoundsOutline} onChange={(e) => setNewMaxRoundsOutline(Number(e.target.value))}
                    min={3} max={30} step={1} style={{ width: 70 }} />
                </div>
                <div style={{ fontSize: 10, opacity: 0.5, marginTop: 4 }}>
                  {t("mwrMaxRoundsHint")}
                </div>
              </div>

              {/* 项目要求（传给大纲生成阶段） */}
              <div className="editor-field">
                <label>{t("projectRequirements")}</label>
                <textarea value={newExtraReqs} onChange={(e) => setNewExtraReqs(e.target.value)}
                  placeholder={t('projectRequirementsPlaceholder')}
                  rows={5} className="editor-textarea" />
                <div style={{ fontSize: 10, opacity: 0.5, marginTop: 4 }}>
                  {t("titleGenreAutoDetermined")}
                </div>
              </div>

              {/* 模型配置（折叠） */}
              <div style={{ borderTop: "1px solid var(--border)", paddingTop: 8, marginTop: 8 }}>
                <button className="wb-btn" style={{ width: "100%", fontSize: 12, opacity: 0.7 }}
                  onClick={() => setShowModelConfig(!showModelConfig)}>
                  {showModelConfig ? "▼" : "▶"} {t("aiModelConfigAdvanced")}
                </button>
                {showModelConfig && (
                  <div style={{ marginTop: 8 }}>
                    {!presets || presets.length === 0 ? (
                      <div style={{ opacity: 0.6, fontSize: 12, padding: 8, background: "var(--bg-surface)", borderRadius: 6 }}>
                        {t("configurePresetsFirst")}
                      </div>
                    ) : (
                      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                        {[
                          { role: "manager", label: t("managerRole"), idx: newManagerIdx, setIdx: setNewManagerIdx },
                          { role: "worker", label: t("writerRole"), idx: newWorkerIdx, setIdx: setNewWorkerIdx },
                          { role: "reviewer", label: t("reviewerRole"), idx: newReviewerIdx, setIdx: setNewReviewerIdx },
                        ].map(r => (
                          <div key={r.role} style={{ display: "flex", alignItems: "center", gap: 8 }}>
                            <span style={{ minWidth: 80, fontSize: 12 }}>{r.label}</span>
                            <select value={r.idx} onChange={e => r.setIdx(parseInt(e.target.value))}
                              className="wb-select" style={{ flex: 1 }}>
                              <option value={-1}>{t("defaultOption")}</option>
                              {presets.map((p, i) => (
                                <option key={i} value={i}>{p.name} ({p.model})</option>
                              ))}
                            </select>
                          </div>
                        ))}
                        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                          <span style={{ minWidth: 80, fontSize: 12 }}>
                            💬 {t("chatModel")}
                          </span>
                          <select value={newChatPreset} onChange={e => setNewChatPreset(e.target.value)}
                            className="wb-select" style={{ flex: 1 }}>
                            <option value="">{t("defaultOption")}</option>
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
                  {t("cancel")}
                </button>
                <button className="pc-btn primary" onClick={handleCreateProject}>
                  {t("create")}
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
              <span>🗑 {t("deleteProject")}</span>
              <button className="pc-modal-close" onClick={() => setConfirmDeleteProject(null)} disabled={deleting}>×</button>
            </div>
            <div className="pc-modal-body">
              <div className="delete-warning-icon">⚠️</div>
              <div className="delete-warning-title">
                {t("confirmDeleteProject")}
              </div>
              <div className="delete-project-name">{confirmDeleteProject}</div>
              <div className="delete-warning-desc">
                {t("deleteProjectWarning")}
              </div>
              <div className="pc-modal-actions">
                <button className="pc-btn" onClick={() => setConfirmDeleteProject(null)} disabled={deleting}>
                  {t("cancel")}
                </button>
                <button className="pc-btn danger" onClick={confirmDelete} disabled={deleting}>
                  {deleting ? t("deleting") : t("confirmDeleteBtn")}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </>
  )
}
