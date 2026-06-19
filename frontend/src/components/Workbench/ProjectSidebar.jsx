import { useApp } from "../../context/AppContext"
import { AccessibleButton } from "../common/AccessibleButton"

export default function ProjectSidebar({
  projects, loadingList, activeProject,
  handleSelectProject, handleOpenProjectConfig, handleDeleteProject,
  stageLabel,
}) {
  const { t, language } = useApp()
  return (
    <>
      <div className="wb-sidebar-tabs" style={{ borderBottom: "1px solid var(--border)" }}>
        <div className="project-list-header">
          <span style={{ fontSize: 11, fontWeight: 600, opacity: 0.7 }}>
            📚 {t("projects")} ({projects?.length || 0})
          </span>
        </div>
      </div>
      <div className="wb-sidebar-content" style={{ padding: 0 }}>
        {/* 项目列表 */}
        <div className="project-list-scroll">
          {loadingList && <div className="side-panel-empty">{t("loading")}</div>}
          {!loadingList && (!projects || projects.length === 0) && (
            <div className="side-panel-empty" style={{ fontSize: 11 }}>
              {t("noProjectsYet")}
            </div>
          )}
          {projects?.map((p) => {
            const active = activeProject?.name === p.name
            return (
              <AccessibleButton key={p.name} className={`wb-project-item ${active ? "active" : ""}`}
                onClick={() => handleSelectProject(p.name)}>
                <div className="wb-project-title">{p.title || p.name}</div>
                <div className="wb-project-meta">
                  <span className={`stage-badge stage-${p.current_stage || "outline"}`}>
                    {stageLabel(p.current_stage || "outline")}
                  </span>
                  <span>{p.genre || ""}</span>
                  <span>{p.chapters_done || 0}/{p.total_chapters || t('tbd')} {t("ch")}</span>
                </div>
                {active && (
                  <div className="flex-gap-xs" style={{ position: "absolute", right: 4, top: 4 }}>
                    <button className="wb-btn-sm"
                      onClick={(e) => { e.stopPropagation(); handleOpenProjectConfig() }}
                      title={t("projectConfig")}
                      aria-label={t("ariaProjectConfig")}
                      style={{ opacity: 0.6, background: "none", border: "none", cursor: "pointer", padding: 2 }}>
                      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>
                    </button>
                    <button className="wb-btn-sm wb-btn-delete"
                      onClick={(e) => { e.stopPropagation(); handleDeleteProject(p.name) }}
                      title={t("delete")}
                      aria-label={t("ariaDelete")}>
                      <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14H6L5 6"/></svg>
                    </button>
                  </div>
                )}
              </AccessibleButton>
            )
          })}
        </div>
      </div>
    </>
  )
}
