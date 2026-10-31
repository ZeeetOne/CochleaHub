import { useMutation } from '@tanstack/react-query'
import { useRef, useState } from 'react'
import Markdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import {
  askAssistant,
  useAssistantStatus,
  type AssistantBackend,
  type AssistantEvent,
  type AssistantSource,
} from '../api/client'
import { Status } from '../components/ui'

type ToolStep = { id: string; name: string; input: unknown; ok?: boolean; text?: string }
type Answer = Extract<AssistantEvent, { type: 'answer' }>
type Turn = {
  question: string
  tools: ToolStep[]
  streaming: string
  answer?: Answer
  done?: Extract<AssistantEvent, { type: 'done' }>
  error?: string
  guard?: number[]
}

const SUGGESTIONS = [
  'How close is the facial nerve to the cochlea in ZETA?',
  'Is the cochlear height of ZETA within the published range? Why or why not?',
  'Which QC warnings does the latest ZETA run have, and what do they mean?',
  'How well do our volumes agree with 3D Slicer?',
  'Which electrode should I choose for my patient?',
]

const BACKEND_LABEL: Record<AssistantBackend, string> = {
  claude: 'Claude (cloud)',
  local: 'Local model (on premises)',
}

/** Turn citations into numbered superscript links; numbers follow the order of the sources. */
function withCitations(answer: Answer, backend: AssistantBackend | undefined): string {
  const number = new Map(answer.sources.map((s, i) => [s.index, i + 1]))
  const ref = (i: number) => (number.has(i) ? ` [${number.get(i)}](#src-${number.get(i)})` : '')
  if (backend === 'local')
    return answer.blocks.map((b) => b.text.replace(/\s?\[S(\d+)\]/g, (_, n) => ref(Number(n) - 1))).join('')
  return answer.blocks.map((b) => b.text + [...new Set(b.citations)].map(ref).join('')).join('')
}

function SourceList({ sources }: { sources: AssistantSource[] }) {
  if (!sources.length) return null
  return (
    <ol className="sources">
      {sources.map((s, i) => (
        <li key={s.index} id={`src-${i + 1}`}>
          <span className="source-title">{s.title}</span>
          <div className="prov mono">{s.source.replace(/^api:/, '')}</div>
        </li>
      ))}
    </ol>
  )
}

const TOOL_LABEL: Record<string, string> = {
  list_specimens: 'List specimens',
  get_measurements: 'Measurements',
  get_cochlea_dimensions: 'Cochlear dimensions',
  get_distances: 'Critical distances',
  compare_metric: 'Compare',
  get_qc_flags: 'QC flags',
  get_validation: 'Validation',
  search_docs: 'Search documentation',
}

function TurnView({ turn, backend }: { turn: Turn; backend?: AssistantBackend }) {
  const pending = !turn.done && !turn.error
  const text = turn.answer
    ? withCitations(turn.answer, backend)
    : turn.streaming.replace(/\s?\[S\d+\]/g, '')
  return (
    <div className="turn">
      <div className="bubble user">{turn.question}</div>
      <div className="bubble bot">
        {turn.tools.length > 0 && (
          <ul className="steps" aria-label="Data looked up">
            {turn.tools.map((t) => (
              <li key={t.id}>
                <Status tone={t.ok === undefined ? 'neutral' : t.ok ? 'good' : 'warning'}>
                  {TOOL_LABEL[t.name] ?? t.name}
                </Status>{' '}
                <span className="prov">
                  {t.ok === undefined ? 'looking up…' : t.text}
                  {t.name === 'search_docs' && typeof t.input === 'object' && t.input
                    ? ` — “${(t.input as { query?: string }).query ?? ''}”`
                    : ''}
                </span>
              </li>
            ))}
          </ul>
        )}
        {text ? (
          <div className="answer">
            <Markdown
              remarkPlugins={[remarkGfm]}
              components={{
                a: ({ href, children }) =>
                  href?.startsWith('#src-') ? (
                    <sup>
                      <a href={href}>{children}</a>
                    </sup>
                  ) : (
                    <a href={href} target="_blank" rel="noreferrer">
                      {children}
                    </a>
                  ),
              }}
            >
              {text}
            </Markdown>
          </div>
        ) : (
          pending && <p className="prov">Thinking…</p>
        )}
        {turn.answer && <SourceList sources={turn.answer.sources} />}
        {turn.guard && (
          <p className="prov">
            A first draft contained numbers not found in any source ({turn.guard.join(', ')}); it
            was rewritten.
          </p>
        )}
        {turn.error && (
          <div className="notice error" role="status">
            {turn.error}
          </div>
        )}
        {turn.done && (
          <div className="prov">
            {turn.done.model} · {turn.done.rounds} round{turn.done.rounds > 1 ? 's' : ''}
            {turn.done.usage.output_tokens ? ` · ${turn.done.usage.output_tokens} output tokens` : ''}
          </div>
        )}
      </div>
    </div>
  )
}

