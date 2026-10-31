// Small SVG charts: one axis, thin marks, recessive grid, hover tooltips, legend for >= 2 series.
// Every chart sits next to a table with the same numbers, so nothing is readable only by colour.
import { useEffect, useRef, useState, type ReactNode } from 'react'
import { useTooltip } from './useTooltip'

function useWidth<T extends HTMLElement>() {
  const ref = useRef<T>(null)
  const [width, setWidth] = useState(600)
  useEffect(() => {
    if (!ref.current) return
    const ro = new ResizeObserver(([e]) => setWidth(e.contentRect.width))
    ro.observe(ref.current)
    return () => ro.disconnect()
  }, [])
  return [ref, width] as const
}

function niceTicks(lo: number, hi: number, count = 5): number[] {
  const span = hi - lo || Math.abs(hi) || 1
  const raw = span / count
  const mag = 10 ** Math.floor(Math.log10(raw))
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw) ?? raw
  const ticks = []
  for (let t = Math.ceil(lo / step) * step; t <= hi + step * 1e-9; t += step) ticks.push(+t.toFixed(10))
  return ticks
}

export type Series = { key: string; label: string; color: string }
export type DotRow = {
  label: string
  band?: { low: number; high: number; title: ReactNode }
  points: { series: string; value: number | null; tip: ReactNode }[]
}

/**
 * Rows of dots on one shared linear axis, each row optionally with a shaded reference band
 * (a published range or a tolerance). Used for cochlea vs. literature, cross-specimen
 * comparison and validation differences.
 */
export function DotPlot({
  rows,
  series,
  format = (v: number) => v.toString(),
  unit,
  zeroLine = false,
  labelWidth = 150,
}: {
  rows: DotRow[]
  series: Series[]
  format?: (v: number) => string
  unit?: string
  zeroLine?: boolean
  labelWidth?: number
}) {
  const [ref, width] = useWidth<HTMLDivElement>()
  const tip = useTooltip()
  const rowH = 30
  const top = 8
  const bottom = 28
  const right = 56
  const values = rows.flatMap((r) => [
    ...r.points.map((p) => p.value).filter((v): v is number => v !== null),
    ...(r.band ? [r.band.low, r.band.high] : []),
  ])
  if (zeroLine) values.push(0)
  let lo = Math.min(...values)
  let hi = Math.max(...values)
  const pad = (hi - lo || Math.abs(hi) || 1) * 0.08
  lo -= pad
  hi += pad
  const ticks = niceTicks(lo, hi)
  lo = Math.min(lo, ticks[0])
  hi = Math.max(hi, ticks[ticks.length - 1])
  const plotW = Math.max(120, width - labelWidth - right)
  const x = (v: number) => labelWidth + ((v - lo) / (hi - lo)) * plotW
  const height = top + rows.length * rowH + bottom
  const color = Object.fromEntries(series.map((s) => [s.key, s.color]))

  return (
    <div className="chart" ref={ref}>
      {series.length > 1 && (
        <div className="legend">
          {series.map((s) => (
            <span key={s.key}>
              <span className="swatch" style={{ background: s.color, borderRadius: '50%' }} />
              {s.label}
            </span>
          ))}
        </div>
      )}
      <svg width={width} height={height} role="img" aria-label="dot plot">
        {ticks.map((t) => (
          <g key={t}>
            <line x1={x(t)} x2={x(t)} y1={top} y2={height - bottom} stroke="var(--grid)" />
            <text x={x(t)} y={height - bottom + 16} textAnchor="middle">
              {format(t)}
            </text>
          </g>
        ))}
        {unit && (
          <text x={labelWidth + plotW} y={height - 2} textAnchor="end">
            {unit}
          </text>
        )}
        {zeroLine && <line x1={x(0)} x2={x(0)} y1={top} y2={height - bottom} stroke="var(--axis)" />}
        {rows.map((r, i) => {
          const cy = top + i * rowH + rowH / 2
          return (
            <g key={r.label}>
              <text className="label" x={labelWidth - 10} y={cy + 4} textAnchor="end">
                {r.label}
              </text>
              <line x1={labelWidth} x2={labelWidth + plotW} y1={cy} y2={cy} stroke="var(--grid)" />
              {r.band && (
                <rect
                  x={x(r.band.low)}
                  width={Math.max(2, x(r.band.high) - x(r.band.low))}
                  y={cy - 9}
                  height={18}
                  rx={4}
                  fill="var(--band)"
                  onPointerMove={(e) => tip.show(e, r.band!.title)}
                  onPointerLeave={tip.hide}
                />
              )}
              {r.points.map((p) =>
                p.value === null ? (
                  <text key={p.series} x={labelWidth + 4} y={cy + 4} className="label">
                    not measured
                  </text>
                ) : (
                  <g key={p.series}>
                    {/* hit target larger than the mark */}
                    <circle
                      cx={x(p.value)}
                      cy={cy}
                      r={11}
                      fill="transparent"
                      tabIndex={0}
                      onPointerMove={(e) => tip.show(e, p.tip)}
                      onPointerLeave={tip.hide}
                      onFocus={(e) => tip.show(e, p.tip)}
                      onBlur={tip.hide}
                    />
                    <circle
                      cx={x(p.value)}
                      cy={cy}
                      r={5}
                      fill={color[p.series]}
                      stroke="var(--surface-1)"
                      strokeWidth={2}
                      pointerEvents="none"
                    />
                  </g>
                ),
              )}
            </g>
          )
        })}
      </svg>
      {tip.node}
    </div>
  )
}

