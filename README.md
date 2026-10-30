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
pytest
uvicorn cochleahub.api.main:app --reload   # http://localhost:8000/docs

# infra
docker compose -f infra/docker-compose.yml --env-file .env up -d   # Postgres :5432, Orthanc :8042

# frontend
cd frontend
npm install
npm run dev                                # http://localhost:5173
```

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
- [ ] **3. Validation & QC** — compare with 3D Slicer Segment Statistics; out-of-range / broken-mesh flags
- [ ] **4. Cloud storage** — CBCT → Orthanc (DICOMweb) on EC2, meshes → S3, results → PostgreSQL
- [ ] **5. Backend API** — specimens, measurements, distances, compare, pipeline runs (versioned)
- [ ] **6. Dashboard & viewer** — Overview, Specimen detail (3D + table), Compare, Operations; OHIF/Cornerstone3D slice viewer
- [ ] **7. AI assistant** — tool calling to the API, RAG over docs/literature, refuses clinical advice, abstains when data is missing
- [ ] **8. Evaluation & deploy** — measurement validation table, 25-question assistant eval, AWS deploy, React vs. Power BI vs. Grafana comparison

## Design basis

Every architectural choice is traced to published work:
[`docs/DECISIONS.md`](docs/DECISIONS.md) (decision log) and
[`docs/REFERENCES.md`](docs/REFERENCES.md) (bibliography).
