import { useApp } from "../../context/AppContext"

export default function Toolbar({
  setShowWorkspaceSettings, setShowPresetSidebar, showPresetSidebar,
  isRunning, stopTask, activeProject,
  runLogs, elapsed, formatTime,
  setShowCreate, setActiveRightPanel, activeRightPanel,
}) {
  const { t, language, isDark, setIsDark, setLanguage } = useApp()
  return (
    <div className="wb-toolbar">
      <div className="wb-toolbar-left">
        <div className="toolbar-brand">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/>
            <path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/>
            <line x1="8" y1="7" x2="16" y2="7"/>
            <line x1="8" y1="11" x2="14" y2="11"/>
          </svg>
          <span>{t("novelForge")}</span>
        </div>
        <div className="toolbar-divider" />
        <button className={`toolbar-btn ${showPresetSidebar ? "active" : ""}`} onClick={() => setShowPresetSidebar(!showPresetSidebar)} title={t("presets")}>
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"/><line x1="3" y1="9" x2="21" y2="9"/><line x1="9" y1="21" x2="9" y2="9"/></svg>
          {t("presets")}
        </button>
        <button className="toolbar-btn" onClick={() => setShowWorkspaceSettings(true)} title={t("settings")}>
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>
          {t("settings")}
        </button>
        <div className="toolbar-divider" />
        <button className="wb-btn wb-btn-new" onClick={() => setShowCreate(true)} disabled={isRunning}>
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
          {t("newProject")}
        </button>
        {activeProject && (
          <>
            <button className={`wb-btn ${activeRightPanel === "logs" ? "active" : ""}`}
              onClick={() => setActiveRightPanel(activeRightPanel === "logs" ? "chapter-editor" : "logs")}
              title={t("runLogs")}>
              📜 {t("logs")}
              {runLogs.length > 0 && (
                <span style={{ marginLeft: 4, padding: "0 5px", borderRadius: 8, background: "var(--accent)", color: "#fff", fontSize: 9, fontWeight: 700, minWidth: 14, display: "inline-block", textAlign: "center" }}>
                  {runLogs.length > 99 ? "99+" : runLogs.length}
                </span>
              )}
            </button>
            {isRunning && (
              <button className="wb-btn wb-btn-stop" onClick={() => stopTask(activeProject?.name)}>
                ⏹ {t("stop")}
              </button>
            )}
          </>
        )}
      </div>
      <div className="wb-toolbar-right">
        {isRunning && <span className="wb-timer">⏱ {formatTime(elapsed)}</span>}
        {activeProject && (
          <span className="wb-progress">
            {activeProject.chapters_done || 0}/{activeProject.total_chapters || t('tbd')} {t("ch")}
          </span>
        )}
        <div className="toolbar-divider" />
        <button className="toolbar-btn lang-toggle" onClick={() => setLanguage(l => l === "zh" ? "en" : "zh")}>
          {language === "en" ? "中文" : "EN"}
        </button>
        <button className="toolbar-btn theme-toggle" onClick={() => setIsDark(!isDark)} aria-label="切换主题">
          {isDark ? (
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true"><circle cx="12" cy="12" r="5"/><path d="M12 1v2m0 18v2M21 12h2M1 12h2m16.95-6.95l1.414 1.414M2.636 21.364l1.414-1.414M4.636 4.636l1.414 1.414M17.95 19.364l1.414-1.414"/></svg>
          ) : (
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true"><path d="M21 12.79A9 9 0 1111.21 3 7 7 0 0021 12.79z"/></svg>
          )}
        </button>
      </div>
    </div>
  )
}
