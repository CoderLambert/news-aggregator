import { lazy, Suspense, useEffect } from 'react'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { QueryClientProvider } from '@tanstack/react-query'
import { queryClient } from '@/services/queryClient'
import { LanguageProvider } from '@/context/LanguageContext'
import { useLanguage } from '@/context/useLanguage'
import { AuthProvider } from '@/context/AuthContext'
import { CapabilityProvider, useCapability } from '@/context/CapabilitiesContext'
import { SpeechPlayerProvider } from '@/context/SpeechPlayerProvider'
import { useSpeechPlayerActions } from '@/context/SpeechPlayerContext'
import Header from '@/components/Header'
import AppErrorBoundary from '@/components/AppErrorBoundary'
import LoadingSpinner from '@/components/LoadingSpinner'
import ResearchLauncher from '@/components/research/ResearchLauncher'
import GlobalSpeechPlayer from '@/components/speech/GlobalSpeechPlayer'
import SuperuserRoute from '@/components/admin/SuperuserRoute'
import FeatureRoute from '@/components/FeatureRoute'
import WorkspaceShell from '@/components/workspace/WorkspaceShell'
import FeedWorkspace from '@/components/workspace/FeedWorkspace'
import ReadingTracker from '@/components/workspace/ReadingTracker'
import WorkspaceSession from '@/components/workspace/WorkspaceSession'
import AIConnectionSettingsLink from '@/components/settings/AIConnectionSettingsLink'

const ChannelsPage = lazy(() => import('@/pages/ChannelsPage'))
const ChannelWorkspace = lazy(() => import('@/pages/ChannelWorkspace'))
const GroupWorkspace = lazy(() => import('@/pages/GroupWorkspace'))
const SmartGroupingWorkspace = lazy(() => import('@/pages/SmartGroupingWorkspace'))
const ChannelDetailWorkspace = lazy(() => import('@/pages/ChannelDetailWorkspace'))
const NewsList = lazy(() => import('@/pages/NewsList'))
const NewsDetail = lazy(() => import('@/pages/NewsDetail'))
const FavoritesPage = lazy(() => import('@/pages/FavoritesPage'))
const ProviderComparisons = lazy(() => import('@/pages/ProviderComparisons'))
const ChatGPTSubscriptionSettings = lazy(() => import('@/pages/ChatGPTSubscriptionSettings'))
const AIModelSettingsPage = lazy(() => import('@/pages/AIModelSettingsPage'))
const SettingsPage = lazy(() => import('@/pages/SettingsPage'))
const LocalSearch = lazy(() => import('@/pages/LocalSearch'))
const CrawlerAdminPage = lazy(() => import('@/pages/admin/CrawlerAdminPage'))
const MascotPreview = lazy(() => import('@/components/mascot/MascotPreview'))

function Footer() {
  const { t } = useLanguage()
  return <footer className="border-t border-border py-6 text-center text-sm text-muted-foreground">{t.footer}</footer>
}
function SpeechCapabilityGate() {
  const { enabled } = useCapability('tts')
  const speech = useSpeechPlayerActions()
  useEffect(() => { if (!enabled) speech.stop() }, [enabled, speech])
  return enabled ? <GlobalSpeechPlayer /> : null
}
function ResearchCapabilityGate() {
  const { enabled: researchEnabled } = useCapability('research')
  const { enabled: byokCreateEnabled } = useCapability('research_byok_create')
  return researchEnabled || byokCreateEnabled
    ? <ResearchLauncher key="research-enabled" />
    : null
}

export default function App() {
  return <QueryClientProvider client={queryClient}><CapabilityProvider><LanguageProvider><AuthProvider><SpeechPlayerProvider><BrowserRouter>
    <WorkspaceSession />
    <div className="min-h-screen bg-background text-foreground">
      <a href="#main-content" className="sr-only z-[100] rounded-md bg-background px-4 py-2 text-foreground shadow focus:not-sr-only focus:fixed focus:left-4 focus:top-4">跳至主要内容</a>
      <WorkspaceShell>
        <Header />
        <main id="main-content" tabIndex={-1}>
          <AppErrorBoundary onReset={() => window.location.reload()}><Suspense fallback={<LoadingSpinner />}><Routes>
            <Route path="/" element={<FeedWorkspace><NewsList /></FeedWorkspace>} />
            <Route path="/channels" element={<ChannelWorkspace />} />
            <Route path="/channels/groups" element={<FeatureRoute feature="accounts"><GroupWorkspace /></FeatureRoute>} />
            <Route path="/channels/smart" element={<FeatureRoute feature="accounts"><SmartGroupingWorkspace /></FeatureRoute>} />
            <Route path="/channels/manual" element={<ChannelsPage />} />
            <Route path="/channels/:id" element={<ChannelDetailWorkspace />} />
            <Route path="/search" element={<LocalSearch />} />
            <Route path="/news/:id" element={<><ReadingTracker /><NewsDetail /></>} />
            <Route path="/favorites" element={<FeatureRoute feature="favorites"><FavoritesPage /></FeatureRoute>} />
            <Route path="/provider-comparisons" element={<FeatureRoute feature="provider_comparisons" requireSuperuser><ProviderComparisons /></FeatureRoute>} />
            <Route path="/settings" element={<><SettingsPage /><AIConnectionSettingsLink /></>} />
            <Route path="/settings/ai" element={<FeatureRoute feature="accounts"><AIModelSettingsPage /></FeatureRoute>} />
            <Route path="/settings/chatgpt" element={<FeatureRoute feature="accounts"><FeatureRoute feature="chatgpt_subscription"><ChatGPTSubscriptionSettings /></FeatureRoute></FeatureRoute>} />
            <Route path="/admin" element={<Navigate to="/admin/crawlers" replace />} />
            <Route path="/admin/crawlers" element={<FeatureRoute feature="admin"><SuperuserRoute><CrawlerAdminPage /></SuperuserRoute></FeatureRoute>} />
            <Route path="/__mascot__" element={<MascotPreview />} />
            <Route path="*" element={<div className="workspace-empty"><h1>页面不存在</h1><a href="/">返回资讯首页</a></div>} />
          </Routes></Suspense></AppErrorBoundary>
          <Footer />
        </main>
      </WorkspaceShell>
      <ResearchCapabilityGate /><SpeechCapabilityGate />
    </div>
  </BrowserRouter></SpeechPlayerProvider></AuthProvider></LanguageProvider></CapabilityProvider></QueryClientProvider>
}
