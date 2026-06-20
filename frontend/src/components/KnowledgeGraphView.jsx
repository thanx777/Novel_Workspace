import { useState, useEffect, useMemo, useCallback, useRef } from "react"
import { useApp } from "../context/AppContext"
import { apiGet, apiPost, apiPut } from "../api/client"

// ============================================================
// 节点类型元数据 — 极简主题（stone + ink + amber）
// ============================================================
const NODE_META = {
  chapter:       { icon: "📖", label: "章节",     color: "#1c1917" },  // stone-900
  character:     { icon: "👤", label: "角色",     color: "#44403c" },  // stone-700
  foreshadowing: { icon: "🔮", label: "伏笔",     color: "#c2410c" },  // orange-700
  outline_node:  { icon: "📋", label: "大纲节点", color: "#0c4a6e" },  // sky-900
  scene:         { icon: "🏞", label: "场景",     color: "#0e7490" },  // cyan-700
  world_fact:    { icon: "🌐", label: "世界观",   color: "#78716c" },  // stone-500
  plot_thread:   { icon: "🧵", label: "剧情线",   color: "#b45309" },  // amber-700
}

const LAYER_COLORS = { L1: "#1c1917", L2: "#c2410c", L3: "#0c4a6e" }

const VIEWS = [
  { key: "graph",   icon: "🌐", name: "关系网" },
  { key: "char",    icon: "👥", name: "角色视角" },
  { key: "time",    icon: "📅", name: "时间线" },
  { key: "table",   icon: "📋", name: "表格" },
]

