import XiaowenMascot from './XiaowenMascot'

/**
 * Mascot preview gallery — visual QA for all moods/sizes.
 * Mounted at /__mascot__ for design review; NOT linked from prod nav.
 *
 * Hardcoded JSX (no .map) to avoid a rolldown-vite bundling quirk that
 * mangles array literals in lazy chunks under PRoot.
 */
export default function MascotPreview() {
  return (
    <div className="min-h-screen bg-neutral-50 p-8">
      <div className="mx-auto max-w-3xl">
        <h1 className="text-2xl font-semibold text-neutral-900 mb-2">小闻 · 吉祥物预览</h1>
        <p className="text-sm text-neutral-500 mb-8">
          AI 新闻助手的吉祥物造型。下方 6 种表情会自动播放（眨眼/说话）。
        </p>

        <div className="grid grid-cols-2 sm:grid-cols-3 gap-4">
          <MoodCard mood="idle" label="默认（默默眨眼）" />
          <MoodCard mood="think" label="思考中（眼睛 ··、歪头）" />
          <MoodCard mood="talk" label="说话中（嘴巴一开一合）" />
          <MoodCard mood="happy" label="开心（眯眼笑）" />
          <MoodCard mood="confused" label="困惑（八字眉张嘴）" />
          <MoodCard mood="sleep" label="睡觉（z）" />
        </div>

        <div className="mt-10 bg-white rounded-2xl border border-neutral-200 p-6">
          <p className="text-sm font-medium text-neutral-900 mb-4">尺寸预览</p>
          <div className="flex items-end gap-6 flex-wrap">
            <SizeCol size={32} />
            <SizeCol size={48} />
            <SizeCol size={64} />
            <SizeCol size={96} />
            <SizeCol size={128} />
          </div>
        </div>

        <div className="mt-10 bg-white rounded-2xl border border-neutral-200 p-6">
          <p className="text-sm font-medium text-neutral-900 mb-4">Hover 抬头</p>
          <div className="flex items-center gap-6">
            <div className="flex flex-col items-center">
              <XiaowenMascot size={96} isLookingUp={false} />
              <p className="mt-2 text-xs text-neutral-500">默认</p>
            </div>
            <div className="flex flex-col items-center">
              <XiaowenMascot size={96} isLookingUp={true} />
              <p className="mt-2 text-xs text-neutral-500">抬头看你</p>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

function MoodCard({ mood, label }) {
  return (
    <div className="bg-white rounded-2xl border border-neutral-200 p-5 flex flex-col items-center shadow-sm">
      <XiaowenMascot mood={mood} size={120} />
      <p className="mt-3 text-sm font-medium text-neutral-900">{mood}</p>
      <p className="mt-1 text-xs text-neutral-500 text-center">{label}</p>
    </div>
  )
}

function SizeCol({ size }) {
  return (
    <div className="flex flex-col items-center">
      <XiaowenMascot size={size} />
      <p className="mt-2 text-xs text-neutral-500">{size}px</p>
    </div>
  )
}
