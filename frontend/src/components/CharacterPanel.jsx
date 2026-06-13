import { useMemo } from "react"

/**
 * CharacterPanel — 人物面板
 * 从知识图谱（KG）角色节点自动读取，不再依赖 characters.md
 * 角色由写作流程自动生成：大纲/写作 → AI 摄取到 KG → 人物面板实时显示
 */

const ROLE_COLORS = {
  protagonist: "#e8954a",
  main: "#e8954a",
  主角: "#e8954a",
  hero: "#e8954a",
  antagonist: "#f85149",
  villain: "#f85149",
  反派: "#f85149",
  boss: "#f85149",
  supporting: "#3fb950",
  配角: "#3fb950",
  mentor: "#a371f7",
  导师: "#a371f7",
  师父: "#a371f7",
  family: "#58a6ff",
  家人: "#58a6ff",
  爱人: "#ec4899",
}

function detectRoleColor(attrs) {
  if (!attrs) return "#7d8590"
  const roleStr = (attrs.role || attrs.角色 || attrs.type || "").toLowerCase()
  for (const [key, color] of Object.entries(ROLE_COLORS)) {
    if (roleStr.includes(key)) return color
  }
  return "#7d8590"
}

function getInitials(name) {
  if (!name) return "?"
  if (/[\u4e00-\u9fa5]/.test(name)) return name.slice(-1)
  return name.slice(0, 1).toUpperCase()
}

export default function CharacterPanel({ kgData = null, language = "zh" }) {
  const characters = useMemo(() => {
    if (!kgData?.nodes) return []
    return kgData.nodes
      .filter(n => n.type === "character")
      .map(n => ({
        id: n.id,
        name: n.label,
        summary: n.summary || "",
        attrs: n.attrs || {},
        color: detectRoleColor(n.attrs),
      }))
  }, [kgData])

  if (characters.length === 0) {
    return (
      <div className="char-panel">
        <div className="char-panel-header">
          <span className="char-panel-title">
            👤 {language === "zh" ? "人物" : "Characters"}
          </span>
        </div>
        <div className="char-panel-empty">
          <div style={{ fontSize: 48, opacity: 0.3 }}>👤</div>
          <div style={{ marginTop: 12, fontWeight: 600 }}>
            {language === "zh" ? "暂无人物" : "No characters yet"}
          </div>
          <div style={{ fontSize: 12, opacity: 0.6, marginTop: 6, maxWidth: 360, lineHeight: 1.6 }}>
            {language === "zh"
              ? "生成大纲或写作后，AI 会自动从内容中提取角色到知识图谱。"
              : "Characters are auto-extracted from outline/writing into the knowledge graph."}
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="char-panel">
      <div className="char-panel-header">
        <span className="char-panel-title">
          👤 {language === "zh" ? "人物" : "Characters"}
          <span className="char-panel-count">{characters.length} {language === "zh" ? "位" : ""}</span>
        </span>
      </div>
      <div className="char-panel-body">
        <div className="char-list">
          {characters.map((c) => (
            <div key={c.id} className="char-card active">
              <div className="char-card-avatar" style={{ background: c.color }}>
                {getInitials(c.name)}
              </div>
              <div className="char-card-info">
                <div className="char-card-name">{c.name}</div>
                {c.summary && c.summary !== c.name && (
                  <div className="char-card-preview">
                    {c.summary.slice(0, 80)}
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>

        <div className="char-detail">
          {characters.map((c) => (
            <div key={c.id} style={{ marginBottom: 16 }}>
              <div className="char-detail-header">
                <div className="char-detail-avatar" style={{ background: c.color }}>
                  {getInitials(c.name)}
                </div>
                <div className="char-detail-titles">
                  <h2 className="char-detail-name">{c.name}</h2>
                </div>
              </div>
              {c.summary && c.summary !== c.name && (
                <div style={{ fontSize: 12, opacity: 0.8, marginTop: 8, lineHeight: 1.6, padding: "0 8px" }}>
                  {c.summary}
                </div>
              )}
              {c.attrs && Object.keys(c.attrs).length > 0 && (
                <div className="char-detail-attrs" style={{ marginTop: 8 }}>
                  {Object.entries(c.attrs).map(([k, v]) => (
                    <div key={k} className="char-attr">
                      <div className="char-attr-key">{k}</div>
                      <div className="char-attr-value">{String(v)}</div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
