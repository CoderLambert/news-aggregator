import { Link } from 'react-router-dom'
import { useLanguage } from '../context/LanguageContext'

export default function Header() {
  const { lang, setLang, t } = useLanguage()

  return (
    <header className="bg-white border-b border-gray-200 sticky top-0 z-50">
      <div className="max-w-6xl mx-auto px-4 h-16 flex items-center justify-between">
        <Link to="/" className="text-xl font-bold text-gray-900 tracking-tight">
          NewsHub
        </Link>
        <nav className="flex items-center gap-4 text-sm text-gray-600">
          <a href="/admin" target="_blank" rel="noreferrer" className="hover:text-gray-900">
            {t.admin}
          </a>
          <button
            onClick={() => setLang(lang === 'zh' ? 'en' : 'zh')}
            className="px-3 py-1 rounded-full border border-gray-300 hover:bg-gray-100 text-xs font-medium transition-colors"
            title={lang === 'zh' ? 'Switch to English' : '切换到中文'}
          >
            {t.langToggle}
          </button>
        </nav>
      </div>
    </header>
  )
}
