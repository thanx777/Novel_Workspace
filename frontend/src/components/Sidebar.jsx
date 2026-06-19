import { API_FORMATS } from '../constants'
import TestResultCard from './TestResultCard'
import { useApp } from '../context/AppContext'
import { usePresetContext } from '../context/PresetContext'

export function PresetPanel({ showNotification, setConfirmDialog }) {
  const { t, language } = useApp()
  const {
    presets, defaultPreset, handleSetDefaultPreset, handleClearDefaultPreset,
    showAddPreset, setShowAddPreset,
    newPresetName, setNewPresetName,
    newPresetConfig, setNewPresetConfig,
    editingPreset, setEditingPreset,
    editPresetConfig, setEditPresetConfig,
    handleAddPreset, handleDeletePreset, handleUpdatePreset,
    runTestConnection, testConnState, testConnResult,
    openEditPreset,
  } = usePresetContext()
  return (
    <div className="sidebar-section preset-section">
      <div className="sidebar-title" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <span>{t('presets')}</span>
        <button className="preset-add-btn" onClick={() => { setShowAddPreset(true); setNewPresetName('') }} title={t('addPreset')}>+</button>
      </div>
      {showAddPreset && (
        <div style={{ padding: '6px 0', display: 'flex', flexDirection: 'column', gap: '6px' }}>
          <input type="text" value={newPresetName} onChange={e => setNewPresetName(e.target.value)} placeholder={t('presetName')}
            style={{ width: '100%', padding: '4px 8px', borderRadius: '4px', border: '1px solid var(--border)', background: 'var(--bg-elevated)', color: 'var(--text)', fontSize: '12px', boxSizing: 'border-box' }}
            onKeyDown={e => { if (e.key === 'Enter') handleAddPreset() }} />
          <div className="format-selector" style={{ gap: '4px' }}>
            {Object.entries(API_FORMATS).map(([key, format]) => (
              <div key={key} className={`format-option ${newPresetConfig.api_format === key ? 'active' : ''}`} onClick={() => setNewPresetConfig(prev => ({ ...prev, api_format: key }))} style={{ padding: '4px 6px', fontSize: '10px' }}>
                <div className="format-name" style={{ fontSize: '11px' }}>{t(key === 'openai' ? 'openaiCompatible' : 'anthropicClaude')}</div>
              </div>
            ))}
          </div>
          <input type="password" value={newPresetConfig.api_key} onChange={e => setNewPresetConfig(prev => ({ ...prev, api_key: e.target.value }))} placeholder={t('apiKey')}
            style={{ width: '100%', padding: '4px 8px', borderRadius: '4px', border: '1px solid var(--border)', background: 'var(--bg-elevated)', color: 'var(--text)', fontSize: '12px', boxSizing: 'border-box' }} />
          <input value={newPresetConfig.model} onChange={e => setNewPresetConfig(prev => ({ ...prev, model: e.target.value }))} placeholder={t('model')}
            style={{ width: '100%', padding: '4px 8px', borderRadius: '4px', border: '1px solid var(--border)', background: 'var(--bg-elevated)', color: 'var(--text)', fontSize: '12px', boxSizing: 'border-box' }} />
          {newPresetConfig.api_format && API_FORMATS[newPresetConfig.api_format] && (
            <div className="model-examples" style={{ flexWrap: 'wrap', gap: '3px' }}>
              {API_FORMATS[newPresetConfig.api_format].modelExamples.map((m, i) => (
                <span key={i} className="example-tag" style={{ fontSize: '10px' }} onClick={() => setNewPresetConfig(prev => ({ ...prev, model: m }))}>{m}</span>
              ))}
            </div>
          )}
          <input value={newPresetConfig.base_url} onChange={e => setNewPresetConfig(prev => ({ ...prev, base_url: e.target.value }))} placeholder={t('baseUrl')}
            style={{ width: '100%', padding: '4px 8px', borderRadius: '4px', border: '1px solid var(--border)', background: 'var(--bg-elevated)', color: 'var(--text)', fontSize: '12px', boxSizing: 'border-box' }} />
          {(newPresetConfig.base_url.includes('deepseek') || newPresetConfig.model.includes('deepseek')) && (
            <div className="config-field" style={{ margin: 0 }}>
              <label style={{ fontSize: '11px' }}>{t('thinkingMode')}</label>
              <div className="format-selector" style={{ gap: '4px' }}>
                {[{ key: 'disabled', label: t('thinkingOff') }, { key: 'enabled', label: t('thinkingOn') }].map(opt => (
                  <div key={opt.key} className={`format-option ${(newPresetConfig.thinking_mode || 'disabled') === opt.key ? 'active' : ''}`}
                    onClick={() => setNewPresetConfig(prev => ({ ...prev, thinking_mode: opt.key }))}
                    style={{ padding: '4px 8px', fontSize: '10px', flex: 1, textAlign: 'center' }}>
                    {opt.label}
                  </div>
                ))}
              </div>
            </div>
          )}
          <div style={{ display: 'flex', gap: '4px' }}>
            <button onClick={handleAddPreset} style={{ flex: 1, padding: '4px', borderRadius: '4px', border: 'none', background: 'var(--accent)', color: '#fff', cursor: 'pointer', fontSize: '12px' }}>{t('savePreset')}</button>
            <button onClick={() => { setShowAddPreset(false); setNewPresetName(''); setNewPresetConfig({ api_key: '', base_url: '', model: '', api_format: 'openai', thinking_mode: 'disabled' }) }} style={{ flex: 1, padding: '4px', borderRadius: '4px', border: '1px solid var(--border)', background: 'transparent', color: 'var(--text)', cursor: 'pointer', fontSize: '12px' }}>{t('close')}</button>
          </div>
        </div>
      )}
      {presets.map((preset, i) => (
        <div key={i} className="model-card" onClick={() => openEditPreset(preset.name)}>
          <div className="model-dot" style={{ background: defaultPreset === preset.name ? '#f59e0b' : '#58a6ff' }} />
          <div className="model-info">
            <div className="model-name" style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
              {preset.name}
              {defaultPreset === preset.name && <span style={{ fontSize: 9, background: '#f59e0b', color: '#fff', padding: '0 4px', borderRadius: 3, fontWeight: 600 }}>默认</span>}
            </div>
            <div className="model-id">{preset.model}</div>
          </div>
          <button className="preset-apply-all-btn"
            onClick={(e) => {
              e.stopPropagation()
              if (defaultPreset === preset.name) {
                handleClearDefaultPreset()
              } else {
                handleSetDefaultPreset(preset.name)
              }
            }}
            title={defaultPreset === preset.name ? '取消默认' : '设为默认（新项目自动使用）'}
            style={defaultPreset === preset.name ? { background: '#f59e0b', color: '#fff' } : {}}>
            {defaultPreset === preset.name ? '★' : '☆'}
          </button>
          <button className="preset-delete-btn"
            onClick={(e) => { e.stopPropagation(); setConfirmDialog({ message: t('confirmDeletePreset'), onConfirm: async () => { await handleDeletePreset(preset.name); setConfirmDialog(null) }, onCancel: () => setConfirmDialog(null) }) }}
            title={t('deletePreset')}
            aria-label="删除预设">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14H6L5 6"/><path d="M10 11v6"/><path d="M14 11v6"/><path d="M9 6V4h6v2"/></svg>
          </button>
        </div>
      ))}
      {editingPreset && (() => {
        const p = presets.find(pr => pr.name === editingPreset)
        if (!p) return null
        return (
          <div className="preset-edit-panel">
            <div className="preset-edit-header">
              <span className="preset-edit-title">{t('editPreset')}</span>
              <button className="preset-edit-close" onClick={() => setEditingPreset(null)} aria-label="关闭">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true"><line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" /></svg>
              </button>
            </div>
            <div className="preset-edit-body">
              <div className="config-field"><label>{t('presetName')}</label><input value={editPresetConfig.name} onChange={e => setEditPresetConfig(prev => ({ ...prev, name: e.target.value }))} /></div>
              <div className="config-field">
                <label>{t('apiFormat')}</label>
                <div className="format-selector" style={{ gap: '4px' }}>
                  {Object.entries(API_FORMATS).map(([key]) => (
                    <div key={key} className={`format-option ${editPresetConfig.api_format === key ? 'active' : ''}`} onClick={() => setEditPresetConfig(prev => ({ ...prev, api_format: key }))} style={{ padding: '4px 6px', fontSize: '10px' }}>
                      <div className="format-name" style={{ fontSize: '11px' }}>{t(key === 'openai' ? 'openaiCompatible' : 'anthropicClaude')}</div>
                    </div>
                  ))}
                </div>
              </div>
              <div className="config-field"><label>{t('apiKey')}</label><input type="password" value={editPresetConfig.api_key} onChange={e => setEditPresetConfig(prev => ({ ...prev, api_key: e.target.value }))} placeholder={t('apiKeyHint')} /></div>
              <div className="config-field">
                <label>{t('model')}</label>
                <input value={editPresetConfig.model} onChange={e => setEditPresetConfig(prev => ({ ...prev, model: e.target.value }))} placeholder={t('modelHint')} />
                {editPresetConfig.api_format && API_FORMATS[editPresetConfig.api_format] && (
                  <div className="model-examples" style={{ flexWrap: 'wrap', gap: '3px' }}>
                    {API_FORMATS[editPresetConfig.api_format].modelExamples.map((m, mi) => (
                      <span key={mi} className="example-tag" style={{ fontSize: '10px' }} onClick={() => setEditPresetConfig(prev => ({ ...prev, model: m }))}>{m}</span>
                    ))}
                  </div>
                )}
              </div>
              <div className="config-field">
                <label>{t('baseUrl')}</label>
                <input value={editPresetConfig.base_url} onChange={e => setEditPresetConfig(prev => ({ ...prev, base_url: e.target.value }))} placeholder={t('baseUrlHint')} />
                {editPresetConfig.api_format && API_FORMATS[editPresetConfig.api_format] && (
                  <div className="url-example" style={{ fontSize: '10px' }}><span className="example-label">{t('urlExample')}:</span><code>{API_FORMATS[editPresetConfig.api_format].baseUrlExample}</code></div>
                )}
              </div>
              {(editPresetConfig.base_url.includes('deepseek') || editPresetConfig.model.includes('deepseek')) && (
                <div className="config-field">
                  <label>{t('thinkingMode')}</label>
                  <div className="format-selector" style={{ gap: '4px' }}>
                    {[{ key: 'disabled', label: t('thinkingOff') }, { key: 'enabled', label: t('thinkingOn') }].map(opt => (
                      <div key={opt.key} className={`format-option ${(editPresetConfig.thinking_mode || 'disabled') === opt.key ? 'active' : ''}`}
                        onClick={() => setEditPresetConfig(prev => ({ ...prev, thinking_mode: opt.key }))}
                        style={{ padding: '4px 8px', fontSize: '10px', flex: 1, textAlign: 'center' }}>
                        {opt.label}
                      </div>
                    ))}
                  </div>
                </div>
              )}
              <div style={{ display: 'flex', gap: '4px', marginTop: '4px' }}>
                <button className="config-test-btn" style={{ flex: 1 }} onClick={() => runTestConnection(editPresetConfig, t)} disabled={testConnState === 'testing'}>
                  {testConnState === 'testing' ? t('testConnTesting') : t('testConnection')}
                </button>
                <button className="preset-edit-save-btn" style={{ flex: 1 }} onClick={() => handleUpdatePreset(t)}>{t('updatePreset')}</button>
              </div>
              <div style={{ marginTop: '6px' }}>
                <button className="ai-config-btn" onClick={() => {
                  const prompt = `${t('aiConfigPrompt')}\n\n---\n${t('name')}: [${t('fillName')}]\nAPI Key: [${t('fillKey')}]\nBase URL: [${t('fillUrl')}]\n${t('model')}: [${t('fillModel')}]\nAPI ${t('format')}: ${editPresetConfig.api_format || 'openai'}\n---\n\n${t('aiConfigHelp')}`
                  navigator.clipboard.writeText(prompt).then(() => showNotification(t('aiConfigCopied'), 'info'))
                }}>{t('aiConfig')}</button>
              </div>
              {testConnResult && (
                <TestResultCard result={testConnResult} onRetry={() => runTestConnection(editPresetConfig, t)} />
              )}
            </div>
          </div>
        )
      })()}
      {presets.length === 0 && !showAddPreset && <div className="sidebar-empty">-</div>}
    </div>
  )
}
