import { useState, useCallback, useEffect } from "react"
import { API_BASE } from "../constants"

export function useProjectCrud(showNotification, t) {
  const [projects, setProjects] = useState([])
  const [activeProject, setActiveProject] = useState(null)
  const [loadingList, setLoadingList] = useState(false)
  const [loadingDetail, setLoadingDetail] = useState(false)

  // ---------- 列表 ----------
  const fetchProjects = useCallback(async () => {
    setLoadingList(true)
    try {
      const resp = await fetch(`${API_BASE}/v2/projects`)
      if (resp.ok) {
        const data = await resp.json()
        setProjects(data.projects || [])
      }
    } catch (e) {
      console.error("[v2] fetch projects failed:", e)
    } finally {
      setLoadingList(false)
    }
  }, [])

  // ---------- 详情 ----------
  const syncChapters = useCallback(async (name) => {
    if (!name) return
    try {
      await fetch(`${API_BASE}/v2/projects/${encodeURIComponent(name)}/sync-chapters`, { method: "POST" })
    } catch (e) {
      console.error("[v2] sync chapters failed:", e)
    }
  }, [])

  const loadProject = useCallback(async (name) => {
    if (!name) return
    setLoadingDetail(true)
    try {
      // 先同步章节标题，确保数据库中的章节信息是最新的
      await syncChapters(name)

      const [projResp, chaptersResp, memoryResp, chatResp] = await Promise.all([
        fetch(`${API_BASE}/v2/projects/${encodeURIComponent(name)}`),
        fetch(`${API_BASE}/v2/projects/${encodeURIComponent(name)}/chapters`),
        fetch(`${API_BASE}/v2/projects/${encodeURIComponent(name)}/memory`),
        fetch(`${API_BASE}/v2/projects/${encodeURIComponent(name)}/chat`),
      ])

      const respData = projResp.ok ? await projResp.json() : null
      // 后端返回的是 {project, chapters, ...} 包装结构，提取 project 部分
      const project = respData && respData.project ? respData.project : respData
      const chapters = chaptersResp.ok ? (await chaptersResp.json()).chapters || [] : []
      const memory = memoryResp.ok ? (await memoryResp.json()).memory || [] : []
      const chat = chatResp.ok ? (await chatResp.json()).chat || [] : []

      setActiveProject({
        ...(project || { name }),
        chapters,
        memory,
        chat,
      })
    } catch (e) {
      console.error("[v2] load project failed:", e)
    } finally {
      setLoadingDetail(false)
    }
  }, [])

  // ---------- 创建 ----------
  const createProject = useCallback(async (payload) => {
    try {
      const resp = await fetch(`${API_BASE}/v2/projects`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      })
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
      const data = await resp.json()
      showNotification && showNotification(t?.("projectCreated") || "项目已创建", "success")
      await fetchProjects()
      return data
    } catch (e) {
      showNotification && showNotification((t?.("createFailed") || "创建失败: ") + e.message, "error")
      return null
    }
  }, [showNotification, fetchProjects, t])

  // ---------- 删除 ----------
  const deleteProject = useCallback(async (name) => {
    try {
      const resp = await fetch(`${API_BASE}/v2/projects/${encodeURIComponent(name)}`, {
        method: "DELETE",
      })
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
      showNotification && showNotification(t?.("projectDeleted") || "项目已删除", "success")
      if (activeProject?.name === name) setActiveProject(null)
      await fetchProjects()
      return true
    } catch (e) {
      showNotification && showNotification("删除失败: " + e.message, "error")
      return false
    }
  }, [showNotification, fetchProjects, activeProject, t])

  useEffect(() => {
    fetchProjects()
  }, [fetchProjects])

  return {
    projects, setProjects,
    activeProject, setActiveProject,
    loadingList, loadingDetail,
    fetchProjects, syncChapters, loadProject,
    createProject, deleteProject,
  }
}