// ============================================================
// 主组件
// ============================================================
export default function KnowledgeGraphView({ projectName }) {
  const { language, t } = useApp()
  const [view, setView] = useState("graph")
  const [data, setData] = useState({ nodes: [], edges: [], stats: { node_count: 0, edge_count: 0, by_type: {} } })
  const [loading, setLoading] = useState(true)
  const [filterTypes, setFilterTypes] = useState(new Set(Object.keys(NODE_META)))
  const [selectedNode, setSelectedNode] = useState(null)
  const [search, setSearch] = useState("")
  const [hovered, setHovered] = useState(null)
  const [editing, setEditing] = useState(false)
  const [editLabel, setEditLabel] = useState("")
  const [editSummary, setEditSummary] = useState("")

  // 加载图谱
  const loadGraph = useCallback(async () => {
    if (!projectName) return
    setLoading(true)
    try {
      const j = await apiGet(`/v2/projects/${encodeURIComponent(projectName)}/graph`)
      setData(j)
    } catch (e) {
      console.error("Graph load failed:", e)
    } finally {
      setLoading(false)
    }
  }, [projectName])

  useEffect(() => { loadGraph() }, [loadGraph])

  // 自动刷新（写作时实时）
  useEffect(() => {
    const t = setInterval(() => loadGraph(), 15000)
    return () => clearInterval(t)
  }, [loadGraph])

  // 过滤后的节点/边
  const filtered = useMemo(() => {
    const nodes = data.nodes.filter(n => filterTypes.has(n.type) &&
      (search === "" || n.label.includes(search) || (n.summary || "").includes(search)))
    const nodeIds = new Set(nodes.map(n => n.id))
    const edges = data.edges.filter(e => nodeIds.has(e.source) && nodeIds.has(e.target))
    return { nodes, edges }
  }, [data, filterTypes, search])

  // 选中节点
  const onSelect = useCallback((n) => {
    setSelectedNode(n)
    setEditLabel(n?.label || "")
    setEditSummary(n?.summary || "")
    setEditing(false)
    // URL hash
    if (n) {
      window.location.hash = `node=${n.id}&view=${view}`
    }
  }, [view])

  // 保存编辑
  const onSaveEdit = async () => {
    if (!selectedNode) return
    try {
      await apiPut(`/v2/projects/${encodeURIComponent(projectName)}/graph/node/${encodeURIComponent(selectedNode.id)}`, { label: editLabel, summary: editSummary })
      await loadGraph()
      setEditing(false)
    } catch (e) {
      console.error("Save failed:", e)
    }
  }

  // 触发摄取
  const onIngest = async (chapter) => {
    if (!chapter) return
    try {
      await apiPost(`/v2/projects/${encodeURIComponent(projectName)}/graph/ingest/${chapter}`)
      await loadGraph()
    } catch (e) {
      console.error("Ingest failed:", e)
    }
  }

  // 邻居节点
  const neighbors = useMemo(() => {
    if (!selectedNode) return new Set()
    const ns = new Set()
    for (const e of data.edges) {
      if (e.source === selectedNode.id) ns.add(e.target)
      if (e.target === selectedNode.id) ns.add(e.source)
    }
    return ns
  }, [selectedNode, data.edges])

  // UI 状态
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false)

  // 关闭详情面板
  const closeDetail = useCallback(() => {
    setSelectedNode(null)
    setEditing(false)
    if (window.location.hash.startsWith("#node=")) {
      window.location.hash = ""
    }
  }, [])

  return (
    <div className="kg-view">
      {/* 顶部统计 + 视图切换 */}
      <div className="kg-topbar">
        <div className="kg-stats">
          <span className="kg-stat"><b>{data.stats.node_count}</b> {t("kgNodes")}</span>
          <span className="kg-stat"><b>{data.stats.edge_count}</b> {t("kgEdges")}</span>
          <span className="kg-stat-divider">·</span>
          {Object.entries(LAYER_COLORS).map(([k, c]) => {
            const cnt = Object.entries(data.stats.by_type || {}).reduce((sum, [type, n]) => {
              if (type === "outline_node" && k === "L1") {
                // 简化：按 layer attr 单独统计
              }
              return sum
            }, 0)
            return (
              <span key={k} className="kg-stat-layer" style={{ color: c }}>
                <span className="layer-dot" style={{ background: c }} />
                {k} {cnt}
              </span>
            )
          })}
          <span className="kg-stat-divider">·</span>
          <span className="kg-stat">最后摄取：{data.stats.last_ingest ? new Date(data.stats.last_ingest * 1000).toLocaleString() : "—"}</span>
        </div>
        <div className="kg-view-tabs">
          {VIEWS.map(v => (
            <button key={v.key}
              className={`kg-view-tab ${view === v.key ? "active" : ""}`}
              onClick={() => setView(v.key)}>
              {v.icon} {v.name}
            </button>
          ))}
        </div>
      </div>

      <div className={`kg-main ${sidebarCollapsed ? "sidebar-collapsed" : ""}`}>
        {/* 左侧三角形开关 */}
        <div
          className="kg-sidebar-toggle"
          onClick={() => setSidebarCollapsed(s => !s)}
          title={sidebarCollapsed ? "展开筛选" : "收起筛选"}
        >
          <span className="toggle-arrow">{sidebarCollapsed ? "▶" : "◀"}</span>
        </div>

        {/* 左侧筛选 + 搜索 */}
        <div className={`kg-sidebar ${sidebarCollapsed ? "collapsed" : ""}`}>
          <div className="kg-search-box">
            <input
              type="text" placeholder="🔍 搜索节点..."
              value={search} onChange={e => setSearch(e.target.value)}
            />
          </div>
          <div className="kg-type-filters">
            <div className="kg-filter-title">节点类型</div>
            {Object.entries(NODE_META).map(([k, m]) => {
              const count = data.stats.by_type?.[k] || 0
              const checked = filterTypes.has(k)
              return (
                <label key={k} className={`kg-type-row ${checked ? "on" : "off"}`}>
                  <input type="checkbox" checked={checked}
                    onChange={() => {
                      const s = new Set(filterTypes)
                      if (s.has(k)) s.delete(k); else s.add(k)
                      setFilterTypes(s)
                    }} />
                  <span className="kg-type-icon">{m.icon}</span>
                  <span className="kg-type-label">{m.label}</span>
                  <span className="kg-type-count">{count}</span>
                </label>
              )
            })}
          </div>
        </div>

        {/* 中部视图区 */}
        <div className="kg-canvas">
          {loading ? (
            <div className="kg-loading">⏳ {t("kgLoading")}</div>
          ) : data.nodes.length === 0 ? (
            <div className="kg-empty">
              <div className="kg-empty-icon">🕸</div>
              <div className="kg-empty-title">{t("kgEmpty")}</div>
              <div className="kg-empty-desc">开始写作后，章节、角色、伏笔、场景、世界观、剧情线、大纲节点会自动构建</div>
            </div>
          ) : view === "graph" ? (
            <ForceGraph nodes={filtered.nodes} edges={filtered.edges}
              selected={selectedNode} onSelect={onSelect}
              hovered={hovered} setHovered={setHovered}
              neighbors={neighbors} t={t} language={language} />
          ) : view === "char" ? (
            <CharacterView nodes={filtered.nodes} edges={filtered.edges} onSelect={onSelect} />
          ) : view === "time" ? (
            <TimelineView nodes={filtered.nodes} edges={filtered.edges} onSelect={onSelect} />
          ) : view === "table" ? (
            <TableView nodes={filtered.nodes} edges={filtered.edges} onSelect={onSelect} projectName={projectName} />
          ) : null}
        </div>

        {/* 右侧详情面板 — 仅在选中节点时显示 */}
        {selectedNode && (
          <div className="kg-detail">
            <NodeDetail node={selectedNode} edges={data.edges} nodes={data.nodes}
              editing={editing} setEditing={setEditing}
              editLabel={editLabel} setEditLabel={setEditLabel}
              editSummary={editSummary} setEditSummary={setEditSummary}
              onSave={onSaveEdit} onIngest={onIngest}
              onClose={closeDetail}
              projectName={projectName} language={language} />
          </div>
        )}
      </div>
    </div>
  )
}

