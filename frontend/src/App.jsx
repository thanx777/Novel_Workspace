import { useState, useEffect, useCallback } from "react"
import "./App.css"
import "./styles/kg_v2.css"
import { apiGet, apiPut, apiFetch } from "./api/client"
import Workbench from "./components/Workbench/index"
import { PresetPanel } from "./components/Sidebar"
import { ConfirmDialog, WorkspaceSettings } from "./components/Modals"
import { AppProvider, useApp } from "./context/AppContext"
import { PresetProvider, usePresetContext } from "./context/PresetContext"
import { ProjectProvider, useProjectContext } from "./context/ProjectContext"
import ErrorBoundary from "./components/ErrorBoundary"

function AppContent({
  t, language,
  agentCatalog, setAgentCatalog,
  notification, confirmDialog, setConfirmDialog,
  showWorkspaceSettings, setShowWorkspaceSettings,
  showPresetSidebar, setShowPresetSidebar,
  showNotification,
  workspaceSettings, setWorkspaceSettings,
  wsConfigLoading,
  fetchWorkspaceConfig,
  handleSaveWorkspaceConfig,
}) {
  const presetHook = usePresetContext()
  const projectV2 = useProjectContext()

  useEffect(() => {
    apiGet("/agent-catalog")
      .then(d => setAgentCatalog(d.agents || []))
      .catch(() => {})
  }, [])

  useEffect(() => { presetHook.fetchPresets() }, [presetHook.fetchPresets])

  return (
    <div className="app">

      <div className="workspace-new">
        {showPresetSidebar && (
          <aside className="preset-sidebar-overlay">
            <div className="preset-sidebar-panel">
              <div className="preset-sidebar-header">
                <span>⚙️ {t("presets")}</span>
                <button className="preset-sidebar-close" onClick={() => setShowPresetSidebar(false)} aria-label={t("ariaClose")}>
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
                </button>
              </div>
              <PresetPanel
                showNotification={showNotification}
                setConfirmDialog={setConfirmDialog}
              />
            </div>
          </aside>
        )}

        <Workbench
          setShowWorkspaceSettings={setShowWorkspaceSettings}
          setShowPresetSidebar={setShowPresetSidebar} showPresetSidebar={showPresetSidebar}
          showNotification={showNotification}
          agentCatalog={agentCatalog}
        />
      </div>

      <WorkspaceSettings
        showWorkspaceSettings={showWorkspaceSettings}
        setShowWorkspaceSettings={setShowWorkspaceSettings}
        workspaceSettings={workspaceSettings} setWorkspaceSettings={setWorkspaceSettings}
        handleSaveWorkspaceConfig={handleSaveWorkspaceConfig}
        wsConfigLoading={wsConfigLoading}
      />

      <ConfirmDialog confirmDialog={confirmDialog} setConfirmDialog={setConfirmDialog} />

      {notification && (
        <div className={`notification ${notification.type}`}>{notification.msg}</div>
      )}
    </div>
  )
}

function AppInner() {
  const { t, language } = useApp()
  const [agentCatalog, setAgentCatalog] = useState([])
  const [notification, setNotification] = useState(null)
  const [confirmDialog, setConfirmDialog] = useState(null)
  const [showWorkspaceSettings, setShowWorkspaceSettings] = useState(false)
  const [showPresetSidebar, setShowPresetSidebar] = useState(false)

  const showNotification = useCallback((msg, type = "info") => {
    setNotification({ msg, type, id: Date.now() })
    setTimeout(() => setNotification(null), 3500)
  }, [])

  const [workspaceSettings, setWorkspaceSettings] = useState({
    workspace_dir: "", projects_dir: "",
    current_workspace: "", current_projects: "",
    default_workspace: "", default_projects: ""
  })
  const [wsConfigLoading, setWsConfigLoading] = useState(false)

  const fetchWorkspaceConfig = useCallback(async () => {
    setWsConfigLoading(true)
    try {
      const data = await apiGet("/workspace-config")
      setWorkspaceSettings(data)
    } catch (e) { console.error(e) }
    finally { setWsConfigLoading(false) }
  }, [])

  useEffect(() => { fetchWorkspaceConfig() }, [fetchWorkspaceConfig])

  const handleSaveWorkspaceConfig = useCallback(async () => {
    try {
      await apiPut("/workspace-config", workspaceSettings)
      showNotification(t("settingsSaved"), "success")
    } catch (e) { showNotification("Failed: " + e.message, "error") }
  }, [workspaceSettings, showNotification, t])

  return (
    <PresetProvider showNotification={showNotification}>
      <ProjectProvider showNotification={showNotification} t={t}>
        <AppContent
          t={t}
          language={language}
          agentCatalog={agentCatalog}
          setAgentCatalog={setAgentCatalog}
          notification={notification}
          confirmDialog={confirmDialog}
          setConfirmDialog={setConfirmDialog}
          showWorkspaceSettings={showWorkspaceSettings}
          setShowWorkspaceSettings={setShowWorkspaceSettings}
          showPresetSidebar={showPresetSidebar}
          setShowPresetSidebar={setShowPresetSidebar}
          showNotification={showNotification}
          workspaceSettings={workspaceSettings}
          setWorkspaceSettings={setWorkspaceSettings}
          wsConfigLoading={wsConfigLoading}
          fetchWorkspaceConfig={fetchWorkspaceConfig}
          handleSaveWorkspaceConfig={handleSaveWorkspaceConfig}
        />
      </ProjectProvider>
    </PresetProvider>
  )
}

export default function App() {
  return (
    <AppProvider>
      <ErrorBoundary>
        <AppInner />
      </ErrorBoundary>
    </AppProvider>
  )
}
