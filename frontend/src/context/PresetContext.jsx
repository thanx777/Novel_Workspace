import { createContext, useContext } from 'react'
import usePreset from '../hooks/usePreset'

const PresetContext = createContext(null)

export function PresetProvider({ children, showNotification }) {
  const presetHook = usePreset({ showNotification })
  return (
    <PresetContext.Provider value={presetHook}>
      {children}
    </PresetContext.Provider>
  )
}

export function usePresetContext() {
  const ctx = useContext(PresetContext)
  if (!ctx) throw new Error('usePresetContext must be used within PresetProvider')
  return ctx
}