// ============================================================
// 关系网视图（分层聚合 + 力导向图 + 平移/缩放/拖动）
// ============================================================
function ForceGraph({ nodes, edges, selected, onSelect, hovered, setHovered, neighbors, t, language }) {
  const svgRef = useRef(null)
  const [dims, setDims] = useState({ w: 800, h: 600 })
  const [positions, setPositions] = useState({})

  // ★ 分层聚合状态：expandedTypes 记录已展开的类型
  const [expandedTypes, setExpandedTypes] = useState(new Set())

  // 视口（平移 + 缩放）
  const [viewport, setViewport] = useState({ x: 0, y: 0, scale: 1 })
  const viewportRef = useRef({ x: 0, y: 0, scale: 1 })
  viewportRef.current = viewport

  // 拖动状态
  const [isPanning, setIsPanning] = useState(false)
  const panStart = useRef({ x: 0, y: 0, vx: 0, vy: 0 })

  // ★ 计算聚合后的节点和边
  const { displayNodes, displayEdges, aggregateNodes } = useMemo(() => {
    // 按类型分组
    const byType = {}
    for (const n of nodes) {
      if (!byType[n.type]) byType[n.type] = []
      byType[n.type].push(n)
    }

    // 聚合节点：未展开的类型显示为大泡泡
    const aggNodes = []
    const detailNodes = []
    for (const [type, group] of Object.entries(byType)) {
      if (expandedTypes.has(type)) {
        detailNodes.push(...group)
      } else {
        const m = NODE_META[type] || { icon: "•", color: "#888", label: type }
        aggNodes.push({
          id: `__agg_${type}`,
          type,
          label: `${m.label} ×${group.length}`,
          summary: group.map(n => n.label).join("、"),
          isAggregate: true,
          count: group.length,
          memberIds: group.map(n => n.id),
          _meta: m,
        })
      }
    }

    const allDisplay = [...aggNodes, ...detailNodes]
    const displayIds = new Set(allDisplay.map(n => n.id))

    // 聚合边：如果 source/target 都是展开的节点，保留原边；否则聚合为类型间边
    const aggEdgeMap = {}
    const detailEdges = []
    for (const e of edges) {
      const srcExpanded = displayIds.has(e.source)
      const tgtExpanded = displayIds.has(e.target)

      if (srcExpanded && tgtExpanded) {
        // 两端都可见，保留原边
        detailEdges.push(e)
      } else {
        // 至少一端是聚合泡泡，创建聚合边
        const srcId = displayIds.has(e.source) ? e.source : `__agg_${nodes.find(n => n.id === e.source)?.type || "unknown"}`
        const tgtId = displayIds.has(e.target) ? e.target : `__agg_${nodes.find(n => n.id === e.target)?.type || "unknown"}`
        if (srcId === tgtId) continue  // 同类型内部边，跳过
        const key = [srcId, tgtId].sort().join("→")
        if (!aggEdgeMap[key]) {
          aggEdgeMap[key] = { source: srcId, target: tgtId, count: 0 }
        }
        aggEdgeMap[key].count++
      }
    }

    const aggEdges = Object.values(aggEdgeMap).map(ae => ({
      source: ae.source,
      target: ae.target,
      type: "aggregate",
      label: ae.count > 1 ? `${ae.count}` : "",
    }))

    return {
      displayNodes: allDisplay,
      displayEdges: [...detailEdges, ...aggEdges],
      aggregateNodes: aggNodes,
    }
  }, [nodes, edges, expandedTypes])

  // 监听容器尺寸变化
  useEffect(() => {
    const updateSize = () => {
      if (svgRef.current?.parentElement) {
        const rect = svgRef.current.parentElement.getBoundingClientRect()
        setDims({ w: rect.width || 800, h: rect.height || 600 })
      }
    }
    updateSize()
    const ro = new ResizeObserver(updateSize)
    if (svgRef.current?.parentElement) ro.observe(svgRef.current.parentElement)
    return () => ro.disconnect()
  }, [])

  // 简易力导向布局
  useEffect(() => {
    if (displayNodes.length === 0) {
      setPositions({})
      return
    }
    // 初始化位置
    const pos = {}
    displayNodes.forEach((n, i) => {
      const angle = (i / displayNodes.length) * Math.PI * 2
      const radius = Math.min(dims.w, dims.h) * 0.32
      pos[n.id] = {
        x: dims.w / 2 + Math.cos(angle) * radius + (Math.random() - 0.5) * 30,
        y: dims.h / 2 + Math.sin(angle) * radius + (Math.random() - 0.5) * 30,
      }
    })
    setPositions(pos)

    // 简单模拟
    let iter = 0
    const interval = setInterval(() => {
      iter++
      setPositions(prev => {
        const next = { ...prev }
        for (let i = 0; i < displayNodes.length; i++) {
          for (let j = i + 1; j < displayNodes.length; j++) {
            const a = next[displayNodes[i].id], b = next[displayNodes[j].id]
            if (!a || !b) continue
            const dx = b.x - a.x, dy = b.y - a.y
            const dist = Math.max(20, Math.sqrt(dx*dx + dy*dy))
            // 聚合泡泡斥力更大
            const isAgg = displayNodes[i].isAggregate || displayNodes[j].isAggregate
            const idealDist = isAgg ? 180 : 120
            const force = (dist - idealDist) * 0.005
            next[displayNodes[i].id] = { ...a, x: a.x + dx/dist*force, y: a.y + dy/dist*force }
            next[displayNodes[j].id] = { ...b, x: b.x - dx/dist*force, y: b.y - dy/dist*force }
          }
        }
        // 向中心
        for (const n of displayNodes) {
          const p = next[n.id]
          if (!p) continue
          next[n.id] = { x: p.x + (dims.w/2 - p.x) * 0.008, y: p.y + (dims.h/2 - p.y) * 0.008 }
        }
        return next
      })
      if (iter > 40) clearInterval(interval)
    }, 30)
    return () => clearInterval(interval)
  }, [displayNodes, dims])

  // 度数
  const degree = useMemo(() => {
    const m = {}
    for (const e of displayEdges) {
      m[e.source] = (m[e.source] || 0) + 1
      m[e.target] = (m[e.target] || 0) + 1
    }
    return m
  }, [displayEdges])

  // ★ 点击聚合泡泡：展开该类型
  const onNodeClick = useCallback((n) => {
    if (n.isAggregate) {
      setExpandedTypes(prev => {
        const next = new Set(prev)
        next.add(n.type)
        return next
      })
    } else {
      onSelect(n)
    }
  }, [onSelect])

  // ★ 收起已展开的类型
  const collapseType = useCallback((type) => {
    setExpandedTypes(prev => {
      const next = new Set(prev)
      next.delete(type)
      return next
    })
  }, [])

  // 鼠标滚轮缩放
  const onWheel = (e) => {
    e.preventDefault()
    const rect = svgRef.current.getBoundingClientRect()
    const mx = e.clientX - rect.left
    const my = e.clientY - rect.top
    const delta = -e.deltaY * 0.0015
    const newScale = Math.max(0.2, Math.min(4, viewportRef.current.scale * (1 + delta)))
    const scaleRatio = newScale / viewportRef.current.scale
    const newX = mx - (mx - viewportRef.current.x) * scaleRatio
    const newY = my - (my - viewportRef.current.y) * scaleRatio
    setViewport({ x: newX, y: newY, scale: newScale })
  }

  // 背景拖动
  const onMouseDown = (e) => {
    if (e.button !== 0) return
    if (e.target !== svgRef.current && e.target.tagName !== "rect" && e.target.tagName !== "svg") return
    setIsPanning(true)
    panStart.current = { x: e.clientX, y: e.clientY, vx: viewport.x, vy: viewport.y }
  }
  const onMouseMove = (e) => {
    if (!isPanning) return
    const dx = e.clientX - panStart.current.x
    const dy = e.clientY - panStart.current.y
    setViewport(v => ({ ...v, x: panStart.current.vx + dx, y: panStart.current.vy + dy }))
  }
  const onMouseUp = () => setIsPanning(false)

  useEffect(() => {
    if (!isPanning) return
    const onMove = (e) => onMouseMove(e)
    const onUp = () => onMouseUp()
    window.addEventListener("mousemove", onMove)
    window.addEventListener("mouseup", onUp)
    return () => {
      window.removeEventListener("mousemove", onMove)
      window.removeEventListener("mouseup", onUp)
    }
  }, [isPanning])

  // 缩放控制
  const zoomBy = (factor) => {
    const newScale = Math.max(0.2, Math.min(4, viewport.scale * factor))
    const cx = dims.w / 2, cy = dims.h / 2
    const scaleRatio = newScale / viewport.scale
    setViewport({ x: cx - (cx - viewport.x) * scaleRatio, y: cy - (cy - viewport.y) * scaleRatio, scale: newScale })
  }
  const resetView = () => setViewport({ x: 0, y: 0, scale: 1 })
  const fitView = () => {
    const xs = Object.values(positions).map(p => p.x)
    const ys = Object.values(positions).map(p => p.y)
    if (xs.length === 0) return resetView()
    const minX = Math.min(...xs), maxX = Math.max(...xs)
    const minY = Math.min(...ys), maxY = Math.max(...ys)
    const w = maxX - minX || 1, h = maxY - minY || 1
    const padding = 60
    const scale = Math.max(0.3, Math.min(2, Math.min((dims.w - padding*2) / w, (dims.h - padding*2) / h)))
    setViewport({ x: dims.w/2 - (minX+maxX)/2*scale, y: dims.h/2 - (minY+maxY)/2*scale, scale })
  }

  if (displayNodes.length === 0) return <div className="kg-empty-small">没有匹配的节点</div>

  return (
    <>
      <svg ref={svgRef} width="100%" height="100%" viewBox={`0 0 ${dims.w} ${dims.h}`}
        className="kg-graph-svg"
        onWheel={onWheel}
        onMouseDown={onMouseDown}
        style={{ cursor: isPanning ? "grabbing" : "grab" }}
      >
        <rect width={dims.w} height={dims.h} fill="transparent" />
        <g transform={`translate(${viewport.x}, ${viewport.y}) scale(${viewport.scale})`}>
          {/* 边 */}
          {displayEdges.map((e, i) => {
            const a = positions[e.source], b = positions[e.target]
            if (!a || !b) return null
            const isHighlighted = (selected && (e.source === selected.id || e.target === selected.id)) ||
                                  (hovered && (e.source === hovered.id || e.target === hovered.id))
            const isAggEdge = e.type === "aggregate"
            const color = isHighlighted ? "#c2410c" : isAggEdge ? "rgba(120,113,108,0.25)" : "rgba(120,113,108,0.4)"
            return (
              <g key={i}>
                <line x1={a.x} y1={a.y} x2={b.x} y2={b.y}
                  stroke={color} strokeWidth={(isHighlighted ? 2 : 1) / viewport.scale} />
                {isAggEdge && e.label && (
                  <text x={(a.x+b.x)/2} y={(a.y+b.y)/2} textAnchor="middle" dy="-4"
                    fontSize={10} fill="#78716c">{e.label}</text>
                )}
              </g>
            )
          })}
          {/* 节点 */}
          {displayNodes.map(n => {
            const p = positions[n.id]
            if (!p) return null

            if (n.isAggregate) {
              // ★ 聚合泡泡：大圆 + 图标 + 数量
              const m = n._meta
              const r = (20 + Math.min(n.count * 2, 30)) / Math.max(viewport.scale, 0.5)
              return (
                <g key={n.id}
                  transform={`translate(${p.x}, ${p.y})`}
                  onClick={(e) => { e.stopPropagation(); onNodeClick(n) }}
                  onMouseEnter={() => setHovered(n)}
                  onMouseLeave={() => setHovered(null)}
                  style={{ cursor: "pointer" }}>
                  <circle r={r} fill={m.color} opacity={0.15} />
                  <circle r={r * 0.75} fill={m.color} opacity={0.6} />
                  <text textAnchor="middle" dy="-2" fontSize={r * 0.7} fill="white" fontWeight="bold">
                    {m.icon}
                  </text>
                  <text textAnchor="middle" y={r * 0.35} fontSize={r * 0.45} fill="white" fontWeight="600">
                    {n.count}
                  </text>
                  <text textAnchor="middle" y={r + 16} fontSize={12} fill="#1c1917"
                    stroke="white" strokeWidth="3" paintOrder="stroke" fontWeight="500">
                    {m.label}
                  </text>
                </g>
              )
            }

            // 普通节点
            const m = NODE_META[n.type] || { icon: "•", color: "#888" }
            const d = degree[n.id] || 0
            const r = (8 + Math.min(d * 1.5, 12)) / Math.max(viewport.scale, 0.5)
            const isSelected = selected?.id === n.id
            const isNeighbor = neighbors.has(n.id)
            const isHovered = hovered?.id === n.id
            const dimmed = (selected || hovered) && !isSelected && !isNeighbor
            return (
              <g key={n.id}
                transform={`translate(${p.x}, ${p.y})`}
                onClick={(e) => { e.stopPropagation(); onNodeClick(n) }}
                onMouseEnter={() => setHovered(n)}
                onMouseLeave={() => setHovered(null)}
                style={{ cursor: "pointer", opacity: dimmed ? 0.25 : 1 }}>
                <circle r={r + 2} fill={m.color} opacity={isSelected || isHovered ? 0.95 : 0.7} />
                <text textAnchor="middle" dy="4" fontSize={r * 1.1} fill="white" fontWeight="bold">
                  {m.icon}
                </text>
                {viewport.scale > 0.5 && (
                  <text textAnchor="middle" y={r + 14} fontSize={11} fill="#1c1917"
                    stroke="white" strokeWidth="3" paintOrder="stroke" fontWeight="500">
                    {n.label.length > 12 ? n.label.slice(0, 12) + "..." : n.label}
                  </text>
                )}
                {isSelected && <circle r={r + 6} fill="none" stroke={m.color} strokeWidth="2" strokeDasharray="3,3" />}
              </g>
            )
          })}
        </g>
      </svg>

      {/* 缩放控制按钮 */}
      <div className="kg-zoom-controls">
        <button className="kg-zoom-btn" onClick={() => zoomBy(1.25)} title="放大">＋</button>
        <div className="kg-zoom-level">{Math.round(viewport.scale * 100)}%</div>
        <button className="kg-zoom-btn" onClick={() => zoomBy(0.8)} title="缩小">−</button>
        <button className="kg-zoom-btn" onClick={fitView} title="适合窗口">⛶</button>
        <button className="kg-zoom-btn" onClick={resetView} title="重置">⌂</button>
      </div>

      {/* ★ 已展开的类型标签（可收起） */}
      {expandedTypes.size > 0 && (
        <div className="kg-expanded-tags">
          {[...expandedTypes].map(type => {
            const m = NODE_META[type] || { icon: "•", label: type }
            return (
              <span key={type} className="kg-expanded-tag" style={{ borderColor: m.color || "#888" }}
                onClick={() => collapseType(type)}>
                {m.icon} {m.label} ✕
              </span>
            )
          })}
          <button className="kg-collapse-all" onClick={() => setExpandedTypes(new Set())}>
            全部收起
          </button>
        </div>
      )}

      {/* 操作提示 */}
      <div className="kg-hint">
        {t("kgClickToExpand")} · {language === "zh" ? "点击节点查看详情" : "Click node for details"} · {language === "zh" ? "滚轮缩放" : "Scroll to zoom"} · {language === "zh" ? "拖动平移" : "Drag to pan"}
      </div>
    </>
  )
}

