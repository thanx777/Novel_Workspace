import { useState, useEffect, useCallback } from "react"
import "./App.css"
import "./styles/kg_v2.css"
import { apiGet, apiPost, apiPut, apiFetch } from "./api/client"
import Workbench from "./components/Workbench/index"
import { PresetPanel } from "./components/Sidebar"
import { ConfirmDialog, WorkspaceSettings } from "./components/Modals"
import { AppProvider, useApp } from "./context/AppContext"
import { PresetProvider, usePresetContext } from "./context/PresetContext"
import { ProjectProvider, useProjectContext } from "./context/ProjectContext"
import ErrorBoundary from "./components/ErrorBoundary"

const setupInputStyle = {
  padding: "10px 14px", borderRadius: 8, border: "1px solid rgba(255,255,255,0.12)",
  background: "rgba(255,255,255,0.06)", color: "#e0e0e0", fontSize: 14, outline: "none"
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
  const [needsSetup, setNeedsSetup] = useState(null) // null=checking, true=引导, false=已配置

  useEffect(() => {
    apiGet("/agent-catalog")
      .then(d => setAgentCatalog(d.agents || []))
      .catch(() => {})
  }, [])

  useEffect(() => { presetHook.fetchPresets() }, [presetHook.fetchPresets])

  // 检测是否需要首次引导
  useEffect(() => {
    if (presetHook.presets.length > 0) {
      setNeedsSetup(false)
    } else if (presetHook.presets.length === 0 && needsSetup === null) {
      // presets 已加载但为空 → 需要引导
      setNeedsSetup(true)
    }
  }, [presetHook.presets, needsSetup])

  // 首次引导：创建预设
  const [setupConfig, setSetupConfig] = useState({
    name: "default", api_key: "", base_url: "", model: "", api_format: "openai", thinking_mode: "disabled"
  })
  const [setupSaving, setSetupSaving] = useState(false)

  const handleSetupSave = useCallback(async () => {
    if (!setupConfig.api_key.trim() || !setupConfig.model.trim() || !setupConfig.base_url.trim()) return
    setSetupSaving(true)
    try {
      await apiPost("/presets", setupConfig)
      await presetHook.fetchPresets()
      setNeedsSetup(false)
    } catch (e) {
      // ignore
    } finally {
      setSetupSaving(false)
    }
  }, [setupConfig, presetHook])

  // 首次引导界面
  if (needsSetup === true) {
    return (
      <div className="app">
        <div style={{
          display: "flex", alignItems: "center", justifyContent: "center",
          minHeight: "100vh", background: "linear-gradient(135deg, #0f0f1a 0%, #1a1a2e 50%, #16213e 100%)"
        }}>
          <div style={{
            background: "rgba(30,30,50,0.95)", borderRadius: 16, padding: 40,
            maxWidth: 480, width: "90%", boxShadow: "0 8px 32px rgba(0,0,0,0.4)",
            border: "1px solid rgba(255,255,255,0.08)"
          }}>
            <h2 style={{ color: "#e0e0e0", marginBottom: 8, fontSize: 22 }}>
              {language === "zh" ? "欢迎使用 Novel Workspace" : "Welcome to Novel Workspace"}
            </h2>
            <p style={{ color: "#999", marginBottom: 24, fontSize: 14 }}>
              {language === "zh"
                ? "首次使用请配置 AI 模型的 API Key，保存后即可开始写作"
                : "Configure your AI model API Key to get started"}
            </p>
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              <input placeholder={language === "zh" ? "API 地址 (Base URL)" : "Base URL"}
                value={setupConfig.base_url} onChange={e => setSetupConfig(p => ({...p, base_url: e.target.value}))}
                style={setupInputStyle} />
              <input placeholder={language === "zh" ? "API Key" : "API Key"} type="password"
                value={setupConfig.api_key} onChange={e => setSetupConfig(p => ({...p, api_key: e.target.value}))}
                style={setupInputStyle} />
              <input placeholder={language === "zh" ? "模型名称 (如 gpt-4o)" : "Model (e.g. gpt-4o)"}
                value={setupConfig.model} onChange={e => setSetupConfig(p => ({...p, model: e.target.value}))}
                style={setupInputStyle} />
              <button onClick={handleSetupSave} disabled={setupSaving || !setupConfig.api_key.trim() || !setupConfig.model.trim() || !setupConfig.base_url.trim()}
                style={{
                  marginTop: 8, padding: "12px 24px", borderRadius: 8, border: "none",
                  background: (setupSaving || !setupConfig.api_key.trim() || !setupConfig.model.trim() || !setupConfig.base_url.trim())
                    ? "#444" : "#6c5ce7", color: "#fff", fontSize: 15, fontWeight: 600, cursor: "pointer"
                }}>
                {setupSaving
                  ? (language === "zh" ? "保存中..." : "Saving...")
                  : (language === "zh" ? "保存并开始" : "Save & Start")}
              </button>
            </div>
          </div>
        </div>
      </div>
    )
  }

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

export default function App() {
  return (
    <AppProvider>
      <ErrorBoundary>
        <AppInner />
      </ErrorBoundary>
    </AppProvider>
  )
}
