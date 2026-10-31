import { useState } from 'react'
import { useHealth, useQc, useRuns, useValidation, type ValidationRow } from '../api/client'
import { DotPlot } from '../components/charts'
import { fmt, pct } from '../lib/format'
import { QcStatus, QueryState, Severity, Status } from '../components/ui'

const pm = (v: number) => `${+(v * 100).toFixed(1)}%`

const SEVERITIES = ['all', 'error', 'warning', 'info'] as const

export function OperationsPage() {
  const health = useHealth()
  const runs = useRuns()
  const [picked, setPicked] = useState<string>()
  const runId = picked ?? runs.data?.find((r) => r.status === 'completed')?.id
  const qc = useQc(runId)
  const validation = useValidation(runId)
  const [severity, setSeverity] = useState<(typeof SEVERITIES)[number]>('all')

  return (
    <div className="stack">
      <div className="page-head">
        <div>
          <h1>Operations</h1>
          <p className="lede">
            Pipeline runs, automatic quality-control flags and the validation of our measurements
            against 3D Slicer and the dataset's own meshes.
          </p>
        </div>
      </div>

      <div className="card">
        <h2>Services</h2>
        <QueryState query={health}>
          {(h) => (
            <div className="row" style={{ gap: 24, marginTop: 8 }}>
              {Object.entries(h.checks ?? {}).map(([name, v]) => (
                <span key={name} title={v}>
                  <Status tone={v === 'ok' ? 'good' : 'critical'}>{name.replace('_', ' ')}</Status>
                </span>
              ))}
              <span className="prov">API v{h.pipeline_version} · refreshed every 30 s</span>
            </div>
          )}
        </QueryState>
      </div>

      <div className="card">
        <h2>Pipeline runs</h2>
        <p className="hint">Newest first. Select a run to inspect its QC and validation.</p>
        <QueryState query={runs}>
          {(list) => (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Run</th>
                    <th>Specimen</th>
                    <th>Started</th>
                    <th>Status</th>
                    <th>Pipeline</th>
                    <th className="num">Duration s</th>
                    <th>QC</th>
                    <th className="num">Errors / warnings / info</th>
                  </tr>
                </thead>
                <tbody>
                  {list.map((r) => (
                    <tr
                      key={r.id}
                      className={`selectable ${r.id === runId ? 'selected' : ''}`}
                      onClick={() => setPicked(r.id)}
                      tabIndex={0}
                      onKeyDown={(e) => e.key === 'Enter' && setPicked(r.id)}
                      aria-selected={r.id === runId}
                    >
                      <td className="mono">{r.id.slice(0, 8)}</td>
                      <td>{r.specimen_id.toUpperCase()}</td>
                      <td>{new Date(r.started_at).toLocaleString()}</td>
                      <td>
                        <Status tone={r.status === 'completed' ? 'good' : 'critical'}>{r.status}</Status>
                      </td>
                      <td>v{r.pipeline_version}</td>
                      <td className="num">{fmt(r.duration_s, 1)}</td>
                      <td>
                        <QcStatus status={r.qc_status} />
                      </td>
                      <td className="num">
                        {r.qc_errors} / {r.qc_warnings} / {r.qc_info}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </QueryState>
      </div>

      {runId && (
        <QueryState query={qc}>
          {(report) => {
            const flags = report.flags.filter((f) => severity === 'all' || f.severity === severity)
            return (
              <div className="card">
                <div className="page-head" style={{ marginBottom: 8 }}>
                  <div>
                    <h2>QC flags</h2>
                    <p className="hint" style={{ margin: 0 }}>
                      Errors first. Source names the reference a check is based on.
                    </p>
                  </div>
                  <div className="row" role="group" aria-label="Severity filter">
                    {SEVERITIES.map((s) => (
                      <button key={s} className="btn" aria-pressed={severity === s} onClick={() => setSeverity(s)}>
                        {s}
                        {s !== 'all' && ` (${report.counts[s] ?? 0})`}
                      </button>
                    ))}
                  </div>
                </div>
                <div className="table-wrap">
                  <table>
                    <thead>
                      <tr>
                        <th>Severity</th>
                        <th>Code</th>
                        <th>Structure</th>
                        <th>Message</th>
                        <th className="num">Value</th>
                        <th className="num">Limit</th>
                        <th>Source</th>
                      </tr>
                    </thead>
                    <tbody>
                      {flags.map((f, i) => (
                        <tr key={i}>
                          <td>
                            <Severity severity={f.severity} />
                          </td>
                          <td className="mono">{f.code}</td>
                          <td>{f.structure ?? '—'}</td>
                          <td>{f.message}</td>
                          <td className="num">{fmt(f.value, 3)}</td>
                          <td className="num">{fmt(f.threshold, 3)}</td>
                          <td>{f.source ?? '—'}</td>
                        </tr>
                      ))}
                      {flags.length === 0 && (
                        <tr>
                          <td colSpan={7} className="prov">
                            No {severity === 'all' ? '' : severity} flags for this run.
                          </td>
                        </tr>
                      )}
                    </tbody>
                  </table>
                </div>
                <ValidationCharts tolerances={report.tolerances} rows={validation.data?.results ?? []} />
              </div>
            )
          }}
        </QueryState>
      )}
    </div>
  )
}

function ValidationCharts({ rows, tolerances }: { rows: ValidationRow[]; tolerances: Record<string, number> }) {
  if (rows.length === 0) return null
  const slicer = rows.filter((r) => r.reference === 'slicer')
  const meshes = rows.filter((r) => r.reference === 'dataset_mesh')
  const vt = tolerances.volume_rel_diff_vs_slicer
  const at = tolerances.surface_area_rel_diff_vs_slicer

  const relRows = (key: 'volume_rel_diff' | 'surface_area_rel_diff', tol: number, what: string) =>
    slicer.map((r) => ({
      label: r.structure,
      band: { low: -tol, high: tol, title: `QC tolerance ±${pm(tol)}` },
      points: [
        {
          series: key,
          value: r[key],
          tip: (
            <>
              <b>{r.structure}</b>: {what} {pct(r[key], 2)} vs. {r.reference_detail}
            </>
          ),
        },
      ],
    }))

  return (
    <div className="grid two" style={{ marginTop: 20 }}>
      <div>
        <h3>Volume vs. 3D Slicer</h3>
        <p className="hint">Relative difference; band = QC tolerance ±{pm(vt)}. Same voxels, so volumes should agree.</p>
        <DotPlot
          rows={relRows('volume_rel_diff', vt, 'volume')}
          series={[{ key: 'volume_rel_diff', label: 'volume', color: 'var(--series-1)' }]}
          format={(v) => pct(v, 1)}
          zeroLine
        />
      </div>
      <div>
        <h3>Surface area vs. 3D Slicer</h3>
        <p className="hint">Relative difference; band = QC tolerance ±{pm(at)}. Thin structures are smoothing-sensitive (D14). Bone and sinus dura use a coarse mesh, so no area.</p>
        <DotPlot
          rows={relRows('surface_area_rel_diff', at, 'surface area')}
          series={[{ key: 'surface_area_rel_diff', label: 'surface area', color: 'var(--series-1)' }]}
          format={(v) => pct(v, 0)}
          zeroLine
        />
      </div>
      <div style={{ gridColumn: '1 / -1' }}>
        <h3>Surface distance to the dataset's meshes</h3>
        <p className="hint">Mean and 95th percentile distance between our mesh and the published PLY, in mm. QC limit for the mean: one voxel per meshing step (bone 3, sinus dura 2, others 1).</p>
        <DotPlot
          rows={meshes.map((r) => ({
            label: r.structure,
            points: (['mean_distance_mm', 'p95_distance_mm'] as const).map((k) => ({
              series: k,
              value: r[k],
              tip: (
                <>
                  <b>{r.structure}</b>: mean {fmt(r.mean_distance_mm, 3)} · p95 {fmt(r.p95_distance_mm, 3)} · max{' '}
                  {fmt(r.max_distance_mm, 3)} mm
                </>
              ),
            })),
          }))}
          series={[
            { key: 'mean_distance_mm', label: 'mean', color: 'var(--series-1)' },
            { key: 'p95_distance_mm', label: '95th percentile', color: 'var(--series-2)' },
          ]}
          format={(v) => v.toFixed(2)}
          unit="mm"
          zeroLine
        />
      </div>
    </div>
  )
}