// ============================================================
// 角色视角视图
// ============================================================
function CharacterView({ nodes, edges, onSelect }) {
  const characters = nodes.filter(n => n.type === "character")
  if (characters.length === 0) return <div className="kg-empty-small">暂无角色节点</div>

  // 计算每个角色的关系数 / 出现章数
  const stats = {}
  for (const c of characters) {
    const related = edges.filter(e => e.source === c.id || e.target === c.id)
    const chapters = c.attrs?.appearances?.length || 0
    const foreshadowings = related.filter(e => {
      const other = e.source === c.id ? e.target : e.source
      const n = nodes.find(x => x.id === other)
      return n?.type === "foreshadowing"
    }).length
    stats[c.id] = { chapters, foreshadowings, relations: related.length }
  }

  return (
    <div className="kg-char-grid">
      {characters.map(c => {
        const s = stats[c.id]
        return (
          <div key={c.id} className="kg-char-card" onClick={() => onSelect(c)}>
            <div className="kg-char-avatar">👤</div>
            <div className="kg-char-name">{c.label}</div>
            <div className="kg-char-stats">
              <span className="char-stat">📖 {s.chapters} 章</span>
              <span className="char-stat">🔮 {s.foreshadowings} 伏笔</span>
              <span className="char-stat">🔗 {s.relations} 关系</span>
            </div>
            {c.summary && <div className="kg-char-summary">{c.summary.slice(0, 60)}{c.summary.length > 60 ? "..." : ""}</div>}
          </div>
        )
      })}
    </div>
  )
}

