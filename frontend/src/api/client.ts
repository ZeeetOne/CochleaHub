// Typed access to the read-only API. Types come from the backend's OpenAPI schema
// (`npm run gen:api`), so a renamed field breaks the build instead of the page.
import { useQuery } from '@tanstack/react-query'
import type { components } from './schema'

export type Schemas = components['schemas']
export type Structure = Schemas['Structure']
export type Provenance = Schemas['Provenance']
export type QcFlag = Schemas['QcFlag']
export type ValidationRow = Schemas['ValidationRow']
export type Distance = Schemas['Distance']
export type ReferenceRange = Schemas['ReferenceRange']

const BASE = '/api/v1'

/** The API says what is missing in `detail`; pages show it verbatim instead of guessing. */
export class ApiError extends Error {
  readonly status: number
  constructor(status: number, detail: string) {
    super(detail)
    this.status = status
  }
}

async function get<T>(path: string, params?: Record<string, string | undefined>): Promise<T> {
  const query = new URLSearchParams()
  for (const [k, v] of Object.entries(params ?? {})) if (v !== undefined) query.set(k, v)
  const qs = query.toString()
  const res = await fetch(`${BASE}${path}${qs ? `?${qs}` : ''}`)
  if (!res.ok) {
    let detail = res.statusText
    try {
      const body = await res.json()
      detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail)
    } catch {
      /* non-JSON error body: keep the status text */
    }
    throw new ApiError(res.status, detail)
  }
  return res.json() as Promise<T>
}

// Results only change when a new run is loaded, so a long stale time is safe.
const STALE = 5 * 60_000

export const useHealth = () =>
  useQuery({
    queryKey: ['health'],
    queryFn: () => get<Schemas['Health']>('/health/ready'),
    refetchInterval: 30_000,
  })

export const useSpecimens = () =>
  useQuery({
    queryKey: ['specimens'],
    queryFn: () => get<Schemas['SpecimenSummary'][]>('/specimens'),
    staleTime: STALE,
  })

export const useSpecimen = (id: string) =>
  useQuery({
    queryKey: ['specimen', id],
    queryFn: () => get<Schemas['Specimen']>(`/specimens/${id}`),
    staleTime: STALE,
  })

export const useMeasurements = (id: string) =>
  useQuery({
    queryKey: ['measurements', id],
    queryFn: () => get<Schemas['Measurements']>(`/specimens/${id}/measurements`),
    staleTime: STALE,
  })

export const useCochlea = (id: string) =>
  useQuery({
    queryKey: ['cochlea', id],
    queryFn: () => get<Schemas['Cochlea']>(`/specimens/${id}/cochlea`),
    staleTime: STALE,
  })

export const useDistances = (id: string) =>
  useQuery({
    queryKey: ['distances', id],
    queryFn: () => get<Schemas['Distances']>(`/specimens/${id}/distances`),
    staleTime: STALE,
  })

// Presigned URLs expire after an hour: refresh well before that.
export const useMeshes = (id: string) =>
  useQuery({
    queryKey: ['meshes', id],
    queryFn: () => get<Schemas['Meshes']>(`/specimens/${id}/meshes`),
    staleTime: 30 * 60_000,
  })

export const useImaging = (id: string) =>
  useQuery({
    queryKey: ['imaging', id],
    queryFn: () => get<Schemas['DicomWeb']>(`/specimens/${id}/imaging`),
    staleTime: STALE,
  })

export const useRuns = (specimenId?: string) =>
  useQuery({
    queryKey: ['runs', specimenId],
    queryFn: () => get<Schemas['RunSummary'][]>('/runs', { specimen_id: specimenId }),
    staleTime: STALE,
  })

export const useQc = (runId: string | undefined) =>
  useQuery({
    queryKey: ['qc', runId],
    queryFn: () => get<Schemas['QcReport']>(`/runs/${runId}/qc`),
    enabled: !!runId,
    staleTime: STALE,
  })

export const useValidation = (runId: string | undefined) =>
  useQuery({
    queryKey: ['validation', runId],
    queryFn: () => get<Schemas['ValidationReport']>(`/runs/${runId}/validation`),
    enabled: !!runId,
    staleTime: STALE,
  })

export type Metric = Schemas['Metric']

export const useComparison = (metric: Metric, structure?: string) =>
  useQuery({
    queryKey: ['compare', metric, structure],
    queryFn: () => get<Schemas['Comparison']>('/compare', { metric, structure }),
    staleTime: STALE,
  })

// --- assistant (stage 7) ----------------------------------------------------------------------

export type AssistantBackend = 'claude' | 'local'

export const useAssistantStatus = () =>
  useQuery({
    queryKey: ['assistant-status'],
    queryFn: () => get<Schemas['AssistantStatus']>('/assistant/status'),
    refetchInterval: 60_000,
  })

export type AssistantSource = { index: number; source: string; title: string; text?: string }

/** Events of POST /assistant/chat (see backend assistant/agent.py). */
export type AssistantEvent =
  | { type: 'conversation'; id: string; backend: AssistantBackend; model: string }
  | { type: 'tool_call'; id: string; name: string; input: unknown }
  | {
      type: 'tool_result'
      id: string
      name: string
      ok: boolean
      summary: string
      error: string | null
      sources: AssistantSource[]
    }
  | { type: 'text'; text: string }
  | { type: 'answer'; blocks: { text: string; citations: number[] }[]; sources: AssistantSource[] }
  | {
      type: 'done'
      stop_reason: string
      backend: AssistantBackend
      model: string
      usage: Record<string, number>
      rounds: number
    }
  | { type: 'guard'; ungrounded: number[] }
  | { type: 'error'; message: string }

/** POST + Server-Sent Events: EventSource only does GET, so the stream is read by hand. */
export async function askAssistant(
  body: { question: string; conversation_id?: string; backend?: AssistantBackend },
  onEvent: (e: AssistantEvent) => void,
  signal?: AbortSignal,
) {
  const res = await fetch(`${BASE}/assistant/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    signal,
  })
  if (!res.ok || !res.body) {
    let detail = res.statusText
    try {
      detail = (await res.json()).detail ?? detail
    } catch {
      /* keep status text */
    }
    throw new ApiError(res.status, detail)
  }
  const reader = res.body.pipeThrough(new TextDecoderStream()).getReader()
  let buffer = ''
  for (;;) {
    const { value, done } = await reader.read()
    if (done) break
    buffer += value
    let cut
    while ((cut = buffer.indexOf('\n\n')) >= 0) {
      const frame = buffer.slice(0, cut)
      buffer = buffer.slice(cut + 2)
      for (const line of frame.split('\n'))
        if (line.startsWith('data: ')) onEvent(JSON.parse(line.slice(6)) as AssistantEvent)
    }
  }
}
