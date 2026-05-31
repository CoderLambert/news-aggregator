import { BrowserRouter, Routes, Route } from 'react-router-dom'
import { LanguageProvider, useLanguage } from './context/LanguageContext'
import Header from './components/Header'
import NewsList from './pages/NewsList'
import NewsDetail from './pages/NewsDetail'

export default function App() {
  return (
    <LanguageProvider>
      <BrowserRouter>
        <div className="min-h-screen bg-gray-50 overflow-x-hidden">
          <Header />
          <main>
            <Routes>
              <Route path="/" element={<NewsList />} />
              <Route path="/news/:id" element={<NewsDetail />} />
            </Routes>
          </main>
          <Footer />
        </div>
      </BrowserRouter>
    </LanguageProvider>
  )
}

function Footer() {
  const { t } = useLanguage()
  return (
    <footer className="border-t border-gray-200 py-6 text-center text-sm text-gray-400">
      {t.footer}
    </footer>
  )
}
