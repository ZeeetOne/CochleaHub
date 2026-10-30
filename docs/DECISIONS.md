# Architecture decision log

Each decision is traced to published work (keys in `REFERENCES.md`). Status: **accepted**
(implemented), **planned** (agreed, not built yet). Where no paper supports a choice, the entry
says so.

---

## D1 — Dataset: OpenEar specimen ZETA (accepted)

- **Context:** need public temporal bone CT with expert segmentations of structures relevant to
  cochlear implantation.
- **Decision:** use OpenEar [Sieber2019], starting with ZETA; other specimens added later through
  the same loader.
- **Basis:** OpenEar provides CBCT, micro-slicing histology, segmentations of inner ear, ossicles
  and nerves, and 3D models per specimen [Sieber2019]. Data opens in 3D Slicer [Fedorov2012],
  as verified for the comparable dataset of [Gerber2017].
- **Consequences:** 8 cadaveric specimens, no malformations [Sennaroglu2017] → results are not
  population statistics; malformation knowledge only appears in the assistant's RAG corpus.

## D2 — Use the existing segmentation, do not train a model (accepted)

- **Context:** automatic segmentation is an active research area [Hussain2021, Heutink2020,
  Neves2021, Stebani2023], but the target internship is about dashboard UX and AI assistance.
- **Decision:** read labels from `Segmentation.seg.nrrd`; the pipeline starts after segmentation.
- **Basis:** Nautilus separates segmentation from downstream metric computation and exposes each
  stage's result independently [Margeta2022].
- **Consequences:** pipeline stays deterministic and fast; the segmentation step is a pluggable
  stage that could later host a model like [Hussain2021].

## D3 — Header-only inspection and per-segment processing (accepted)

- **Context:** the segmentation is a 13-component vector image (≈ 2.3 GB uncompressed).
- **Decision:** `inspect` reads headers only; measurement processes one component at a time,
  cropped to its `Extent`.
- **Basis:** engineering constraint; no paper needed. SimpleITK chosen per D4.

## D4 — Image processing with SimpleITK (accepted)

- **Decision:** SimpleITK for all voxel-level work.
- **Basis:** SimpleITK simplifies ITK for reproducible image-analysis workflows [Yaniv2018].

## D5 — Metric set: volume, surface area, dimensions, cochlear height (planned, stage 2)

- **Decision:** per structure: volume (voxel count × voxel volume), surface area (from mesh),
  bounding dimensions; for the cochlea (scala tympani ∪ scala vestibuli): A/B dimensions and
  height.
- **Basis:** these are the global metrics reported by Nautilus [Margeta2022]; size variability
  motivating per-patient measurement [Avci2014]; CDL estimation lacks a clinical standard
  [Breitsprecher2022, Schurzig2018], so CDL is **not** computed — only A/B, which CDL formulas
  build on.

## D6 — Minimum distance facial nerve ↔ cochlea / chorda tympani (planned, stage 2)

- **Decision:** compute minimum surface-to-surface distance between facial nerve, chorda tympani
  and cochlea.
- **Basis:** the facial recess (≈ 1.0–3.5 mm) bounded by facial nerve and chorda tympani is the
  surgical access route; both structures are small and low-contrast in CT [Noble2008].

## D7 — Validation against 3D Slicer + automatic QC flags (planned, stage 3)

- **Decision:** compare pipeline volumes with 3D Slicer Segment Statistics, report relative error
  per structure; flag out-of-range values and broken meshes.
- **Basis:** Nautilus reports per-stage accuracy and flags failures so faulty cases can be
  excluded from analysis [Margeta2022]. The dataset's own CBCT-vs-histology error report
  (`Accuracy Analysis`) gives the reference error level [Sieber2019].

## D8 — Storage: Orthanc (DICOMweb) + S3 + PostgreSQL (planned, stage 4)

- **Decision:** CBCT DICOM in Orthanc with the DICOMweb plugin; meshes in S3; specimens,
  measurements and pipeline runs in PostgreSQL. Production path: AWS HealthImaging.
- **Basis:** Orthanc is a lightweight open-source DICOM server with REST API and DICOMweb plugin
  [Jodogne2018]; Imaging Data Commons stores DICOM in the cloud behind a web viewer
  [Fedorov2023]; Nautilus uses PostgreSQL [Margeta2022].

## D9 — Read-only API, results tagged with pipeline version (accepted, stage 5 in progress)

- **Decision:** FastAPI, GET-only; every result carries `pipeline_version`.
- **Basis:** Nautilus tags each analysis result with the version of the pipeline that produced it
  for traceability [Margeta2022].

## D10 — React + TypeScript dashboard, web 3D + DICOMweb slice viewer (planned, stage 6)

- **Decision:** React/TS SPA with Overview, Specimen detail (3D + table), Compare and Operations
  pages; CT slices through OHIF/Cornerstone3D over DICOMweb; three.js for meshes.
- **Basis:** Nautilus frontend is React with vtk.js viewports and Plotly/Chart.js [Margeta2022];
  OHIF is a zero-footprint DICOMweb viewer [Ziegler2020]; accessible dashboards are associated
  with better care processes [Dowding2015]. Power BI / Grafana are evaluated in stage 8 as the
  posting requests; no paper compares them — the comparison will be our own.

## D11 — AI assistant: tool calling over the API + RAG, with refusal/abstention (planned, stage 7)

- **Decision:** an agent loop where the LLM calls the read-only API as tools for data questions,
  retrieves from a corpus (user guide + literature summaries) for concept questions, refuses
  clinical advice and answers "unknown" when data are absent.
- **Basis:** interleaving reasoning and tool actions [Yao2023]; clinical data QA framed as tool
  planning [Shi2024]; retrieval-augmented generation [Lewis2020]; distinguishing answerable from
  unanswerable questions [Lee2022].
- **Consequences:** the assistant never sees raw voxels, only API results → answers are
  traceable to versioned measurements (D9). LLM provider (Claude) is an engineering choice, not
  paper-based.

## D12 — Evaluation (planned, stage 8)

- **Decision:** measurement validation table (D7); 25-question assistant test set including
  questions that must be refused/abstained, scored for accuracy.
- **Basis:** abstention evaluation follows [Lee2022]; per-stage accuracy reporting follows
  [Margeta2022].
