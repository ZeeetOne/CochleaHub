# Stage 5 — Backend API

**Goal:** one read path for the dashboard and the assistant, where every number says where it
came from and missing data are named rather than hidden.

```mermaid
flowchart LR
    C["dashboard / assistant"] --> V1["/api/v1"]
    V1 --> SP["specimens<br/>measurements · cochlea<br/>distances · meshes · imaging"]
    V1 --> RU["runs<br/>qc · validation"]
    V1 --> CO["compare<br/>reference-ranges"]
    V1 --> HE["health · health/ready"]
    V1 --> AS["assistant<br/>(stage 7)"]
    V1 --> DOC["documents<br/>upload · list · delete<br/>(D25)"]
    DOC -- "original" --> S3
    DOC -- "passages" --> PG
    SP & RU & CO --> SEL{"run selection<br/>latest completed,<br/>or pinned run_id"}
    SEL --> PG[("PostgreSQL")]
    SP -- "presigned URL" --> S3[("S3")]
    SEL -- "missing" --> E404["404 + what is missing"]
```

Every run-derived response carries:

```json
"provenance": {"run_id": "19ac527c-…", "specimen_id": "zeta",
               "pipeline_version": "0.1.0", "started_at": "…", "qc_status": "pass_with_warnings"}
```

| | |
|---|---|
| **Code** | `backend/src/cochleahub/api/` (routers, Pydantic schemas, run selection) |
| **Contract** | OpenAPI at `/docs`, exported to `docs/api/openapi.json`; the frontend's TypeScript types are generated from it |

## Decisions

| | Decision | Basis |
|---|---|---|
| D9 | read-only API; results tagged with the pipeline version | traceability [Margeta2022] |
| D17 | latest *completed* run by default, so a failed newer run never hides good results | engineering |
| D17 | 404 names what is missing (unknown specimen, no completed run, …) | lets the assistant abstain instead of guessing [Lee2022] |
| D17 | meshes through short-lived presigned URLs; DICOMweb through a same-origin proxy | private storage; Orthanc never exposed [Jodogne2018] |
| D25 | the document library is the only writable resource besides the assistant log; uploads require a no-patient-data attestation, type checked by content, duplicates refused | [Kresevic2024]; patient documents need an institutional setting [Unlu2024] |

## Checks

- API tests assert that the only writes are the assistant's chat and the document library
  (`POST /documents`, `DELETE /documents/{id}`); measurement routes stay read-only.
- Document tests cover upload → indexed → searchable → deleted, the attestation, duplicates,
  wrong file types and unreadable PDFs.
- Live: readiness reports all three dependencies ok; all 13 presigned mesh URLs download.
