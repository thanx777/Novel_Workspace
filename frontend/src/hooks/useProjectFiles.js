import { useCallback } from "react"
import { API_BASE } from "../constants"

export function useProjectFiles(activeProject, showNotification, loadProject) {
  // ---------- 更新章节 ----------
  const updateChapter = useCallback(async (name, chapterIndex, body) => {
    try {
      const resp = await fetch(`${API_BASE}/v2/projects/${encodeURIComponent(name)}/chapters/${chapterIndex}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      })
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
      await loadProject(name)
      return true
    } catch (e) {
      showNotification && showNotification("更新失败: " + e.message, "error")
      return false
    }
  }, [showNotification, loadProject])

  // ---------- 添加记忆 ----------
  const addMemory = useCallback(async (name, content, memType = "note", chapterRef = 0) => {
    try {
      const resp = await fetch(`${API_BASE}/v2/projects/${encodeURIComponent(name)}/memory`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ type: memType, content, chapter_ref: chapterRef }),
      })
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
      await loadProject(name)
      return true
    } catch (e) {
      showNotification && showNotification("添加记忆失败: " + e.message, "error")
      return false
    }
  }, [showNotification, loadProject])

  // ---------- 写入文件 ----------
  const putFile = useCallback(async (name, file, content) => {
    try {
      const resp = await fetch(`${API_BASE}/v2/projects/${encodeURIComponent(name)}/file/${encodeURIComponent(file)}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content }),
      })
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
      await loadProject(name)
      showNotification && showNotification("文件已保存", "success")
      return true
    } catch (e) {
      showNotification && showNotification("保存失败: " + e.message, "error")
      return false
    }
  }, [showNotification, loadProject])

  // ---------- 读取文件 ----------
  const getFile = useCallback(async (name, file) => {
    try {
      const resp = await fetch(`${API_BASE}/v2/projects/${encodeURIComponent(name)}/file/${encodeURIComponent(file)}`)
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
      const data = await resp.json()
      return data.content || ""
    } catch (e) {
      return ""
    }
  }, [])

  return {
    putFile, getFile, updateChapter, addMemory,
  }
}
