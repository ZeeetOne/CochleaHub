import { lazy, Suspense } from 'react'
import { NavLink, Route, Routes } from 'react-router-dom'
import { useSpecimens } from './api/client'
import { ComparePage } from './pages/ComparePage'
import { DocumentsPage } from './pages/DocumentsPage'
import { OperationsPage } from './pages/OperationsPage'
import { Overview } from './pages/Overview'

// three.js and the 3D viewer are only needed on the specimen page, markdown on the assistant
const SpecimenPage = lazy(() => import('./pages/SpecimenPage').then((m) => ({ default: m.SpecimenPage })))
const AssistantPage = lazy(() => import('./pages/AssistantPage').then((m) => ({ default: m.AssistantPage })))

function Sidebar() {
  const specimens = useSpecimens()
  const link = ({ isActive }: { isActive: boolean }) => `nav-link${isActive ? ' active' : ''}`
  return (
    <nav className="sidebar" aria-label="Main">
      <div className="brand">CochleaHub</div>
      <div className="brand-sub">Temporal bone analysis</div>
      <NavLink to="/" end className={link}>
        Overview
      </NavLink>
      {specimens.data?.map((s) => (
        <NavLink key={s.id} to={`/specimens/${s.id}`} className={link}>
          Specimen {s.id.toUpperCase()}
        </NavLink>
      ))}
      <NavLink to="/compare" className={link}>
        Compare
      </NavLink>
      <NavLink to="/operations" className={link}>
        Operations
      </NavLink>
      <NavLink to="/assistant" className={link}>
        Assistant
      </NavLink>
      <NavLink to="/documents" className={link}>
        Documents
      </NavLink>
      <div className="sidebar-foot">Research use only. Not a medical device.</div>
    </nav>
  )
}

export default function App() {
  return (
    <div className="app">
      <Sidebar />
      <main>
        <Suspense fallback={<p className="prov">Loading…</p>}>
          <Routes>
            <Route path="/" element={<Overview />} />
            <Route path="/specimens/:id" element={<SpecimenPage />} />
            <Route path="/compare" element={<ComparePage />} />
            <Route path="/operations" element={<OperationsPage />} />
            <Route path="/assistant" element={<AssistantPage />} />
            <Route path="/documents" element={<DocumentsPage />} />
            <Route path="*" element={<div className="notice">Page not found.</div>} />
          </Routes>
        </Suspense>
      </main>
    </div>
  )
}
