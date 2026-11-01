import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useRef, useState } from 'react'
import {
  deleteDocument,
  documentDownloadUrl,
  uploadDocument,
  useDocuments,
  type LibraryDocument,
} from '../api/client'
import { QueryState, Status } from '../components/ui'

const ACCEPT = '.pdf,.docx,.txt,.md'
const MAX_MB = 20

const STATUS_TONE = {
  queued: 'neutral',
  processing: 'neutral',
  indexed: 'good',
  failed: 'critical',
} as const

function size(bytes: number | null) {
  if (bytes === null) return '—'
  return bytes < 1024 * 1024 ? `${(bytes / 1024).toFixed(0)} KB` : `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

function UploadForm() {
  const queryClient = useQueryClient()
  const input = useRef<HTMLInputElement>(null)
  const [file, setFile] = useState<File | null>(null)
  const [title, setTitle] = useState('')
  const [attested, setAttested] = useState(false)

  const upload = useMutation({
    mutationFn: () => uploadDocument(file!, attested, title.trim() || undefined),
    onSuccess: () => {
      setFile(null)
      setTitle('')
      setAttested(false)
      if (input.current) input.current.value = ''
      queryClient.invalidateQueries({ queryKey: ['documents'] })
    },
  })
  const tooBig = !!file && file.size > MAX_MB * 1024 * 1024

  return (
    <form
      className="card stack"
      onSubmit={(e) => {
        e.preventDefault()
        if (file && attested && !tooBig) upload.mutate()
      }}
    >
      <div>
        <h2>Add a document</h2>
        <p className="hint">
          Protocols, guidelines, papers or de-identified case reports: PDF, DOCX, TXT or Markdown, up to{' '}
          {MAX_MB} MB. Tables are kept as tables; the assistant cites the page it used. Scanned PDFs without a
          text layer cannot be read.
        </p>
      </div>
      <div className="notice" role="note">
        <b>No patient data.</b> CochleaHub is a research tool and does not handle patient-identifiable
        information. Do not upload patient records, reports with names, dates of birth or record numbers, or
        anything you could not share with a colleague outside the care team.
      </div>
      <div className="row">
        <input
          ref={input}
          type="file"
          accept={ACCEPT}
          aria-label="File"
          onChange={(e) => setFile(e.target.files?.[0] ?? null)}
        />
        <input
          className="text-input"
          type="text"
          placeholder="Title (optional, defaults to the file name)"
          value={title}
          maxLength={200}
          onChange={(e) => setTitle(e.target.value)}
          aria-label="Title"
        />
      </div>
      <label className="check">
        <input type="checkbox" checked={attested} onChange={(e) => setAttested(e.target.checked)} />
        I confirm this document contains no patient-identifiable information.
      </label>
      <div className="row">
        <button className="btn primary" type="submit" disabled={!file || !attested || tooBig || upload.isPending}>
          {upload.isPending ? 'Uploading…' : 'Upload'}
        </button>
        {tooBig && <span className="prov">The file is larger than {MAX_MB} MB.</span>}
        {upload.isError && (
          <span className="notice error" role="status">
            {upload.error.message}
          </span>
        )}
      </div>
    </form>
  )
}

function DocumentRow({ doc }: { doc: LibraryDocument }) {
  const queryClient = useQueryClient()
  const remove = useMutation({
    mutationFn: () => deleteDocument(doc.id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['documents'] }),
  })
  const download = async () => {
    const url = await documentDownloadUrl(doc.id)
    if (url) window.open(url, '_blank', 'noopener')
  }
  return (
    <tr>
      <td>
        {doc.title}
        <div className="prov mono">{doc.filename}</div>
      </td>
      <td>
        <Status tone={STATUS_TONE[doc.status as keyof typeof STATUS_TONE] ?? 'neutral'}>{doc.status}</Status>
        {doc.error && <div className="prov">{doc.error}</div>}
      </td>
      <td className="num">{doc.sections ?? '—'}</td>
      <td className="num">{doc.chunk_count}</td>
      <td className="num">{size(doc.size_bytes)}</td>
      <td>{doc.uploaded_at ? new Date(doc.uploaded_at).toLocaleString() : '—'}</td>
      <td>
        <div className="row">
          <button className="btn" type="button" onClick={download}>
            Download
          </button>
          <button
            className="btn"
            type="button"
            disabled={remove.isPending}
            onClick={() => {
              if (window.confirm(`Delete "${doc.title}" and remove it from the assistant's sources?`)) remove.mutate()
            }}
          >
            Delete
          </button>
        </div>
      </td>
    </tr>
  )
}

export function DocumentsPage() {
  const docs = useDocuments()
  return (
    <div className="stack">
      <div className="page-head">
        <div>
          <h1>Documents</h1>
          <p className="lede">
            The assistant answers concept questions from CochleaHub's own documentation and from the documents
            added here. Every passage it uses is cited with its document and page.
          </p>
        </div>
      </div>
      <UploadForm />
      <QueryState query={docs}>
        {(list) => {
          const uploads = list.filter((d) => d.source === 'upload')
          const builtIn = list.filter((d) => d.source === 'corpus')
          return (
            <div className="card">
              <h2>Library</h2>
              <p className="hint">
                {uploads.length} uploaded document{uploads.length === 1 ? '' : 's'}, plus {builtIn.length} built-in
                documentation files ({builtIn.reduce((n, d) => n + d.chunk_count, 0)} passages) maintained with
                the code.
              </p>
              {uploads.length === 0 ? (
                <p className="prov">No documents uploaded yet.</p>
              ) : (
                <div className="table-wrap">
                  <table>
                    <thead>
                      <tr>
                        <th>Document</th>
                        <th>Status</th>
                        <th className="num">Pages/sections</th>
                        <th className="num">Passages</th>
                        <th className="num">Size</th>
                        <th>Uploaded</th>
                        <th />
                      </tr>
                    </thead>
                    <tbody>
                      {uploads.map((d) => (
                        <DocumentRow key={d.id} doc={d} />
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          )
        }}
      </QueryState>
    </div>
  )
}