// ============================================================
// 时间线视图
// ============================================================
function TimelineView({ nodes, edges, onSelect }) {
  // 横轴：按章节分组
  const chapterNodes = nodes.filter(n => n.type === "chapter").sort((a, b) =>
    (a.attrs?.chapter_num || 0) - (b.attrs?.chapter_num || 0))
  if (chapterNodes.length === 0) return <div className="kg-empty-small">暂无章节节点</div>

  const maxCh = Math.max(...chapterNodes.map(n => n.attrs?.chapter_num || 0), 1)

  // 按 type 分泳道
  const lanes = Object.keys(NODE_META).filter(t => t !== "chapter")
  const laneH = 60

  // 节点按章节定位
  const positioned = []
  for (const n of nodes) {
    if (n.type === "chapter") continue
    let ch = 0
    if (n.type === "foreshadowing") {
      ch = n.attrs?.set_chapter || 1
    } else if (n.type === "character") {
      const apps = n.attrs?.appearances || []
      ch = apps[0] || 1
    } else if (n.attrs?.chapter_num) {
      ch = n.attrs.chapter_num
    } else {
      ch = 1
    }
    positioned.push({ ...n, chapter: Math.max(1, Math.min(ch, maxCh)) })
  }

  return (
    <div className="kg-timeline" style={{ minHeight: (lanes.length + 1) * laneH + 60 }}>
      <div className="kg-timeline-axis">
        {chapterNodes.map(n => (
          <div key={n.id} className="kg-timeline-chapter" style={{ left: `${(n.attrs.chapter_num / maxCh) * 100}%` }}>
            <div className="ch-num">Ch{n.attrs.chapter_num}</div>
            <div className="ch-line" />
          </div>
        ))}
      </div>
      {lanes.map((lane, idx) => {
        const laneNodes = positioned.filter(n => n.type === lane)
        const m = NODE_META[lane]
        return (
          <div key={lane} className="kg-timeline-lane" style={{ top: 30 + idx * laneH }}>
            <div className="lane-label" style={{ background: m.color }}>
              {m.icon} {m.label}
            </div>
            <div className="lane-content">
              {laneNodes.map(n => (
                <div key={n.id} className="kg-timeline-node" style={{
                  left: `${(n.chapter / maxCh) * 100}%`,
                  background: m.color
                }} title={n.label} onClick={() => onSelect(n)}>
                  {n.label.slice(0, 6)}
                </div>
              ))}
            </div>
          </div>
        )
      })}
    </div>
  )
}

