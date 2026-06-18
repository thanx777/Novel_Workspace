import { useApp } from "../../context/AppContext"

export default function OutlineEditor({
  outlineDraft, setOutlineDraft, handleSaveOutline,
}) {
  const { t } = useApp()
  return (
    <div className="editor-wrap">
      <div className="editor-header">
        <span>📋 {t("outlineEditor")}</span>
        <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
          <button className="pc-btn primary small" onClick={handleSaveOutline}>
            💾 {t("saveChapter")}
          </button>
        </div>
      </div>
      <div className="editor-body">
        <textarea value={outlineDraft}
          onChange={(e) => setOutlineDraft(e.target.value)}
          placeholder="# Outline\n\n1. Chapter 1 ..."
          rows={25} className="editor-textarea" />
      </div>
    </div>
  )
}
