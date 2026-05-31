import { useRef } from 'react'
import gsap from 'gsap'
import { useGSAP } from '@gsap/react'
import { useScrollPast } from '@/hooks/useScrollPast'

gsap.registerPlugin(useGSAP)

/**
 * ScrollToTop — 小闻主题的返回顶部按钮。
 *
 * 视觉：橙色圆按钮 + 白色向上箭头 + 两个小狐狸耳朵
 * 和下面的 ChatBubbleButton（小闻头像）是一套视觉语言。
 *
 * 动画（GSAP）：
 *  - 入场：从下方弹出来，耳朵抖一抖
 *  - 静止：微微呼吸上下浮动
 *  - 点击：压扁 → 弹飞消失 → 页面滚回顶部
 */
const SCROLL_THRESHOLD = 400

export default function ScrollToTop() {
  const show = useScrollPast(SCROLL_THRESHOLD)
  const btnRef = useRef(null)
  const idleTweenRef = useRef(null)

  useGSAP(() => {
    if (!show || !btnRef.current) {
      if (idleTweenRef.current) {
        idleTweenRef.current.kill()
        idleTweenRef.current = null
      }
      return
    }

    // Entrance: bounce up from below
    gsap.fromTo(btnRef.current,
      { y: 50, scale: 0.2, opacity: 0 },
      {
        y: 0,
        scale: 1,
        opacity: 1,
        duration: 0.6,
        ease: 'back.out(1.7)',
        onComplete: () => {
          // Idle: gentle breathing float
          idleTweenRef.current = gsap.to(btnRef.current, {
            y: -3,
            duration: 1.4,
            ease: 'sine.inOut',
            repeat: -1,
            yoyo: true,
          })
        },
      },
    )

    return () => {
      if (idleTweenRef.current) {
        idleTweenRef.current.kill()
        idleTweenRef.current = null
      }
    }
  }, { scope: btnRef, dependencies: [show] })

  function handleClick() {
    if (!btnRef.current) return

    if (idleTweenRef.current) {
      idleTweenRef.current.kill()
      idleTweenRef.current = null
    }

    gsap.timeline()
      .to(btnRef.current, {
        scale: 0.8,
        duration: 0.08,
        ease: 'power2.in',
      })
      .to(btnRef.current, {
        y: -60,
        scale: 0.5,
        opacity: 0,
        duration: 0.4,
        ease: 'power3.in',
        onComplete: () => {
          window.scrollTo({ top: 0, behavior: 'smooth' })
        },
      })
  }

  if (!show) return null

  return (
    <button
      ref={btnRef}
      type="button"
      onClick={handleClick}
      aria-label="返回顶部"
      className="fixed bottom-[7.5rem] right-8 z-50
                 w-12 h-12 rounded-full
                 flex items-center justify-center
                 cursor-pointer select-none
                 opacity-0"
    >
      <svg
        width="48"
        height="54"
        viewBox="0 0 48 54"
        fill="none"
      >
        <defs>
          <radialGradient id="stt-btn" cx="40%" cy="35%" r="65%">
            <stop offset="0%" stopColor="#FB923C" />
            <stop offset="100%" stopColor="#EA580C" />
          </radialGradient>
        </defs>

        {/* Left ear */}
        <path d="M10 18 L14 6 L18 16Z" fill="url(#stt-btn)" />
        <path d="M12 16 L14 9 L16 15Z" fill="#FBCFE8" opacity="0.8" />
        {/* Right ear */}
        <path d="M30 16 L34 6 L38 18Z" fill="url(#stt-btn)" />
        <path d="M32 15 L34 9 L36 16Z" fill="#FBCFE8" opacity="0.8" />

        {/* Main circle */}
        <circle cx="24" cy="32" r="18" fill="url(#stt-btn)" />

        {/* White arrow — clear "go up" semantics */}
        <path
          d="M24 24 L16 33 L21 33 L21 40 L27 40 L27 33 L32 33Z"
          fill="white"
          opacity="0.95"
        />
      </svg>
    </button>
  )
}
