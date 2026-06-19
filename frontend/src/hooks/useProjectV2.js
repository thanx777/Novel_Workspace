import { useCallback } from "react"
import { useProjectCrud } from "./useProjectCrud"
import { useEngineStream } from "./useEngineStream"
import { useStageReview } from "./useStageReview"
import { useProjectFiles } from "./useProjectFiles"
import { useProjectLogs } from "./useProjectLogs"
import { useEngineState } from "./useEngineState"

/**
 * v2 Project Hook — SQLite 驱动的项目中心。
 * 聚合子 hooks，保持向后兼容的返回值结构。
 *
 * 核心功能：
 * 1. 拉取所有项目（list）/ 单个项目详情（with chapters, memory, chat）
 * 2. 创建 / 删除项目
 * 3. 阶段执行（outline / writing / polish）
 * 4. 大纲人工审核推进或驳回
 * 5. 人工编辑章节、添加记忆
 * 6. AI 助理对话
 * 7. 项目文件读写（outline / characters）
 */
export default function useProjectV2({ showNotification, presets = [], t }) {
  const crud = useProjectCrud(showNotification, t)
  const files = useProjectFiles(crud.activeProject, showNotification, crud.loadProject)
  const logs = useProjectLogs(crud.activeProject, showNotification)
  const stageReview = useStageReview(showNotification, crud.loadProject, crud.fetchProjects)
  const engineState = useEngineState(crud.activeProject, showNotification, presets)
  const engineStream = useEngineStream(
    showNotification, crud.loadProject, crud.fetchProjects, t
  )

  // migrateOld needs fetchProjects from crud, wrap it
  const migrateOld = useCallback(async () => {
    return logs.migrateOld(crud.fetchProjects)
  }, [logs.migrateOld, crud.fetchProjects])

  return {
    // state
    projects: crud.projects, setProjects: crud.setProjects,
    activeProject: crud.activeProject, setActiveProject: crud.setActiveProject,
    loadingList: crud.loadingList, loadingDetail: crud.loadingDetail,
    isRunning: engineStream.isRunning, setIsRunning: engineStream.setIsRunning,
    runningStage: engineStream.runningStage, kgRefreshKey: engineStream.kgRefreshKey,

    // actions
    fetchProjects: crud.fetchProjects, loadProject: crud.loadProject,
    createProject: crud.createProject, deleteProject: crud.deleteProject,
    updateChapter: files.updateChapter, addMemory: files.addMemory,
    confirmOutline: stageReview.confirmOutline, rejectOutline: stageReview.rejectOutline,
    confirmWriting: stageReview.confirmWriting, confirmReview: stageReview.confirmReview,
    stopTask: engineStream.stopTask,
    assistantChat: engineState.assistantChat,
    putFile: files.putFile, getFile: files.getFile,
    migrateOld,
    loadProjectPresets: logs.loadProjectPresets, saveProjectPresets: logs.saveProjectPresets,
    // 新引擎 API
    getEngineState: engineState.getEngineState,
    loadRunLogs: logs.loadRunLogs, clearRunLogs: logs.clearRunLogs,
    engineOutlineGenerate: engineStream.engineOutlineGenerate, engineOutlineChat: engineState.engineOutlineChat, getOutlineState: engineState.getOutlineState,
    engineWritingStart: engineStream.engineWritingStart, engineWritingChat: engineState.engineWritingChat, getWritingState: engineState.getWritingState,
    engineReviewStart: engineStream.engineReviewStart, getReviewState: engineState.getReviewState,
  }
}
