import { useApp } from "../../context/AppContext"

export default function ChapterEditor({
  chapterTitle, chapterMode, editDraft, chapterDraft,
  setChapterMode, setAiMode, setEditDraft,
  aiMode, aiInstruction, setAiInstruction, handleAiEdit, aiLoading,
  handleSaveChapter, setActiveRightPanel, runLogs, isRunning,
  activeProject, stageLabel,
}) {
  const { t, language } = useApp()
  return (
    <div className="chapter-editor">
      {/* Toolbar */}
      <div className="chapter-editor-toolbar">
        <div className="chapter-editor-info">
          {chapterTitle ? (
            <>
              <span className="ce-filename">{chapterTitle}</span>
              <span className={`ce-badge ${chapterMode === "read" ? "ce-badge-read" : "ce-badge-edit"}`}>
                {chapterMode === "read" ? t("read") : t("editing")}
              </span>
              <span className="ce-badge"> {(editDraft || chapterDraft).length.toLocaleString()} {t("wordCount")}</span>
            </>
          ) : (
            <span style={{ opacity: 0.5 }}>{t("noChapterSelected")}</span>
          )}
        </div>
        <div className="chapter-editor-actions">
          {chapterMode === "read" ? (
            <>
              <button className="ce-btn ce-btn-edit" onClick={() => setChapterMode("edit")} disabled={!chapterDraft}>
                {t("editChapter")}
              </button>
              <button className="ce-btn ce-btn-ai" onClick={() => setAiMode(true)} disabled={!chapterDraft}>
                AI {t("aiEdit")}
              </button>
            </>
          ) : (
            <>
              <button className="ce-btn ce-btn-cancel" onClick={() => { setEditDraft(chapterDraft); setChapterMode("read") }}>
                Esc {t("cancel")}
              </button>
              <button className="ce-btn ce-btn-save" onClick={handleSaveChapter}>
                Ctrl+S {t("saveChapter")}
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
            placeholder={t("aiEditPlaceholder")}
            onKeyDown={e => { if (e.key === "Enter" && aiInstruction.trim()) handleAiEdit() }}
            disabled={aiLoading}
            autoFocus
          />
          <button className="ce-btn ce-btn-ai-submit" onClick={handleAiEdit} disabled={aiLoading || !aiInstruction.trim()}>
            {aiLoading ? t("processing") : t("submit")}
          </button>
          <button className="ce-btn ce-btn-ai-cancel" onClick={() => { setAiMode(false); setAiInstruction("") }} disabled={aiLoading}>
            {t("cancel")}
          </button>
        </div>
      )}

      {/* Content */}
      <div className="chapter-editor-content">
        {!chapterDraft && (
          <div className="read-empty">
            <div className="read-empty-icon">📖</div>
            <p>{t("noChapterContent")}</p>
            <p className="read-empty-hint">
              {t("selectChapterHint")}
            </p>
            <div style={{ display: "flex", gap: 8, marginTop: 16 }}>
              <button className="pc-btn primary small" onClick={() => setActiveRightPanel("logs")}>
                📜 {t("viewRunLogs")}
                {runLogs.length > 0 && (
                  <span style={{ marginLeft: 6, padding: "1px 6px", borderRadius: 8, background: "var(--accent)", color: "#fff", fontSize: 9, fontWeight: 700 }}>
                    {runLogs.length}
                  </span>
                )}
              </button>
              {isRunning && (
                <button className="pc-btn small" onClick={() => setActiveRightPanel("logs")}>
                  ⏱ {t("runningNow")}
                </button>
              )}
            </div>
            {activeProject && (
              <div style={{ marginTop: 20, padding: "10px 16px", background: "var(--bg-elevated)", borderRadius: 8, fontSize: 11, opacity: 0.7, maxWidth: 400 }}>
                <div style={{ marginBottom: 4 }}>
                  {t("currentProject")}：
                  <strong>{activeProject.title || activeProject.name}</strong>
                </div>
                <div>
                  {t("stage")}：
                  <span className={`stage-badge stage-${activeProject.current_stage || "outline"}`} style={{ marginLeft: 4 }}>
                    {stageLabel(activeProject.current_stage || "outline")}
                  </span>
                  <span style={{ marginLeft: 8 }}>
                    {activeProject.chapters_done || 0}/{activeProject.total_chapters || t('tbd')} {t("ch")}
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
            placeholder={t("startWritingPlaceholder")}
            autoFocus
          />
        )}
      </div>

      {/* Status bar */}
      <div className="chapter-editor-status">
        <span>{chapterTitle || t("noChapterSelected")}</span>
        <span>{t("lines")}: {(editDraft || chapterDraft).split("\n").length} · {t("wordCount")}: {(editDraft || chapterDraft).length.toLocaleString()}</span>
      </div>
    </div>
  )
}
