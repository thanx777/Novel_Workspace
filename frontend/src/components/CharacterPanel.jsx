import { useState, useMemo } from "react"

/**
 * CharacterPanel — 人物面板
 * 将 characters.md 解析为角色卡片，左侧列表 + 右侧预览
 * 支持"卡片视图"和"原始 markdown 视图"切换
 * 支持删除单个角色（带确认弹窗）
 */

const ROLE_PATTERNS = {
  protagonist: { label: "主角", emoji: "🦸", color: "#e8954a" },
  main: { label: "主角", emoji: "🦸", color: "#e8954a" },
  主角: { label: "主角", emoji: "🦸", color: "#e8954a" },
  hero: { label: "主角", emoji: "🦸", color: "#e8954a" },

  antagonist: { label: "反派", emoji: "🦹", color: "#f85149" },
  villain: { label: "反派", emoji: "🦹", color: "#f85149" },
  boss: { label: "反派", emoji: "🦹", color: "#f85149" },
  反派: { label: "反派", emoji: "🦹", color: "#f85149" },
  敌人: { label: "反派", emoji: "🦹", color: "#f85149" },

  supporting: { label: "配角", emoji: "🧝", color: "#3fb950" },
  deuteragonist: { label: "配角", emoji: "🧝", color: "#3fb950" },
  配角: { label: "配角", emoji: "🧝", color: "#3fb950" },
  朋友: { label: "配角", emoji: "🧝", color: "#3fb950" },
  师兄: { label: "配角", emoji: "🧝", color: "#3fb950" },
  师姐: { label: "配角", emoji: "🧝", color: "#3fb950" },

  mentor: { label: "导师", emoji: "🧙", color: "#a371f7" },
  master: { label: "导师", emoji: "🧙", color: "#a371f7" },
  师父: { label: "导师", emoji: "🧙", color: "#a371f7" },
  老师: { label: "导师", emoji: "🧙", color: "#a371f7" },
  前辈: { label: "导师", emoji: "🧙", color: "#a371f7" },

  family: { label: "家人", emoji: "👨‍👩‍👧", color: "#58a6ff" },
  孩子: { label: "家人", emoji: "👶", color: "#58a6ff" },
  母亲: { label: "家人", emoji: "👩", color: "#58a6ff" },
  父亲: { label: "家人", emoji: "👨", color: "#58a6ff" },
  爱人: { label: "家人", emoji: "❤️", color: "#ec4899" },
  爱妻: { label: "家人", emoji: "❤️", color: "#ec4899" },
  丈夫: { label: "家人", emoji: "❤️", color: "#ec4899" },
  妻子: { label: "家人", emoji: "❤️", color: "#ec4899" },
}

function detectRole(name, allText) {
  const lower = (name + " " + allText).toLowerCase()
  const priority = ["protagonist", "主角", "antagonist", "反派", "师父", "导师", "爱人", "妻子", "丈夫", "孩子", "配角", "反派"]
  for (const key of priority) {
    if (lower.includes(key.toLowerCase())) {
      return ROLE_PATTERNS[key] || ROLE_PATTERNS.配角
    }
  }
  return { label: "角色", emoji: "🧑", color: "#7d8590" }
}

function getInitials(name) {
  if (!name) return "?"
  if (/[\u4e00-\u9fa5]/.test(name)) return name.slice(-1)
  return name.slice(0, 1).toUpperCase()
}

function parseCharacters(markdown) {
  if (!markdown || !markdown.trim()) return []
  const lines = markdown.split("\n")
  const characters = []
  let current = null
  let section = "人物列表"

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i]
    const trimmed = line.trim()

    if (trimmed.startsWith("# ") || trimmed.startsWith("## ")) {
      if (trimmed.startsWith("## ") && !trimmed.includes("列表") && !trimmed.includes("关系")) {
        section = trimmed.replace(/^##\s+/, "").trim()
      }
      continue
    }
    if (trimmed.startsWith("#")) continue
    if (!trimmed) continue

    const numMatch = trimmed.match(/^\d+[\.、]\s*\**(.{1,30}?)\**\s*[:：]?\s*$/)
    if (numMatch) {
      if (current) characters.push(current)
      current = { name: numMatch[1].trim(), section, attributes: [], raw: [line] }
      continue
    }

    const headingMatch = trimmed.match(/^###\s+(.+)$/)
    if (headingMatch) {
      if (current) characters.push(current)
      current = { name: headingMatch[1].replace(/\*\*/g, "").trim(), section, attributes: [], raw: [line] }
      continue
    }

    const attrMatch = trimmed.match(/^[-*]\s*\*?\*?(.+?)\*?\*?[：:]\s*(.+)$/)
    if (attrMatch && current) {
      current.attributes.push({ key: attrMatch[1].trim(), value: attrMatch[2].trim() })
      current.raw.push(line)
      continue
    }

    if (current) current.raw.push(line)
  }

  if (current) characters.push(current)

  for (const c of characters) {
    const allText = c.attributes.map(a => a.key + a.value).join(" ")
    c.role = detectRole(c.name, allText)
  }

  return characters
}

