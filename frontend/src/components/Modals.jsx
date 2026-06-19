import { useApp } from '../context/AppContext'

export function WorkspaceSettings({ showWorkspaceSettings, setShowWorkspaceSettings, workspaceSettings, setWorkspaceSettings, handleSaveWorkspaceConfig, wsConfigLoading }) {
  const { t } = useApp()
  if (!showWorkspaceSettings) return null
  return (
    <div className="confirm-overlay" onClick={() => setShowWorkspaceSettings(false)}>
      <div className="confirm-dialog project-modal" role="dialog" aria-modal="true" onClick={e => e.stopPropagation()}>
        <div className="project-modal-header">
          <span>{t('pathSettings')}</span>
          <button className="preset-edit-close" onClick={() => setShowWorkspaceSettings(false)} aria-label="关闭">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true"><line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" /></svg>
          </button>
        </div>
        <div className="project-modal-body">
          <div className="config-field">
            <label>{t('workspacePath')}</label>
            <input
              value={workspaceSettings.workspace_dir}
              onChange={e => setWorkspaceSettings(prev => ({ ...prev, workspace_dir: e.target.value }))}
              placeholder={workspaceSettings.default_workspace || ''}
            />
            <div style={{ fontSize: '10px', color: 'var(--text-dim)', marginTop: '2px' }}>
              {t('currentPath')}: {workspaceSettings.current_workspace || workspaceSettings.default_workspace || t('defaultPath')}
            </div>
          </div>
          <div className="config-field">
            <label>{t('projectsPath')}</label>
            <input
              value={workspaceSettings.projects_dir}
              onChange={e => setWorkspaceSettings(prev => ({ ...prev, projects_dir: e.target.value }))}
              placeholder={workspaceSettings.default_projects || ''}
            />
            <div style={{ fontSize: '10px', color: 'var(--text-dim)', marginTop: '2px' }}>
              {t('currentPath')}: {workspaceSettings.current_projects || workspaceSettings.default_projects || t('defaultPath')}
            </div>
          </div>
          <button
            className="preset-edit-save-btn"
            style={{ width: '100%', marginTop: '8px' }}
            onClick={handleSaveWorkspaceConfig}
            disabled={wsConfigLoading}
          >
            {wsConfigLoading ? t('testing') : t('savePreset')}
          </button>
        </div>
      </div>
    </div>
  )
}


export function ConfirmDialog({ confirmDialog, setConfirmDialog }) {
  const { t } = useApp()
  if (!confirmDialog) return null
  return (
    <div className="confirm-overlay" onClick={() => setConfirmDialog(null)}>
      <div className="confirm-dialog" role="dialog" aria-modal="true" onClick={e => e.stopPropagation()}>
        <div className="confirm-icon-wrapper">
          <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>
        </div>
        <div className="confirm-message">{confirmDialog.message}</div>
        <div className="confirm-actions">
          <button className="confirm-cancel" onClick={confirmDialog.onCancel}>{t('cancel')}</button>
          <button className="confirm-ok" onClick={confirmDialog.onConfirm}>{t('confirm')}</button>
        </div>
      </div>
    </div>
  )
}

export function DangerConfirmModal({ dangerCommand, setDangerCommand, onConfirm }) {
  const { t, language } = useApp()
  if (!dangerCommand) return null
  return (
    <div className="confirm-overlay" onClick={() => setDangerCommand(null)}>
      <div className="danger-confirm-dialog" role="dialog" aria-modal="true" onClick={e => e.stopPropagation()}>
        <div className="danger-confirm-icon">⚠️</div>
        <div className="danger-confirm-title">{language === 'zh' ? '危险命令确认' : 'Dangerous Command'}</div>
        <div className="danger-confirm-desc">{language === 'zh' ? 'Agent 请求执行以下命令，该命令可能造成不可逆操作：' : 'Agent requested to execute the following command, which may cause irreversible changes:'}</div>
        <div className="danger-confirm-cmd">{dangerCommand}</div>
        <div className="danger-confirm-actions">
          <button className="danger-confirm-reject" onClick={() => setDangerCommand(null)}>{language === 'zh' ? '拒绝执行' : 'Reject'}</button>
          <button className="danger-confirm-approve" onClick={() => { onConfirm(dangerCommand); setDangerCommand(null) }}>{language === 'zh' ? '确认执行' : 'Execute'}</button>
        </div>
      </div>
    </div>
  )
}
