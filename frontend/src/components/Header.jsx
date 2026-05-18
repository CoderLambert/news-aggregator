import { Link } from 'react-router-dom'

export default function Header() {
  return (
    <header className="bg-white border-b border-gray-200 sticky top-0 z-50">
      <div className="max-w-6xl mx-auto px-4 h-16 flex items-center justify-between">
        <Link to="/" className="text-xl font-bold text-gray-900 tracking-tight">
          NewsHub
        </Link>
        <nav className="flex items-center gap-4 text-sm text-gray-600">
          <a href="/admin" target="_blank" rel="noreferrer" className="hover:text-gray-900">
            后台管理
          </a>
        </nav>
      </div>
    </header>
  )
}