export default function CharacterPanel({
  markdown = "",
  language = "zh",
  onChange = null,
  onSave = null,
  onDeleteCharacter = null,
}) {
  const [viewMode, setViewMode] = useState("cards")
  const [selectedIdx, setSelectedIdx] = useState(0)
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(markdown)

  const [pendingDelete, setPendingDelete] = useState(null)
  const [deleting, setDeleting] = useState(false)

  const characters = useMemo(() => parseCharacters(markdown), [markdown])
  const selected = characters[selectedIdx] || null

  const toggleEdit = () => {
    if (viewMode === "raw" && editing && onChange) {
      onChange(draft)
    }
    if (viewMode === "raw" && !editing) {
      setDraft(markdown)
    }
    setEditing(!editing)
  }

  const handleDeleteClick = (c, idx) => {
    if (!onDeleteCharacter) return
    setPendingDelete({ name: c.name, idx })
  }

  const confirmDelete = async () => {
    if (!pendingDelete || !onDeleteCharacter || deleting) return
    setDeleting(true)
    try {
      const result = await onDeleteCharacter(pendingDelete.name)
      if (result?.success !== false) {
        if (pendingDelete.idx <= selectedIdx && selectedIdx > 0) {
          setSelectedIdx(selectedIdx - 1)
        } else if (characters.length <= 1) {
          setSelectedIdx(0)
        }
      }
      setPendingDelete(null)
    } finally {
      setDeleting(false)
    }
  }

  if (viewMode === "raw") {
    return (
      <div className="char-panel char-panel-raw">
        <div className="char-panel-header">
          <span className="char-panel-title">
            👤 {language === "zh" ? "人物设定（原始 markdown）" : "Characters (Raw Markdown)"}
          </span>
          <div className="char-panel-actions">
            <button className="pc-btn small" onClick={() => setViewMode("cards")}>
              🃏 {language === "zh" ? "切换到卡片视图" : "Card View"}
            </button>
            <button
              className={`pc-btn small ${editing ? "primary" : ""}`}
              onClick={toggleEdit}
            >
              {editing
                ? (language === "zh" ? "✏️ 编辑中..." : "✏️ Editing...")
                : (language === "zh" ? "✎ 编辑" : "Edit")}
            </button>
            {onSave && (
              <button className="pc-btn primary small" onClick={onSave}>
                💾 {language === "zh" ? "保存" : "Save"}
              </button>
            )}
          </div>
        </div>
        <div className="char-panel-raw-body">
          <textarea
            className="editor-textarea"
            value={editing ? draft : markdown}
            onChange={(e) => setDraft(e.target.value)}
            readOnly={!editing}
            placeholder="# Characters..."
          />
        </div>
      </div>
    )
  }

  return (
    <div className="char-panel">
      <div className="char-panel-header">
        <span className="char-panel-title">
          👤 {language === "zh" ? "人物设定" : "Characters"}
          <span className="char-panel-count">{characters.length} {language === "zh" ? "位" : ""}</span>
        </span>
        <div className="char-panel-actions">
          <button className="pc-btn small" onClick={() => setViewMode("raw")}>
            📝 {language === "zh" ? "原始 markdown" : "Raw Markdown"}
          </button>
          {onSave && (
            <button className="pc-btn primary small" onClick={onSave}>
              💾 {language === "zh" ? "保存" : "Save"}
            </button>
          )}
        </div>
      </div>

      {characters.length === 0 ? (
        <div className="char-panel-empty">
          <div style={{ fontSize: 48, opacity: 0.3 }}>👤</div>
          <div style={{ marginTop: 12, fontWeight: 600 }}>
            {language === "zh" ? "暂无人物设定" : "No characters yet"}
          </div>
          <div style={{ fontSize: 12, opacity: 0.6, marginTop: 6, maxWidth: 360, lineHeight: 1.6 }}>
            {language === "zh"
              ? "在「原始 markdown」视图编辑 characters.md，或者在启动大纲阶段后由 AI 自动生成。"
              : "Edit characters.md in 'Raw Markdown' view, or let AI generate them during the outline stage."}
          </div>
          <button className="pc-btn primary small" style={{ marginTop: 16 }}
            onClick={() => setViewMode("raw")}>
            ✎ {language === "zh" ? "去编辑" : "Edit Now"}
          </button>
        </div>
      ) : (
        <div className="char-panel-body">
          <div className="char-list">
            {characters.map((c, i) => (
              <div key={i}
                className={`char-card ${selectedIdx === i ? "active" : ""}`}
                onClick={() => setSelectedIdx(i)}>
                <div className="char-card-avatar" style={{ background: c.role.color }}>
                  {getInitials(c.name)}
                </div>
                <div className="char-card-info">
                  <div className="char-card-name">{c.name}</div>
                  <div className="char-card-role">
                    <span className="char-role-tag" style={{ color: c.role.color, background: c.role.color + "1a" }}>
                      {c.role.emoji} {c.role.label}
                    </span>
                  </div>
                  {c.attributes.length > 0 && (
                    <div className="char-card-preview">
                      {c.attributes[0].key}：{c.attributes[0].value}
                    </div>
                  )}
                </div>
                {onDeleteCharacter && (
                  <button className="char-card-delete"
                    title={language === "zh" ? "删除此角色" : "Delete this character"}
                    onClick={(e) => { e.stopPropagation(); handleDeleteClick(c, i) }}>
                    🗑
                  </button>
                )}
              </div>
            ))}
          </div>

          <div className="char-detail">
            {selected && (
              <>
                <div className="char-detail-header">
                  <div className="char-detail-avatar" style={{ background: selected.role.color }}>
                    {getInitials(selected.name)}
                  </div>
                  <div className="char-detail-titles">
                    <h2 className="char-detail-name">{selected.name}</h2>
                    <div className="char-detail-role">
                      <span className="char-role-tag large" style={{ color: selected.role.color, background: selected.role.color + "1a" }}>
                        {selected.role.emoji} {selected.role.label}
                      </span>
                      {selected.section && (
                        <span className="char-detail-section">{selected.section}</span>
                      )}
                    </div>
                  </div>
                  {onDeleteCharacter && (
                    <button className="char-detail-delete"
                      title={language === "zh" ? "删除此角色" : "Delete this character"}
                      onClick={() => handleDeleteClick(selected, selectedIdx)}>
                      🗑 {language === "zh" ? "删除" : "Delete"}
                    </button>
                  )}
                </div>

                {selected.attributes.length === 0 ? (
                  <div className="char-detail-empty">
                    {language === "zh" ? "该角色暂无属性描述" : "No attributes for this character"}
                  </div>
                ) : (
                  <div className="char-detail-attrs">
                    {selected.attributes.map((attr, i) => (
                      <div key={i} className="char-attr">
                        <div className="char-attr-key">{attr.key}</div>
                        <div className="char-attr-value">{attr.value}</div>
                      </div>
                    ))}
                  </div>
                )}
              </>
            )}
          </div>
        </div>
      )}

      {pendingDelete && (
        <div className="modal-overlay" onClick={() => !deleting && setPendingDelete(null)}>
          <div className="pc-modal danger-modal" onClick={(e) => e.stopPropagation()}
            style={{ maxWidth: 420 }}>
            <div className="pc-modal-header danger">
              <span>🗑 {language === "zh" ? "删除角色" : "Delete Character"}</span>
              <button className="pc-modal-close" onClick={() => setPendingDelete(null)} disabled={deleting}>×</button>
            </div>
            <div className="pc-modal-body">
              <div className="delete-warning-icon">⚠️</div>
              <div className="delete-warning-title">
                {language === "zh" ? "确定要删除以下角色吗？" : "Are you sure you want to delete this character?"}
              </div>
              <div className="delete-project-name">{pendingDelete.name}</div>
              <div className="delete-warning-desc">
                {language === "zh"
                  ? "此操作不可撤销！该角色将从 characters.md 中永久移除，相关属性一并删除。"
                  : "This action cannot be undone! The character will be permanently removed from characters.md."}
              </div>
              <div className="pc-modal-actions">
                <button className="pc-btn" onClick={() => setPendingDelete(null)} disabled={deleting}>
                  {language === "zh" ? "取消" : "Cancel"}
                </button>
                <button className="pc-btn danger" onClick={confirmDelete} disabled={deleting}>
                  {deleting
                    ? (language === "zh" ? "删除中..." : "Deleting...")
                    : (language === "zh" ? "🗑 确认删除" : "🗑 Delete")}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
