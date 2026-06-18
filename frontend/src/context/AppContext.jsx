import { createContext, useContext, useState, useEffect, useCallback } from 'react'
import translations from '../translations'

const AppContext = createContext(null)

export function AppProvider({ children }) {
  const [language, setLanguage] = useState(() => localStorage.getItem('language') || 'zh')
  const [isDark, setIsDark] = useState(() => localStorage.getItem('theme') === 'dark')

  useEffect(() => {
    localStorage.setItem('language', language)
  }, [language])

  useEffect(() => {
    localStorage.setItem('theme', isDark ? 'dark' : 'light')
    document.documentElement.setAttribute('data-theme', isDark ? 'dark' : 'light')
  }, [isDark])

  // Translation function — falls back to the key itself if missing
  const t = useCallback((key) => {
    const lang = translations[language]
    return (lang && lang[key]) || key
  }, [language])

  const value = { language, setLanguage, isDark, setIsDark, t }
  return <AppContext.Provider value={value}>{children}</AppContext.Provider>
}

export function useApp() {
  const ctx = useContext(AppContext)
  if (!ctx) throw new Error('useApp must be used within AppProvider')
  return ctx
}
