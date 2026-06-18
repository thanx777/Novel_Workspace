import { useApp } from "../../context/AppContext"

export default function AssistantPanel({
  assistantInput, setAssistantInput,
  handleAssistantSend, assistantLoading, assistantReply,
}) {
  const { t } = useApp()
  return (
    <div className="editor-wrap">
      <div className="editor-header">
        <span>🤖 {t("aiAssistant")}</span>
      </div>
      <div className="assistant-body">
        <div className="assistant-input-row">
          <input type="text" value={assistantInput}
            onChange={(e) => setAssistantInput(e.target.value)}
            placeholder={t("askAiPlaceholder")}
            onKeyDown={(e) => { if (e.key === "Enter") handleAssistantSend() }} />
          <button className="pc-btn primary" onClick={handleAssistantSend} disabled={assistantLoading}>
            {assistantLoading ? t("thinkingEllipsis") : t("send")}
          </button>
        </div>
        {assistantReply && (
          <div className="assistant-reply">
            {assistantReply}
          </div>
        )}
      </div>
    </div>
  )
}
