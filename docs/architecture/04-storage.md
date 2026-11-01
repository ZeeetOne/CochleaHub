# Stage 4 — Storage (local, AWS-compatible)

**Goal:** put each kind of data where a production system would keep it, with the same
interfaces locally and on AWS.

```mermaid
flowchart LR
    CBCT[("CBCT DICOM<br/>axial series")] --> P10["rewrite as DICOM Part 10<br/>(add preamble + file meta)"]
    P10 --> OR[("Orthanc<br/>DICOMweb plugin")]
    J[/"measurements + validation JSON"/] --> L["cochleahub load<br/>idempotent"]
    L --> PG[("PostgreSQL<br/>Alembic migrations")]
    G[/".glb meshes"/] --> L
    L --> S3[("S3 bucket<br/>meshes/&lt;specimen&gt;/&lt;run&gt;/…<br/>documents/&lt;sha256&gt;/…")]
    D[/"docs/ + uploaded documents"/] --> IX["index-docs / upload<br/>chunk + local embeddings"]
    IX --> PG
```

**Schema (run-centred, D16):** every result belongs to a pipeline run that records its version.

```mermaid
erDiagram
    specimens ||--o{ pipeline_runs : has
    specimens ||--o{ imaging_series : has
    pipeline_runs ||--o{ structure_measurements : produced
    pipeline_runs ||--o| cochlea_dimensions : produced
    pipeline_runs ||--o{ distances : produced
    pipeline_runs ||--o{ qc_flags : raised
    pipeline_runs ||--o{ validation_results : checked
    assistant_conversations ||--o{ assistant_turns : contains
    rag_documents ||--o{ rag_chunks : "split into"
```

`rag_chunks` holds each passage with a `vector(384)` embedding (HNSW index, cosine) and a
generated `tsvector` (GIN index). `rag_documents` records whether a document is built-in
documentation or an upload, with its processing status (D24, D25).

| Local (Docker) | AWS | Content |
|---|---|---|
| PostgreSQL 17 + pgvector 0.8.7 | RDS for PostgreSQL (pgvector) | specimens, runs, measurements, QC, validation, assistant log, retrieval index |
| SeaweedFS (S3 API) | Amazon S3 | meshes and uploaded documents; same boto3 code, only the endpoint differs |
| Orthanc + DICOMweb | Orthanc on EC2 / AWS HealthImaging | CBCT, 481 + 401 slices per specimen |

## Decisions

| | Decision | Basis |
|---|---|---|
| D8 | Orthanc (DICOMweb) + S3 + PostgreSQL; axial series only | [Jodogne2018, Fedorov2023, Margeta2022]; X/Y/Z are the same scan |
| D15 | rewrite CBCT as DICOM Part 10 before archiving | [DICOM-PS3.10]; pixel data byte-identical, only retired group lengths dropped [DICOM-PS3.5] |
| D16 | run-centred schema, idempotent loader, migrations | traceability per pipeline version [Margeta2022] |
| D24 | retrieval index in the same PostgreSQL: pgvector + full-text search | fusing lexical and dense retrieval [Xiong2024]; pgvector is an engineering choice available on RDS |
| D25 | uploaded documents: original in S3, passages in the index | [Kresevic2024, Xiong2024] |

The local S3 is SeaweedFS because MinIO images could not be pulled (October 2026). This is an
engineering choice; no paper is involved. PostgreSQL runs the `pgvector/pgvector:0.8.7-pg17-trixie`
image, whose Debian base matches the C library of the existing database, so text collation stays
valid (D24).

## Checks

- **CT:** all 882 rewritten files have pixel data byte-identical to the originals. QIDO-RS finds
  both studies, and WADO-RS returns metadata and rendered frames.
- **Meshes:** downloadable through presigned URLs.
- **Loader:** loading the same run twice changes nothing. Both specimens are loaded; each
  specimen's ear side comes from its manifest.
- **Retrieval index:** a second `index-docs` embeds 0 passages; edited passages are re-embedded
  and removed ones deleted.
