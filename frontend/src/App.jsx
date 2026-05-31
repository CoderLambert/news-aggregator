import { lazy, Suspense } from 'react'
import { BrowserRouter, Routes, Route } from 'react-router-dom'
import { LanguageProvider } from './context/LanguageContext'
import { useLanguage } from './context/useLanguage'
import Header from './components/Header'
import AppErrorBoundary from './components/AppErrorBoundary'
import LoadingSpinner from './components/LoadingSpinner'

// Route-level code splitting — NewsDetail (markstream-react + react-markdown) is
// the heaviest component. Lazy-loading means the list page loads faster.
const NewsList = lazy(() => import('./pages/NewsList'))
const NewsDetail = lazy(() => import('./pages/NewsDetail'))

export default function App() {
  return (
    <LanguageProvider>
      <BrowserRouter>
        <div className="min-h-screen bg-gray-50 overflow-x-hidden">
          <Header />
          <main>
            <AppErrorBoundary onReset={() => window.location.reload()}>
              <Suspense fallback={<LoadingSpinner />}>
                <Routes>
                  <Route path="/" element={<NewsList />} />
                  <Route path="/news/:id" element={<NewsDetail />} />
                </Routes>
              </Suspense>
            </AppErrorBoundary>
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
