import { lazy, Suspense } from 'react'
import { BrowserRouter, Route, Routes } from 'react-router-dom'
import { QueryClientProvider } from '@tanstack/react-query'
import { queryClient } from '@/services/queryClient'
import { LanguageProvider } from '@/context/LanguageContext'
import { useLanguage } from '@/context/useLanguage'
import { AuthProvider } from '@/context/AuthContext'
import { SpeechPlayerProvider } from '@/context/SpeechPlayerProvider'
import Header from '@/components/Header'
import AppErrorBoundary from '@/components/AppErrorBoundary'
import LoadingSpinner from '@/components/LoadingSpinner'
import ResearchLauncher from '@/components/research/ResearchLauncher'
import GlobalSpeechPlayer from '@/components/speech/GlobalSpeechPlayer'

// Keep feature-heavy routes out of the initial list bundle.
const NewsList = lazy(() => import('@/pages/NewsList'))
const NewsDetail = lazy(() => import('@/pages/NewsDetail'))
const FavoritesPage = lazy(() => import('@/pages/FavoritesPage'))
const ProviderComparisons = lazy(() => import('@/pages/ProviderComparisons'))
const ChatGPTSubscriptionSettings = lazy(() => import('@/pages/ChatGPTSubscriptionSettings'))
const SettingsPage = lazy(() => import('@/pages/SettingsPage'))
const LocalSearch = lazy(() => import('@/pages/LocalSearch'))

// This is an isolated design preview, not part of the news reading flow.
const MascotPreview = lazy(() => import('@/components/mascot/MascotPreview'))

function Footer() {
  const { t } = useLanguage()
  return <footer className="border-t border-border py-6 text-center text-sm text-muted-foreground">{t.footer}</footer>
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <LanguageProvider>
        <AuthProvider>
          <SpeechPlayerProvider>
            <BrowserRouter>
              <div className="min-h-screen overflow-x-hidden bg-background text-foreground">
                <a
                  href="#main-content"
                  className="sr-only z-[100] rounded-md bg-background px-4 py-2 text-foreground shadow focus:not-sr-only focus:fixed focus:left-4 focus:top-4"
                >
                  跳至主要内容
                </a>
                <Header />
                <main id="main-content" tabIndex={-1}>
                  <AppErrorBoundary onReset={() => window.location.reload()}>
                    <Suspense fallback={<LoadingSpinner />}>
                      <Routes>
                        <Route path="/" element={<NewsList />} />
                        <Route path="/search" element={<LocalSearch />} />
                        <Route path="/news/:id" element={<NewsDetail />} />
                        <Route path="/favorites" element={<FavoritesPage />} />
                        <Route path="/provider-comparisons" element={<ProviderComparisons />} />
                        <Route path="/settings" element={<SettingsPage />} />
                        <Route path="/settings/chatgpt" element={<ChatGPTSubscriptionSettings />} />
                        <Route path="/__mascot__" element={<MascotPreview />} />
                      </Routes>
                    </Suspense>
                  </AppErrorBoundary>
                </main>
                <Footer />
                <ResearchLauncher />
                <GlobalSpeechPlayer />
              </div>
            </BrowserRouter>
          </SpeechPlayerProvider>
        </AuthProvider>
      </LanguageProvider>
    </QueryClientProvider>
  )
}
