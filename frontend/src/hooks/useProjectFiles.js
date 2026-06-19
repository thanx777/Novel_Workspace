import { useCallback } from "react"
import { apiGet, apiPost, apiPut, apiFetch } from "../api/client"

export function useProjectFiles(activeProject, showNotification, loadProject) {
  // ---------- 更新章节 ----------
  const updateChapter = useCallback(async (name, chapterIndex, body) => {
    try {
      await apiFetch(`/v2/projects/${encodeURIComponent(name)}/chapters/${chapterIndex}`, {
        method: "PATCH",
        body: JSON.stringify(body),
      })
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
      await apiPost(`/v2/projects/${encodeURIComponent(name)}/memory`, { type: memType, content, chapter_ref: chapterRef })
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
      await apiPut(`/v2/projects/${encodeURIComponent(name)}/file/${encodeURIComponent(file)}`, { content })
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
      const data = await apiGet(`/v2/projects/${encodeURIComponent(name)}/file/${encodeURIComponent(file)}`)
      return data.content || ""
    } catch (e) {
      return ""
    }
  }, [])

  return {
    putFile, getFile, updateChapter, addMemory,
  }
}