// ============================================================
// 表格视图
// ============================================================
function TableView({ nodes, edges, onSelect, projectName }) {
  const [sortKey, setSortKey] = useState("type")
  const [sortDir, setSortDir] = useState("asc")
  const [expanded, setExpanded] = useState(null)
  const [tableFilter, setTableFilter] = useState("")

  const filtered = nodes.filter(n =>
    !tableFilter || n.type === tableFilter ||
    n.label.includes(tableFilter) || (n.summary || "").includes(tableFilter))
  const sorted = [...filtered].sort((a, b) => {
    const av = a[sortKey] || "", bv = b[sortKey] || ""
    return sortDir === "asc" ? (av > bv ? 1 : -1) : (av < bv ? 1 : -1)
  })

  const degree = useMemo(() => {
    const m = {}
    for (const e of edges) {
      m[e.source] = (m[e.source] || 0) + 1
      m[e.target] = (m[e.target] || 0) + 1
    }
    return m
  }, [edges])

  // 导出 CSV
  const exportCSV = () => {
    const rows = [["id", "type", "label", "summary", "degree"]]
    for (const n of sorted) {
      rows.push([n.id, n.type, n.label, (n.summary || "").replace(/[\n,]/g, " "), degree[n.id] || 0])
    }
    const csv = "﻿" + rows.map(r => r.map(c => `"${c}"`).join(",")).join("\n")
    const blob = new Blob([csv], { type: "text/csv" })
    const a = document.createElement("a")
    a.href = URL.createObjectURL(blob)
    a.download = `${projectName}_graph.csv`
    a.click()
  }

  return (
    <div className="kg-table">
      <div className="kg-table-toolbar">
        <select value={tableFilter} onChange={e => setTableFilter(e.target.value)}>
          <option value="">全部类型</option>
          {Object.entries(NODE_META).map(([k, m]) => <option key={k} value={k}>{m.icon} {m.label}</option>)}
        </select>
        <button className="kg-table-export" onClick={exportCSV}>📥 导出 CSV</button>
      </div>
      <table>
        <thead>
          <tr>
            {[
              { k: "type", l: "类型" },
              { k: "label", l: "标签" },
              { k: "summary", l: "摘要" },
              { k: "degree", l: "连接" },
            ].map(c => (
              <th key={c.k} onClick={() => { if (c.k !== "degree") { setSortKey(c.k); setSortDir(d => d === "asc" ? "desc" : "asc") } }}>
                {c.l} {sortKey === c.k && (sortDir === "asc" ? "↑" : "↓")}
              </th>
            ))}
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          {sorted.map(n => {
            const m = NODE_META[n.type] || { icon: "•", color: "#888" }
            return (
              <tr key={n.id} onClick={() => onSelect(n)}>
                <td><span className="kg-table-type" style={{ background: m.color }}>{m.icon} {m.label}</span></td>
                <td><b>{n.label}</b></td>
                <td>{(n.summary || "").slice(0, 80)}{(n.summary || "").length > 80 ? "..." : ""}</td>
                <td>{degree[n.id] || 0}</td>
                <td><button onClick={(e) => { e.stopPropagation(); setExpanded(expanded === n.id ? null : n.id) }}>{expanded === n.id ? "收起" : "JSON"}</button></td>
              </tr>
            )
          })}
        </tbody>
      </table>
      {expanded && (
        <div className="kg-table-json">
          <pre>{JSON.stringify(nodes.find(n => n.id === expanded), null, 2)}</pre>
        </div>
      )}
    </div>
  )
}

