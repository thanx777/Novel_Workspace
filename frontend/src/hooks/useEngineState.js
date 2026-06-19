import { useCallback } from "react"
import { apiGet, apiPost } from "../api/client"

export function useEngineState(activeProject, showNotification, presets) {
  // ---------- 引擎状态 ----------
  const getEngineState = useCallback(async (name) => {
    try {
      return await apiGet(`/v2/projects/${encodeURIComponent(name)}/engine/state`)
    } catch (e) {
      return null
    }
  }, [])

  // ---------- 引擎：获取各阶段状态 ----------
  const getOutlineState = useCallback(async (name) => {
    try {
      return await apiGet(`/v2/projects/${encodeURIComponent(name)}/outline/state`)
    } catch (e) { return null }
  }, [])

  const getWritingState = useCallback(async (name) => {
    try {
      return await apiGet(`/v2/projects/${encodeURIComponent(name)}/writing/state`)
    } catch (e) { return null }
  }, [])

  const getReviewState = useCallback(async (name) => {
    try {
      return await apiGet(`/v2/projects/${encodeURIComponent(name)}/review/state`)
    } catch (e) { return null }
  }, [])

  // ---------- AI 助理对话 ----------
  const assistantChat = useCallback(async (name, message) => {
    try {
      const presetsPayload = (presets || []).map(p => ({
        name: p.name || "", api_key: p.api_key || "",
        base_url: p.base_url || "", model: p.model || "",
        api_format: p.api_format || "openai",
        chat_template_kwargs: p.chat_template_kwargs || null,
      }))
      const data = await apiPost(`/v2/projects/${encodeURIComponent(name)}/assistant/chat`, { message, presets: presetsPayload })
      return data.reply || ""
    } catch (e) {
      showNotification && showNotification("AI 助理失败: " + e.message, "error")
      return ""
    }
  }, [showNotification, presets])

  // ---------- 引擎：大纲 AI 对话 ----------
  const engineOutlineChat = useCallback(async (name, message, layer = "") => {
    try {
      const data = await apiPost(`/v2/projects/${encodeURIComponent(name)}/outline/chat`, { message, layer })
      return data.response || ""
    } catch (e) {
      showNotification && showNotification("大纲对话失败: " + e.message, "error")
      return ""
    }
  }, [showNotification])

  // ---------- 引擎：写作 AI 对话 ----------
  const engineWritingChat = useCallback(async (name, message, chapter = 0) => {
    try {
      const data = await apiPost(`/v2/projects/${encodeURIComponent(name)}/writing/chat`, { message, chapter })
      return data.response || ""
    } catch (e) {
      showNotification && showNotification("写作对话失败: " + e.message, "error")
      return ""
    }
  }, [showNotification])

  return {
    getEngineState,
    getOutlineState, getWritingState, getReviewState,
    assistantChat, engineOutlineChat, engineWritingChat,
  }
}
