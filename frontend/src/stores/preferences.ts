import { create } from 'zustand'
import { DISPLAY_MODE_KEY, LANG_KEY } from '@/constants'
import type { DisplayMode, Language } from '@/types/news'

export interface Translations {
  home: string
  admin: string
  backToList: string
  readOriginal: string
  notFound: string
  backHome: string
  author: string
  source: string
  justNow: string
  minAgo: string
  hrAgo: string
  dayAgo: string
  search: string
  allCategories: string
  allSources: string
  langToggle: string
  loading: string
  noResults: string
  footer: string
}

export interface PreferencesState {
  lang: Language
  displayMode: DisplayMode
  setLang: (lang: Language) => void
  setDisplayMode: (mode: DisplayMode) => void
}

const translations: Record<Language, Translations> = {
  zh: {
    home: '首页', admin: '后台管理', backToList: '返回列表', readOriginal: '阅读原文 →',
    notFound: '新闻未找到', backHome: '返回首页', author: '作者', source: '来源',
    justNow: '刚刚', minAgo: '分钟前', hrAgo: '小时前', dayAgo: '天前', search: '搜索新闻...',
    allCategories: '全部分类', allSources: '全部来源', langToggle: 'EN', loading: '加载中...',
    noResults: '没有找到相关新闻', footer: 'NewsHub - 新闻聚合平台',
  },
  en: {
    home: 'Home', admin: 'Admin', backToList: 'Back to List', readOriginal: 'Read Original →',
    notFound: 'News not found', backHome: 'Back to Home', author: 'Author', source: 'Source',
    justNow: 'Just now', minAgo: 'min ago', hrAgo: 'hr ago', dayAgo: 'days ago', search: 'Search news...',
    allCategories: 'All Categories', allSources: 'All Sources', langToggle: '中文', loading: 'Loading...',
    noResults: 'No news found', footer: 'NewsHub - News Aggregator',
  },
}

function readLanguage(): Language {
  try { return localStorage.getItem(LANG_KEY) === 'en' ? 'en' : 'zh' } catch { return 'zh' }
}

function readDisplayMode(): DisplayMode {
  try {
    const value = localStorage.getItem(DISPLAY_MODE_KEY)
    return value === 'original' || value === 'bilingual' ? value : 'zh'
  } catch { return 'zh' }
}

function persist(key: string, value: string) {
  try { localStorage.setItem(key, value) } catch { /* storage can be unavailable */ }
}

export const usePreferencesStore = create<PreferencesState>()((set) => ({
  lang: readLanguage(),
  displayMode: readDisplayMode(),
  setLang: (lang) => {
    persist(LANG_KEY, lang)
    set({ lang })
  },
  setDisplayMode: (displayMode) => {
    persist(DISPLAY_MODE_KEY, displayMode)
    set({ displayMode })
  },
}))

export function translationsFor(lang: Language): Translations {
  return translations[lang]
}
