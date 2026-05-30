import { createContext, useContext, useState, useEffect, useCallback } from 'react'

const LANG_KEY = 'newshub_lang'
export { LANG_KEY }

const LanguageContext = createContext({
  lang: 'zh',
  setLang: () => {},
  t: {},
})

export function LanguageProvider({ children }) {
  const [lang, setLangState] = useState(() => {
    return localStorage.getItem(LANG_KEY) || 'zh'
  })

  const setLang = useCallback((newLang) => {
    setLangState(newLang)
    localStorage.setItem(LANG_KEY, newLang)
  }, [])

  // Translations for UI elements
  const translations = {
    zh: {
      home: '首页',
      admin: '后台管理',
      backToList: '← 返回列表',
      readOriginal: '阅读原文 →',
      notFound: '新闻未找到',
      backHome: '返回首页',
      author: '作者',
      source: '来源',
      justNow: '刚刚',
      minAgo: '分钟前',
      hrAgo: '小时前',
      dayAgo: '天前',
      search: '搜索新闻...',
      allCategories: '全部分类',
      allSources: '全部来源',
      langToggle: 'EN',
      loading: '加载中...',
      noResults: '没有找到相关新闻',
      footer: 'NewsHub - 新闻聚合平台',
    },
    en: {
      home: 'Home',
      admin: 'Admin',
      backToList: '← Back to List',
      readOriginal: 'Read Original →',
      notFound: 'News not found',
      backHome: 'Back to Home',
      author: 'Author',
      source: 'Source',
      justNow: 'Just now',
      minAgo: 'min ago',
      hrAgo: 'hr ago',
      dayAgo: 'days ago',
      search: 'Search news...',
      allCategories: 'All Categories',
      allSources: 'All Sources',
      langToggle: '中文',
      loading: 'Loading...',
      noResults: 'No news found',
      footer: 'NewsHub - News Aggregator',
    },
  }

  const value = {
    lang,
    setLang,
    t: translations[lang] || translations.zh,
  }

  return (
    <LanguageContext.Provider value={value}>
      {children}
    </LanguageContext.Provider>
  )
}

export function useLanguage() {
  return useContext(LanguageContext)
}
