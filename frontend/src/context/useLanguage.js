import { createContext, useContext } from 'react'

/**
 * Language context — keeps the React Context object and the consumer hook
 * together (and away from the Provider component file) so that
 * react-refresh/only-export-components stays happy.
 *
 * Consumers should import { useLanguage } from this module. The Provider
 * lives in ./LanguageContext.jsx.
 */
export const LanguageContext = createContext({
  lang: 'zh',
  setLang: () => {},
  displayMode: 'zh',
  setDisplayMode: () => {},
  t: {},
})

export function useLanguage() {
  return useContext(LanguageContext)
}
