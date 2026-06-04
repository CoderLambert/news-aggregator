import { lazy, Suspense, useState, useRef, useEffect, useCallback } from 'react'
import { BrowserRouter, Routes, Route } from 'react-router-dom'
import { LanguageProvider } from './context/LanguageContext'
import { useLanguage } from './context/useLanguage'
import { AuthProvider } from './context/AuthContext'
import { SpeechPlayerProvider } from './context/SpeechPlayerProvider'
import { useSpeechPlayer } from './context/SpeechPlayerContext'
import { VOICES, RATES, SCOPES } from './constants/tts'
import Header from './components/Header'
import AppErrorBoundary from './components/AppErrorBoundary'
import LoadingSpinner from './components/LoadingSpinner'
import { Headphones, Play, Pause, Square, Loader2, Gauge, ChevronUp, FileText } from 'lucide-react'

// Route-level code splitting — NewsDetail (Markdown rendering + chat) is
// the heaviest component. Lazy-loading means the list page loads faster.
const NewsList = lazy(() => import('./pages/NewsList'))
const NewsDetail = lazy(() => import('./pages/NewsDetail'))
const FavoritesPage = lazy(() => import('./pages/FavoritesPage'))
const ProviderComparisons = lazy(() => import('./pages/ProviderComparisons'))
// Design QA route — preview the Xiaowen mascot in all moods.
const MascotPreview = lazy(() => import('./components/mascot/MascotPreview'))

