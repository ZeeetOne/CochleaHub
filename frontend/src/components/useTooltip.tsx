import { useState, type ReactNode } from 'react'

/** Fixed-position tooltip that follows the pointer (or the focused mark); used by the SVG charts. */
export function useTooltip() {
  const [tip, setTip] = useState<{ x: number; y: number; content: ReactNode } | null>(null)
  const show = (e: React.PointerEvent | React.FocusEvent, content: ReactNode) => {
    if ('clientX' in e) setTip({ x: e.clientX + 12, y: e.clientY + 12, content })
    else {
      const r = (e.target as Element).getBoundingClientRect()
      setTip({ x: r.right + 8, y: r.top, content })
    }
  }
  const hide = () => setTip(null)
  const node = tip && (
    <div className="tooltip" style={{ left: tip.x, top: tip.y }}>
      {tip.content}
    </div>
  )
  return { show, hide, node }
}
