import { useEffect, useState } from 'react'

const COLORS = ['#FB923C', '#F472B6', '#FACC15', '#34D399', '#60A5FA', '#A78BFA']

function makePieces(count) {
  return Array.from({ length: count }, (_, i) => ({
    id: i,
    left: Math.random() * 100, // %
    delay: Math.random() * 0.4, // s
    duration: 1.4 + Math.random() * 0.8, // s
    rotate: Math.random() * 360, // deg
    color: COLORS[i % COLORS.length],
    size: 6 + Math.random() * 5, // px
  }))
}

/**
 * Lightweight pure-CSS + DOM confetti — no canvas, no third-party library.
 *
 * Spawns N absolutely-positioned <span> "pieces" at the top of the parent,
 * each with random color / x-offset / rotation / fall delay. CSS keyframe
 * `confetti-fall` (declared in index.css) animates them down + spinning.
 * Self-unmounts after durationMs to keep DOM clean.
 *
 * Props:
 *   fire        : trigger render. Set true exactly once per celebration.
 *   pieceCount  : number of paper bits (default 40)
 *   durationMs  : how long to live (default 2200)
 *
 * Why not canvas-confetti? +5KB gzip dependency for one feature; we only need
 * a 1.5s burst. ~30 spans + 1 keyframe is plenty.
 *
 * Notes on React 19 rules:
 *  - We can't use Math.random() inside useMemo (impure-in-render). Pieces
 *    are generated inside the effect, after fire becomes true.
 *  - setActive is wrapped in Promise.resolve().then(...) so it's not a
 *    synchronous setState-in-effect (cascading render).
 */
export default function Confetti({ fire, pieceCount = 40, durationMs = 2200 }) {
  const [pieces, setPieces] = useState([])

  useEffect(() => {
    if (!fire) {
      Promise.resolve().then(() => setPieces([]))
      return
    }
    Promise.resolve().then(() => setPieces(makePieces(pieceCount)))
    const t = setTimeout(() => setPieces([]), durationMs)
    return () => clearTimeout(t)
  }, [fire, pieceCount, durationMs])

  if (pieces.length === 0) return null

  return (
    <div
      data-testid="confetti-root"
      className="pointer-events-none absolute inset-0 overflow-hidden z-10"
      aria-hidden="true"
    >
      {pieces.map(p => (
        <span
          key={p.id}
          className="absolute top-0 block rounded-sm"
          style={{
            left: `${p.left}%`,
            width: `${p.size}px`,
            height: `${p.size * 0.4}px`,
            backgroundColor: p.color,
            transform: `rotate(${p.rotate}deg)`,
            animation: `confetti-fall ${p.duration}s ${p.delay}s linear forwards`,
          }}
        />
      ))}
    </div>
  )
}
