import { Minimize2, Maximize2, Trash2, X } from 'lucide-react'
import { Button } from '../ui/button'
import XiaowenMascot from '../mascot/XiaowenMascot'

/**
 * Chat panel header — small Xiaowen avatar + name + subtitle
 * + fullscreen / clear / close buttons.
 *
 * mood: forwarded from the chat phase so the avatar reacts in real time.
 *   - 'thinking'  → mascot.think
 *   - 'streaming' → mascot.talk
 *   - 'success'   → mascot.happy
 *   - 'error'     → mascot.confused
 *   - 'idle'      → mascot.idle
 */
export default function ChatHeader({
  mood = 'idle',
  isFullscreen,
  onToggleFullscreen,
  onClear,
  onClose,
}) {
  return (
    <div className="flex items-center justify-between px-4 py-3 border-b border-neutral-100 bg-white/80 backdrop-blur-md">
      <div className="flex items-center gap-3 min-w-0">
        <div className="flex-shrink-0 w-11 h-11 rounded-full bg-orange-50 ring-1 ring-orange-100 flex items-center justify-center">
          <XiaowenMascot mood={mood} size={38} />
        </div>
        <div className="min-w-0">
          <h3 className="text-sm font-semibold text-neutral-900 leading-tight">小闻</h3>
          <p className="text-xs text-neutral-500 truncate">{subtitleFor(mood)}</p>
        </div>
      </div>

      <div className="flex items-center gap-1 flex-shrink-0">
        <Button
          type="button"
          variant="ghost"
          size="icon"
          onClick={onToggleFullscreen}
          aria-label={isFullscreen ? '退出全屏' : '全屏观看'}
          title={isFullscreen ? '退出全屏' : '全屏观看'}
          className="text-neutral-400 hover:text-orange-500 h-8 w-8 rounded-full"
        >
          {isFullscreen ? <Minimize2 className="h-4 w-4" /> : <Maximize2 className="h-4 w-4" />}
        </Button>
        <Button
          type="button"
          variant="ghost"
          size="icon"
          onClick={onClear}
          aria-label="清空对话"
          title="清空对话"
          className="text-neutral-400 hover:text-rose-500 h-8 w-8 rounded-full"
        >
          <Trash2 className="h-4 w-4" />
        </Button>
        <Button
          type="button"
          variant="ghost"
          size="icon"
          onClick={onClose}
          aria-label="关闭对话窗口"
          title="关闭"
          className="text-neutral-500 hover:text-neutral-900 h-8 w-8 rounded-full"
        >
          <X className="h-5 w-5" />
        </Button>
      </div>
    </div>
  )
}

function subtitleFor(mood) {
  switch (mood) {
    case 'think':    return '让我想想…'
    case 'talk':     return '正在回答你～'
    case 'happy':    return '希望对你有帮助 🎉'
    case 'confused': return '咦，好像出了点问题'
    case 'sleep':    return '在打盹儿…'
    default:         return '读完文章再来聊'
  }
}
