import { usePreferencesStore, translationsFor } from '@/stores/preferences'

export function useLanguage() {
  const lang = usePreferencesStore((state) => state.lang)
  const setLang = usePreferencesStore((state) => state.setLang)
  const displayMode = usePreferencesStore((state) => state.displayMode)
  const setDisplayMode = usePreferencesStore((state) => state.setDisplayMode)
  return { lang, setLang, displayMode, setDisplayMode, t: translationsFor(lang) }
}
