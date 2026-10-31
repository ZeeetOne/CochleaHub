import { Link } from 'react-router-dom'
import { useHealth, useSpecimens } from '../api/client'
import { QcStatus, QueryState, StatTile, Status } from '../components/ui'

export function Overview() {
  const specimens = useSpecimens()
  const health = useHealth()

  return (
    <div className="stack">
      <div className="page-head">
        <div>
          <h1>Overview</h1>
          <p className="lede">
            Temporal-bone measurements from segmented CT, validated against 3D Slicer and the
            dataset's published meshes. Every number is tied to the pipeline run that produced it.
            Research use only — not a clinical tool.
          </p>
        </div>
      </div>

      <QueryState query={specimens}>
        {(list) => {
          const runs = list.flatMap((s) => (s.latest_run ? [s.latest_run] : []))
          const warnings = runs.reduce((n, r) => n + r.qc_warnings, 0)
          const errors = runs.reduce((n, r) => n + r.qc_errors, 0)
          return (
            <>
              <div className="grid tiles">
                <StatTile label="Specimens" value={list.length} foot={`${runs.length} with a completed run`} />
                <StatTile
                  label="QC errors"
                  value={errors}
                  foot={errors ? <Status tone="critical">needs review</Status> : 'none in latest runs'}
                />
                <StatTile label="QC warnings" value={warnings} foot="see Operations for details" />
                <StatTile
                  label="Services"
                  value={
                    health.data ? (
                      health.data.status === 'ok' ? (
                        <Status tone="good">all up</Status>
                      ) : (
                        <Status tone="serious">degraded</Status>
                      )
                    ) : (
                      '…'
                    )
                  }
                  foot="database · object store · DICOM archive"
                />
              </div>

              <div className="card">
                <h2>Specimens</h2>
                <p className="hint">Latest completed pipeline run per specimen.</p>
                <div className="table-wrap">
                  <table>
                    <thead>
                      <tr>
                        <th>Specimen</th>
                        <th>Dataset</th>
                        <th>Side</th>
                        <th>Latest run</th>
                        <th>Pipeline</th>
                        <th>QC</th>
                      </tr>
                    </thead>
                    <tbody>
                      {list.map((s) => (
                        <tr key={s.id}>
                          <td>
                            <Link to={`/specimens/${s.id}`}>{s.id.toUpperCase()}</Link>
                            <div className="prov">{s.description}</div>
                          </td>
                          <td>{s.dataset}</td>
                          <td>{s.side ?? '—'}</td>
                          <td>
                            {s.latest_run ? new Date(s.latest_run.started_at).toLocaleString() : 'no completed run'}
                          </td>
                          <td>{s.latest_run ? `v${s.latest_run.pipeline_version}` : '—'}</td>
                          <td>
                            <QcStatus status={s.latest_run?.qc_status} />
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            </>
          )
        }}
      </QueryState>
    </div>
  )
}
