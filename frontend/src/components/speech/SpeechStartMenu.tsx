import { useEffect, useRef, useState } from 'react'
import { FileText, Headphones, Languages, Loader2, Volume2, X } from 'lucide-react'
import type { SpeechLanguage, SpeechScope } from '@/constants/tts'

interface SpeechStartMenuProps {
  isEnglishSource: boolean
  hasOriginalFull: boolean
  hasChineseFull: boolean
  hasChineseSummary: boolean
  translating: boolean
  onPlay: (language: SpeechLanguage, scope: SpeechScope) => void
  onTranslateAndPlay: (scope: SpeechScope) => void
}

export default function SpeechStartMenu({
  isEnglishSource,
  hasOriginalFull,
  hasChineseFull,
  hasChineseSummary,
  translating,
  onPlay,
  onTranslateAndPlay,
}: SpeechStartMenuProps) {
  const [open, setOpen] = useState(false)
  const [language, setLanguage] = useState<SpeechLanguage>('zh')
  const [scope, setScope] = useState<SpeechScope>('full')
  const rootRef = useRef<HTMLDivElement | null>(null)
  const triggerRef = useRef<HTMLButtonElement | null>(null)
  const firstChoiceRef = useRef<HTMLButtonElement | null>(null)

  useEffect(() => {
    if (!open) return
    firstChoiceRef.current?.focus()
    const handlePointerDown = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false)
    }
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return
      event.preventDefault()
      setOpen(false)
      triggerRef.current?.focus()
    }
    document.addEventListener('pointerdown', handlePointerDown)
    document.addEventListener('keydown', handleKeyDown)
    return () => {
      document.removeEventListener('pointerdown', handlePointerDown)
      document.removeEventListener('keydown', handleKeyDown)
    }
  }, [open])

  const chineseReady = scope === 'full' ? hasChineseFull : hasChineseSummary
  const originalReady = scope === 'full' ? hasOriginalFull : true
  const selectedReady = language === 'zh' ? chineseReady : originalReady
  const canTranslate = language === 'zh' && scope === 'full' && hasOriginalFull

  const start = () => {
    if (selectedReady) onPlay(language, scope)
    else if (canTranslate) onTranslateAndPlay(scope)
    setOpen(false)
  }

  return (
    <div ref={rootRef} className="relative">
      <button
        ref={triggerRef}
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-label="选择语音播报方式"
        aria-haspopup="dialog"
        aria-expanded={open}
        className="flex size-10 items-center justify-center rounded-xl transition-colors hover:bg-neutral-100 active:bg-neutral-200"
      >
        <Headphones aria-hidden="true" className="size-4.5 text-neutral-400" />
      </button>

      {open && (
        <div
          role="dialog"
          aria-label="语音播报设置"
          className="absolute right-0 top-12 z-40 w-[min(21rem,calc(100vw-2rem))] rounded-2xl border border-neutral-200 bg-white p-4 text-neutral-900 shadow-xl"
        >
          <div className="mb-3 flex items-start justify-between gap-3">
            <div>
              <p className="text-sm font-semibold">语音播报</p>
              <p className="mt-0.5 text-xs text-neutral-500">选择朗读语言和内容范围</p>
            </div>
            <button type="button" onClick={() => { setOpen(false); triggerRef.current?.focus() }} aria-label="关闭语音设置" className="rounded-lg p-1 text-neutral-400 hover:bg-neutral-100 hover:text-neutral-700">
              <X aria-hidden="true" className="size-4" />
            </button>
          </div>

          {isEnglishSource && (
            <div className="mb-3" role="group" aria-label="朗读语言">
              <p className="mb-1.5 flex items-center gap-1 text-xs font-medium text-neutral-600"><Languages aria-hidden="true" className="size-3.5" />语言</p>
              <div className="grid grid-cols-2 gap-2">
                <button ref={firstChoiceRef} type="button" aria-pressed={language === 'zh'} onClick={() => setLanguage('zh')} className={`rounded-xl border px-3 py-2 text-left text-sm ${language === 'zh' ? 'border-violet-400 bg-violet-50 text-violet-800' : 'border-neutral-200 hover:bg-neutral-50'}`}>
                  <span className="block font-medium">中文译文</span><span className="text-[11px] opacity-70">推荐</span>
                </button>
                <button type="button" aria-pressed={language === 'original'} onClick={() => setLanguage('original')} className={`rounded-xl border px-3 py-2 text-left text-sm ${language === 'original' ? 'border-violet-400 bg-violet-50 text-violet-800' : 'border-neutral-200 hover:bg-neutral-50'}`}>
                  <span className="block font-medium">英文原文</span><span className="text-[11px] opacity-70">原声朗读</span>
                </button>
              </div>
            </div>
          )}

          <div className="mb-3" role="group" aria-label="朗读范围">
            <p className="mb-1.5 flex items-center gap-1 text-xs font-medium text-neutral-600"><FileText aria-hidden="true" className="size-3.5" />范围</p>
            <div className="flex gap-2">
              {(['full', 'summary'] as const).map((value) => (
                <button
                  ref={!isEnglishSource && value === 'full' ? firstChoiceRef : undefined}
                  key={value}
                  type="button"
                  aria-pressed={scope === value}
                  onClick={() => setScope(value)}
                  className={`rounded-full border px-3 py-1.5 text-xs font-medium ${scope === value ? 'border-violet-400 bg-violet-50 text-violet-800' : 'border-neutral-200 hover:bg-neutral-50'}`}
                >
                  {value === 'full' ? '全文' : '摘要'}
                </button>
              ))}
            </div>
          </div>

          <p role="status" className="mb-3 min-h-5 text-xs text-neutral-500">
            {language === 'zh' && chineseReady && '中文内容已就绪，可以播放。'}
            {language === 'zh' && !chineseReady && scope === 'summary' && '暂无中文摘要，可选择中文全文。'}
            {language === 'zh' && !chineseReady && scope === 'full' && hasOriginalFull && (translating ? '翻译任务正在进行，继续等待后将自动播放。' : '需要先翻译全文，完成后自动播放。')}
            {language === 'zh' && !chineseReady && scope === 'full' && !hasOriginalFull && '请先获取完整原文。'}
            {language === 'original' && !originalReady && '请先获取完整原文。'}
          </p>

          <button
            type="button"
            disabled={!selectedReady && !canTranslate}
            onClick={start}
            className="inline-flex w-full items-center justify-center gap-2 rounded-xl bg-violet-600 px-4 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-violet-700 disabled:cursor-not-allowed disabled:bg-neutral-200 disabled:text-neutral-500"
          >
            {canTranslate && !selectedReady
              ? translating
                ? <><Loader2 aria-hidden="true" className="size-4 animate-spin" />等待翻译并播放</>
                : <><Languages aria-hidden="true" className="size-4" />翻译全文并播放</>
              : <><Volume2 aria-hidden="true" className="size-4" />开始播放</>}
          </button>
        </div>
      )}
    </div>
  )
}
