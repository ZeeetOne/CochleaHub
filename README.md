# CochleaHub

Research web platform that turns temporal bone CT and segmentations into anatomical
measurements, 3D models and natural-language answers for cochlear implant research.

Built on the public [OpenEar](https://doi.org/10.1038/sdata.2018.297) dataset (Sieber et al., 2019),
starting with specimen **ZETA**. Architecture follows the published Nautilus platform
(Margeta et al., 2022).

> **Not a clinical tool.** No medical recommendations. Data come from cadaveric specimens and
> do not represent population statistics.

## Architecture

```
Dataset/ (OpenEar ZETA, not committed)
   │
   ▼
backend/cochleahub/pipeline   SimpleITK: volumes, dimensions, surface area, min distances, QC flags
   │            │
   │            ├──► data/meshes/*.glb ──► S3
   │            └──► PostgreSQL (specimens, measurements, pipeline runs)
   ▼
backend/cochleahub/api        FastAPI, read-only, every result tagged with pipeline version
   │
   ├──► frontend/  React + TypeScript dashboard (Overview, Specimen, Compare, Operations)
   │                3D viewer (three.js) + CT slice viewer (OHIF / Cornerstone3D via DICOMweb)
   └──► assistant  LLM tool calling over the API + RAG over user guide & literature
Orthanc (DICOMweb)  CBCT archive on AWS EC2 (production path: AWS HealthImaging)
```

## Repository layout

| Path | Content |
|---|---|
| `backend/src/cochleahub/pipeline` | Dataset loading, measurement, mesh export, QC |
| `backend/src/cochleahub/api` | FastAPI app |
| `backend/src/cochleahub/db` | SQLAlchemy models (stage 4) |
| `backend/tests` | pytest |
| `frontend/` | Vite + React + TypeScript dashboard |
| `infra/docker-compose.yml` | Local PostgreSQL + Orthanc (DICOMweb) |
| `data/` | Generated outputs (git-ignored) |
| `Dataset/` | Extracted OpenEar specimen (git-ignored) |

## Setup

Requirements: Python ≥ 3.11, Node ≥ 20, Docker.

```bash
cp .env.example .env                       # adjust DATASET_ROOT if needed

# backend
cd backend
python -m venv .venv
.venv/Scripts/activate                     # Windows; use .venv/bin/activate on Linux/macOS
pip install -e ".[dev]"
cochleahub inspect                         # verifies the dataset, writes data/outputs/zeta_manifest.json
cochleahub measure                         # stage 2: metrics, meshes, distances
cochleahub validate                        # stage 3: Slicer + dataset-mesh comparison, QC report (SLICER_EXE optional)
pytest

# infra (Postgres :5432, Orthanc :8042, S3 API :8333)
docker compose -f infra/docker-compose.yml --env-file .env up -d
cd backend
alembic upgrade head                       # create / migrate the schema
cochleahub load                            # stage 4: run + QC -> PostgreSQL, meshes -> S3
cochleahub upload-dicom                    # stage 4: CBCT -> DICOM Part 10 -> Orthanc
uvicorn cochleahub.api.main:app --reload   # stage 5: http://localhost:8000/docs
cochleahub openapi                         # API schema -> docs/api/openapi.json
cochleahub index-docs                      # stage 7: assistant documentation index (local embeddings)

# assistant backends: set ANTHROPIC_API_KEY for Claude, and/or run a local model
docker compose -f infra/docker-compose.yml --env-file .env --profile local-llm up -d ollama
docker exec infra-ollama-1 ollama pull qwen3:4b

# frontend (needs the API on :8000 and Orthanc on :8042; Vite proxies /api and /dicom-web)
cd frontend
npm install
npm run dev                                # http://localhost:5173
npm run gen:api                            # regenerate API types after `cochleahub openapi`
```

## API

Read-only, under `/api/v1` (OpenAPI: `http://localhost:8000/docs`, exported to
[`docs/api/openapi.json`](docs/api/openapi.json)). Results come from a specimen's latest
completed run unless `run_id` pins another one; each carries a `provenance` block (run id,
pipeline version, QC status). Missing data return 404 saying what is missing.

| Route | Content |
|---|---|
| `GET /health`, `/health/ready` | liveness; readiness of PostgreSQL, S3, Orthanc |
| `GET /specimens`, `/specimens/{id}` | specimens with latest run and CT series |
| `GET /specimens/{id}/measurements` | per-structure volume, area, dimensions, connectivity |
| `GET /specimens/{id}/cochlea` | A, B, height with the published range and source |
| `GET /specimens/{id}/distances` | minimum distances between critical structures |
| `GET /specimens/{id}/meshes` | presigned glTF URLs (LPS) |
| `GET /specimens/{id}/imaging` | DICOMweb root + series UIDs for the slice viewer |
| `GET /runs`, `/runs/{id}`, `/runs/{id}/qc`, `/runs/{id}/validation` | operations view |
| `GET /compare?metric=…&structure=…` | one metric across specimens + published range |
| `GET /reference-ranges` | published ranges and their reference keys |
| `GET /assistant/status`, `POST /assistant/chat` (SSE), `GET /assistant/conversations/{id}` | assistant: backend availability, streamed answers with tool steps and cited sources, logged turns |

## Dataset: ZETA

| Folder | Content | Used for |
|---|---|---|
| `01_CBCT_Unembedded`, `02_CBCT_Embedded` | CBCT DICOM series (X/Y/Z) | Orthanc upload, slice viewer |
| `05_Registred_Slicer_Volumes` | CBCT registered to micro-slicing, 0.125 mm isotropic (.nrrd) | Measurement reference space |
| `06_Segmentation/Segmentation.seg.nrrd` | 13-layer 3D Slicer segmentation, 0.125 mm | Volumes, surface areas, distances |
| `07_3D_Models/*.ply` | Surface mesh per structure | 3D viewer (converted to .glb) |
| `05_.../Accuracy Analysis` | Hausdorff / volumetric error CBCT vs. histology | Validation context |

Segments: Scala Tympani, Scala Vestibuli, Malleus, Incus, Stapes, Cochleovestibular nerve,
Facial Nerve, Chorda Tympani, Bone, Tympanic Membrane, External Auditory Canal, Sinus Dura,
Carotis Interna.

## Roadmap

- [x] **1. Data & exploration** — dataset loader, `cochleahub inspect`, manifest
- [x] **2. Processing & measurement** — `cochleahub measure`: volume, dimensions, surface area per structure; cochlear A/B/height; `.glb` meshes; min distances between facial nerve, chorda tympani and cochlea
- [x] **3. Validation & QC** — `cochleahub validate`: against headless 3D Slicer Segment Statistics and the dataset's published meshes; QC flags with severities and published ranges → [`docs/validation/zeta.md`](docs/validation/zeta.md)
- [x] **4. Storage (local, AWS-compatible)** — CBCT rewritten as DICOM Part 10 → Orthanc (DICOMweb); meshes → S3 API; runs, measurements, QC and validation → PostgreSQL (Alembic). AWS provisioning in stage 8
- [x] **5. Backend API** — read-only `/api/v1`: specimens, measurements, cochlea vs. published ranges, distances, compare, runs, QC, validation, presigned mesh URLs, DICOMweb series; every result carries its run and pipeline version → [API](#api)
- [x] **6. Dashboard & viewer** — Overview, Specimen (3D anatomy with measured distances, cochlea vs. published range, CT axial/coronal/sagittal via Cornerstone3D + DICOMweb, measurement table), Compare, Operations (services, runs, QC flags, validation charts)
- [x] **7. AI assistant** — agent loop over the read-only API + hybrid RAG (BM25 + local embeddings, RRF) over the docs, native citations; Claude (API, or Bedrock EU in production) or a local model on Ollama; refuses clinical advice, says what is missing; every turn logged for evaluation
- [ ] **8. Evaluation & deploy** — measurement validation table, 25-question assistant eval, AWS deploy, React vs. Power BI vs. Grafana comparison

## Design basis

Every architectural choice is traced to published work:
[`docs/DECISIONS.md`](docs/DECISIONS.md) (decision log) and
[`docs/REFERENCES.md`](docs/REFERENCES.md) (bibliography).
