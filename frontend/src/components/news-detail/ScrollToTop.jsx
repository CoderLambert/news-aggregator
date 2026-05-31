import { useRef } from 'react'
import gsap from 'gsap'
import { useGSAP } from '@gsap/react'
import { useScrollPast } from '@/hooks/useScrollPast'

gsap.registerPlugin(useGSAP)

/**
 * ScrollToTop — 小闻的尾巴，从右下角探出来。
 *
 * 设计语言和 ChatBubbleButton（小闻头像）统一：
 *  - 同色系橙色毛茸茸尾巴
 *  - 位置在 AI 助手上方，视觉上像小闻竖起尾巴
 *  - 入场：从右侧探出来 + 轻轻摇摆
 *  - 静止：微微摇尾巴
 *  - 点击：尾巴弹起 + wag 加速 → 页面滚回顶部
 */
const SCROLL_THRESHOLD = 400

export default function ScrollToTop() {
  const show = useScrollPast(SCROLL_THRESHOLD)
  const wrapRef = useRef(null)
  const idleTweenRef = useRef(null)

  useGSAP(() => {
    if (!show || !wrapRef.current) {
      if (idleTweenRef.current) {
        idleTweenRef.current.kill()
        idleTweenRef.current = null
      }
      return
    }

    // Entrance: tail peeks in from right with a cute wag
    gsap.fromTo(wrapRef.current,
      { x: 60, rotation: 0, opacity: 0 },
      {
        x: 0,
        rotation: 0,
        opacity: 1,
        duration: 0.6,
        ease: 'back.out(1.4)',
        onComplete: () => {
          // Idle: gentle tail wag
          idleTweenRef.current = gsap.to(wrapRef.current, {
            rotation: 8,
            duration: 0.8,
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
  }, { scope: wrapRef, dependencies: [show] })

  function handleClick() {
    if (!wrapRef.current) return

    if (idleTweenRef.current) {
      idleTweenRef.current.kill()
      idleTweenRef.current = null
    }

    gsap.timeline()
      .to(wrapRef.current, {
        rotation: 18,
        duration: 0.08,
        ease: 'power2.in',
      })
      .to(wrapRef.current, {
        rotation: -12,
        duration: 0.08,
        ease: 'power2.in',
      })
      .to(wrapRef.current, {
        rotation: 14,
        duration: 0.08,
        ease: 'power2.in',
      })
      .to(wrapRef.current, {
        y: -50,
        x: 20,
        rotation: -20,
        opacity: 0,
        scale: 0.7,
        duration: 0.45,
        ease: 'power3.in',
        onComplete: () => {
          window.scrollTo({ top: 0, behavior: 'smooth' })
        },
      })
  }

  if (!show) return null

  return (
    <button
      ref={wrapRef}
      type="button"
      onClick={handleClick}
      aria-label="返回顶部"
      className="fixed bottom-[7.5rem] right-8 z-50
                 w-12 h-12 rounded-full
                 flex items-center justify-center
                 cursor-pointer select-none
                 opacity-0
                 active:scale-90 transition-none"
      style={{ transformOrigin: '70% 90%' }}
    >
      {/* 小闻的尾巴 — 和吉祥物同色系的橙色毛茸尾巴 */}
      <svg
        width="48"
        height="48"
        viewBox="0 0 48 48"
        fill="none"
      >
        <defs>
          <radialGradient id="tail-grad" cx="35%" cy="30%" r="70%">
            <stop offset="0%" stopColor="#FDBA74" />
            <stop offset="55%" stopColor="#FB923C" />
            <stop offset="100%" stopColor="#EA580C" />
          </radialGradient>
        </defs>
        {/* Tail shape — curvy fox tail curling up */}
        <path
          d="M10 38 Q8 28 14 20 Q20 12 24 14 Q22 20 26 18 Q30 16 28 22 Q26 28 30 26 Q34 24 32 30 Q30 36 24 40 Q18 44 10 38Z"
          fill="url(#tail-grad)"
        />
        {/* Tail tip — white/cream like fox tail tip */}
        <path
          d="M20 16 Q22 12 24 14 Q22 18 26 18 Q24 20 22 19 Q20 18 20 16Z"
          fill="#FEF3C7"
          opacity="0.9"
        />
        {/* Tiny paw pad hint at base */}
        <ellipse cx="14" cy="38" rx="3" ry="2" fill="#F87171" opacity="0.3" />
      </svg>
    </button>
  )
}
