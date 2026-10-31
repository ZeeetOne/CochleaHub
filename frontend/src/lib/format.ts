// Number formatting shared by tables, tooltips and charts.

export const fmt = (v: number | null | undefined, digits = 2) =>
  v === null || v === undefined
    ? '—'
    : v.toLocaleString('en-US', { maximumFractionDigits: digits, minimumFractionDigits: digits })

export const pct = (v: number | null | undefined, digits = 1) =>
  v === null || v === undefined ? '—' : `${v > 0 ? '+' : ''}${(v * 100).toFixed(digits)}%`

/** Segment colours are stored as 0-1 RGB floats. */
export function rgb(color: number[]) {
  const [r, g, b] = color.map((c) => Math.round(c * 255))
  return `rgb(${r}, ${g}, ${b})`
}
