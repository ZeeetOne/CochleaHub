import { useState } from 'react'
import { useComparison, useMeasurements, useSpecimens, type Metric } from '../api/client'
import { DotPlot } from '../components/charts'
import { fmt } from '../lib/format'
import { QueryState } from '../components/ui'

const METRICS: { value: Metric; label: string; perStructure: boolean }[] = [
  { value: 'cochlea_a_mm', label: 'Cochlea A (basal diameter)', perStructure: false },
  { value: 'cochlea_b_mm', label: 'Cochlea B', perStructure: false },
  { value: 'cochlea_height_mm', label: 'Cochlea height', perStructure: false },
  { value: 'volume_mm3', label: 'Volume', perStructure: true },
  { value: 'surface_area_mm2', label: 'Surface area', perStructure: true },
  { value: 'length_mm', label: 'Length', perStructure: true },
  { value: 'width_mm', label: 'Width', perStructure: true },
  { value: 'thickness_mm', label: 'Thickness', perStructure: true },
]

export function ComparePage() {
  const [metric, setMetric] = useState<Metric>('volume_mm3')
  const [structure, setStructure] = useState('Scala Tympani')
  const perStructure = METRICS.find((m) => m.value === metric)!.perStructure
  const specimens = useSpecimens()
  // structure names come from any specimen's latest measurements
  const first = specimens.data?.find((s) => s.latest_run)?.id ?? ''
  const names = useMeasurements(first)
  const comparison = useComparison(metric, perStructure ? structure : undefined)

  return (
    <div className="stack">
      <div className="page-head">
        <div>
          <h1>Compare</h1>
          <p className="lede">
            One metric across specimens, against the published range where one exists. Values come
            from each specimen's latest completed run.
          </p>
        </div>
      </div>

      <div className="row">
        <select aria-label="Metric" value={metric} onChange={(e) => setMetric(e.target.value as Metric)}>
          {METRICS.map((m) => (
            <option key={m.value} value={m.value}>
              {m.label}
            </option>
          ))}
        </select>
        {perStructure && (
          <select aria-label="Structure" value={structure} onChange={(e) => setStructure(e.target.value)}>
            {(names.data?.structures.map((s) => s.name) ?? [structure]).map((n) => (
              <option key={n}>{n}</option>
            ))}
          </select>
        )}
      </div>

      <QueryState query={comparison}>
        {(c) => {
          const ref = c.reference
          const rows = c.values.map((v) => ({
            label: v.specimen_id.toUpperCase(),
            band: ref
              ? {
                  low: ref.low,
                  high: ref.high,
                  title: (
                    <>
                      Published {ref.low}–{ref.high} {ref.unit}
                      <br />[{ref.source}] {ref.population}
                    </>
                  ),
                }
              : undefined,
            points: [
              {
                series: 'value',
                value: v.value,
                tip: (
                  <>
                    <b>{v.specimen_id.toUpperCase()}</b>: {fmt(v.value)} {c.unit}
                    {v.provenance && (
                      <>
                        <br />
                        run {v.provenance.run_id.slice(0, 8)} · v{v.provenance.pipeline_version}
                      </>
                    )}
                  </>
                ),
              },
            ],
          }))
          return (
            <div className="grid two">
              <div className="card">
                <h2>
                  {METRICS.find((m) => m.value === metric)!.label}
                  {c.structure ? ` — ${c.structure}` : ''} ({c.unit})
                </h2>
                <p className="hint">
                  {ref
                    ? `Band: published range [${ref.source}], ${ref.population}.`
                    : 'No published range is recorded for this metric; values only.'}
                </p>
                <DotPlot
                  rows={rows}
                  series={[{ key: 'value', label: 'value', color: 'var(--series-1)' }]}
                  format={(v) => fmt(v, 1)}
                  unit={c.unit}
                  labelWidth={90}
                />
              </div>
              <div className="card">
                <h2>Values</h2>
                <p className="hint">
                  {c.values.length === 1
                    ? 'One specimen is loaded; more appear here as their runs are loaded.'
                    : `${c.values.length} specimens.`}
                </p>
                <table>
                  <thead>
                    <tr>
                      <th>Specimen</th>
                      <th className="num">{c.unit}</th>
                      <th>In range</th>
                      <th>Run</th>
                    </tr>
                  </thead>
                  <tbody>
                    {c.values.map((v) => (
                      <tr key={v.specimen_id}>
                        <td>{v.specimen_id.toUpperCase()}</td>
                        <td className="num">{v.value === null ? 'not measured' : fmt(v.value)}</td>
                        <td>
                          {ref && v.value !== null ? (v.value >= ref.low && v.value <= ref.high ? 'yes' : 'no') : '—'}
                        </td>
                        <td className="mono">
                          {v.provenance ? `${v.provenance.run_id.slice(0, 8)} · v${v.provenance.pipeline_version}` : '—'}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )
        }}
      </QueryState>
    </div>
  )
}