export function AssistantPage() {
  const status = useAssistantStatus()
  const [backend, setBackend] = useState<AssistantBackend>()
  const [conversation, setConversation] = useState<{ id: string; backend: AssistantBackend }>()
  const [turns, setTurns] = useState<Turn[]>([])
  const [question, setQuestion] = useState('')
  const abort = useRef<AbortController | null>(null)

  // default backend if it is up, otherwise the first one that is
  const fallback = status.data
    ? ([status.data.default, 'claude', 'local'] as AssistantBackend[]).find(
        (b) => status.data.backends[b]?.available,
      )
    : undefined
  const chosen: AssistantBackend | undefined = conversation?.backend ?? backend ?? fallback

  const update = (fn: (t: Turn) => Turn) => setTurns((ts) => [...ts.slice(0, -1), fn(ts[ts.length - 1])])

  const ask = useMutation({
    mutationFn: async (q: string) => {
      setTurns((ts) => [...ts, { question: q, tools: [], streaming: '' }])
      abort.current = new AbortController()
      await askAssistant(
        { question: q, conversation_id: conversation?.id, backend: chosen },
        (e) => {
          if (e.type === 'conversation') setConversation({ id: e.id, backend: e.backend })
          else if (e.type === 'tool_call')
            update((t) => ({ ...t, tools: [...t.tools, { id: e.id, name: e.name, input: e.input }] }))
          else if (e.type === 'tool_result')
            update((t) => ({
              ...t,
              tools: t.tools.map((s) =>
                s.id === e.id ? { ...s, ok: e.ok, text: e.ok ? e.summary : (e.error ?? '') } : s,
              ),
            }))
          else if (e.type === 'text') update((t) => ({ ...t, streaming: t.streaming + e.text }))
          // the draft had numbers no source backs: it is discarded and rewritten
          else if (e.type === 'guard') update((t) => ({ ...t, streaming: '', guard: e.ungrounded }))
          else if (e.type === 'answer') update((t) => ({ ...t, answer: e }))
          else if (e.type === 'done') update((t) => ({ ...t, done: e }))
          else if (e.type === 'error') update((t) => ({ ...t, error: e.message }))
        },
        abort.current.signal,
      )
    },
    onError: (e) => update((t) => ({ ...t, error: e instanceof Error ? e.message : String(e) })),
  })

  const submit = (q: string) => {
    if (!q.trim() || ask.isPending) return
    setQuestion('')
    ask.mutate(q.trim())
  }

  const backends = status.data?.backends ?? {}

  return (
    <div className="stack assistant">
      <div className="page-head">
        <div>
          <h1>Assistant</h1>
          <p className="lede">
            Ask about the measurements, QC and methods. Answers come from the CochleaHub API and
            documentation, with numbered sources. It says when data are missing and does not give
            medical advice.
          </p>
        </div>
        {turns.length > 0 && (
          <button
            className="btn"
            onClick={() => {
              abort.current?.abort()
              setTurns([])
              setConversation(undefined)
            }}
          >
            New conversation
          </button>
        )}
      </div>

      <div className="card">
        <div className="row" role="radiogroup" aria-label="Model">
          {(['claude', 'local'] as const).map((name) => {
            const s = backends[name]
            return (
              <label key={name} className="check backend-option" title={s?.reason ?? s?.where}>
                <input
                  type="radio"
                  name="backend"
                  value={name}
                  checked={chosen === name}
                  disabled={!s?.available || !!conversation}
                  onChange={() => setBackend(name)}
                />
                <span>
                  <b>{BACKEND_LABEL[name]}</b>
                  <span className="prov">
                    {' '}
                    · {s ? `${s.model} · ${s.where}` : '…'}
                    {s && !s.available && ` · unavailable: ${s.reason}`}
                  </span>
                </span>
              </label>
            )
          })}
        </div>
        {conversation && (
          <p className="prov" style={{ margin: '6px 0 0' }}>
            A conversation stays on the model it started with.
          </p>
        )}
      </div>

      <div className="chat">
        {turns.length === 0 && (
          <div className="suggestions">
            {SUGGESTIONS.map((s) => (
              <button key={s} className="btn" onClick={() => submit(s)} disabled={!chosen}>
                {s}
              </button>
            ))}
          </div>
        )}
        {turns.map((t, i) => (
          <TurnView key={i} turn={t} backend={conversation?.backend ?? chosen} />
        ))}
      </div>

      <form
        className="composer"
        onSubmit={(e) => {
          e.preventDefault()
          submit(question)
        }}
      >
        <textarea
          aria-label="Question"
          rows={2}
          value={question}
          placeholder="Ask about ZETA's measurements, QC or methods…"
          onChange={(e) => setQuestion(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault()
              submit(question)
            }
          }}
        />
        <button className="btn primary" type="submit" disabled={ask.isPending || !question.trim() || !chosen}>
          {ask.isPending ? 'Answering…' : 'Ask'}
        </button>
      </form>
      <p className="prov">
        Research use only. Not a medical device; do not use for diagnosis or treatment decisions.
      </p>
    </div>
  )
}
