import { useState, useEffect, useCallback } from "react"
import "./App.css"
import "./styles/kg_v2.css"
import { API_BASE } from "./constants"
import usePreset from "./hooks/usePreset"
import useProjectV2 from "./hooks/useProjectV2"
import Workbench from "./components/Workbench/index"
import { PresetPanel } from "./components/Sidebar"
import { ConfirmDialog, DangerConfirmModal, WorkspaceSettings } from "./components/Modals"
import { AppProvider, useApp } from "./context/AppContext"
import ErrorBoundary from "./components/ErrorBoundary"

function AppInner() {
  const { t, language } = useApp()
  const [agentCatalog, setAgentCatalog] = useState([])
  const [notification, setNotification] = useState(null)
  const [confirmDialog, setConfirmDialog] = useState(null)
  const [showWorkspaceSettings, setShowWorkspaceSettings] = useState(false)
  // eslint-disable-next-line no-unused-vars
  const [testLogs, setTestLogs] = useState([])
  const [dangerCommand, setDangerCommand] = useState(null)
  const [depMissing, setDepMissing] = useState(null)
  const [showPresetSidebar, setShowPresetSidebar] = useState(false)

  const showNotification = useCallback((msg, type = "info") => {
    setNotification({ msg, type, id: Date.now() })
    setTimeout(() => setNotification(null), 3500)
  }, [])

  const presetHook = usePreset({ showNotification })
  const projectV2 = useProjectV2({ t, showNotification, presets: presetHook.presets })

  useEffect(() => {
    fetch(`${API_BASE}/agent-catalog`)
      .then(r => r.json())
      .then(d => setAgentCatalog(d.agents || []))
      .catch(() => {})
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
      const resp = await fetch(`${API_BASE}/workspace-config`)
      if (resp.ok) setWorkspaceSettings(await resp.json())
    } catch (e) { console.error(e) }
    finally { setWsConfigLoading(false) }
  }, [])

  useEffect(() => { fetchWorkspaceConfig() }, [fetchWorkspaceConfig])

  useEffect(() => { presetHook.fetchPresets() }, [presetHook.fetchPresets])

  const handleSaveWorkspaceConfig = useCallback(async () => {
    try {
      await fetch(`${API_BASE}/workspace-config`, {
        method: "PUT", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(workspaceSettings)
      })
      showNotification(t("settingsSaved"), "success")
    } catch (e) { showNotification("Failed: " + e.message, "error") }
  }, [workspaceSettings, showNotification, t])

  const handleDangerConfirm = useCallback(async (command) => {
    try {
      const resp = await fetch(`${API_BASE}/test/confirm`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ instruction: `[TEST:CMD: ${command}]` })
      })
      const result = await resp.json()
      setTestLogs(prev => [...prev,
        { type: "prompt", data: `$ ${command} (force)`, elapsed: 0 },
        { type: result.success ? "done" : "error", data: result.output || result.error, exit_code: result.exit_code, elapsed: result.duration || 0 }
      ])
    } catch (err) {
      setTestLogs(prev => [...prev, { type: "error", data: err.message, elapsed: 0 }])
    }
  }, [])

  const handleDepInstall = useCallback(async (dep) => {
    setDepMissing(null)
    try {
      await fetch(`${API_BASE}/test/dep-install`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ module: dep.module, suggestion: dep.suggestion })
      })
      showNotification(`Installed ${dep.module}`, "success")
    } catch (e) { showNotification("Install failed: " + e.message, "error") }
  }, [showNotification])

  const handleDepSkip = useCallback(() => setDepMissing(null), [])

  return (
    <div className="app">

      <div className="workspace-new">
        {showPresetSidebar && (
          <aside className="preset-sidebar-overlay">
            <div className="preset-sidebar-panel">
              <div className="preset-sidebar-header">
                <span>⚙️ {t("presets")}</span>
                <button className="preset-sidebar-close" onClick={() => setShowPresetSidebar(false)} aria-label="关闭">
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
                </button>
              </div>
              <PresetPanel
                presets={presetHook.presets}
                defaultPreset={presetHook.defaultPreset}
                handleSetDefaultPreset={presetHook.handleSetDefaultPreset}
                handleClearDefaultPreset={presetHook.handleClearDefaultPreset}
                showAddPreset={presetHook.showAddPreset} setShowAddPreset={presetHook.setShowAddPreset}
                newPresetName={presetHook.newPresetName} setNewPresetName={presetHook.setNewPresetName}
                newPresetConfig={presetHook.newPresetConfig} setNewPresetConfig={presetHook.setNewPresetConfig}
                handleAddPreset={presetHook.handleAddPreset}
                handleDeletePreset={presetHook.handleDeletePreset}
                editingPreset={presetHook.editingPreset} setEditingPreset={presetHook.setEditingPreset}
                editPresetConfig={presetHook.editPresetConfig} setEditPresetConfig={presetHook.setEditPresetConfig}
                handleUpdatePreset={presetHook.handleUpdatePreset}
                runTestConnection={presetHook.runTestConnection}
                testConnState={presetHook.testConnState} testConnResult={presetHook.testConnResult}
                selectedNode={null} updateNodeConfig={() => {}}
                openEditPreset={presetHook.openEditPreset}
                showNotification={showNotification}
                setConfirmDialog={setConfirmDialog}
                applyPresetToAll={() => {}}
                allNodes={[]}
              />
            </div>
          </aside>
        )}

        <Workbench
          setShowWorkspaceSettings={setShowWorkspaceSettings}
          setShowPresetSidebar={setShowPresetSidebar} showPresetSidebar={showPresetSidebar}
          presets={presetHook.presets}
          defaultPreset={presetHook.defaultPreset}
          showNotification={showNotification}
          isRunning={projectV2.isRunning} setIsRunning={projectV2.setIsRunning}
          runningStage={projectV2.runningStage}
          agentCatalog={agentCatalog}
          projectV2={projectV2}
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
      <DangerConfirmModal dangerCommand={dangerCommand} setDangerCommand={setDangerCommand} onConfirm={handleDangerConfirm} />

      {depMissing && (
        <div className="confirm-overlay" onClick={handleDepSkip} onKeyDown={handleDepSkip} role="button" tabIndex={0}>
          <div className="danger-confirm-dialog" role="dialog" aria-modal="true">
            <div className="danger-confirm-icon">⚠️</div>
            <div className="danger-confirm-title">{t("missingDependency")}</div>
            <div className="danger-confirm-desc">
              {language === "zh"
                ? `Agent 测试时发现缺少依赖 "${depMissing.module}"，是否安装？`
                : `Agent detected missing dependency "${depMissing.module}". Install?`}
            </div>
            <div className="danger-confirm-cmd">{depMissing.suggestion}</div>
            <div className="danger-confirm-actions">
              <button className="danger-confirm-reject" onClick={handleDepSkip}>{t("skip")}</button>
              <button className="danger-confirm-approve" onClick={() => handleDepInstall(depMissing)}>
                {language === "zh" ? `安装 ${depMissing.module}` : `Install ${depMissing.module}`}
              </button>
            </div>
          </div>
        </div>
      )}

      {notification && (
        <div className={`notification ${notification.type}`}>{notification.msg}</div>
      )}
    </div>
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