export default function App() {
  return (
    <LanguageProvider>
      <AuthProvider>
        <SpeechPlayerProvider>
          <BrowserRouter>
            <div className="min-h-screen bg-gray-50 overflow-x-hidden">
              <Header />
              <main>
                <AppErrorBoundary onReset={() => window.location.reload()}>
                  <Suspense fallback={<LoadingSpinner />}>
                  <Routes>
                    <Route path="/" element={<NewsList />} />
                    <Route path="/news/:id" element={<NewsDetail />} />
                    <Route path="/favorites" element={<FavoritesPage />} />
                    <Route path="/provider-comparisons" element={<ProviderComparisons />} />
                    <Route path="/__mascot__" element={<MascotPreview />} />
                  </Routes>
                  </Suspense>
                </AppErrorBoundary>
              </main>
              <Footer />
              <GlobalSpeechPlayer />
            </div>
          </BrowserRouter>
        </SpeechPlayerProvider>
      </AuthProvider>
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

/* ── Global Speech Player ──────────────────────────────────────────── */

function GlobalSpeechPlayer() {
  const player = useSpeechPlayer()
  const [expanded, setExpanded] = useState(false)

  // --- Drag-to-seek state ---
  // Use refs + direct DOM for drag visuals to avoid React re-render jitter.
  const barRef = useRef(null)
  const fillRef = useRef(null)
  const dotRef = useRef(null)
  const draggingRef = useRef(false)

  const getPctFromEvent = useCallback((clientX) => {
    const bar = barRef.current
    if (!bar) return 0.5
    const rect = bar.getBoundingClientRect()
    return Math.max(0, Math.min(1, (clientX - rect.left) / rect.width))
  }, [])

  // Update DOM directly — no state, no re-render
  const updateDragVisuals = useCallback((fraction) => {
    const pct = fraction * 100
    const fill = fillRef.current
    const dot = dotRef.current
    if (fill) {
      fill.style.transition = 'none'
      fill.style.width = `${pct}%`
    }
    if (dot) {
      dot.style.transition = 'none'
      dot.style.left = `calc(${pct}% - 6px)`
      dot.style.opacity = '1'
      dot.style.transform = 'translateY(-50%) scale(1.25)'
    }
  }, [])

  const startDrag = useCallback((clientX) => {
    draggingRef.current = true
    updateDragVisuals(getPctFromEvent(clientX))
  }, [getPctFromEvent, updateDragVisuals])

  const moveDrag = useCallback((clientX) => {
    if (!draggingRef.current) return
    updateDragVisuals(getPctFromEvent(clientX))
  }, [getPctFromEvent, updateDragVisuals])

  const endDrag = useCallback((clientX) => {
    if (!draggingRef.current) return
    draggingRef.current = false
    // Seek from the actual release position, not a cached value
    const fraction = getPctFromEvent(clientX)
    player.seek(fraction)
    // Do NOT clear inline styles here — React will override them on the
    // next render triggered by audio 'timeupdate'. Clearing causes a flash
    // to the pre-drag position.
  }, [player, getPctFromEvent])

  // Global move/up listeners for drag (works even when cursor leaves the bar)
  useEffect(() => {
    const onMouseMove = (e) => moveDrag(e.clientX)
    const onMouseUp = (e) => endDrag(e.clientX)
    const onTouchMove = (e) => {
      if (draggingRef.current) {
        e.preventDefault()
        moveDrag(e.touches[0].clientX)
      }
    }
    const onTouchEnd = (e) => endDrag(e.changedTouches[0].clientX)
    window.addEventListener('mousemove', onMouseMove)
    window.addEventListener('mouseup', onMouseUp)
    window.addEventListener('touchmove', onTouchMove, { passive: false })
    window.addEventListener('touchend', onTouchEnd)
    return () => {
      window.removeEventListener('mousemove', onMouseMove)
      window.removeEventListener('mouseup', onMouseUp)
      window.removeEventListener('touchmove', onTouchMove)
      window.removeEventListener('touchend', onTouchEnd)
    }
  }, [moveDrag, endDrag])

  if (player.status === 'idle') return null

  const isPlaying = player.status === 'playing'
  const isLoading = player.status === 'loading'
  const pct = Math.round(player.progress * 100)

  const displayPct = pct

  const formatTime = (s) => {
    if (!s || !isFinite(s)) return '0:00'
    const m = Math.floor(s / 60)
    const sec = Math.floor(s % 60)
    return `${m}:${sec.toString().padStart(2, '0')}`
  }

  return (
    <div className="fixed bottom-0 left-0 right-0 z-50">
      <div className="bg-white/95 backdrop-blur-xl border-t border-neutral-200 shadow-[0_-4px_24px_-4px_rgba(0,0,0,0.08)]">
        {/* Progress bar — clickable + drag-to-seek */}
        <div
          ref={barRef}
          className="h-[14px] flex items-center bg-neutral-100 cursor-pointer relative group"
          onMouseDown={(e) => {
            e.preventDefault()
            startDrag(e.clientX)
          }}
          onTouchStart={(e) => startDrag(e.touches[0].clientX)}
        >
          {/* Visual bar inside hit area */}
          <div className="h-1 w-full relative">
            <div
              ref={fillRef}
              className={`absolute inset-y-0 left-0 transition-[width] duration-150 ease-linear ${
                isLoading ? 'bg-violet-300 animate-pulse' : 'bg-violet-500'
              }`}
              style={{ width: isLoading ? '100%' : `${displayPct}%` }}
            />
            {/* Thumb dot — hover-reveal when not dragging */}
            {!isLoading && displayPct > 0 && (
              <div
                ref={dotRef}
                className="absolute top-1/2 -translate-y-1/2 size-3 bg-violet-600 rounded-full shadow opacity-0 group-hover:opacity-100 transition-opacity"
                style={{ left: `calc(${displayPct}% - 6px)` }}
              />
            )}
          </div>
        </div>

        <div className="flex items-center gap-3 px-4 py-2 max-w-3xl mx-auto">
          {/* Icon */}
          <div className="flex-shrink-0">
            <div className="size-9 rounded-full bg-violet-50 flex items-center justify-center">
              {isLoading ? (
                <Loader2 className="size-4 text-violet-600 animate-spin" />
              ) : (
                <Headphones className="size-4 text-violet-600" />
              )}
            </div>
          </div>

          {/* Title + time */}
          <div className="flex-1 min-w-0">
            <p className="text-[13px] font-medium text-neutral-800 truncate">{player.title}</p>
            <p className="text-[11px] text-neutral-400">
              {isLoading ? '正在生成语音...' : (
                <>{formatTime(player.currentTime)} / {formatTime(player.duration)} · {displayPct}%</>
              )}
            </p>
          </div>

          {/* Expand button */}
          <button
            type="button"
            onClick={() => setExpanded(!expanded)}
            className={`p-1.5 rounded-full hover:bg-neutral-100 transition-all ${expanded ? 'rotate-180' : ''}`}
            aria-label="展开控制"
          >
            <ChevronUp className="size-3.5 text-neutral-400" />
          </button>

          {/* Playback controls */}
          <div className="flex items-center gap-0.5">
            {!isLoading && (
              <>
                {isPlaying ? (
                  <button
                    type="button"
                    onClick={player.pause}
                    aria-label="暂停"
                    className="p-2 rounded-full hover:bg-neutral-100"
                  >
                    <Pause className="size-4 text-neutral-700" />
                  </button>
                ) : (
                  <button
                    type="button"
                    onClick={player.resume}
                    aria-label="继续"
                    className="p-2 rounded-full hover:bg-neutral-100"
                  >
                    <Play className="size-4 text-violet-600" />
                  </button>
                )}
                <button
                  type="button"
                  onClick={player.stop}
                  aria-label="停止"
                  className="p-2 rounded-full hover:bg-neutral-100"
                >
                  <Square className="size-3.5 text-neutral-500" />
                </button>
              </>
            )}
          </div>
        </div>

        {/* Expanded controls: speed + voice */}
        {expanded && (
          <div className="px-4 pb-3 pt-1 border-t border-neutral-100 max-w-3xl mx-auto">
            {/* Speed control */}
            <div className="flex items-center gap-2 mb-2">
              <Gauge className="size-3.5 text-neutral-400" />
              <span className="text-[11px] text-neutral-400 w-8">倍速</span>
              <div className="flex gap-1">
                {RATES.map(r => (
                  <button
                    key={r}
                    type="button"
                    onClick={() => player.setRate(r)}
                    className={`px-2 py-0.5 rounded-full text-[11px] font-medium transition-colors ${
                      Math.abs(player.rate - r) < 0.01
                        ? 'bg-violet-100 text-violet-700'
                        : 'bg-neutral-100 text-neutral-500 hover:bg-neutral-200'
                    }`}
                  >
                    {r}x
                  </button>
                ))}
              </div>
            </div>

            {/* Voice selection */}
            <div className="flex items-center gap-2">
              <Headphones className="size-3.5 text-neutral-400" />
              <span className="text-[11px] text-neutral-400 w-8">声音</span>
              <div className="flex gap-1">
                {VOICES.map(v => (
                  <button
                    key={v.key}
                    type="button"
                    onClick={() => player.setVoice(v.key)}
                    className={`px-2.5 py-0.5 rounded-full text-[11px] font-medium transition-colors ${
                      player.voice === v.key
                        ? 'bg-violet-100 text-violet-700'
                        : 'bg-neutral-100 text-neutral-500 hover:bg-neutral-200'
                    }`}
                  >
                    {v.label}<span className="text-neutral-400 ml-0.5">{v.desc}</span>
                  </button>
                ))}
              </div>
            </div>

            {/* Scope selection */}
            <div className="flex items-center gap-2 mt-2">
              <FileText className="size-3.5 text-neutral-400" />
              <span className="text-[11px] text-neutral-400 w-8">范围</span>
              <div className="flex gap-1">
                {SCOPES.map(s => (
                  <button
                    key={s.key}
                    type="button"
                    onClick={() => player.setScope(s.key)}
                    className={`px-2.5 py-0.5 rounded-full text-[11px] font-medium transition-colors ${
                      player.scope === s.key
                        ? 'bg-violet-100 text-violet-700'
                        : 'bg-neutral-100 text-neutral-500 hover:bg-neutral-200'
                    }`}
                  >
                    {s.label}
                  </button>
                ))}
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
