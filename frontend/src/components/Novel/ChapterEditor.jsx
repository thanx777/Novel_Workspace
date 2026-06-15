import { useState, useEffect, useCallback, useRef } from "react"
import { API_BASE } from "../../constants"

export default function ChapterEditor({
  t, language,
  fileName, fileContent, setFileContent,
  onSave, showNotification, projectName
}) {
  const [mode, setMode] = useState("read")
  const [editContent, setEditContent] = useState(fileContent)
  const textareaRef = useRef(null)
  const [aiMode, setAiMode] = useState(false)
  const [aiInstruction, setAiInstruction] = useState("")
  const [aiLoading, setAiLoading] = useState(false)

  useEffect(() => {
    setEditContent(fileContent)
  }, [fileContent])

  // Auto-focus textarea when entering edit mode
  useEffect(() => {
    if (mode === "edit" && textareaRef.current) {
      textareaRef.current.focus()
    }
  }, [mode])

  const handleSave = async () => {
    if (!fileName) return
    const ok = await onSave(fileName, editContent)
    if (ok) {
      showNotification(language === "zh" ? "章节已保存" : "Chapter saved", "success")
      setMode("read")
    }
  }

  const handleCancel = () => {
    setEditContent(fileContent)
    setMode("read")
  }

  const handleAiEdit = async () => {
    if (!fileName || !aiInstruction.trim()) return
    setAiLoading(true)
    try {
      const chapterNum = parseInt(fileName.replace(/[^0-9]/g, ""))
      if (!chapterNum) { showNotification(language === "zh" ? "无法识别章节号" : "Cannot identify chapter number", "error"); return }

      const resp = await fetch(`${API_BASE}/v2/projects/${encodeURIComponent(projectName)}/chapters/${chapterNum}/ai-edit`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ instruction: aiInstruction.trim() })
      })

      if (!resp.ok) {
        const err = await resp.json().catch(() => ({}))
        throw new Error(err.detail || err.error || `HTTP ${resp.status}`)
      }

      const data = await resp.json()

      if (data.error) {
        showNotification(data.error, "error")
        return
      }

      if (data.content) {
        setEditContent(data.content)
        setFileContent(data.content)
        setMode("edit")
        setAiMode(false)
        setAiInstruction("")
        showNotification(language === "zh" ? "AI修改完成，请确认后保存" : "AI edit done, please confirm and save", "success")
      }
    } catch (e) {
      showNotification((language === "zh" ? "AI修改失败: " : "AI edit failed: ") + e.message, "error")
    } finally {
      setAiLoading(false)
    }
  }

  // Keyboard shortcuts
  const handleKeyDown = useCallback((e) => {
    if ((e.ctrlKey || e.metaKey) && e.key === "s") {
      e.preventDefault()
      if (mode === "edit") handleSave()
    }
    if (e.key === "Escape" && mode === "edit") {
      handleCancel()
    }
  }, [mode, editContent, fileName])

  const wordCount = editContent.length
  const lines = editContent.split("\n")
  const paragraphs = editContent.split(/\n\s*\n/).filter(p => p.trim())

  // Render with basic formatting for read mode
  const renderContent = () => {
    if (!fileContent) return null
    return fileContent.split("\n").map((line, i) => {
      if (line.startsWith("# ")) return <h2 key={i} className="read-h2">{line.replace("# ", "")}</h2>
      if (line.startsWith("## ")) return <h3 key={i} className="read-h3">{line.replace("## ", "")}</h3>
      if (line.trim() === "") return <br key={i} />
      return <p key={i} className="read-p">{line}</p>
    })
  }

  const chapterNum = fileName ? (parseInt(fileName.replace(/[^0-9]/g, "")) || "-") : "-"

  return (
    <div className="chapter-editor">
      {/* Toolbar */}
      <div className="chapter-editor-toolbar">
        <div className="chapter-editor-info">
          {fileName && (
            <span className="ce-filename">
               {language === "zh" ? "第" : "Ch."}{chapterNum}{language === "zh" ? "章" : ""}
            </span>
          )}
          {mode === "read" ? (
            <>
              <span className="ce-badge ce-badge-read"> {language === "zh" ? "阅读" : "Read"}</span>
              <span className="ce-badge"> {wordCount.toLocaleString()} {language === "zh" ? "字" : "chars"}</span>
              <span className="ce-badge"> {paragraphs.length} {language === "zh" ? "段" : "para"}</span>
            </>
          ) : (
            <>
              <span className="ce-badge ce-badge-edit"> {language === "zh" ? "编辑中" : "Editing"}</span>
              <span className="ce-badge"> {wordCount.toLocaleString()} {language === "zh" ? "字" : "chars"}</span>
            </>
          )}
        </div>
        <div className="chapter-editor-actions">
          {mode === "read" ? (
            <>
              <button className="ce-btn ce-btn-edit" onClick={() => setMode("edit")}>
                 {language === "zh" ? "编辑" : "Edit"}
              </button>
              <button className="ce-btn ce-btn-ai" onClick={() => setAiMode(true)}>
                AI {language === "zh" ? "修改" : "Edit"}
              </button>
            </>
          ) : (
            <>
              <button className="ce-btn ce-btn-cancel" onClick={handleCancel}>
                Esc {language === "zh" ? "取消" : "Cancel"}
              </button>
              <button className="ce-btn ce-btn-save" onClick={handleSave}>
                 Ctrl+S {language === "zh" ? "保存" : "Save"}
              </button>
            </>
          )}
        </div>
      </div>

      {/* AI Edit Input Bar */}
      {aiMode && (
        <div className="ce-ai-input-bar">
          <input
            type="text"
            className="ce-ai-input"
            value={aiInstruction}
            onChange={e => setAiInstruction(e.target.value)}
            placeholder={language === "zh" ? "输入修改要求，如：把第三段的对话改得更紧张..." : "Enter edit instruction..."}
            onKeyDown={e => { if (e.key === "Enter" && aiInstruction.trim()) handleAiEdit() }}
            disabled={aiLoading}
          />
          <button className="ce-btn ce-btn-ai-submit" onClick={handleAiEdit} disabled={aiLoading || !aiInstruction.trim()}>
            {aiLoading ? (language === "zh" ? "处理中..." : "Processing...") : (language === "zh" ? "提交" : "Submit")}
          </button>
          <button className="ce-btn ce-btn-ai-cancel" onClick={() => { setAiMode(false); setAiInstruction("") }} disabled={aiLoading}>
            {language === "zh" ? "取消" : "Cancel"}
          </button>
        </div>
      )}

      {/* Content */}
      <div className="chapter-editor-content">
        {mode === "read" ? (
          <div className="read-view">
            {fileContent ? (
              <div className="read-text">{renderContent()}</div>
            ) : (
              <div className="read-empty">
                <div className="read-empty-icon"></div>
                <p>{language === "zh" ? "从左侧章节列表选择一章开始阅读" : "Select a chapter from the list to start reading"}</p>
                <p className="read-empty-hint">{language === "zh" ? "点击「编辑」进入编辑模式" : "Click Edit to enter edit mode"}</p>
              </div>
            )}
          </div>
        ) : (
          <textarea
            ref={textareaRef}
            className="edit-textarea"
            value={editContent}
            onChange={e => setEditContent(e.target.value)}
            onKeyDown={handleKeyDown}
            spellCheck={false}
            placeholder={language === "zh"
              ? "在此输入章节内容...\n\n快捷键：Ctrl+S 保存 · Esc 取消编辑"
              : "Write your chapter here...\n\nShortcuts: Ctrl+S Save · Esc Cancel"}
          />
        )}
      </div>

      {/* Status bar */}
      <div className="chapter-editor-status">
        <span>{mode === "read" ? "" : ""} {fileName || (language === "zh" ? "未选择章节" : "No chapter selected")}</span>
        <span>{language === "zh" ? "行" : "Lines"}: {lines.length} · {language === "zh" ? "字" : "Chars"}: {wordCount.toLocaleString()}</span>
      </div>
    </div>
  )
}