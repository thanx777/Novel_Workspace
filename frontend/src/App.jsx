import { useState, useEffect, useRef, useCallback } from 'react'
import './App.css'
import translations from './translations'
import { NODE_TYPES, API_BASE } from './constants'
import useCanvas from './hooks/useCanvas'
import usePreset from './hooks/usePreset'

import useProject from './hooks/useProject'
import useTask from './hooks/useTask'
import Toolbar from './components/Toolbar'
import { PresetPanel, ChatPanel, TaskPanel } from './components/Sidebar'
import { ConnectionLayer, NodeCanvas } from './components/Canvas'
import ConfigPanel from './components/ConfigPanel'
import { LogsPanel, FilesPanel, ProjectModal, WorkspaceSettings, ConnContextMenu, AnnotationEditor, ConfirmDialog, DangerConfirmModal } from './components/Modals'
import TerminalPanel from './components/TerminalPanel'

function App() {
  const [language, setLanguage] = useState('zh')
  const [isDark, setIsDark] = useState(false)
  const [executionMode, setExecutionMode] = useState('standard')
  const [agentCatalog, setAgentCatalog] = useState([])
  const t = (key) => translations[language][key] || key

  const mkNode = (id, type, x, y, label) => ({
    id, type, x, y, config: { preset_name: '', agent_role: '', custom_prompt: '', label },
    ports: type === 'manager'
      ? { inputs: [{ id: `${id}_in_fb`, name: 'feedback' }, { id: `${id}_in_task`, name: 'task' }], outputs: [{ id: `${id}_out_disp`, name: 'dispatch' }, { id: `${id}_out_info`, name: 'info' }] }
      : type === 'worker'
      ? { inputs: [{ id: `${id}_in_task`, name: 'task' }], outputs: [{ id: `${id}_out_result`, name: 'result' }] }
      : { inputs: [{ id: `${id}_in_code`, name: 'code' }, { id: `${id}_in_result`, name: 'result' }], outputs: [{ id: `${id}_out_review`, name: 'review' }, { id: `${id}_out_fb`, name: 'feedback' }] },
    activity: 'idle', thought: '', response: '', history: []
  })
  const mkConn = (id, from, fromPort, to, toPort, annotation) =>
    ({ id, from, fromPort, to, toPort, annotation })

  const NOVEL_DEFAULT_NODES = [
    mkNode('m_1', 'manager', 60, 40, '📖 大纲'),
    mkNode('w_1', 'worker', 340, 40, ''),
    mkNode('r_1', 'reviewer', 620, 40, ''),
    mkNode('m_2', 'manager', 60, 190, '✍️ 创作'),
    mkNode('w_2', 'worker', 340, 190, ''),
    mkNode('r_2', 'reviewer', 620, 190, ''),
    mkNode('m_3', 'manager', 60, 340, '🔍 审校'),
    mkNode('w_3', 'worker', 340, 340, ''),
    mkNode('r_3', 'reviewer', 620, 340, ''),
  ]
  const NOVEL_DEFAULT_CONNS = [
    mkConn('c1_mw', 'm_1', 'm_1_out_disp', 'w_1', 'w_1_in_task', '大纲指令'),
    mkConn('c1_wr', 'w_1', 'w_1_out_result', 'r_1', 'r_1_in_code', '大纲产出'),
    mkConn('c1_rm', 'r_1', 'r_1_out_fb', 'm_1', 'm_1_in_fb', '审查反馈'),
    mkConn('c1_to_2', 'r_1', 'r_1_out_review', 'm_2', 'm_2_in_task', '大纲传递给创作'),
    mkConn('c2_mw', 'm_2', 'm_2_out_disp', 'w_2', 'w_2_in_task', '写作指令'),
    mkConn('c2_wr', 'w_2', 'w_2_out_result', 'r_2', 'r_2_in_code', '待审查章节'),
    mkConn('c2_rm', 'r_2', 'r_2_out_fb', 'm_2', 'm_2_in_fb', '审查反馈'),
    mkConn('c2_to_3', 'r_2', 'r_2_out_review', 'm_3', 'm_3_in_task', '章节传递给审校'),
    mkConn('c3_mw', 'm_3', 'm_3_out_disp', 'w_3', 'w_3_in_task', '审校指令'),
    mkConn('c3_wr', 'w_3', 'w_3_out_result', 'r_3', 'r_3_in_code', '待审查修订'),
    mkConn('c3_rm', 'r_3', 'r_3_out_fb', 'm_3', 'm_3_in_fb', '审校反馈'),
  ]

  // 兼容/完整模式：13节点，写作+审校阶段加润色循环
  const ENHANCED_NODES = [
    // 阶段1 - 大纲 (3节点)
    mkNode('m_1', 'manager', 60, 40, '📖 大纲'),
    mkNode('w_1', 'worker', 240, 40, ''),
    mkNode('r_1', 'reviewer', 420, 40, ''),
    // 阶段2 - 写作 (5节点：创作→审查→润色→终审)
    mkNode('m_2', 'manager', 60, 190, '✍️ 创作'),
    mkNode('w_2a', 'worker', 210, 190, ''),
    mkNode('r_2a', 'reviewer', 360, 190, ''),
    mkNode('w_2b', 'worker', 510, 190, ''),
    mkNode('r_2b', 'reviewer', 660, 190, ''),
    // 阶段3 - 审校 (5节点：修订→初审→精修→终审)
    mkNode('m_3', 'manager', 60, 340, '🔍 审校'),
    mkNode('w_3a', 'worker', 210, 340, ''),
    mkNode('r_3a', 'reviewer', 360, 340, ''),
    mkNode('w_3b', 'worker', 510, 340, ''),
    mkNode('r_3b', 'reviewer', 660, 340, ''),
  ]
  const ENHANCED_CONNS = [
    // 阶段1：大纲
    mkConn('c1_mw', 'm_1', 'm_1_out_disp', 'w_1', 'w_1_in_task', '大纲指令'),
    mkConn('c1_wr', 'w_1', 'w_1_out_result', 'r_1', 'r_1_in_code', '大纲产出'),
    mkConn('c1_rm', 'r_1', 'r_1_out_fb', 'm_1', 'm_1_in_fb', '审查反馈'),
    mkConn('c1_to_2', 'r_1', 'r_1_out_review', 'm_2', 'm_2_in_task', '大纲传递给创作'),
    // 阶段2：写作（润色循环）m_2→w_2a→r_2a→w_2b→r_2b→m_2
    mkConn('c2_mw', 'm_2', 'm_2_out_disp', 'w_2a', 'w_2a_in_task', '写作指令'),
    mkConn('c2_wr', 'w_2a', 'w_2a_out_result', 'r_2a', 'r_2a_in_code', '初稿待审查'),
    mkConn('c2_rw', 'r_2a', 'r_2a_out_fb', 'w_2b', 'w_2b_in_task', '审查意见→润色'),
    mkConn('c2_w2r', 'w_2b', 'w_2b_out_result', 'r_2b', 'r_2b_in_code', '润色稿待终审'),
    mkConn('c2_rm', 'r_2b', 'r_2b_out_fb', 'm_2', 'm_2_in_fb', '终审反馈'),
    mkConn('c2_to_3', 'r_2b', 'r_2b_out_review', 'm_3', 'm_3_in_task', '章节传递给审校'),
    // 阶段3：审校（精修循环）m_3→w_3a→r_3a→w_3b→r_3b→m_3
    mkConn('c3_mw', 'm_3', 'm_3_out_disp', 'w_3a', 'w_3a_in_task', '审校指令'),
    mkConn('c3_wr', 'w_3a', 'w_3a_out_result', 'r_3a', 'r_3a_in_code', '修订待初审'),
    mkConn('c3_rw', 'r_3a', 'r_3a_out_fb', 'w_3b', 'w_3b_in_task', '初审意见→精修'),
    mkConn('c3_w2r', 'w_3b', 'w_3b_out_result', 'r_3b', 'r_3b_in_code', '精修稿待终审'),
    mkConn('c3_rm', 'r_3b', 'r_3b_out_fb', 'm_3', 'm_3_in_fb', '终审反馈'),
  ]

  const [nodes, setNodes] = useState(NOVEL_DEFAULT_NODES)
  const [connections, setConnections] = useState(NOVEL_DEFAULT_CONNS)
  const [selectedNode, setSelectedNode] = useState(null)
  const [selectedConn, setSelectedConn] = useState(null)
  const [pan, setPan] = useState({ x: 0, y: 0 })
  const [notification, setNotification] = useState(null)
  const [confirmDialog, setConfirmDialog] = useState(null)
  const [logs, setLogs] = useState([])
  const [showLogs, setShowLogs] = useState(false)
  const [showFiles, setShowFiles] = useState(false)
  const [showTerminal, setShowTerminal] = useState(false)
  const [testLogs, setTestLogs] = useState([])
  const [dangerCommand, setDangerCommand] = useState(null)
  const [depMissing, setDepMissing] = useState(null)  // {module, suggestion}
  const [files, setFiles] = useState([])
  const [activeFile, setActiveFile] = useState(null)
  const [fileContent, setFileContent] = useState('')
  const [conversations, setConversations] = useState([])
  const [memory, setMemory] = useState('')
  const [showWorkspaceSettings, setShowWorkspaceSettings] = useState(false)
  const [workspaceSettings, setWorkspaceSettings] = useState({ workspace_dir: '', projects_dir: '', current_workspace: '', current_projects: '', default_workspace: '', default_projects: '' })
  const [wsConfigLoading, setWsConfigLoading] = useState(false)

  const dialogEndRef = useRef(null)
  const logEndRef = useRef(null)
  const logBufferRef = useRef([])
  const logFlushRef = useRef(null)

  const showNotification = useCallback((msg, type = 'info') => {
    setNotification({ msg, type, id: Date.now() })
    setTimeout(() => setNotification(null), 3500)
  }, [])

  const handleDangerConfirm = useCallback(async (command) => {
    try {
      const response = await fetch(`${API_BASE}/test/confirm`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ instruction: `[TEST:CMD: ${command}]` })
      })
      const result = await response.json()
      setTestLogs(prev => [...prev,
        { type: 'prompt', data: `$ ${command} (force)`, elapsed: 0 },
        { type: result.success ? 'done' : 'error', data: result.output || result.error, exit_code: result.exit_code, elapsed: result.duration || 0 }
      ])
    } catch (err) {
      setTestLogs(prev => [...prev, { type: 'error', data: err.message, elapsed: 0 }])
    }
  }, [])

  const handleDepInstall = useCallback(async (dep) => {
    setDepMissing(null)
    try {
      const response = await fetch(`${API_BASE}/test/dep-install`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ module: dep.module, suggestion: dep.suggestion })
      })
      const result = await response.json()
      const cmd = result.command || dep.suggestion
      setTestLogs(prev => [...prev,
        { type: 'prompt', data: `$ ${cmd}`, elapsed: 0 },
        ...(result.output ? result.output.split('\n').map(line => ({ type: 'stdout', data: line, elapsed: 0 })) : []),
        { type: 'done', exit_code: result.exit_code || 0, elapsed: 0 }
      ])
    } catch (err) {
      setTestLogs(prev => [...prev, { type: 'error', data: err.message, elapsed: 0 }])
    }
  }, [])

  const handleDepSkip = useCallback(() => {
    setDepMissing(null)
  }, [])

  const updateNodeConfig = useCallback((id, config) => {
    setNodes(prev => prev.map(n => n.id === id ? { ...n, config: { ...n.config, ...config } } : n))
  }, [])

  const updateNodeActivity = useCallback((id, activity, thought, response) => {
    setNodes(prev => prev.map(n => {
      if (n.id !== id) return n
      const newHistory = [...n.history]
      if (thought || response) {
        newHistory.push({ timestamp: Date.now(), thought, response })
        if (newHistory.length > 10) newHistory.shift()
      }
      return { ...n, activity, thought: thought || n.thought, response: response || n.response, history: newHistory }
    }))
  }, [])

  const clearAllNodeActivity = useCallback(() => {
    setNodes(prev => prev.map(n => ({ ...n, activity: 'idle', thought: '', response: '', history: [] })))
  }, [])

  const loadFiles = useCallback(() => {
    fetch(`${API_BASE}/workspace/files`)
      .then(r => r.json())
      .then(d => setFiles(d.files || []))
      .catch(() => {})
  }, [])

  const loadFile = useCallback((filename) => {
    fetch(`${API_BASE}/workspace/files/${filename}`)
      .then(r => r.json())
      .then(d => { setActiveFile(filename); setFileContent(d.content || '') })
  }, [])

  const saveFile = useCallback(() => {
    if (!activeFile) return
    fetch(`${API_BASE}/workspace/files/${activeFile}`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content: fileContent })
    }).then(() => showNotification(t('saved'), 'success'))
  }, [activeFile, fileContent, showNotification, t])

  const fetchWorkspaceConfig = useCallback(async () => {
    setWsConfigLoading(true)
    try {
      const r = await fetch(`${API_BASE}/workspace-config`)
      const data = await r.json()
      setWorkspaceSettings(data)
    } catch (e) {
      showNotification('Failed to load workspace config', 'error')
    }
    setWsConfigLoading(false)
  }, [showNotification])

  const handleSaveWorkspaceConfig = useCallback(async () => {
    setWsConfigLoading(true)
    try {
      const r = await fetch(`${API_BASE}/workspace-config`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          workspace_dir: workspaceSettings.workspace_dir,
          projects_dir: workspaceSettings.projects_dir
        })
      })
      if (!r.ok) {
        const err = await r.json()
        throw new Error(err.detail || `HTTP ${r.status}`)
      }
      const data = await r.json()
      setWorkspaceSettings(prev => ({ ...prev, ...data }))
      showNotification(t('settingsSaved'), 'success')
      setShowWorkspaceSettings(false)
    } catch (e) {
      showNotification(`${language === 'zh' ? '保存失败' : 'Save failed'}: ${e.message}`, 'error')
    }
    setWsConfigLoading(false)
  }, [workspaceSettings, showNotification, t, language])

  const canvasHook = useCanvas({ nodes, setNodes, connections, setConnections, selectedNode, setSelectedNode, selectedConn, setSelectedConn, pan, setPan })
  const presetHook = usePreset({ language, showNotification, setNodes })
  const projectHook = useProject({ language, showNotification, setNodes, setConnections, setConversations, setMemory, setLogs })
  const [isRunning, setIsRunning] = useState(false)
  const [elapsed, setElapsed] = useState(0)
  const elapsedOffsetRef = useRef(0)  // 续跑时累计时间偏移，避免重新从0开始
  const taskHook = useTask({ showNotification, nodes, setNodes, connections, presets: presetHook.presets, conversations, setConversations, setLogs, setIsRunning, setElapsed, clearAllNodeActivity, updateNodeActivity, loadFiles, executionMode, elapsedOffsetRef })

  // 任务管理（断点续跑）
  const [tasks, setTasks] = useState([])
  const fetchTasks = useCallback(() => {
    fetch(`${API_BASE}/tasks`).then(r => r.json()).then(d => setTasks(d.tasks || [])).catch(() => {})
  }, [])
  const handleResumeTask = useCallback((folder) => {
    if (taskHook.isRunning) return
    // 获取任务检查点，恢复完整画布管线
    fetch(`${API_BASE}/tasks/${encodeURIComponent(folder)}`)
      .then(r => r.json())
      .then(async state => {
        // 1. 恢复执行模式 + 画布
        const mode = state.execution_mode || 'standard'
        setExecutionMode(mode)
        const templateNodes = (mode === 'compatible' || mode === 'full') ? ENHANCED_NODES : NOVEL_DEFAULT_NODES
        const templateConns = (mode === 'compatible' || mode === 'full') ? ENHANCED_CONNS : NOVEL_DEFAULT_CONNS
        const checkpointNodeMap = {}
        if (state.nodes?.length) state.nodes.forEach(n => { checkpointNodeMap[n.id] = n })
        setNodes(templateNodes.map(tn => {
          const saved = checkpointNodeMap[tn.id]
          return saved ? { ...tn, config: { ...tn.config, ...saved.config } } : tn
        }))
        setConnections(templateConns)
        setLogs([])

        // 2. 恢复预设到 config.json（已存在的跳过，缺失的补齐）
        try {
          const currentPresets = await fetch(`${API_BASE}/presets`).then(r => r.json()).catch(() => ({ presets: [] }))
          const existingNames = new Set((currentPresets.presets || []).map(p => p.name))
          const presetsObj = state.presets || {}
          const presetList = Array.isArray(presetsObj) ? presetsObj : Object.values(presetsObj)
          for (const p of presetList) {
            if (p.name && !existingNames.has(p.name)) {
              await fetch(`${API_BASE}/presets`, {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ name: p.name, api_key: p.api_key || '', base_url: p.base_url || '', model: p.model || '', api_format: p.api_format || 'openai' })
              }).catch(() => {})
            }
          }
          await presetHook.fetchPresets()
        } catch(e) { console.error('Preset restore failed:', e) }

        // 3. 恢复对话 + 启动续跑
        const history = state.conversation_history
        if (history && history.length > 0) {
          setConversations(history.map(m => ({
            role: m.role, content: m.content, timestamp: m.timestamp || Date.now()
          })))
        }
        startResumeStream(folder)
      })
      .catch((err) => {
        console.error('Load task state failed:', err)
        showNotification(language === 'zh' ? '加载任务状态失败' : 'Failed to load task state', 'error')
      })

    const startResumeStream = (folder) => {
      taskHook.setTaskInput('')
      setLogs([])
      logBufferRef.current = []
      taskHook.setIsRunning(true)

      // 批量日志刷新
      const MAX_LOGS = 800
      const flushLogs = () => {
        const batch = logBufferRef.current
        if (batch.length === 0) return
        logBufferRef.current = []
        logFlushRef.current = null
        setLogs(prev => {
          const next = prev.concat(batch)
          return next.length > MAX_LOGS ? next.slice(-MAX_LOGS) : next
        })
      }
      // 续跑：从上次中断的累计时间继续计时
      const offset = elapsedOffsetRef.current
      setElapsed(offset)
      taskHook.setElapsed(offset)
      clearAllNodeActivity()
      const startTime = Date.now()
      const timer = setInterval(() => {
        const current = offset + Math.floor((Date.now() - startTime) / 1000)
        taskHook.setElapsed(current)  // 用 useTask 的 wrapper，确保 App + 内部状态同步
        elapsedOffsetRef.current = current
      }, 1000)
      const controller = new AbortController()
      if (taskHook.abortRef) taskHook.abortRef.current = controller
      fetch(`${API_BASE}/tasks/${encodeURIComponent(folder)}/resume`, {
        method: 'POST', signal: controller.signal,
        headers: { 'Content-Type': 'application/json' },
      }).then(async (response) => {
        const reader = response.body.getReader()
        const decoder = new TextDecoder()
        let buffer = ''
        while (true) {
          const { done, value } = await reader.read()
          if (done) break
          buffer += decoder.decode(value, { stream: true })
          const lines = buffer.split('\n')
          buffer = lines.pop() || ''
          for (const line of lines) {
            if (line.startsWith('data: ')) {
              try {
                const msg = JSON.parse(line.slice(6))
                // 所有消息都进日志
                // 批量日志：避免积压时 React 卡死
                logBufferRef.current.push(msg)
                if (logFlushRef.current) clearTimeout(logFlushRef.current)
                logFlushRef.current = setTimeout(flushLogs, 120)

                if (msg.status === 'done') {
                  clearInterval(timer)
                  taskHook.setIsRunning(false)
                  setElapsed(0)
                  fetchTasks()
                } else if (msg.status === 'error') {
                  showNotification(msg.message, 'error')
                  if (msg.node_id) updateNodeActivity(msg.node_id, 'idle', '', msg.message)
                } else if (msg.status === 'warning') {
                  showNotification(msg.message, 'warning')
                } else if (msg.status === 'feedback_processing') {
                  // 反馈处理：清空节点旧状态，Manager 重新规划
                  clearAllNodeActivity()
                  setConversations(prev => [...prev, { role: 'assistant', content: msg.message, timestamp: Date.now() }])
                } else if (msg.status === 'info') {
                  if (msg.node_id) updateNodeActivity(msg.node_id, 'thinking', msg.message, '')
                  else if (msg.role) updateNodeActivity(msg.role, 'thinking', msg.message, '')
                } else if (msg.status === 'working') {
                  if (msg.node_id) updateNodeActivity(msg.node_id, 'responding', '', msg.message)
                } else if (msg.status === 'success') {
                  if (msg.node_id) updateNodeActivity(msg.node_id, 'completed', '', msg.message)
                }
              } catch (e) { console.error('SSE parse error:', e, line) }
            }
          }
        }
        flushLogs()
        clearInterval(timer)
        taskHook.setIsRunning(false)
        setElapsed(0)
        fetchTasks()
      }).catch((err) => {
        console.error('Resume stream error:', err)
        flushLogs()
        clearInterval(timer)
        taskHook.setIsRunning(false)
        setElapsed(0)
        showNotification(language === 'zh' ? '续跑连接失败' : 'Resume connection failed', 'error')
      })
      return () => { controller.abort(); clearInterval(timer) }
    }
  }, [taskHook.isRunning, setNodes, setConnections, setExecutionMode, presetHook, showNotification, setConversations, setLogs, setElapsed, clearAllNodeActivity, updateNodeActivity, fetchTasks, language])
  const handleDeleteTask = useCallback((folder) => {
    setConfirmDialog({
      message: language === 'zh' ? `确认删除任务「${folder}」及其所有文件？` : `Delete task "${folder}" and all files?`,
      onConfirm: () => {
        fetch(`${API_BASE}/tasks/${encodeURIComponent(folder)}`, { method: 'DELETE' })
          .then(() => { fetchTasks(); showNotification(language === 'zh' ? '任务已删除' : 'Task deleted', 'success') })
          .catch(() => showNotification(language === 'zh' ? '删除失败' : 'Delete failed', 'error'))
        setConfirmDialog(null)
      },
      onCancel: () => setConfirmDialog(null)
    })
  }, [language, fetchTasks, showNotification, setConfirmDialog])

  const resetNovelCanvas = useCallback((mode = 'standard') => {
    if (mode === 'compatible' || mode === 'full') {
      setNodes(ENHANCED_NODES)
      setConnections(ENHANCED_CONNS)
    } else {
      setNodes(NOVEL_DEFAULT_NODES)
      setConnections(NOVEL_DEFAULT_CONNS)
    }
    setLogs([])
  }, [])

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', isDark ? 'dark' : 'light')
  }, [isDark])

  useEffect(() => {
    if (dialogEndRef.current) {
      dialogEndRef.current.scrollIntoView({ behavior: 'smooth' })
    }
  }, [conversations])

  useEffect(() => {
    if (logEndRef.current) {
      logEndRef.current.scrollIntoView({ behavior: 'smooth' })
    }
    const lastLog = logs[logs.length - 1]
    if (lastLog) {
      if (lastLog.test_confirm && lastLog.test_instruction) {
        const cmdMatch = lastLog.test_instruction.match(/\[TEST:CMD:\s*(.+)\]/)
        if (cmdMatch) setDangerCommand(cmdMatch[1])
      }
      if (lastLog.dep_missing) {
        setDepMissing({ module: lastLog.dep_missing, suggestion: lastLog.dep_suggestion || `pip install ${lastLog.dep_missing}` })
      }
      if (lastLog.test_output || lastLog.test_exit_code !== undefined) {
        setTestLogs(prev => {
          const newLogs = []
          if (lastLog.message && lastLog.message.includes('🧪')) {
            newLogs.push({ type: 'prompt', data: `$ [Agent Test] ${lastLog.message}`, elapsed: 0 })
          }
          if (lastLog.test_output) {
            lastLog.test_output.split('\n').forEach(line => {
              newLogs.push({ type: 'stdout', data: line, elapsed: 0 })
            })
          }
          if (lastLog.test_error) {
            lastLog.test_error.split('\n').forEach(line => {
              newLogs.push({ type: 'error', data: line, elapsed: 0 })
            })
          }
          if (lastLog.test_exit_code !== undefined) {
            newLogs.push({ type: 'done', exit_code: lastLog.test_exit_code, elapsed: 0 })
          }
          return [...prev, ...newLogs]
        })
      }
    }
  }, [logs])

  useEffect(() => {
    fetch(`${API_BASE}/presets`)
      .then(r => r.json())
      .then(d => {
        presetHook.setPresets(d.presets || [])
        if (d.presets && d.presets.length > 0) {
          setNodes(prev => prev.map((n, i) => ({
            ...n,
            config: { ...n.config, preset_name: n.config.preset_name || d.presets[i % d.presets.length].name }
          })))
        }
      })
      .catch(err => { console.error('init fetchPresets error:', err) })
    loadFiles()
    projectHook.fetchProjects()
    fetchTasks()
    fetch(`${API_BASE}/agent-catalog`)
      .then(r => r.json())
      .then(d => setAgentCatalog(d.agents || []))
      .catch(() => {})
  }, [])

  useEffect(() => {
    const handleClick = () => { canvasHook.setConnContextMenu(null); taskHook.setShowOptimizeDropdown(false) }
    window.addEventListener('click', handleClick)
    return () => window.removeEventListener('click', handleClick)
  }, [])

  const selectedNodeData = nodes.find(n => n.id === selectedNode)

  const getNodeActivityColor = (activity) => {
    switch (activity) {
      case 'thinking': return '#58a6ff'
      case 'responding': return '#3fb950'
      case 'completed': return '#d29922'
      default: return 'transparent'
    }
  }

  const getNodeGlowStyle = (activity) => {
    if (activity === 'thinking' || activity === 'responding') {
      return {
        boxShadow: `0 0 12px 3px ${getNodeActivityColor(activity)}`,
        borderColor: getNodeActivityColor(activity),
        borderWidth: '2px'
      }
    }
    return {}
  }

  return (
    <div className="app">
      <Toolbar
        t={t} language={language} isDark={isDark}
        isRunning={taskHook.isRunning} elapsed={taskHook.elapsed}
        executionMode={executionMode} setExecutionMode={setExecutionMode}
        setPan={setPan}
        setShowProjectModal={projectHook.setShowProjectModal}
        fetchProjects={projectHook.fetchProjects}
        setShowWorkspaceSettings={setShowWorkspaceSettings}
        fetchWorkspaceConfig={fetchWorkspaceConfig}
        showLogs={showLogs} setShowLogs={setShowLogs}
        showFiles={showFiles} setShowFiles={setShowFiles}
        showTerminal={showTerminal} setShowTerminal={setShowTerminal}
        setLanguage={setLanguage} setIsDark={setIsDark}
        resetNovelCanvas={resetNovelCanvas}
      />

      <div className="workspace">
        <aside className="sidebar">
          <PresetPanel
            t={t} language={language}
            presets={presetHook.presets}
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
            selectedNode={selectedNode} updateNodeConfig={updateNodeConfig}
            openEditPreset={presetHook.openEditPreset}
            showNotification={showNotification}
            setConfirmDialog={setConfirmDialog}
            applyPresetToAll={(presetName) => setNodes(prev => prev.map(n => ({...n, config: {...n.config, preset_name: presetName}})))}
            allNodes={nodes}
          />
          <ChatPanel
            t={t} language={language}
            conversations={conversations} dialogEndRef={dialogEndRef}
            memory={memory} setMemory={setMemory} showNotification={showNotification}
            taskInput={taskHook.taskInput} setTaskInput={taskHook.setTaskInput}
            chapterCount={taskHook.chapterCount} setChapterCount={taskHook.setChapterCount}
            isRunning={taskHook.isRunning}
            runTask={taskHook.runTask} handleStop={taskHook.handleStop} sendFeedback={taskHook.sendFeedback}
            optimizing={taskHook.optimizing}
            showOptimizeDropdown={taskHook.showOptimizeDropdown} setShowOptimizeDropdown={taskHook.setShowOptimizeDropdown}
            handleOptimize={taskHook.handleOptimize}
            presets={presetHook.presets}
          />
          <TaskPanel
            t={t} language={language}
            tasks={tasks} onResume={handleResumeTask}
            onDelete={handleDeleteTask} onRefresh={fetchTasks}
            isRunning={taskHook.isRunning}
          />
        </aside>

        <div className="canvas-wrapper">
          <div className="canvas" ref={canvasHook.canvasRef} onMouseDown={canvasHook.handleCanvasMouseDown} style={{ '--pan-x': `${pan.x}px`, '--pan-y': `${pan.y}px` }}>
            <div className="canvas-content" style={{ transform: `translate(${pan.x}px, ${pan.y}px)` }}>
              <ConnectionLayer
                connections={connections}
                selectedConn={selectedConn} setSelectedConn={setSelectedConn}
                setSelectedNode={setSelectedNode}
                setConnContextMenu={canvasHook.handleConnContextMenu}
                hoveredConn={canvasHook.hoveredConn} setHoveredConn={canvasHook.setHoveredConn}
                getPortPos={canvasHook.getPortPos} renderCurve={canvasHook.renderCurve}
                isConnecting={canvasHook.isConnecting} tempConnEnd={canvasHook.tempConnEnd}
                connectingRef={canvasHook.connectingRef}
              />
              <NodeCanvas
                nodes={nodes} selectedNode={selectedNode}
                agentCatalog={agentCatalog} presets={presetHook.presets}
                handleNodeMouseDown={canvasHook.handleNodeMouseDown}
                handlePortMouseDown={canvasHook.handlePortMouseDown}
                handlePortMouseUp={canvasHook.handlePortMouseUp}
                removeNode={canvasHook.removeNode} t={t}
                getNodeActivityColor={getNodeActivityColor}
                getNodeGlowStyle={getNodeGlowStyle}
              />
            </div>
          </div>

          <ConfigPanel
            selectedNodeData={selectedNodeData} selectedNode={selectedNode}
            t={t} language={language}
            agentCatalog={agentCatalog} presets={presetHook.presets} nodes={nodes}
            updateNodeConfig={updateNodeConfig}
            addPort={canvasHook.addPort} removePort={canvasHook.removePort}
            renamePort={canvasHook.renamePort} removeNode={canvasHook.removeNode}
            setSelectedNode={setSelectedNode}
            testConnection={(nodeId) => presetHook.testConnection(nodeId, nodes, t, showNotification)}
            testConnResult={presetHook.testConnResult}
            runTestConnection={(config) => presetHook.runTestConnection(config, t)}
            updateNodeActivity={updateNodeActivity}
          />
        </div>

        {showLogs && (
          <LogsPanel t={t} logs={logs} setLogs={setLogs} logEndRef={logEndRef} setShowLogs={setShowLogs} />
        )}

        {showFiles && (
          <FilesPanel t={t} files={files} activeFile={activeFile} setActiveFile={setActiveFile}
            fileContent={fileContent} setFileContent={setFileContent}
            loadFiles={loadFiles} loadFile={loadFile} saveFile={saveFile}
            showNotification={showNotification} setShowFiles={setShowFiles} />
        )}

        <ProjectModal
          t={t} showProjectModal={projectHook.showProjectModal}
          setShowProjectModal={projectHook.setShowProjectModal}
          projectName={projectHook.projectName} setProjectName={projectHook.setProjectName}
          handleSaveProject={projectHook.handleSaveProject}
          projectList={projectHook.projectList}
          handleLoadProject={projectHook.handleLoadProject}
          handleDeleteProject={projectHook.handleDeleteProject}
          setConfirmDialog={setConfirmDialog}
          nodes={nodes} connections={connections}
          conversations={conversations} memory={memory} logs={logs}
        />

        <WorkspaceSettings
          t={t} showWorkspaceSettings={showWorkspaceSettings}
          setShowWorkspaceSettings={setShowWorkspaceSettings}
          workspaceSettings={workspaceSettings} setWorkspaceSettings={setWorkspaceSettings}
          handleSaveWorkspaceConfig={handleSaveWorkspaceConfig}
          wsConfigLoading={wsConfigLoading}
        />
      </div>

      <ConnContextMenu
        t={t} connContextMenu={canvasHook.connContextMenu}
        setConnContextMenu={canvasHook.setConnContextMenu}
        connections={connections}
        setAnnotationText={canvasHook.setAnnotationText}
        setEditingAnnotation={canvasHook.setEditingAnnotation}
        setConnections={setConnections} setSelectedConn={setSelectedConn}
      />

      <AnnotationEditor
        t={t} editingAnnotation={canvasHook.editingAnnotation}
        setEditingAnnotation={canvasHook.setEditingAnnotation}
        annotationText={canvasHook.annotationText}
        setAnnotationText={canvasHook.setAnnotationText}
        updateConnAnnotation={canvasHook.updateConnAnnotation}
      />

      <ConfirmDialog t={t} confirmDialog={confirmDialog} setConfirmDialog={setConfirmDialog} />

      <DangerConfirmModal t={t} language={language} dangerCommand={dangerCommand} setDangerCommand={setDangerCommand} onConfirm={handleDangerConfirm} />

      {depMissing && (
        <div className="confirm-overlay" onClick={handleDepSkip}>
          <div className="danger-confirm-dialog" onClick={e => e.stopPropagation()} style={{ borderColor: 'var(--orange, #d2991d)' }}>
            <div className="danger-confirm-icon">📦</div>
            <div className="danger-confirm-title">{language === 'zh' ? '环境依赖缺失' : 'Missing Dependency'}</div>
            <div className="danger-confirm-desc">
              {language === 'zh'
                ? `Agent 测试时发现缺少依赖 "${depMissing.module}"，可能导致任务无法继续。是否安装？`
                : `Agent detected missing dependency "${depMissing.module}". Install it?`}
            </div>
            <div className="danger-confirm-cmd">{depMissing.suggestion}</div>
            <div className="danger-confirm-actions">
              <button className="danger-confirm-reject" onClick={handleDepSkip}>
                {language === 'zh' ? '跳过 (让 Agent 找替代方案)' : 'Skip'}
              </button>
              <button className="danger-confirm-approve" onClick={() => handleDepInstall(depMissing)}>
                {language === 'zh' ? `安装 ${depMissing.module}` : `Install ${depMissing.module}`}
              </button>
            </div>
          </div>
        </div>
      )}

      <TerminalPanel t={t} language={language} showTerminal={showTerminal} setShowTerminal={setShowTerminal} testLogs={testLogs} setTestLogs={setTestLogs} dangerCommand={dangerCommand} setDangerCommand={setDangerCommand} />

      {notification && (
        <div className={`notification ${notification.type}`}>{notification.msg}</div>
      )}
    </div>
  )
}

export default App
