import { useState, useEffect, useRef } from "react"
import { useApp } from "../context/AppContext"
import { AccessibleButton } from "./common/AccessibleButton"
import ReactMarkdown from "react-markdown"

const LAYER_META = {
  L1: { icon: "📚", label: "L1 全书大纲", color: "#1c1917" },
  L2: { icon: "📝", label: "L2 章节细纲", color: "#c2410c" },
}

const VIEW_META = {
  L1: [
    { key: "md",    icon: "📝", label: "Markdown" },
    { key: "tree",  icon: "🌲", label: "树形" },
    { key: "graph", icon: "🕸", label: "关系网" },
  ],
  L2: [
    { key: "md",     icon: "📝", label: "Markdown" },
    { key: "tree",   icon: "🌲", label: "树形" },
    { key: "map",    icon: "🗺", label: "章节地图" },
    { key: "fslink", icon: "🔗", label: "伏笔链路" },
  ],
}

export default function OutlinePanel({ projectName, API_BASE, showNotification }) {
  const { t } = useApp()
  const [layer, setLayer] = useState("L1")
  const [view, setView] = useState("md")
  const [data, setData] = useState({})  // {L1: {md, json_data}, L2: {md, json_data}}
  const [status, setStatus] = useState({})  // 2 层状态
  const [regenerating, setRegenerating] = useState(false)
  const [chatMessages, setChatMessages] = useState([])
  const [chatInput, setChatInput] = useState("")
  const [chatLoading, setChatLoading] = useState(false)
  const [chatExpanded, setChatExpanded] = useState(false)
  const chatEndRef = useRef(null)

  // 加载 2 层状态
  const loadStatus = async () => {
    if (!projectName) return
    try {
      const r = await fetch(`${API_BASE}/v2/projects/${encodeURIComponent(projectName)}/outlines`)
      const j = await r.json()
      setStatus(j)
      // 默认选中第一个存在的层
      for (const k of ["L1", "L2"]) {
        if (j[k]?.exists) { setLayer(k); break }
      }
    } catch (e) { console.error(e) }
  }

  // 加载某层大纲
  const loadLayer = async (targetLayer) => {
    if (!projectName) return
    try {
      const r = await fetch(`${API_BASE}/v2/projects/${encodeURIComponent(projectName)}/outlines/${targetLayer}`)
      if (r.ok) {
        const j = await r.json()
        setData(prev => ({ ...prev, [targetLayer]: j }))
      }
    } catch (e) { console.error(e) }
  }

  useEffect(() => {
    loadStatus()
  }, [projectName])

  useEffect(() => {
    if (projectName) loadLayer(layer)
  }, [layer, projectName])

  // 切层时重置 view
  useEffect(() => {
    setView(VIEW_META[layer]?.[0]?.key || "md")
  }, [layer])

  // 重新生成
  const onRegenerate = async () => {
    if (!projectName) return
    setRegenerating(true)
    showNotification?.(t('regenerating'), "info")
    try {
      const url = `${API_BASE}/v2/projects/${encodeURIComponent(projectName)}/outlines/${layer}/regenerate`
      await fetch(url, { method: "POST" })
      await loadStatus()
      await loadLayer(layer)
      showNotification?.(t('regenerated'), "success")
    } catch (e) {
      showNotification?.(String(e), "error")
    } finally {
      setRegenerating(false)
    }
  }

  // AI 对话：发送消息
  const sendChatMessage = async () => {
    const msg = chatInput.trim()
    if (!msg || chatLoading || !projectName) return
    setChatInput("")
    setChatLoading(true)
    setChatMessages(prev => [...prev, { role: "user", content: msg }])
    try {
      const body = { message: msg, layer }
      const r = await fetch(`${API_BASE}/v2/projects/${encodeURIComponent(projectName)}/outline/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      })
      const j = await r.json()
      setChatMessages(prev => [...prev, { role: "assistant", content: j.response || "（无回复）" }])
      // 刷新大纲数据
      await loadStatus()
      await loadLayer(layer)
    } catch (e) {
      setChatMessages(prev => [...prev, { role: "assistant", content: `❌ ${e.message || "请求失败"}` }])
    } finally {
      setChatLoading(false)
    }
  }

  // 聊天区域自动滚到底部
  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" })
  }, [chatMessages])

  return (
    <div className="side-panel outline-panel outline-panel-v2">
      <div className="side-panel-header">
        <span>📋 {t('outline')}</span>
        <button className="side-panel-action" onClick={() => onRegenerate()}
          disabled={regenerating || !status[layer]?.enabled}>
          {regenerating ? "⏳" : "🔄"}
        </button>
      </div>

      {/* 2 层 Tab */}
      <div className="outline-tabs">
        {["L1", "L2"].map(k => {
          const m = LAYER_META[k]
          const s = status[k] || {}
          return (
            <AccessibleButton key={k} className={`outline-tab ${layer === k ? "active" : ""} ${s.enabled === false ? "disabled" : ""}`}
              style={layer === k ? { borderBottomColor: m.color, color: m.color } : {}}
              disabled={s.enabled === false}
              onClick={() => setLayer(k)}>
              <span className="tab-icon">{m.icon}</span>
              <span className="tab-label">{m.label}</span>
              {s.exists && <span className="tab-dot" style={{ background: m.color }} />}
            </AccessibleButton>
          )
        })}
      </div>

      {/* 视图切换 */}
      <div className="outline-views">
        {(VIEW_META[layer] || []).map(v => (
          <button key={v.key}
            className={`outline-view-btn ${view === v.key ? "active" : ""}`}
            onClick={() => setView(v.key)}>
            {v.icon} {v.label}
          </button>
        ))}
      </div>

      <div className="side-panel-body">
        {/* 内容渲染 */}
        {layer === "L1" && <L1View view={view} data={data.L1} status={status.L1} />}
        {layer === "L2" && <L2View view={view} data={data.L2} status={status.L2} />}

        {/* AI 对话 */}
        <div className="outline-chat">
          <AccessibleButton className="outline-chat-header"
            onClick={() => setChatExpanded(!chatExpanded)}>
            <span>💬 {t('aiChat')}</span>
            <span className="outline-chat-toggle">{chatExpanded ? "▾" : "▸"}</span>
          </AccessibleButton>
          {chatExpanded && (
            <div className="outline-chat-body">
              <div className="outline-chat-messages">
                {chatMessages.length === 0 && (
                  <div className="outline-chat-hint">{t('outlineChatHint')}</div>
                )}
                {chatMessages.map((m, i) => (
                  <div key={i} className={`outline-chat-msg ${m.role}`}>
                    <span className="outline-chat-msg-role">{m.role === "user" ? "🧑" : "🤖"}</span>
                    <span className="outline-chat-msg-content">{m.content}</span>
                  </div>
                ))}
                {chatLoading && (
                  <div className="outline-chat-msg assistant">
                    <span className="outline-chat-msg-role">🤖</span>
                    <span className="outline-chat-msg-content loading">{t('thinkingEllipsisZh')}</span>
                  </div>
                )}
                <div ref={chatEndRef} />
              </div>
              <div className="outline-chat-input-row">
                <input
                  type="text"
                  className="outline-chat-input"
                  value={chatInput}
                  onChange={e => setChatInput(e.target.value)}
                  onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendChatMessage() } }}
                  placeholder={t('typeFeedback')}
                  disabled={chatLoading}
                />
                <button className="outline-chat-send" onClick={sendChatMessage} disabled={chatLoading || !chatInput.trim()}>
                  ➤
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

// ============================================================
// L1 视图
// ============================================================
function L1View({ view, data, status }) {
  if (!status?.exists) {
    return <div className="outline-empty">📚 L1 全书大纲尚未生成</div>
  }
  if (view === "md") return <MarkdownView text={data?.md || ""} />
  if (view === "tree") return <L1TreeView data={data?.json_data} />
  if (view === "graph") return <div className="outline-graph-hint">🕸 关系网视图请切换到"🕸 知识图谱"标签页查看完整效果</div>
  return null
}

function L1TreeView({ data }) {
  if (!data) return <div className="outline-empty">暂无结构化数据</div>
  const basic = data.basic || {}
  const worldview = data.worldview || {}
  const characters = data.characters || {}
  const plot = data.plot || {}
  const volumes = data.volumes || []
  const ending = data.ending || {}

  return (
    <div className="outline-tree">
      <TreeNode icon="📘" title="基础信息" defaultOpen>
        {Object.entries(basic).map(([k, v]) => v && <TreeLeaf key={k} label={k} value={v} />)}
      </TreeNode>
      <TreeNode icon="🌐" title="世界观" defaultOpen>
        {Object.entries(worldview).map(([k, v]) => v && <TreeLeaf key={k} label={k} value={v} />)}
      </TreeNode>
      <TreeNode icon="👥" title="人物">
        <TreeNode icon="🦸" title="核心主角">
          {(characters["核心主角"] || []).map((line, i) => <TreeLeaf key={i} label="" value={line} />)}
        </TreeNode>
        <TreeNode icon="🤝" title="主要配角">
          {(characters["主要配角"] || []).map((line, i) => <TreeLeaf key={i} label="" value={line} />)}
        </TreeNode>
        <TreeNode icon="😈" title="反派">
          {(characters["反派"] || []).map((line, i) => <TreeLeaf key={i} label="" value={line} />)}
        </TreeNode>
      </TreeNode>
      <TreeNode icon="📖" title="剧情">
        {Object.entries(plot).map(([k, v]) => v && <TreeLeaf key={k} label={k} value={v} />)}
      </TreeNode>
      <TreeNode icon="📚" title={`分卷（${volumes.length}）`}>
        {volumes.map((v, i) => (
          <TreeNode key={i} icon="📕" title={`第${v["卷号"] || i+1}卷 ${v["卷名"]}`}>
            {Object.entries(v).filter(([k]) => k !== "卷号" && k !== "卷名").map(([k, val]) => val && <TreeLeaf key={k} label={k} value={val} />)}
          </TreeNode>
        ))}
      </TreeNode>
      <TreeNode icon="🏁" title="结局">
        {Object.entries(ending).map(([k, v]) => v && <TreeLeaf key={k} label={k} value={v} />)}
      </TreeNode>
    </div>
  )
}

// ============================================================
// L2 视图（合并版：阶段划分 + 逐章细纲）
// ============================================================
function L2View({ view, data, status }) {
  if (!status?.exists) {
    return <div className="outline-empty">📝 L2 章节细纲尚未生成</div>
  }
  if (view === "md") return <MarkdownView text={data?.md || ""} />
  if (view === "tree") {
    const j = data?.json_data || {}
    const chapters = j.chapters || []
    const phases = j.phases || []
    return (
      <div className="outline-tree">
        <TreeNode icon="🎬" title={`阶段划分（${phases.length}）`} defaultOpen>
          {phases.map((p, i) => (
            <TreeLeaf key={i} label={`阶段${p.阶段号 || i+1}（${p.章节范围 || ""}）`}
              value={p.核心目标 || ""} />
          ))}
        </TreeNode>
        <TreeNode icon="📝" title={`逐章细纲（${chapters.length}）`}>
          {chapters.map((ch, i) => (
            <TreeNode key={i} icon="📄" title={`第${ch.chapter_num || i+1}章 ${ch.title || ""}`}>
              {ch["核心目的"] && <TreeLeaf label="核心目的" value={ch["核心目的"]} />}
              {ch["出场人物"] && <TreeLeaf label="出场人物" value={ch["出场人物"]} />}
              {ch["章节流程"] && <TreeLeaf label="章节流程" value={ch["章节流程"]} />}
              {ch["情绪/爽点"] && <TreeLeaf label="情绪/爽点" value={ch["情绪/爽点"]} />}
              {ch["伏笔"] && <TreeLeaf label="伏笔" value={ch["伏笔"]} />}
              {ch["衔接下章"] && <TreeLeaf label="衔接下章" value={ch["衔接下章"]} />}
            </TreeNode>
          ))}
        </TreeNode>
      </div>
    )
  }
  if (view === "map") {
    // 章节地图：横轴=章号，纵轴=情绪曲线
    const j = data?.json_data || {}
    const chapters = j.chapters || []
    const points = chapters.map((ch, i) => {
      const text = `${ch["情绪/爽点"] || ""} ${ch["核心目的"] || ""}`
      const mood = (text.match(/(爽|虐|喜|悲|惊|反转|高潮|低谷|逆袭|打脸|升级)/g) || []).length
      return { ch: ch.chapter_num || i + 1, mood, title: ch.title || `Ch${ch.chapter_num || i+1}` }
    })
    const maxMood = Math.max(1, ...points.map(p => p.mood))
    return (
      <div className="l3-map">
        <div className="l3-map-title">🗺 章节地图</div>
        <svg width="100%" height="280" viewBox="0 0 800 280" className="l3-map-svg">
          {[1,2,3,4].map(i => <line key={i} x1="40" y1={i*50} x2="780" y2={i*50} stroke="#e2e8f0" />)}
          <polyline points={points.map((p, i) => {
            const x = 40 + (i / Math.max(1, points.length-1)) * 740
            const y = 200 - (p.mood / maxMood) * 150
            return `${x},${y}`
          }).join(" ")} fill="none" stroke="#c2410c" strokeWidth="2" />
          {points.map((p, i) => {
            const x = 40 + (i / Math.max(1, points.length-1)) * 740
            const y = 200 - (p.mood / maxMood) * 150
            return (
              <g key={p.ch}>
                <circle cx={x} cy={y} r={5 + p.mood} fill="#c2410c" style={{ cursor: "default" }} />
                <text x={x} y={260} textAnchor="middle" fontSize="11" fill="#475569">Ch{p.ch}</text>
              </g>
            )
          })}
          <text x="10" y="50" fontSize="10" fill="#64748b">情绪↑</text>
          <text x="10" y="200" fontSize="10" fill="#64748b">情绪↓</text>
        </svg>
      </div>
    )
  }
  if (view === "fslink") {
    const j = data?.json_data || {}
    const chapters = j.chapters || []
    return <ForeshadowingLink chapters={chapters} />
  }
  return null
}

function ForeshadowingLink({ chapters }) {
  // 解析每章伏笔
  const fsByCh = {}
  const chapterList = chapters.map((ch, i) => ch.chapter_num || i + 1)
  for (const ch of chapters) {
    const chNum = ch.chapter_num || 1
    const text = `${ch["伏笔"] || ""}`
    const setFs = [...text.matchAll(/埋设[：:]*\s*(FS-\d+)/g)].map(m => m[1])
    const payFs = [...text.matchAll(/回收[：:]*\s*(FS-\d+)/g)].map(m => m[1])
    fsByCh[chNum] = { set: setFs, pay: payFs }
  }
  const allFs = new Set()
  for (const ch of chapterList) {
    fsByCh[ch].set.forEach(x => allFs.add(x))
    fsByCh[ch].pay.forEach(x => allFs.add(x))
  }
  const fsList = [...allFs]
  if (fsList.length === 0) {
    return <div className="outline-empty">暂无伏笔数据</div>
  }
  return (
    <div className="l3-fslink">
      <div className="l3-fslink-title">🔗 伏笔链路</div>
      <div className="l3-fslink-grid">
        <div className="fs-row fs-header">
          <div className="fs-cell">伏笔</div>
          {chapterList.map(ch => <div key={ch} className="fs-cell fs-ch">Ch{ch}</div>)}
        </div>
        {fsList.map(fs => (
          <div key={fs} className="fs-row">
            <div className="fs-cell fs-label">{fs}</div>
            {chapterList.map(ch => {
              const isSet = fsByCh[ch]?.set.includes(fs)
              const isPay = fsByCh[ch]?.pay.includes(fs)
              return (
                <div key={ch} className="fs-cell">
                  {isSet && <span className="fs-dot fs-set" title="埋下">●</span>}
                  {isPay && <span className="fs-dot fs-pay" title="回收">●</span>}
                </div>
              )
            })}
          </div>
        ))}
      </div>
    </div>
  )
}

// ============================================================
// 公共子组件
// ============================================================
function MarkdownView({ text }) {
  if (!text) return <div className="outline-empty">暂无内容</div>
  return (
    <div className="outline-markdown">
      <ReactMarkdown>{text}</ReactMarkdown>
    </div>
  )
}

function TreeNode({ icon, title, defaultOpen = false, children }) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <div className="tree-node">
      <AccessibleButton className="tree-node-header"
        onClick={() => setOpen(!open)}>
        <span className="tree-arrow">{open ? "▼" : "▶"}</span>
        <span className="tree-icon">{icon}</span>
        <span className="tree-title">{title}</span>
      </AccessibleButton>
      {open && <div className="tree-node-children">{children}</div>}
    </div>
  )
}

function TreeLeaf({ label, value }) {
  return (
    <div className="tree-leaf">
      {label && <span className="tree-leaf-label">{label}：</span>}
      <span className="tree-leaf-value">{String(value).slice(0, 200)}{String(value).length > 200 ? "..." : ""}</span>
    </div>
  )
}
