import type { UseQueryResult } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { ApiError, type Provenance } from '../api/client'

type Tone = 'good' | 'warning' | 'serious' | 'critical' | 'neutral'
const ICON: Record<Tone, string> = { good: '✓', warning: '!', serious: '!', critical: '✕', neutral: 'i' }

export function Status({ tone, children }: { tone: Tone; children: ReactNode }) {
  return (
    <span className={`status ${tone}`}>
      <span className="icon" aria-hidden>
        {ICON[tone]}
      </span>
      {children}
    </span>
  )
}

const QC_TONE: Record<string, Tone> = {
  pass: 'good',
  pass_with_warnings: 'warning',
  fail: 'critical',
}
const QC_LABEL: Record<string, string> = {
  pass: 'QC pass',
  pass_with_warnings: 'QC pass with warnings',
  fail: 'QC fail',
}

export function QcStatus({ status }: { status: string | null | undefined }) {
  if (!status) return <Status tone="neutral">QC not run</Status>
  return <Status tone={QC_TONE[status] ?? 'neutral'}>{QC_LABEL[status] ?? status}</Status>
}

const SEVERITY_TONE: Record<string, Tone> = { error: 'critical', warning: 'warning', info: 'neutral' }

export function Severity({ severity }: { severity: string }) {
  return <Status tone={SEVERITY_TONE[severity] ?? 'neutral'}>{severity}</Status>
}

/** Loading / error wrapper. Errors show the API's own explanation of what is missing. */
export function QueryState<T>({
  query,
  children,
}: {
  query: UseQueryResult<T>
  children: (data: T) => ReactNode
}) {
  if (query.isPending) return <p className="prov">Loading…</p>
  if (query.isError) {
    const e = query.error
    const notFound = e instanceof ApiError && e.status === 404
    return (
      <div className={`notice ${notFound ? '' : 'error'}`} role="status">
        {notFound ? 'No data: ' : 'Could not load: '}
        {e.message}
      </div>
    )
  }
  return <>{children(query.data)}</>
}

export function ProvenanceLine({ p }: { p: Provenance }) {
  return (
    <span className="prov" title={`run ${p.run_id}`}>
      Run <span className="mono">{p.run_id.slice(0, 8)}</span> · pipeline v{p.pipeline_version} ·{' '}
      {new Date(p.started_at).toLocaleString()}
    </span>
  )
}

export function StatTile({ label, value, foot }: { label: string; value: ReactNode; foot?: ReactNode }) {
  return (
    <div className="card">
      <div className="tile-label">{label}</div>
      <div className="tile-value">{value}</div>
      {foot && <div className="tile-foot">{foot}</div>}
    </div>
  )
}
