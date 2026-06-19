import { useCallback } from "react"
import { API_BASE } from "../constants"

export function useEngineState(activeProject, showNotification, presets) {
  // ---------- 引擎状态 ----------
  const getEngineState = useCallback(async (name) => {
    try {
      const resp = await fetch(`${API_BASE}/v2/projects/${encodeURIComponent(name)}/engine/state`)
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
      return await resp.json()
    } catch (e) {
      return null
    }
  }, [])

  // ---------- 引擎：获取各阶段状态 ----------
  const getOutlineState = useCallback(async (name) => {
    try {
      const resp = await fetch(`${API_BASE}/v2/projects/${encodeURIComponent(name)}/outline/state`)
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
      return await resp.json()
    } catch (e) { return null }
  }, [])

  const getWritingState = useCallback(async (name) => {
    try {
      const resp = await fetch(`${API_BASE}/v2/projects/${encodeURIComponent(name)}/writing/state`)
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
      return await resp.json()
    } catch (e) { return null }
  }, [])

  const getReviewState = useCallback(async (name) => {
    try {
      const resp = await fetch(`${API_BASE}/v2/projects/${encodeURIComponent(name)}/review/state`)
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
      return await resp.json()
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
      const resp = await fetch(`${API_BASE}/v2/projects/${encodeURIComponent(name)}/assistant/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message, presets: presetsPayload }),
      })
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
      const data = await resp.json()
      return data.reply || ""
    } catch (e) {
      showNotification && showNotification("AI 助理失败: " + e.message, "error")
      return ""
    }
  }, [showNotification, presets])

  // ---------- 引擎：大纲 AI 对话 ----------
  const engineOutlineChat = useCallback(async (name, message, layer = "") => {
    try {
      const resp = await fetch(`${API_BASE}/v2/projects/${encodeURIComponent(name)}/outline/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message, layer }),
      })
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
      const data = await resp.json()
      return data.response || ""
    } catch (e) {
      showNotification && showNotification("大纲对话失败: " + e.message, "error")
      return ""
    }
  }, [showNotification])

  // ---------- 引擎：写作 AI 对话 ----------
  const engineWritingChat = useCallback(async (name, message, chapter = 0) => {
    try {
      const resp = await fetch(`${API_BASE}/v2/projects/${encodeURIComponent(name)}/writing/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message, chapter }),
      })
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
      const data = await resp.json()
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
