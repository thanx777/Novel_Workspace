import { useCallback } from "react"
import { API_BASE } from "../constants"
import { formatSSEEvent } from "../utils/sse"

export function useProjectLogs(activeProject, showNotification) {
  // ---------- 历史日志 ----------
  const loadRunLogs = useCallback(async (name, limit = 100) => {
    try {
      const resp = await fetch(`${API_BASE}/v2/projects/${encodeURIComponent(name)}/logs?limit=${limit}`)
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
      const data = await resp.json()
      return (data.logs || []).map(evt => formatSSEEvent({ ...evt, timestamp: evt.timestamp || Date.now() }))
    } catch (e) {
      return []
    }
  }, [])

  const clearRunLogs = useCallback(async (name) => {
    try {
      const resp = await fetch(`${API_BASE}/v2/projects/${encodeURIComponent(name)}/logs`, { method: "DELETE" })
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
      return true
    } catch (e) {
      return false
    }
  }, [])

  // ---------- 迁移旧项目 ----------
  const migrateOld = useCallback(async (fetchProjects) => {
    try {
      const resp = await fetch(`${API_BASE}/v2/projects/migrate-old`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
      })
      const data = resp.ok ? await resp.json() : {}
      await fetchProjects()
      return data
    } catch (e) {
      return { success: false, error: e.message }
    }
  }, [])

  // ---------- 项目模型预设（保存到项目数据库） ----------
  const loadProjectPresets = useCallback(async (name) => {
    try {
      const resp = await fetch(`${API_BASE}/v2/projects/${encodeURIComponent(name)}/presets`)
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
      const data = await resp.json()
      return data.presets || { manager: {}, worker: {}, reviewer: {} }
    } catch (e) {
      showNotification && showNotification("加载模型预设失败: " + e.message, "error")
      return { manager: {}, worker: {}, reviewer: {} }
    }
  }, [showNotification])

  const saveProjectPresets = useCallback(async (name, { manager, worker, reviewer }) => {
    try {
      const resp = await fetch(`${API_BASE}/v2/projects/${encodeURIComponent(name)}/presets`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ manager, worker, reviewer }),
      })
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
      showNotification && showNotification("模型配置已保存到项目", "success")
      return true
    } catch (e) {
      showNotification && showNotification("保存失败: " + e.message, "error")
      return false
    }
  }, [showNotification])

  return {
    loadRunLogs, clearRunLogs,
    migrateOld,
    loadProjectPresets, saveProjectPresets,
  }
}
