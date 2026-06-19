import { useCallback } from "react"
import { apiPost } from "../api/client"

export function useStageReview(showNotification, loadProject, fetchProjects) {
  // ---------- 大纲审核 ----------
  const confirmOutline = useCallback(async (name) => {
    try {
      await apiPost(`/v2/projects/${encodeURIComponent(name)}/confirm-outline`)
      await loadProject(name)
      showNotification && showNotification("大纲已确认，推进至写作阶段", "success")
      return true
    } catch (e) {
      showNotification && showNotification("确认失败: " + e.message, "error")
      return false
    }
  }, [showNotification, loadProject])

  const rejectOutline = useCallback(async (name) => {
    try {
      await apiPost(`/v2/projects/${encodeURIComponent(name)}/reject-outline`)
      await loadProject(name)
      showNotification && showNotification("大纲已驳回", "info")
      return true
    } catch (e) {
      showNotification && showNotification("驳回失败: " + e.message, "error")
      return false
    }
  }, [showNotification, loadProject])

  // ---------- 写作确认 ----------
  const confirmWriting = useCallback(async (name) => {
    try {
      await apiPost(`/v2/projects/${encodeURIComponent(name)}/confirm-writing`)
      await loadProject(name)
      showNotification && showNotification("写作已确认，推进至审校阶段", "success")
      return true
    } catch (e) {
      showNotification && showNotification("确认失败: " + e.message, "error")
      return false
    }
  }, [showNotification, loadProject])

  // ---------- 审校确认 ----------
  const confirmReview = useCallback(async (name) => {
    try {
      await apiPost(`/v2/projects/${encodeURIComponent(name)}/confirm-review`)
      await loadProject(name)
      showNotification && showNotification("审校完成，项目已标记为完成", "success")
      return true
    } catch (e) {
      showNotification && showNotification("确认失败: " + e.message, "error")
      return false
    }
  }, [showNotification, loadProject])

  return {
    confirmOutline, rejectOutline,
    confirmWriting, confirmReview,
  }
}
