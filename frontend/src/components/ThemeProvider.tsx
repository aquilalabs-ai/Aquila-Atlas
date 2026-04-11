import { useEffect } from 'react'
import { useAppStore } from '@/store/app'

/** Syncs the Zustand theme state to the <html> class attribute. */
export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const theme = useAppStore((s) => s.theme)

  useEffect(() => {
    document.documentElement.classList.toggle('dark', theme === 'dark')
  }, [theme])

  return <>{children}</>
}
