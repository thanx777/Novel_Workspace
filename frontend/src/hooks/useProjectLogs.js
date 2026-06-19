import { useCallback } from "react"
import { apiGet, apiPost, apiPut, apiDelete } from "../api/client"
import { formatSSEEvent } from "../utils/sse"

export function useProjectLogs(activeProject, showNotification) {
  // ---------- 历史日志 ----------
  const loadRunLogs = useCallback(async (name, limit = 100) => {
    try {
      const data = await apiGet(`/v2/projects/${encodeURIComponent(name)}/logs?limit=${limit}`)
      return (data.logs || []).map(evt => formatSSEEvent({ ...evt, timestamp: evt.timestamp || Date.now() }))
    } catch (e) {
      return []
    }
  }, [])

  const clearRunLogs = useCallback(async (name) => {
    try {
      await apiDelete(`/v2/projects/${encodeURIComponent(name)}/logs`)
      return true
    } catch (e) {
      return false
    }
  }, [])

  // ---------- 迁移旧项目 ----------
  const migrateOld = useCallback(async (fetchProjects) => {
    try {
      const data = await apiPost("/v2/projects/migrate-old")
      await fetchProjects()
      return data
    } catch (e) {
      return { success: false, error: e.message }
    }
  }, [])

  // ---------- 项目模型预设（保存到项目数据库） ----------
  const loadProjectPresets = useCallback(async (name) => {
    try {
      const data = await apiGet(`/v2/projects/${encodeURIComponent(name)}/presets`)
      return data.presets || { manager: {}, worker: {}, reviewer: {} }
    } catch (e) {
      showNotification && showNotification("加载模型预设失败: " + e.message, "error")
      return { manager: {}, worker: {}, reviewer: {} }
    }
  }, [showNotification])

  const saveProjectPresets = useCallback(async (name, { manager, worker, reviewer }) => {
    try {
      await apiPut(`/v2/projects/${encodeURIComponent(name)}/presets`, { manager, worker, reviewer })
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