/**
 * Horizontal bars on a log axis: structure volumes span four orders of magnitude
 * (stapes ~3 mm³ to bone ~35,000 mm³), which a linear axis would flatten to nothing.
 */
export function LogBars({
  rows,
  format,
  unit,
  labelWidth = 170,
}: {
  rows: { label: string; value: number; tip: ReactNode }[]
  format: (v: number) => string
  unit: string
  labelWidth?: number
}) {
  const [ref, width] = useWidth<HTMLDivElement>()
  const tip = useTooltip()
  const rowH = 24
  const bar = 14
  const top = 4
  const bottom = 28
  const right = 70
  const vmax = Math.max(...rows.map((r) => r.value))
  const vmin = Math.min(...rows.map((r) => r.value))
  const lo = 10 ** Math.floor(Math.log10(vmin))
  const hi = 10 ** Math.ceil(Math.log10(vmax))
  const plotW = Math.max(120, width - labelWidth - right)
  const x = (v: number) => labelWidth + (Math.log10(v / lo) / Math.log10(hi / lo)) * plotW
  const ticks: number[] = []
  for (let t = lo; t <= hi * 1.0001; t *= 10) ticks.push(t)
  const height = top + rows.length * rowH + bottom

  return (
    <div className="chart" ref={ref}>
      <svg width={width} height={height} role="img" aria-label="bar chart, logarithmic axis">
        {ticks.map((t) => (
          <g key={t}>
            <line x1={x(t)} x2={x(t)} y1={top} y2={height - bottom} stroke="var(--grid)" />
            <text x={x(t)} y={height - bottom + 16} textAnchor="middle">
              {t.toLocaleString('en-US')}
            </text>
          </g>
        ))}
        <text x={labelWidth + plotW} y={height - 2} textAnchor="end">
          {unit} (log scale)
        </text>
        <line x1={labelWidth} x2={labelWidth} y1={top} y2={height - bottom} stroke="var(--axis)" />
        {rows.map((r, i) => {
          const y = top + i * rowH + (rowH - bar) / 2
          const w = Math.max(2, x(r.value) - labelWidth)
          // square at the baseline, 4px round at the data end
          const d = `M${labelWidth},${y} h${w - 4} a4,4 0 0 1 4,4 v${bar - 8} a4,4 0 0 1 -4,4 h${-(w - 4)} z`
          return (
            <g
              key={r.label}
              onPointerMove={(e) => tip.show(e, r.tip)}
              onPointerLeave={tip.hide}
            >
              <rect x={0} y={top + i * rowH} width={width} height={rowH} fill="transparent" />
              <text className="label" x={labelWidth - 10} y={y + bar - 3} textAnchor="end">
                {r.label}
              </text>
              <path d={d} fill="var(--series-1)" />
              <text x={labelWidth + w + 6} y={y + bar - 3}>
                {format(r.value)}
              </text>
            </g>
          )
        })}
      </svg>
      {tip.node}
    </div>
  )
}
