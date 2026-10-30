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
- `infra/` — docker-compose (Postgres, Orthanc DICOMweb); AWS deploy later (stage 8)
- `data/` — generated outputs, git-ignored

## Commands

```bash
backend/.venv/Scripts/cochleahub inspect          # dataset check + manifest
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