// ============================================================
// 节点详情面板
// ============================================================
function NodeDetail({ node, edges, nodes, editing, setEditing,
  editLabel, setEditLabel, editSummary, setEditSummary,
  onSave, onIngest, onClose, projectName, language }) {
  const m = NODE_META[node.type] || { icon: "•", color: "#888", label: node.type }
  const related = edges.filter(e => e.source === node.id || e.target === node.id)
  const chapter = node.attrs?.chapter_num
  const layer = node.attrs?.layer

  return (
    <div className="kg-node-detail">
      <div className="kg-node-header" style={{ background: m.color }}>
        <span className="kg-node-icon">{m.icon}</span>
        <span className="kg-node-type">{m.label}</span>
        {layer && <span className="kg-node-layer">{layer}</span>}
        <button className="kg-close-btn" onClick={onClose} title="关闭" aria-label="关闭">✕</button>
      </div>
      {editing ? (
        <div className="kg-node-edit">
          <label>标签</label>
          <input value={editLabel} onChange={e => setEditLabel(e.target.value)} />
          <label>摘要</label>
          <textarea value={editSummary} onChange={e => setEditSummary(e.target.value)} rows={6} />
          <div className="kg-node-edit-actions">
            <button onClick={() => setEditing(false)}>取消</button>
            <button className="primary" onClick={onSave}>💾 保存</button>
          </div>
        </div>
      ) : (
        <div className="kg-node-body">
          <h3>{node.label}</h3>
          {node.summary && <p className="kg-node-summary">{node.summary}</p>}
          {chapter && (
            <div className="kg-node-link">
              <a href="#" onClick={(e) => { e.preventDefault(); alert(`跳转到第 ${chapter} 章内容`) }}>
                📖 查看第 {chapter} 章
              </a>
            </div>
          )}
          {node.type === "outline_node" && layer && (
            <div className="kg-node-link">
              <a href="#" onClick={(e) => { e.preventDefault(); window.location.hash = `tab=outline&layer=${layer}` }}>
                📋 跳转到 {layer} 大纲
              </a>
            </div>
          )}
          <div className="kg-node-attrs">
            <h4>属性</h4>
            <pre>{JSON.stringify(node.attrs || {}, null, 2)}</pre>
          </div>
          <div className="kg-node-relations">
            <h4>连接 ({related.length})</h4>
            {related.map((e, i) => {
              const other = e.source === node.id ? e.target : e.source
              const o = nodes.find(x => x.id === other)
              return (
                <div key={i} className="kg-relation-row">
                  <span className="rel-type">{e.type}</span>
                  <span className="rel-target">{o?.label || other}</span>
                </div>
              )
            })}
          </div>
          <div className="kg-node-actions">
            <button onClick={() => setEditing(true)}>✏️ 编辑</button>
            {chapter && <button onClick={() => onIngest(chapter)}>🔄 重新摄取</button>}
          </div>
        </div>
      )}
    </div>
  )
}
