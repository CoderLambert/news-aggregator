import type { ReactNode } from 'react'

/** Compatibility wrapper while older consumers keep the established provider boundary. */
export function LanguageProvider({ children }: { children: ReactNode }) {
  return children
}
