import { lazy, Suspense, useMemo, useState } from 'react'
import { useParams, useSearchParams } from 'react-router-dom'
import {
  useCochlea,
  useDistances,
  useImaging,
  useMeasurements,
  useMeshes,
  useSpecimen,
  type Distance,
  type Structure,
} from '../api/client'
import { DotPlot, LogBars } from '../components/charts'
import { MeshViewer } from '../components/MeshViewer'
import { fmt } from '../lib/format'
import { ProvenanceLine, QcStatus, QueryState } from '../components/ui'

// Cornerstone is large; load it only when the CT section is opened.
const CtViewer = lazy(() => import('../components/CtViewer').then((m) => ({ default: m.CtViewer })))

export function SpecimenPage() {
  const { id = '' } = useParams()
  const specimen = useSpecimen(id)
  const measurements = useMeasurements(id)
  const meshes = useMeshes(id)
  const distances = useDistances(id)
  const [selected, setSelected] = useState<Distance | null>(null)

  const center = useMemo<[number, number, number]>(() => {
    const st = measurements.data?.structures.find((s) => s.name === 'Scala Tympani')
    return (st?.centroid_lps_mm as [number, number, number]) ?? [0, 0, 0]
  }, [measurements.data])

  return (
    <div className="stack">
      <QueryState query={specimen}>
        {(s) => (
          <div className="page-head">
            <div>
              <h1>
                Specimen {s.id.toUpperCase()} <span className="prov">· {s.dataset} · {s.side} ear</span>
              </h1>
              <p className="lede">{s.description}</p>
            </div>
            <div className="row">
              <QcStatus status={s.latest_run?.qc_status} />
              {measurements.data && <ProvenanceLine p={measurements.data.provenance} />}
            </div>
          </div>
        )}
      </QueryState>

      <div className="card">
        <h2>3D anatomy</h2>
        <p className="hint">
          Meshes from the segmentation (marching cubes + Taubin smoothing). Select a distance below
          to draw it.
        </p>
        <QueryState query={meshes}>
          {(m) => <MeshViewer meshes={m.meshes} center={center} distance={selected} />}
        </QueryState>
      </div>

      <div className="grid two">
        <div className="card">
          <h2>Critical distances</h2>
          <p className="hint">Minimum surface-to-surface distance. Click a row to show it in 3D.</p>
          <QueryState query={distances}>
            {(d) => (
              <table>
                <thead>
                  <tr>
                    <th>From → to</th>
                    <th className="num">mm</th>
                    <th>Meaning</th>
                  </tr>
                </thead>
                <tbody>
                  {d.distances.map((row) => {
                    const key = `${row.from_structure}-${row.to_structure}`
                    const isSel = selected?.from_structure === row.from_structure && selected?.to_structure === row.to_structure
                    return (
                      <tr
                        key={key}
                        className={`selectable ${isSel ? 'selected' : ''}`}
                        onClick={() => setSelected(isSel ? null : row)}
                        tabIndex={0}
                        onKeyDown={(e) => e.key === 'Enter' && setSelected(isSel ? null : row)}
                        aria-selected={isSel}
                      >
                        <td>
                          {row.from_structure} → {row.to_structure}
                        </td>
                        <td className="num">{fmt(row.distance_mm)}</td>
                        <td className="prov">{row.meaning}</td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            )}
          </QueryState>
        </div>
        <CochleaCard id={id} />
      </div>

      <CtSection id={id} />

      <QueryState query={measurements}>{(m) => <MeasurementsCard structures={m.structures} />}</QueryState>
    </div>
  )
}

function CochleaCard({ id }: { id: string }) {
  const cochlea = useCochlea(id)
  return (
    <div className="card">
      <h2>Cochlear size vs. published range</h2>
      <QueryState query={cochlea}>
        {(c) => {
          const rows = (
            [
              ['A (basal diameter)', c.a],
              ['B (perpendicular)', c.b],
              ['Height', c.height],
            ] as const
          ).map(([label, v]) => ({
            label,
            band: v.reference
              ? {
                  low: v.reference.low,
                  high: v.reference.high,
                  title: (
                    <>
                      Published range {v.reference.low}–{v.reference.high} {v.reference.unit}
                      <br />[{v.reference.source}] {v.reference.population}
                    </>
                  ),
                }
              : undefined,
            points: [
              {
                series: 'zeta',
                value: v.value_mm,
                tip: (
                  <>
                    <b>{label}</b>: {fmt(v.value_mm)} mm
                    <br />
                    {v.in_range === false ? 'outside' : v.in_range ? 'inside' : 'no'} published range
                  </>
                ),
              },
            ],
          }))
          const outside = rows.filter((_, i) => [c.a, c.b, c.height][i].in_range === false)
          return (
            <>
              <p className="hint">
                Dot: this specimen. Band: published range. Method: {c.method}.
              </p>
              <DotPlot
                rows={rows}
                series={[{ key: 'zeta', label: id.toUpperCase(), color: 'var(--series-1)' }]}
                format={(v) => v.toFixed(0)}
                unit="mm"
                labelWidth={140}
              />
              {outside.length > 0 && (
                <p className="prov">
                  Outside range: {outside.map((r) => r.label).join(', ')}. A warning, not an error: the
                  reference covers one population and imaging method (QC rule D14).
                </p>
              )}
            </>
          )
        }}
      </QueryState>
    </div>
  )
}

function CtSection({ id }: { id: string }) {
  const imaging = useImaging(id)
  // ?ct=<series label> opens the viewer on that series, so a view can be linked
  const [params, setParams] = useSearchParams()
  const [picked, setPicked] = useState<string>()
  const label = params.get('ct') || picked
  const open = params.has('ct')
  const setLabel = (l: string) => setParams({ ct: l }, { replace: true })
  const setOpen = (next: boolean) =>
    setParams(next ? { ct: label ?? imaging.data?.series[0]?.label ?? '' } : {}, { replace: true })
  return (
    <div className="card">
      <div className="page-head" style={{ marginBottom: 8 }}>
        <div>
          <h2>CT slices (DICOMweb)</h2>
          <p className="hint" style={{ margin: 0 }}>
            CBCT streamed from the DICOM archive; axial, coronal and sagittal views of one volume.
          </p>
        </div>
        <QueryState query={imaging}>
          {(img) => (
            <div className="row">
              <select
                aria-label="Series"
                value={label ?? img.series[0]?.label}
                onChange={(e) => (open ? setLabel(e.target.value) : setPicked(e.target.value))}
              >
                {img.series.map((s) => (
                  <option key={s.label} value={s.label}>
                    {s.label.replaceAll('_', ' ')} ({s.n_instances} slices)
                  </option>
                ))}
              </select>
              <button className="btn" aria-pressed={open} onClick={() => setOpen(!open)}>
                {open ? 'Close viewer' : 'Load CT'}
              </button>
            </div>
          )}
        </QueryState>
      </div>
      {open && imaging.data && (
        <Suspense fallback={<p className="prov">Loading viewer…</p>}>
          {(() => {
            const series = imaging.data.series.find((s) => s.label === (label ?? imaging.data.series[0]?.label))
            return series ? (
              <CtViewer key={series.series_instance_uid} root={imaging.data.dicomweb_root} series={series} />
            ) : (
              <div className="notice">No CT series archived for this specimen.</div>
            )
          })()}
        </Suspense>
      )}
    </div>
  )
}

type SortKey = 'name' | 'volume_mm3' | 'surface_area_mm2' | 'length_mm' | 'width_mm' | 'thickness_mm' | 'connected_components'

function MeasurementsCard({ structures }: { structures: Structure[] }) {
  const [sort, setSort] = useState<{ key: SortKey; desc: boolean }>({ key: 'volume_mm3', desc: true })
  const sorted = [...structures].sort((a, b) => {
    const va = a[sort.key] ?? -Infinity
    const vb = b[sort.key] ?? -Infinity
    const c = va < vb ? -1 : va > vb ? 1 : 0
    return sort.desc ? -c : c
  })
  const col = (key: SortKey, label: string, num = true) => (
    <th
      className={num ? 'num' : ''}
      aria-sort={sort.key === key ? (sort.desc ? 'descending' : 'ascending') : 'none'}
    >
      <button onClick={() => setSort((s) => ({ key, desc: s.key === key ? !s.desc : num }))}>
        {label}
        {sort.key === key ? (sort.desc ? ' ↓' : ' ↑') : ''}
      </button>
    </th>
  )
  const byVolume = [...structures].sort((a, b) => b.volume_mm3 - a.volume_mm3)

  return (
    <div className="card">
      <h2>Structure measurements</h2>
      <p className="hint">Voxel volume, smoothed-mesh surface area and oriented-bounding-box dimensions. Area is not computed for structures meshed on a coarse grid (bone, sinus dura).</p>
      <LogBars
        unit="mm³"
        format={(v) => fmt(v, v < 100 ? 1 : 0)}
        rows={byVolume.map((s) => ({
          label: s.name,
          value: s.volume_mm3,
          tip: (
            <>
              <b>{s.name}</b>
              <br />
              {fmt(s.volume_mm3)} mm³ · {s.voxel_count.toLocaleString()} voxels
            </>
          ),
        }))}
      />
      <div className="table-wrap" style={{ marginTop: 16 }}>
        <table>
          <thead>
            <tr>
              {col('name', 'Structure', false)}
              {col('volume_mm3', 'Volume mm³')}
              {col('surface_area_mm2', 'Area mm²')}
              {col('length_mm', 'Length mm')}
              {col('width_mm', 'Width mm')}
              {col('thickness_mm', 'Thickness mm')}
              {col('connected_components', 'Components')}
            </tr>
          </thead>
          <tbody>
            {sorted.map((s) => (
              <tr key={s.name}>
                <td>{s.name}</td>
                <td className="num">{fmt(s.volume_mm3)}</td>
                <td className="num">{fmt(s.surface_area_mm2)}</td>
                <td className="num">{fmt(s.length_mm)}</td>
                <td className="num">{fmt(s.width_mm)}</td>
                <td className="num">{fmt(s.thickness_mm)}</td>
                <td className="num" title={`largest component holds ${(s.largest_component_fraction * 100).toFixed(2)}%`}>
                  {s.connected_components}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
