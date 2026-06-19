import { createContext, useContext } from 'react'
import useProjectV2 from '../hooks/useProjectV2'
import { usePresetContext } from './PresetContext'

const ProjectContext = createContext(null)

export function ProjectProvider({ children, showNotification, t }) {
  const { presets } = usePresetContext()
  const projectHook = useProjectV2({ showNotification, presets, t })
  return (
    <ProjectContext.Provider value={projectHook}>
      {children}
    </ProjectContext.Provider>
  )
}

export function useProjectContext() {
  const ctx = useContext(ProjectContext)
  if (!ctx) throw new Error('useProjectContext must be used within ProjectProvider')
  return ctx
}
