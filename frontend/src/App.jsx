import { BrowserRouter, Routes, Route } from 'react-router-dom'
import Header from './components/Header'
import NewsList from './pages/NewsList'
import NewsDetail from './pages/NewsDetail'

export default function App() {
  return (
    <BrowserRouter>
      <div className="min-h-screen bg-gray-50">
        <Header />
        <main>
          <Routes>
            <Route path="/" element={<NewsList />} />
            <Route path="/news/:id" element={<NewsDetail />} />
          </Routes>
        </main>
        <footer className="border-t border-gray-200 py-6 text-center text-sm text-gray-400">
          NewsHub - 新闻聚合平台
        </footer>
      </div>
    </BrowserRouter>
  )
}
