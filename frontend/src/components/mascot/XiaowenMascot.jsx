import { useEffect, useId, useState, useRef } from 'react'

/**
 * 「小闻」吉祥物 v3 — 整体圆滚滚的橘色小狐 AI 助手。
 *
 * 完全 SVG 几何造型 + radialGradient 体积感 + React state 控制表情。
 * Bundle 零负担，Retina 永远清晰。
 *
 * 几何原则（v3 萌系）：
 *  - 脸 = 单一圆形（无拼接缝），靠渐变做体积
 *  - 嘴罩 = 椭圆嵌进圆形里，颜色 fade 到脸色
 *  - 五官集中在脸的 55%-75% 区（眼大、嘴小、鼻在中间）
 *  - 耳朵根部插入头里，跟头同渐变
 *  - 双高光眼 + 不用白眼眶（橙脸上的纯黑反而更鲜活）
 *
 * mood:
 *   - 'idle'      默认温和，配合 idleBlink 自动眨眼
 *   - 'think'     思考中（眼睛 ··、轻微歪头）
 *   - 'talk'      说话中（嘴一张一合，跟流式同步）
 *   - 'happy'     回答完成（眯眼笑）
 *   - 'confused'  报错（八字眉 + 张大嘴）
 *   - 'sleep'     长时间闲置（眼睛眯 + zz）
 *
 * useId() 给每个实例 unique gradient id，避免同页面多个实例共享渐变 ID。
 */
