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

## D5 — Metric set: volume, surface area, dimensions, cochlear A/B/height (accepted, stage 2)

- **Decision:** per structure: volume (voxel count × voxel volume), surface area (from the
  smoothed mesh, D13), principal dimensions (oriented bounding box, largest first), centroid and
  number of connected components. Cochlear A, B and height are taken from the oriented bounding
  box of the **scala tympani** alone.
- **Basis:** global metrics reported by Nautilus [Margeta2022]; size variability motivating
  per-patient measurement [Avci2014]. CDL estimation lacks a clinical standard
  [Breitsprecher2022, Schurzig2018], so CDL is **not** computed — only A/B, which CDL formulas
  build on.
- **Finding that changed the plan:** the dataset's "Scala Vestibuli" label measures 152 mm³ and
  18.0 × 12.6 × 10.1 mm, too large for the cochlea alone; it appears to include the vestibule and
  semicircular canals (to be confirmed in the 3D viewer). Scala tympani (34.7 mm³,
  9.0 × 6.8 × 4.4 mm) spans the whole cochlear spiral, so it is used for A/B/height.
- **Limitation:** A/B/height are a landmark-free proxy. The classical definitions use the round
  window and modiolar axis; landmark detection as in [Stebani2023] is future work.

## D6 — Minimum distances between critical structures (accepted, stage 2)

- **Decision:** minimum distance between smoothed meshes (KD-tree over vertices, resolution ≈ one
  voxel = 0.125 mm) for facial nerve ↔ scala tympani, facial nerve ↔ labyrinth (scala vestibuli
  label), chorda tympani ↔ scala tympani, and facial nerve ↔ chorda tympani; the closest points
  are stored for display.
- **Basis:** the facial recess (≈ 1.0–3.5 mm) bounded by facial nerve and chorda tympani is the
  surgical access route; both structures are small and low-contrast in CT [Noble2008].
- **Finding:** facial nerve ↔ chorda tympani is 0 mm because the chorda tympani branches off the
  facial nerve. The minimum gap is therefore **not** the facial recess width; measuring the width
  needs a reference level (landmarks) and is left as future work.

## D7 — Validation against two independent references (accepted, stage 3)

- **Decision:** `cochleahub validate` compares every structure with (1) 3D Slicer Segment
  Statistics on the same segmentation, run headless from a script, and (2) the surface meshes
  published with the dataset (`07_3D_Models`, RAS → LPS), reporting volume and area differences
  and symmetric surface distances. The dataset's own CBCT-vs-histology report is included as the
  error floor of the segmentation itself. A Markdown report is written to `docs/validation/`.
- **Basis:** Nautilus reports the accuracy of each pipeline stage [Margeta2022]; 3D Slicer is
  the reference platform for quantitative imaging [Fedorov2012]; the published meshes and the
  accuracy report come with the dataset [Sieber2019].
- **Finding:** volumes equal Slicer's for all 13 structures (identical voxel counts). Surface
  areas are 3–15% above Slicer's. On synthetic spheres both methods are within 1.5% of the true
  area, so the gap on anatomy is a smoothing effect on thin, curved structures (stapes, chorda
  tympani), not an error of either tool: area is reported as method-dependent.

## D8 — Storage: Orthanc (DICOMweb) + S3 + PostgreSQL (accepted locally, stage 4)

- **Decision:** CBCT DICOM in Orthanc with the DICOMweb plugin; meshes in S3; specimens,
  measurements, pipeline runs, QC flags and validation results in PostgreSQL. Production path:
  RDS for PostgreSQL, S3, Orthanc on EC2 (or AWS HealthImaging). Locally the same three roles
  run in `infra/docker-compose.yml`; code reaches S3 through boto3, so only the endpoint differs.
- **Basis:** Orthanc is a lightweight open-source DICOM server with REST API and DICOMweb plugin
  [Jodogne2018]; Imaging Data Commons stores DICOM in the cloud behind a web viewer
  [Fedorov2023]; Nautilus uses PostgreSQL [Margeta2022].
- **Scope:** only the axial (Z) series of each CBCT is archived (481 + 401 instances): X/Y/Z
  are the same volume resliced, and the viewer reslices itself.
- **Local S3 emulation (engineering, no paper):** MinIO images could not be pulled from Docker
  Hub or Quay (October 2026), so SeaweedFS's S3 gateway is used locally.
- **Checks on ZETA:** DICOMweb QIDO-RS lists both studies, WADO-RS returns series metadata and a
  rendered frame; mesh objects are downloadable through presigned URLs.

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

