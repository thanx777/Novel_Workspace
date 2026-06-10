import { useState, useEffect, useMemo, useRef } from "react"

const LAYER_META = {
  L1: { icon: "📚", label: "L1 完整版", color: "#1c1917" },
  L2: { icon: "🚀", label: "L2 网文版", color: "#c2410c" },
  L3: { icon: "📝", label: "L3 单章细纲", color: "#0c4a6e" },
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
    { key: "matrix", icon: "⚡", label: "爽点矩阵" },
  ],
  L3: [
    { key: "list",   icon: "📋", label: "列表" },
    { key: "map",    icon: "🗺", label: "章节地图" },
    { key: "fslink", icon: "🔗", label: "伏笔链路" },
  ],
}

export default function OutlinePanel({ t, language, projectName, API_BASE, showNotification }) {
  const [layer, setLayer] = useState("L1")
  const [view, setView] = useState("md")
  const [data, setData] = useState({})  // {L1: {md, json_data}, L2: {md, json_data}, L3: {chapters: [...]}}
  const [status, setStatus] = useState({})  // 3 层状态
  const [selectedCh, setSelectedCh] = useState(null)
  const [regenerating, setRegenerating] = useState(false)
  const [chatMessages, setChatMessages] = useState([])
  const [chatInput, setChatInput] = useState("")
  const [chatLoading, setChatLoading] = useState(false)
  const [chatExpanded, setChatExpanded] = useState(false)
  const chatEndRef = useRef(null)

  // 加载 3 层状态
  const loadStatus = async () => {
    if (!projectName) return
    try {
      const r = await fetch(`${API_BASE}/v2/projects/${encodeURIComponent(projectName)}/outlines`)
      const j = await r.json()
      setStatus(j)
      // 默认选中第一个存在的层
      for (const k of ["L1", "L2", "L3"]) {
        if (j[k]?.exists) { setLayer(k); break }
      }
    } catch (e) { console.error(e) }
  }

  // 加载某层大纲
  const loadLayer = async (targetLayer) => {
    if (!projectName) return
    try {
      if (targetLayer === "L3") {
        // 加载所有章节细纲列表
        const r = await fetch(`${API_BASE}/api/v2/projects/${encodeURIComponent(projectName)}/outlines/L3`)
        // 实际是 layer 路径，需要 L3 路径下提供 list 接口；这里改用 status
        const statusR = await fetch(`${API_BASE}/api/v2/projects/${encodeURIComponent(projectName)}/outlines`)
        const status = await statusR.json()
        const chapters = status.L3?.chapters || []
        // 加载每个章节的细纲
        const chapterData = {}
        for (const ch of chapters) {
          const chR = await fetch(`${API_BASE}/api/v2/projects/${encodeURIComponent(projectName)}/outlines/L3?chapter=${ch}`)
          if (chR.ok) {
            const chData = await chR.json()
            chapterData[ch] = chData
          }
        }
        setData(prev => ({ ...prev, L3: { chapters: chapterData } }))
        if (chapters.length > 0 && !selectedCh) {
          setSelectedCh(chapters[0])
        }
      } else {
        const r = await fetch(`${API_BASE}/v2/projects/${encodeURIComponent(projectName)}/outlines/${targetLayer}`)
        if (r.ok) {
          const j = await r.json()
          setData(prev => ({ ...prev, [targetLayer]: j }))
        }
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
  const onRegenerate = async (chapter) => {
    if (!projectName) return
    setRegenerating(true)
    showNotification?.(language === "zh" ? "🔄 正在重新生成..." : "🔄 Regenerating...", "info")
    try {
      const url = chapter
        ? `${API_BASE}/v2/projects/${encodeURIComponent(projectName)}/outlines/L3/regenerate?chapter=${chapter}`
        : `${API_BASE}/v2/projects/${encodeURIComponent(projectName)}/outlines/${layer}/regenerate`
      await fetch(url, { method: "POST" })
      await loadStatus()
      await loadLayer(layer)
      showNotification?.(language === "zh" ? "✅ 重新生成完成" : "✅ Regenerated", "success")
    } catch (e) {
      showNotification?.(String(e), "error")
    } finally {
      setRegenerating(false)
    }
  }

  // 切到 L3
  const goToL3 = (ch) => {
    setLayer("L3")
    setSelectedCh(ch)
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
      if (layer === "L3" && selectedCh != null) body.chapter = selectedCh
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
        <span>📋 {language === "zh" ? "大纲" : "Outline"}</span>
        <button className="side-panel-action" onClick={() => onRegenerate()}
          disabled={regenerating || !status[layer]?.enabled}>
          {regenerating ? "⏳" : "🔄"}
        </button>
      </div>

      {/* 3 层 Tab */}
      <div className="outline-tabs">
        {["L1", "L2", "L3"].map(k => {
          const m = LAYER_META[k]
          const s = status[k] || {}
          return (
            <div key={k} className={`outline-tab ${layer === k ? "active" : ""} ${s.enabled === false ? "disabled" : ""}`}
              style={layer === k ? { borderBottomColor: m.color, color: m.color } : {}}
              onClick={() => s.enabled !== false && setLayer(k)}>
              <span className="tab-icon">{m.icon}</span>
              <span className="tab-label">{m.label}</span>
              {s.exists && <span className="tab-dot" style={{ background: m.color }} />}
            </div>
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
        {layer === "L1" && <L1View view={view} data={data.L1} status={status.L1} goToL3={goToL3} language={language} />}
        {layer === "L2" && <L2View view={view} data={data.L2} status={status.L2} goToL3={goToL3} language={language} />}
        {layer === "L3" && <L3View view={view} data={data.L3} selectedCh={selectedCh} setSelectedCh={setSelectedCh} onRegenerate={onRegenerate} regenerating={regenerating} language={language} />}

        {/* AI 对话 */}
        <div className="outline-chat">
          <div className="outline-chat-header" onClick={() => setChatExpanded(!chatExpanded)}>
            <span>💬 {language === "zh" ? "AI 对话" : "AI Chat"}</span>
            <span className="outline-chat-toggle">{chatExpanded ? "▾" : "▸"}</span>
          </div>
          {chatExpanded && (
            <div className="outline-chat-body">
              <div className="outline-chat-messages">
                {chatMessages.length === 0 && (
                  <div className="outline-chat-hint">{language === "zh" ? "输入反馈或修改指令，AI 将帮你调整大纲" : "Type feedback or instructions, AI will help modify the outline"}</div>
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
                    <span className="outline-chat-msg-content loading">{language === "zh" ? "思考中…" : "Thinking…"}</span>
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
                  placeholder={language === "zh" ? "输入修改意见…" : "Type feedback…"}
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
function L1View({ view, data, status, goToL3, language }) {
  if (!status?.exists) {
    return <div className="outline-empty">📚 L1 完整版大纲尚未生成</div>
  }
  if (view === "md") return <MarkdownView text={data?.md || ""} />
  if (view === "tree") return <L1TreeView data={data?.json_data} goToL3={goToL3} language={language} />
  if (view === "graph") return <div className="outline-graph-hint">🕸 关系网视图请切换到"🕸 知识图谱"标签页查看完整效果</div>
  return null
}

function L1TreeView({ data, goToL3, language }) {
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
// L2 视图
// ============================================================
function L2View({ view, data, status, language }) {
  if (!status?.exists) {
    return <div className="outline-empty">🚀 L2 网文精简版大纲尚未生成</div>
  }
  if (view === "md") return <MarkdownView text={data?.md || ""} />
  if (view === "tree") {
    const j = data?.json_data || {}
    return (
      <div className="outline-tree">
        <TreeNode icon="📘" title="基础信息" defaultOpen>
          {Object.entries(j.basic || {}).map(([k, v]) => v && <TreeLeaf key={k} label={k} value={v} />)}
        </TreeNode>
        <TreeNode icon="🌍" title="简略世界观" defaultOpen>
          <TreeLeaf label="" value={j.world_brief || "（无）"} />
        </TreeNode>
        <TreeNode icon="👥" title="人物速览" defaultOpen>
          {Object.entries(j.characters || {}).map(([k, v]) => v && <TreeLeaf key={k} label={k} value={v} />)}
        </TreeNode>
        <TreeNode icon="🎬" title="三幕" defaultOpen>
          {Object.entries(j.three_acts || {}).map(([k, v]) => v && <TreeLeaf key={k} label={k} value={v} />)}
        </TreeNode>
        <TreeNode icon="⚡" title="阶段节点">
          {(j.phases || []).map((p, i) => (
            <TreeLeaf key={i} label={`阶段${p.阶段号 || i+1}（${p.章节范围 || ""}）`}
              value={`爽点：${p.爽点 || ""} | ${p.剧情要点 || ""}`} />
          ))}
        </TreeNode>
      </div>
    )
  }
  if (view === "matrix") return <HookMatrix data={data?.json_data} language={language} />
  return null
}

function HookMatrix({ data, language }) {
  if (!data) return <div className="outline-empty">暂无数据</div>
  const phases = data.phases || []
  const hookTypes = ["升级", "打脸", "逆袭", "甜宠", "解谜", "反转"]
  // 解析每个阶段的爽点
  return (
    <div className="hook-matrix">
      <div className="hook-matrix-title">⚡ 爽点矩阵</div>
      <table>
        <thead>
          <tr>
            <th></th>
            {phases.map((p, i) => <th key={i}>阶段 {i+1}</th>)}
          </tr>
        </thead>
        <tbody>
          {hookTypes.map(hook => (
            <tr key={hook}>
              <th>{hook}</th>
              {phases.map((p, i) => {
                const text = `${p.爽点 || ""} ${p.剧情要点 || ""}`
                const hit = text.includes(hook)
                return <td key={i} className={hit ? "hit" : ""}>{hit ? "⚡" : ""}</td>
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// ============================================================
// L3 视图
// ============================================================
function L3View({ view, data, selectedCh, setSelectedCh, onRegenerate, regenerating, language }) {
  if (!data?.chapters || Object.keys(data.chapters).length === 0) {
    return <div className="outline-empty">📝 还没有单章细纲，开始写作后会自动生成</div>
  }
  const chapterList = Object.keys(data.chapters).map(Number).sort((a, b) => a - b)
  const current = data.chapters[selectedCh]

  if (view === "list") {
    return (
      <div className="l3-list-view">
        <div className="l3-chapter-list">
          {chapterList.map(ch => (
            <div key={ch} className={`l3-chapter-row ${selectedCh === ch ? "active" : ""}`}
              onClick={() => setSelectedCh(ch)}>
              <span className="l3-ch-num">Ch{ch}</span>
              <span className="l3-ch-title">{data.chapters[ch]?.json_data?.chapter_title || `第${ch}章`}</span>
            </div>
          ))}
        </div>
        <div className="l3-detail">
          {current ? (
            <>
              <div className="l3-detail-header">
                <h4>第 {selectedCh} 章：{current.json_data?.chapter_title || ""}</h4>
                <button onClick={() => onRegenerate(selectedCh)} disabled={regenerating}>🔄 重新生成</button>
              </div>
              <MarkdownView text={current.md || ""} />
            </>
          ) : <div className="outline-empty">选择左侧章节查看细纲</div>}
        </div>
      </div>
    )
  }

  if (view === "map") {
    // 章节地图：横轴=章号，纵轴=情绪曲线
    const points = chapterList.map(ch => {
      const text = data.chapters[ch]?.md || ""
      const mood = (text.match(/(爽|虐|喜|悲|惊|反转|高潮|低谷)/g) || []).length
      return { ch, mood, title: data.chapters[ch]?.json_data?.chapter_title || `Ch${ch}` }
    })
    const maxMood = Math.max(1, ...points.map(p => p.mood))
    return (
      <div className="l3-map">
        <div className="l3-map-title">🗺 章节地图</div>
        <svg width="100%" height="280" viewBox="0 0 800 280" className="l3-map-svg">
          {/* 网格线 */}
          {[1,2,3,4].map(i => <line key={i} x1="40" y1={i*50} x2="780" y2={i*50} stroke="#e2e8f0" />)}
          {/* 折线 */}
          <polyline points={points.map((p, i) => {
            const x = 40 + (i / Math.max(1, points.length-1)) * 740
            const y = 200 - (p.mood / maxMood) * 150
            return `${x},${y}`
          }).join(" ")} fill="none" stroke="#a855f7" strokeWidth="2" />
          {/* 节点 */}
          {points.map((p, i) => {
            const x = 40 + (i / Math.max(1, points.length-1)) * 740
            const y = 200 - (p.mood / maxMood) * 150
            return (
              <g key={p.ch}>
                <circle cx={x} cy={y} r={5 + p.mood} fill="#a855f7"
                  onClick={() => setSelectedCh(p.ch)} style={{ cursor: "pointer" }} />
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
    // 伏笔链路
    return <ForeshadowingLink chapters={data.chapters} chapterList={chapterList} />
  }

  return null
}

function ForeshadowingLink({ chapters, chapterList }) {
  // 解析每章伏笔
  const fsByCh = {}
  for (const ch of chapterList) {
    const text = chapters[ch]?.md || ""
    const setFs = [...text.matchAll(/埋设[：:]\s*(FS-\d+)/g)].map(m => m[1])
    const payFs = [...text.matchAll(/回收[：:]\s*(FS-\d+)/g)].map(m => m[1])
    fsByCh[ch] = { set: setFs, pay: payFs }
  }
  // 所有伏笔 ID
  const allFs = new Set()
  for (const ch of chapterList) {
    fsByCh[ch].set.forEach(x => allFs.add(x))
    fsByCh[ch].pay.forEach(x => allFs.add(x))
  }
  const fsList = [...allFs]
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
              const isSet = fsByCh[ch].set.includes(fs)
              const isPay = fsByCh[ch].pay.includes(fs)
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
      {text.split("\n").map((line, i) => {
        if (line.startsWith("# ")) return <h1 key={i}>{line.slice(2)}</h1>
        if (line.startsWith("## ")) return <h2 key={i}>{line.slice(3)}</h2>
        if (line.startsWith("### ")) return <h3 key={i}>{line.slice(4)}</h3>
        if (line.match(/^[\-\*]\s/)) return <li key={i}>{line.slice(2)}</li>
        if (line.match(/^\d+\.\s/)) return <li key={i}>{line.replace(/^\d+\.\s/, "")}</li>
        if (!line.trim()) return <br key={i} />
        return <p key={i}>{line}</p>
      })}
    </div>
  )
}

function TreeNode({ icon, title, defaultOpen = false, children }) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <div className="tree-node">
      <div className="tree-node-header" onClick={() => setOpen(!open)}>
        <span className="tree-arrow">{open ? "▼" : "▶"}</span>
        <span className="tree-icon">{icon}</span>
        <span className="tree-title">{title}</span>
      </div>
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