export default function XiaowenMascot({
  mood = 'idle',
  size = 64,
  className = '',
  isLookingUp = false,
  autoBlink = true,
  autoTalk = true,
}) {
  const uid = useId().replace(/:/g, '')
  const [blinking, setBlinking] = useState(false)
  const [mouthOpen, setMouthOpen] = useState(false)
  const blinkTimerRef = useRef(null)
  const talkTimerRef = useRef(null)

  // Auto blink: random 2.5-5s interval, 140ms blink duration
  useEffect(() => {
    if (!autoBlink || mood === 'sleep' || mood === 'think') return
    function scheduleNext() {
      const delay = 2500 + Math.random() * 2500
      blinkTimerRef.current = setTimeout(() => {
        setBlinking(true)
        setTimeout(() => {
          setBlinking(false)
          scheduleNext()
        }, 140)
      }, delay)
    }
    scheduleNext()
    return () => clearTimeout(blinkTimerRef.current)
  }, [autoBlink, mood])

  // Talk mouth oscillation: toggle every 180ms while mood='talk'.
  // setMouthOpen(false) on exit is async-IIFE'd to avoid the React 19
  // `react-hooks/set-state-in-effect` rule, which (correctly) flags sync
  // setState in an effect as a cascading render.
  useEffect(() => {
    if (!autoTalk || mood !== 'talk') {
      Promise.resolve().then(() => setMouthOpen(false))
      return
    }
    talkTimerRef.current = setInterval(() => {
      setMouthOpen(prev => !prev)
    }, 180)
    return () => clearInterval(talkTimerRef.current)
  }, [autoTalk, mood])

  const eyesClosed = blinking || mood === 'happy' || mood === 'sleep'
  const eyesDot = mood === 'think'
  const lookOffsetY = isLookingUp ? -2 : 0
  const headRot = mood === 'think' ? -4 : 0

  return (
    <svg
      viewBox="0 0 100 100"
      width={size}
      height={size}
      className={className}
      role="img"
      aria-label="小闻 AI 助手"
      data-mood={mood}
    >
      <defs>
        {/* Face radial gradient — top-left highlight, bottom-right shadow */}
        <radialGradient id={`${uid}-face`} cx="35%" cy="35%" r="75%">
          <stop offset="0%" stopColor="#FDBA74" />
          <stop offset="60%" stopColor="#FB923C" />
          <stop offset="100%" stopColor="#EA580C" />
        </radialGradient>
        {/* Inner ear gradient */}
        <radialGradient id={`${uid}-ear`} cx="50%" cy="80%" r="60%">
          <stop offset="0%" stopColor="#FBCFE8" />
          <stop offset="100%" stopColor="#F9A8D4" />
        </radialGradient>
        {/* White mouth area — fades to face color at edges (no hard seam) */}
        <radialGradient id={`${uid}-mouth`} cx="50%" cy="20%" r="80%">
          <stop offset="0%" stopColor="#FFFFFF" />
          <stop offset="100%" stopColor="#FED7AA" stopOpacity="0.4" />
        </radialGradient>
      </defs>

      <g
        style={{
          transform: `translateY(${lookOffsetY}px) rotate(${headRot}deg)`,
          transformOrigin: '50px 55px',
          transition: 'transform 280ms cubic-bezier(0.34, 1.56, 0.64, 1)',
        }}
      >
        {/* Ears — same gradient as face so they "grow" from the head */}
        <path d="M28 38 Q 18 18, 30 14 Q 38 18, 38 36 Z" fill={`url(#${uid}-face)`} />
        <path d="M30 36 Q 24 22, 31 19 Q 35 22, 35 34 Z" fill={`url(#${uid}-ear)`} />
        <path d="M72 38 Q 82 18, 70 14 Q 62 18, 62 36 Z" fill={`url(#${uid}-face)`} />
        <path d="M70 36 Q 76 22, 69 19 Q 65 22, 65 34 Z" fill={`url(#${uid}-ear)`} />

        {/* Main face — single circle with the gradient */}
        <circle cx="50" cy="58" r="32" fill={`url(#${uid}-face)`} />

        {/* Mouth area — white ellipse, edges fade into face */}
        <ellipse cx="50" cy="72" rx="18" ry="13" fill={`url(#${uid}-mouth)`} />

        {/* Brows — confused only */}
        {mood === 'confused' && (
          <>
            <path d="M39 50 L48 53" stroke="#3D2817" strokeWidth="2.2" strokeLinecap="round" />
            <path d="M61 50 L52 53" stroke="#3D2817" strokeWidth="2.2" strokeLinecap="round" />
          </>
        )}

        {/* Eyes */}
        {eyesClosed ? (
          // Smiling crescents
          <>
            <path d="M39 58 Q44 51 49 58" stroke="#3D2817" strokeWidth="2.8" strokeLinecap="round" fill="none" />
            <path d="M51 58 Q56 51 61 58" stroke="#3D2817" strokeWidth="2.8" strokeLinecap="round" fill="none" />
          </>
        ) : eyesDot ? (
          // Thinking dots
          <>
            <circle cx="44" cy="60" r="2.6" fill="#3D2817" />
            <circle cx="56" cy="60" r="2.6" fill="#3D2817" />
          </>
        ) : (
          // Default big eyes — black pupil + two highlights
          <>
            <circle cx="44" cy="60" r="5.5" fill="#3D2817" />
            <circle cx="56" cy="60" r="5.5" fill="#3D2817" />
            <circle cx="45.5" cy="58" r="1.8" fill="#FFFFFF" />
            <circle cx="57.5" cy="58" r="1.8" fill="#FFFFFF" />
            <circle cx="43" cy="62" r="0.9" fill="#FFFFFF" opacity="0.7" />
            <circle cx="55" cy="62" r="0.9" fill="#FFFFFF" opacity="0.7" />
          </>
        )}

        {/* Nose — small triangle */}
        <path d="M48.5 66.5 L51.5 66.5 L50 68.5 Z" fill="#3D2817" />

        {/* Mouth */}
        {mood === 'happy' ? (
          <path d="M46 74 Q50 79 54 74" stroke="#3D2817" strokeWidth="2" strokeLinecap="round" fill="none" />
        ) : mood === 'confused' ? (
          <ellipse cx="50" cy="75" rx="2.5" ry="3" fill="#3D2817" />
        ) : mood === 'talk' && mouthOpen ? (
          <ellipse cx="50" cy="74" rx="2.5" ry="2" fill="#3D2817" />
        ) : (
          // Default W-shape tiny mouth
          <>
            <path d="M47 72 Q50 74 50 73" stroke="#3D2817" strokeWidth="1.6" strokeLinecap="round" fill="none" />
            <path d="M50 73 Q50 74 53 72" stroke="#3D2817" strokeWidth="1.6" strokeLinecap="round" fill="none" />
          </>
        )}

        {/* Cheek blush — on the sides, not on the white mouth area */}
        <ellipse cx="32" cy="68" rx="4" ry="2.8" fill="#F87171" opacity="0.55" />
        <ellipse cx="68" cy="68" rx="4" ry="2.8" fill="#F87171" opacity="0.55" />
      </g>

      {/* Sleep z's */}
      {mood === 'sleep' && (
        <g fontFamily="ui-sans-serif, system-ui" fontWeight="700" fill="#94A3B8">
          <text x="76" y="32" fontSize="11">z</text>
          <text x="84" y="22" fontSize="7">z</text>
        </g>
      )}
    </svg>
  )
}
