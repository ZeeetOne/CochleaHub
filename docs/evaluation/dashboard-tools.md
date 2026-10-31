# React vs. Power BI vs. Grafana for CochleaHub

Stage 8 comparison requested by the internship posting (D10, D22). No paper compares these three
tools for surgical-planning software, so this comparison is our own. It uses two sources of
evidence:

- **Built:** the React dashboard (stage 6) and a Grafana prototype of the Operations view
  (`infra/grafana/`, profile `grafana`), both on the same PostgreSQL database.
- **Desk analysis:** Power BI, from vendor documentation and pricing. It was not prototyped,
  because it needs a Microsoft tenant and the Windows desktop authoring tool.

Requirements come from what the dashboard has to do (D10, D17, D18, D20). The weight given to
clinical usability follows the dashboard review of [Dowding2015]. A user study is not part of
this comparison (see "Not measured").

## Evidence from the two builds

| | React (stage 6) | Grafana prototype |
|---|---|---|
| Operations view | `OperationsPage.tsx` 243 lines, plus shared chart/UI components (~320 lines) | 10 panels from an 88-line generator (`build_dashboard.py`), SQL only |
| Database access | through the versioned API (provenance, run selection, missing-data messages) | direct SQL as a read-only role (`grafana_ro`); conversation contents revoked |
| Defaults that needed fixing | none (palette validated for colour-vision deficiency, status = icon + label) | threshold colours painted volumes red, which reads as "bad"; series lost their colours after a fixed colour was set |
| Volumes spanning 3 → 35,000 mm³ | log axis | linear bar gauge only; inner-ear structures are invisible next to bone |
| New in Grafana for free | — | time-range picker, auto-refresh, per-model latency over time, alerting (not configured) |

Screenshots: [React](img/react-operations.png), [Grafana](img/grafana-operations.png).

## Requirement by requirement

| Requirement | React + FastAPI | Grafana OSS | Power BI |
|---|---|---|---|
| 3D anatomy with measured distance overlay | ✅ three.js, built (D18) | ❌ no built-in 3D panel; a custom panel plugin would be React code again | ❌ no built-in 3D; a custom visual (TypeScript SDK) would re-implement it |
| CT slices over DICOMweb | ✅ Cornerstone3D, built | ❌ not built in | ❌ not built in |
| Assistant chat with streamed answers and cited sources | ✅ built (stage 7) | ❌ not a chat surface | ⚠️ Copilot exists but answers over the semantic model, not our tools and guardrails (D20) |
| Provenance (run, pipeline version) on every number | ✅ from the API | ⚠️ possible per query, by hand | ⚠️ possible in the model, by hand |
| Missing data shown as such (abstention, D17) | ✅ API messages shown verbatim | ❌ empty panels ("No data") | ❌ blank visuals |
| Accessible charts (CVD-safe, icon + label) | ✅ by construction | ⚠️ configurable per panel | ⚠️ configurable per visual |
| Operations monitoring over time (runs, QC, assistant latency/cost), alerting | ⚠️ would have to be built | ✅ native strength | ⚠️ reporting rather than alerting |
| Self-hosting, data stays on premises | ✅ | ✅ AGPLv3 (plugins Apache 2.0) | ⚠️ cloud service; Report Server for on-premises with a reduced feature set |
| Licence cost | none (open source stack) | none (OSS) | per-user Pro licences for authors; Embedded capacity billed hourly (A1 ≈ $1/h) |
| Effort for a new view | high (code) | low (SQL + panel) | low to medium (drag and drop, DAX) |

✅ = supported and shown here, ⚠️ = possible with effort or with limits, ❌ = not supported.

## Recommendation

Use each tool for the job it is good at. Do not pick one for everything.

1. **React + the API for anything a clinician or researcher works in.** This covers 3D, CT, the
   measurement tables, and the assistant. Only this option can show the anatomy and the CT and
   host the assistant with its guardrails. Every number keeps its provenance, and "no data"
   stays distinguishable from zero.
2. **Grafana for internal operations.** It suits pipeline runs, QC trends, assistant latency,
   tokens and errors, with alerts. It needs only SQL per panel and gives time ranges and alerting
   for free. It reads the database through a read-only role and cannot see conversation
   contents.
3. **Power BI only if the organisation already reports in Microsoft.** It fits aggregate KPIs
   across many cases for management. It does not fit the surgical-planning surface: there is no
   3D or DICOM, and it is a cloud service by default, which conflicts with on-premises data
   needs (D20).

## Not measured

- **Usability with clinicians.** The usual instruments are the System Usability Scale and
  task-based tests [Almasi2023]. That needs participants; it is the next evaluation, not part of
  this one.
- **Power BI build effort.** It is estimated, not measured (no prototype).
