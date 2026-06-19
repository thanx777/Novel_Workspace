import { useState, useCallback, useEffect } from "react"
import { apiGet, apiPost, apiDelete } from "../api/client"

export function useProjectCrud(showNotification, t) {
  const [projects, setProjects] = useState([])
  const [activeProject, setActiveProject] = useState(null)
  const [loadingList, setLoadingList] = useState(false)
  const [loadingDetail, setLoadingDetail] = useState(false)

  // ---------- 列表 ----------
  const fetchProjects = useCallback(async () => {
    setLoadingList(true)
    try {
      const data = await apiGet("/v2/projects")
      setProjects(data.projects || [])
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
      await apiPost(`/v2/projects/${encodeURIComponent(name)}/sync-chapters`)
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

      const [projData, chaptersData, memoryData, chatData] = await Promise.all([
        apiGet(`/v2/projects/${encodeURIComponent(name)}`),
        apiGet(`/v2/projects/${encodeURIComponent(name)}/chapters`),
        apiGet(`/v2/projects/${encodeURIComponent(name)}/memory`),
        apiGet(`/v2/projects/${encodeURIComponent(name)}/chat`),
      ])

      // 后端返回的是 {project, chapters, ...} 包装结构，提取 project 部分
      const project = projData && projData.project ? projData.project : projData
      const chapters = chaptersData.chapters || []
      const memory = memoryData.memory || []
      const chat = chatData.chat || []

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
      const data = await apiPost("/v2/projects", payload)
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
      await apiDelete(`/v2/projects/${encodeURIComponent(name)}`)
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