## D13 — Meshes: marching cubes + Taubin smoothing, glTF for the web (accepted, stage 2)

- **Decision:** surface = marching cubes [Lorensen1987] on each binary mask, then 20 iterations
  of Taubin smoothing [Taubin1995]; this mesh is used for area and distances. Display copies are
  decimated to ≤ 150k faces and exported as `.glb`. Bone and sinus dura are meshed on a coarser
  grid (step 3 / 2) and get no surface area.
- **Basis:** Nautilus exports per-structure surface meshes (STL) next to its metrics
  [Margeta2022]. On synthetic spheres raw marching cubes overestimated area by 7.8–8.7% (staircase
  effect); Taubin smoothing, which avoids the shrinkage of plain Laplacian smoothing
  [Taubin1995], reduced the error to < 1% with volume unchanged (`tests/test_measure.py`).
  glTF binary is an engineering choice for three.js, not paper-based.
- **Check on ZETA:** mesh volumes agree with voxel volumes within 1% for every structure.

## D14 — Automatic QC flags with severities (accepted, stage 3)

- **Decision:** every run gets flags with severity `error` (do not use the number), `warning`
  (usable with care) or `info`, and an overall status pass / pass_with_warnings / fail.

  | Code | Severity | Rule |
  | --- | --- | --- |
  | RUN_NOT_COMPLETED, STRUCTURE_FAILED | error | pipeline status / per-structure exception |
  | MESH_NOT_WATERTIGHT | error | full-resolution mesh not closed |
  | SLICER_VOXEL_MISMATCH, SLICER_VOLUME_MISMATCH | error | voxel count differs, or volume > 1% |
  | AREA_METHOD_SENSITIVE | warning | area differs from Slicer by > 10% (D7 finding) |
  | MESH_VOLUME_MISMATCH | warning | mesh vs voxel volume > 2% |
  | FRAGMENTED | warning / info | > 1 component; warning if the largest holds < 99% |
  | SURFACE_DEVIATES_FROM_DATASET_MESH | warning | mean distance > 1 voxel per meshing step |
  | OUT_OF_PUBLISHED_RANGE | warning | outside a published range, source cited |

- **Basis:** failure flags that let faulty cases be excluded [Margeta2022]. Published ranges:
  scala tympani volume 23–50 µL from 30 micro-CT temporal bones [Dhanasingh2021]; cochlear
  A 8.17–9.33, B 5.73–7.50, H 2.80–3.72 mm from HRCT of 36 ears of implant candidates aged 2–17
  [Zahara2019]. Range flags are warnings because each source covers one population and one
  measurement definition. Numeric tolerances (1%, 2%, 10%, one voxel) are engineering choices,
  set from the validation results in D7, not from a paper.
- **Finding:** the landmark-free cochlear height proxy (4.36 mm) exceeds the published H range;
  the bounding box spans the outer envelope of the scala, while H is measured from the basal
  turn to the apex. The flag surfaces this limitation of D5 instead of hiding it.

## D15 — Rewrite CBCT files as DICOM Part 10 before archiving (accepted, stage 4)

- **Context:** OpenEar's CBCT files are bare datasets (implicit VR little endian) with no
  128-byte preamble, no "DICM" prefix and no File Meta Information.
- **Decision:** rewrite each file with a File Meta header (Media Storage SOP Class/Instance UID
  from the file itself, Transfer Syntax implicit VR little endian), then upload to Orthanc.
- **Basis:** the DICOM file format requires the preamble, prefix and File Meta group
  [DICOM-PS3.10]; archives exchange Part 10 files [Jodogne2018].
- **Check on ZETA:** pixel data byte-identical for all 882 files; all other elements kept except
  the group-length elements (gggg,0000), retired outside group 0002 [DICOM-PS3.5], which pydicom
  drops when writing.

## D16 — Run-centred schema with migrations (accepted, stage 4)

- **Decision:** every structure measurement, cochlear dimension, distance, QC flag and validation
  row references a `pipeline_runs` row that stores the pipeline version, status, timing and QC
  summary; mesh objects are keyed `meshes/<specimen>/<run id>/…`. Loading is idempotent per
  (specimen, run start time). Schema changes go through Alembic migrations.
- **Basis:** traceability of each result to the pipeline version that produced it
  [Margeta2022]. Alembic and the idempotent loader are engineering choices.

## D12 — Evaluation (planned, stage 8)

- **Decision:** measurement validation table (D7); 25-question assistant test set including
  questions that must be refused/abstained, scored for accuracy.
- **Basis:** abstention evaluation follows [Lee2022]; per-stage accuracy reporting follows
  [Margeta2022].
