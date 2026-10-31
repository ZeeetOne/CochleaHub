# CochleaHub — instructions for Claude

Portfolio project for the Cochlear internship "Enhancing Surgical Software User Experience with
AI Assistant Technology" (dashboard, React/TS, FastAPI, AWS, LLM + RAG). The owner communicates
in Indonesian; code, comments, commits and docs are in English.

## Ground rules

1. **Every design decision must cite a paper.** Before implementing a stage, check
   `docs/DECISIONS.md` and `docs/REFERENCES.md`. New decisions get a new entry in
   `docs/DECISIONS.md` (context → decision → paper basis → consequences). If no paper supports
   a choice, say so explicitly in the entry instead of inventing a citation.
2. **One commit per logical change**, Conventional Commits style (`feat(pipeline): ...`,
   `docs: ...`). No `Co-Authored-By` trailers or any AI attribution in commits or PRs.
3. **Never modify, move or delete anything in `Dataset/`** (read-only source data, including
   `ZETA.zip`, which the owner keeps locally). Never commit it.
4. Not a clinical tool: the assistant must refuse medical advice and abstain when data are missing.

## Layout

- `backend/src/cochleahub/pipeline` — SimpleITK pipeline (stages 1–3)
- `backend/src/cochleahub/api` — FastAPI, read-only, results tagged with pipeline version (stage 5)
- `backend/src/cochleahub/db` — SQLAlchemy models (stage 4)
- `backend/src/cochleahub/assistant` — LLM tool calling + RAG (stage 7)
- `frontend/` — Vite + React + TypeScript dashboard (stage 6)
- `backend/src/cochleahub/storage` — S3 object store, DICOM Part 10 rewrite + Orthanc upload (stage 4)
- `backend/alembic` — schema migrations
- `infra/` — docker-compose (Postgres, Orthanc DICOMweb, SeaweedFS S3); AWS deploy later (stage 8)
- `data/` — generated outputs, git-ignored

## Commands

```bash
backend/.venv/Scripts/cochleahub inspect          # dataset check + manifest
backend/.venv/Scripts/cochleahub measure          # stage 2 metrics, meshes, distances
backend/.venv/Scripts/cochleahub validate         # stage 3 validation + QC report
cd backend && .venv/Scripts/alembic upgrade head  # schema migrations
backend/.venv/Scripts/cochleahub load             # stage 4: run -> Postgres, meshes -> S3
backend/.venv/Scripts/cochleahub upload-dicom     # stage 4: CBCT -> Orthanc
backend/.venv/Scripts/python -m pytest backend    # tests
cd backend && .venv/Scripts/uvicorn cochleahub.api.main:app --reload
cd frontend && npm run dev | npm run build
docker compose -f infra/docker-compose.yml --env-file .env up -d
```

## Data notes (OpenEar ZETA)

- `06_Segmentation/Segmentation.seg.nrrd`: 13-layer binary vector image (one component per
  segment), 0.125 mm isotropic, RAS header. Full read ≈ 2.3 GB RAM — process per segment and
  crop to `SegmentN_Extent` where possible.
- `05_Registred_Slicer_Volumes/*.nrrd`: CBCT in the same 0.125 mm space (LPS header).
- `07_3D_Models/*.ply`: per-structure meshes; `Bone.ply` is 135 MB.
- The "Scala Vestibuli" label (152 mm³, 18 mm long) appears to include vestibule and
  semicircular canals; cochlear dimensions use scala tympani only (D5).
- Chorda tympani branches off the facial nerve, so their minimum distance is 0 mm (D6).
- Headless Slicer: never call CreateClosedSurfaceRepresentation up front on the full
  segmentation (hours instead of ~20 s); the stats script only falls back to it when needed.
- CBCT DICOM files lack the DICM preamble (read with `force=True`); X/Y/Z folders are the same
  scan resliced sagittal/coronal/axial.
