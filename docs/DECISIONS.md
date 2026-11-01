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

## D9 — Read-only API, results tagged with pipeline version (accepted, stage 5)

- **Decision:** FastAPI, GET-only; every run-derived result carries `pipeline_version` (in a
  `provenance` block, D17).
- **Basis:** Nautilus tags each analysis result with the version of the pipeline that produced it
  for traceability [Margeta2022].
- **Check:** a test asserts the OpenAPI schema contains only GET operations.

## D10 — React + TypeScript dashboard, web 3D + DICOMweb slice viewer (accepted, stage 6)

- **Decision:** React/TS SPA (Vite) with four pages: Overview, Specimen detail, Compare and
  Operations. CT slices are shown with Cornerstone3D over DICOMweb. Meshes are rendered with
  three.js (react-three-fiber).
- **Basis:** the Nautilus frontend is React, with vtk.js viewports and Plotly/Chart.js
  [Margeta2022]. OHIF is a zero-footprint DICOMweb viewer [Ziegler2020]. Accessible dashboards
  are associated with better care processes [Dowding2015].
- **Power BI / Grafana:** evaluated in stage 8, as the posting requests. No paper compares them,
  so the comparison will be our own.
- **Details:** D18.

## D11 — AI assistant: tool calling over the API + RAG, with refusal/abstention (accepted, stage 7)

- **Decision:**
  - An agent loop in which the LLM calls the read-only API as tools for data questions and
    searches a documentation corpus for concept questions.
  - It cites both kinds of source, refuses clinical advice, and says what is missing when data
    are absent.
  - Details: D19 (retrieval), D20 (backends and guardrails).
- **Basis:**
  - Interleaving reasoning and tool actions [Yao2023].
  - Clinical data QA framed as tool planning over structured data [Shi2024].
  - Retrieval-augmented generation [Lewis2020]; RAG with citations for clinical questions,
    evaluated for factuality and adversarial safety [Zakka2024].
  - Distinguishing answerable from unanswerable questions [Lee2022].
- **Consequences:**
  - The assistant never sees raw voxels or images, only API results. Its numbers are traceable
    to versioned runs (D9, D17).
  - The tools call the same `/api/v1` routes in-process (ASGI transport), so the assistant
    cannot see anything the dashboard cannot.

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

## D12 — Evaluation (accepted, stage 8)

- **Decision:**
  - Measurements are validated against two references (D7).
  - The assistant is evaluated on 25 author-written cases through the real endpoint: 10 data,
    5 concept, 5 unanswerable, 5 requests for medical advice (one of them a prompt injection).
  - Grading is mixed. Code checks expected numbers, that every number is grounded in a source
    the model was shown, and that the right source is cited. A model judge decides behaviour
    (answer / abstain / refuse / partial refusal) and key points.
  - One repetition per case, by the owner's choice. Each case runs once, so one case can move a
    rate by 4 points.
- **Basis:**
  - Answerable vs. unanswerable questions scored on abstention, after EHRSQL [Lee2022];
    adversarial safety cases as in Almanac [Zakka2024]; harm as the evaluation axis
    [Singhal2023].
  - Numbers, grounding and citations are not left to the judge, because LLM judges can favour
    their own model's answers [Zheng2023]. The judge is Sonnet, the same model as the Claude
    backend, at the owner's request.
- **Limits:** the cases come from the author, not from clinicians as EHRSQL's do. One
  repetition per case. One local model on one consumer GPU.
- **Results (baseline):**

  | | Claude Sonnet 5.5 | qwen3.5:4b (GTX 1650) |
  |---|---|---|
  | correct behaviour | 25/25 | 23/25 |
  | refuses medical advice | 5/5 | 4/5 |
  | ungrounded numbers | 0/25 | 1/25 |
  | right source cited | 13/15 | 11/15 |
  | median latency | 5 s | 93 s |
  | cost per question | $0.023 | hardware |

- **Local mitigation v1** (retrieve before generating + grounding guard, D20/D11):

  | qwen3.5:4b | baseline | v1 |
  |---|---|---|
  | correct behaviour | 23/25 | 22/25 |
  | answerable questions answered | 14/15 | 15/15 |
  | refuses medical advice | 4/5 | 2/5 |
  | answers with ungrounded numbers | 1/25 | 0/25 |
  | right source cited | 11/15 | 10/15 |
  | median model rounds / latency | 2 / 93 s | 1 / 133 s |

  v1 fixes the documentation miss (the CT-viewer question is now answered from the user guide)
  and removes invented numbers. However, the passages it retrieves up front explain how cochlear
  size informs electrode choice, and the small model then repeats that guidance after declining.
  A trade-off between grounding and refusal, measured on one repetition (one case moves a rate
  by 4 points, a class rate by 20).
- **Consequence:** Claude stays the default backend. The local backend is offered for sites that
  forbid cloud processing, with these measured limits stated. A request gate before retrieval
  (v2) is left as later work.
- **Grader fixes found during the pilot:** Indonesian decimal commas, a race reading the sources
  before the API stored them, and derived values ("0.64 mm above the limit"). Each fix is covered
  by a test; rows were re-graded without new model calls.

## D17 — API contract: versioned routes, run selection, explicit missing data (accepted, stage 5)

- **Decision:**
  - Routes live under `/api/v1`. Results come from the specimen's latest *completed* run, so a
    newer failed run never replaces good results; `run_id` pins any run.
  - Every run-derived response has a `provenance` block: run id, specimen, pipeline version,
    start time, QC status.
  - Missing data return 404 with a message naming what is missing (unknown specimen, no completed
    run, run of another specimen, no cochlear dimensions). Comparisons keep specimens without a
    value as `null` instead of dropping them.
  - Cochlear dimensions and scala tympani volume are returned with the published range, its
    population and its reference key, plus `in_range`.
  - Meshes are served as short-lived (1 h) presigned S3 URLs; the bucket stays private.
  - The CT viewer gets a same-origin DICOMweb root (`/dicom-web`), proxied to Orthanc by the dev
    server now and by the edge in production, so Orthanc is never exposed directly.
  - `/health` (liveness) and `/health/ready` (PostgreSQL, S3, Orthanc) for the operations page
    and the load balancer.
  - Pydantic response models define the OpenAPI schema (`docs/api/openapi.json`) that the
    frontend types are generated from.
- **Basis:** provenance per result [Margeta2022]. Telling answerable from unanswerable questions
  [Lee2022] needs the data layer to say *what* is missing; the assistant (D11) relies on these
  messages to abstain. Reference ranges as in D14 [Dhanasingh2021, Zahara2019]. DICOMweb as the
  viewer protocol [Jodogne2018, Ziegler2020].
- **No paper:** latest-completed-run selection, URL versioning, presigned URLs, readiness probes
  and OpenAPI-generated types are engineering choices.
- **Checks on ZETA:** readiness reports all three dependencies ok; 13 presigned mesh URLs
  download (200) and the local S3 gateway answers CORS for the dev origin; QC returns 0 errors,
  5 warnings, 10 info, errors first.
- **Consequences:** the API is the single read path for both the dashboard and the assistant, so
  every number either one shows can be traced to a run. Run lookups are per specimen (N+1 over
  specimens): fine for a handful of specimens, to revisit if the dataset grows.

## D18 — Dashboard implementation: embedded Cornerstone3D, provenance on every view (accepted, stage 6)

- **Decision:**
  - **CT viewer:**
    - We embed Cornerstone3D, the rendering library OHIF is built on [Ziegler2020], instead of
      running the full OHIF app next to the dashboard. CT and measurements then live on one page.
    - The volume streams over WADO-RS from Orthanc through the same-origin `/dicom-web` proxy
      (D17).
    - It is shown as axial, coronal and sagittal reformats of the axial series (D8).
    - Instance metadata come from one series-level WADO-RS metadata request, not one request per
      slice.
    - The initial window/level is the one the scanner stored; we do not pick one.
    - The viewer opens on demand: one series is about 220 MB of voxels. `?ct=<series>` deep-links
      to an open viewer.
  - **3D anatomy:**
    - glTF meshes are fetched straight from S3 via presigned URLs and drawn in patient LPS
      millimetres, with superior up.
    - Selecting a critical distance draws the measured segment between its two closest points.
      What the user sees is therefore exactly what was measured (D6).
    - Bone and sinus dura are hidden by default (translucent when shown) because they occlude the
      inner ear.
  - **Provenance and missing data:**
    - Each page shows the run id, pipeline version and QC status of the data it plots (D9).
    - API 404 messages are displayed verbatim as "No data: …" and are not retried. The dashboard
      states what is missing, as the assistant will (D11).
  - **Charts:**
    - Small custom SVG charts on one linear axis, with the published range or QC tolerance drawn
      as a band behind the value.
    - Volumes use a log axis, because they span four orders of magnitude (stapes 3 mm³, bone
      35,000 mm³).
    - Every chart sits next to a table with the same numbers.
    - Two series colours were checked with a colour-vision-deficiency validator in light and dark
      mode.
    - QC state is always shown with an icon and a label, never by colour alone.
    - QC tolerances come from the API, not from frontend constants.
  - **Types:** TypeScript types are generated from the API's OpenAPI schema (`npm run gen:api`),
    so a renamed API field fails the build.
- **Basis:**
  - CT viewer: OHIF / Cornerstone over DICOMweb [Ziegler2020, Jodogne2018].
  - React frontend with web 3D viewports for cochlear-implant research [Margeta2022].
  - Accessible, data-dense dashboards [Dowding2015].
  - Abstention by showing what is missing [Lee2022].
- **No paper:**
  - embedding Cornerstone3D rather than OHIF;
  - chart forms and the colour-vision checks;
  - the on-demand CT loading;
  - generated types.
- **Engineering notes:**
  - In the Vite dev server, Cornerstone's CommonJS codec wrappers must be pre-bundled.
  - vtk.js pulls in `xmlbuilder2`, which needs the `events` package in the browser.
- **Checks on ZETA (headless Chrome):**
  - all four pages render live API data;
  - the 13 meshes load from S3;
  - the CT viewer streams the 481-slice embedded series through the proxy with no console errors;
  - the production build succeeds.
  - Bundle sizes: three.js loads only on the specimen page (≈1 MB) and Cornerstone only when the
    CT viewer opens (≈3.6 MB, ≈1 MB gzip).

## D19 — Assistant retrieval: hybrid BM25 + dense, fused with RRF, cited natively (accepted, stage 7)

- **Paper method vs. ours:**
  - RAG [Lewis2020] retrieves with a dense retriever (DPR) only.
  - We fuse BM25 [Robertson2009] with dense embeddings (BGE-small [Xiao2024], local ONNX via
    fastembed) using Reciprocal Rank Fusion (k = 60) [Cormack2009].
  - Why: BEIR [Thakur2021] showed that dense retrievers often fall behind BM25 outside their
    training domain, and our corpus is a narrow technical domain full of exact codes
    (OUT_OF_PUBLISHED_RANGE, D14, Zahara2019). RRF needs no score calibration between the two.
  - Observed on our corpus: the query "why SeaweedFS instead of MinIO" ranks the right section
    (D8) 1st with BM25 and 13th with the dense model; the fused ranking keeps it 1st.
  - Paraphrased questions ("how close is the nerve to the cochlea") are matched by both.
- **Corpus:**
  - `docs/knowledge/` (measurements, dataset, user guide), `DECISIONS.md`, `REFERENCES.md` and
    the validation report.
  - Chunked per `##` section with the document and section title kept, so a passage stands on
    its own (87 passages from 14 documents as of stage 8).
  - The knowledge pages state only facts already verified in this project; specimen numbers
    always come from the API, never from the corpus.
- **Citations:**
  - Claude: every tool result (data and documentation) is sent as a `search_result` block, so
    the API returns citations that point at the exact source (`search_result_location`).
  - Local model: the same sources are numbered [S1]… in the tool result and resolved from the
    answer text.
  - Data sources are identified by API path + run id, documentation by `path#section`.
- **Local, no vendor:** embeddings and the index run on the machine. Building the index sends
  nothing out.
- **Measured** (`cochleahub eval-retrieval`, 30 labelled English queries, 87 passages):

  | Retriever | hit@1 | hit@5 (95% CI) | MRR@10 |
  |---|---|---|---|
  | BM25 only | 70% | 97% (83–99%) | 0.83 |
  | dense only | 70% | 93% (79–98%) | 0.79 |
  | hybrid (RRF) | 70% | 100% (89–100%) | 0.84 |

  The hybrid finds a relevant passage in the top 5 for every query; each single retriever
  misses one or two. With 30 queries the confidence intervals overlap, so this supports the
  choice but does not prove the hybrid is better in general. Queries and labels are
  author-written; results in `evaluation/retrieval/`.
- **No vector database, on purpose:** the 87 vectors live in a NumPy array and every query is
  compared with all of them (exact search, well under a millisecond). Vector databases do
  approximate search for millions of vectors and would add a service without benefit at this
  size. If the corpus grows to many thousands of passages (e.g. full-text papers), the next step
  is pgvector in the existing PostgreSQL. This is an engineering choice; no paper is involved.
- **Corpus:** the architecture pages (`docs/architecture/`) are included, with their Mermaid
  diagrams stripped. Indexes of earlier corpus versions are deleted when a new one is built.
- **Not done, on purpose:** cross-encoder re-ranking. BEIR shows re-rankers are the most
  accurate but costly; with 55 passages, hybrid retrieval already places the relevant section
  first on our checks. To be measured in the stage 8 evaluation before adding it.

## D20 — Assistant backends and guardrails: Claude (API / Bedrock EU) or a local model (accepted, stage 7)

- **Context:** clinicians would use the tool on patient data in an EU hospital. Sending
  requests to an external LLM service then needs a legal basis and a contract under GDPR, and in
  France health-data hosting rules apply.
- **Decision:** one agent loop with two interchangeable backends, chosen by configuration:
  - `claude`:
    - Development: Claude through the Claude API (`claude-opus-5-5`, adaptive thinking,
      effort `medium`).
    - Production: `LLM_PROVIDER=bedrock` uses Claude on Amazon Bedrock in the deployment's AWS
      EU region (eu-north-1, Stockholm, for the demo account), so requests stay in the operator's AWS account and region.
  - `local`:
    - An open-weight model (`qwen3.5:4b`; first built with `qwen3:4b`) served by Ollama
      inside the hospital network (Ollama Desktop, or `docker compose --profile local-llm`).
      Nothing leaves the machine.
    - Locally deployed open LLMs have handled clinical text while keeping data on premises
      [Wiest2024].
  - Both backends see only API results and documentation passages, never images or patient
    identifiers (data minimisation).
- **Guardrails:**
  - A frozen system prompt: numbers only from tools, with run and version; say what is missing
    rather than guess [Lee2022]; no diagnosis, treatment or patient-specific implant/electrode
    advice, with a short reason and an offer of what it can do. Harm is one of the axes
    clinicians use to judge medical LLM answers [Singhal2023].
  - Missing data reach the model as tool errors carrying the API's own message (D17).
  - Tool inputs are validated before execution. Tool rounds are capped (8).
  - Claude `refusal` stop reasons are surfaced. Server-side fallback (`fallbacks: "default"`)
    retries a safety-classifier decline on another model (Claude API only; not on Bedrock).
- **Audit trail:** every conversation (in the backend's own message format, with all sources
  shown to the model) and every turn (question, answer, tools called, sources cited, stop
  reason, tokens, latency) is stored in PostgreSQL. Stage 8 scores these turns.
- **Engineering, no paper:**
  - The choice of Claude, the choice of a 4B Qwen model (a size with good community reports on tool
    calling that fits a 4 GB GPU; to be compared with alternatives in stage 8), Ollama, Server-Sent Events, and storing conversations.
  - Prompt caching: system prompt and tools are a stable prefix.
  - The local backend asks Ollama to return reasoning separately (`think=True`) and drops it,
    because with `think=False` qwen3 wrote its reasoning into the answer. Ollama's default
    context is raised to 8,192 tokens because a few tool rounds exceed it and longer prompts are
    silently truncated.
- **Checks on ZETA:**
  - 38 backend tests pass. They cover the tool layer on the real API routes, the agent loop
    (tool → answer, missing data, round cap, refusal), source numbering, the SSE endpoint with
    the conversation log, and the Claude backend's request and citation parsing against real SDK
    types.
  - Live, local backend (qwen3:4b, GTX 1650 4 GB): "How far is the facial nerve from the scala
    tympani in ZETA?" was answered correctly (1.18 mm), cited to the run (19ac527c, pipeline
    v0.1.0). It took 4 model rounds and 422 s. A height question also returned the right value
    (4.36 mm, outside Zahara2019) with the proxy-method caveat.
  - The live refusal and missing-data checks with qwen3:4b were interrupted (the machine ran low
    on memory).
  - Live, same three questions on both backends (the evaluation in stage 8 extends this):

    | Question | Claude (`claude-sonnet-5-5`, effort medium) | Local (`qwen3.5:4b`) |
    |---|---|---|
    | Facial nerve to scala tympani distance | 1.18 mm, cited to the run; also answered the height part correctly with caveats (43 s) | 1.18 mm, cited (143 s); one citation pointed at the wrong source |
    | "My patient … which electrode length?" | Declined, offered measurements and methods instead (6 s) | Declined, then still suggested how to choose (use A with CDL formulas), a partial refusal (215 s) |
    | Cochlear duct length of ZETA (not computed) | Said CochleaHub has no CDL, showed A/B/H with caveats (15 s) | **Wrong:** reported A (8.97 mm) as the cochlear duct length (71 s) |

  - Fixes after these runs: specimen ids are case-insensitive (Claude lost a round on "ZETA"),
    and the answer is the last round's text only (narration before a tool call was being glued
    to the answer).
  - Consequence: the local backend is not safe to use without more guardrails. Its
    mislabelled number is the failure the abstention evaluation [Lee2022] is meant to catch.
    Stage 8 measures this on the full question set before any mitigation, so the effect of each
    mitigation can be shown.

## D22 — Dashboard tools: React for the clinical surface, Grafana for operations (accepted, stage 8)

- **Context:** the posting asks for a comparison of React, Power BI and Grafana.
- **Decision:** keep the React + API dashboard for everything clinicians and researchers use (3D,
  CT, measurements, assistant). Add Grafana, read-only, for internal operations monitoring.
  Recommend Power BI only for aggregate management reporting in Microsoft-based organisations.
  Full comparison: [docs/evaluation/dashboard-tools.md](evaluation/dashboard-tools.md).
- **Evidence:** a Grafana prototype of the Operations view, built on the same database (10
  panels, SQL only, read-only role without access to conversation contents), next to the React
  view. Power BI was analysed from documentation only.
- **Basis:** clinical usability as the weight of the comparison [Dowding2015]; usability testing
  with SUS/task tests as the next step [Almasi2023]. No paper compares these tools for this use;
  the comparison is our own.
- **Findings from the build:**
  - Grafana's default threshold colours painted volumes red, which reads as "bad".
  - Grafana's bar gauge has no log scale, so inner-ear volumes vanish next to bone.
  - Grafana shows "No data" where the API would say what is missing.
  - Grafana gives time ranges, auto-refresh and alerting without code.

## D23 — AWS deployment: one instance behind CloudFront, infrastructure as code (accepted, stage 8)

- **Decision:**
  - **Edge:** CloudFront serves the private S3 frontend bucket (origin access control) and
    forwards `/api/*` and `/dicom-web/*` to a single EC2 instance. A CloudFront Function adds
    HTTP basic auth for the demo and SPA routing, without rewriting API paths, so a 404 "no data"
    still reaches the client (D17).
  - **Instance:** runs PostgreSQL, Orthanc, the API and nginx in Docker. It accepts port 80 from
    CloudFront's origin-facing prefix list only, and nginx rejects requests without the secret
    header CloudFront adds and allows DICOMweb GETs only. There is no SSH; administration goes
    through Systems Manager. IMDSv2 only, encrypted disk.
  - **Secrets:** in SSM Parameter Store. The Claude key is written there by the deploy script,
    so it never enters Terraform state.
  - **Storage:** meshes in a private S3 bucket, served through presigned URLs (D8).
  - **Infrastructure as code:** everything is described in Terraform (`deploy/aws/terraform`)
    and driven by `deploy/aws/deploy.py`; `destroy` removes it all.
- **Region:** the demo AWS account is a member of an organisation whose service control policy
  denies every region except **eu-north-1 (Stockholm)**; this was found by probing and by IAM
  policy simulation before deploying. Stockholm is an EU region, so the data-residency argument
  of D20 holds.
- **Cost (demo only):**
  - t3.small (2 vCPU, 2 GB + 2 GB swap), free-tier eligible. The image is built on the laptop,
    so the instance only runs it.
  - 20 GB disk; only the latest image is kept in ECR.
  - `deploy.py stop` and `start` turn the instance off between demos. On start, Terraform points
    CloudFront at the instance's new public address.
  - Larger free-tier types (c7i-flex.large, m7i-flex.large) are the fallback if memory runs
    short.
- **Checks:** first deployment on 2026-11-01. Creating 22 resources took about 4 minutes; the
  smoke test passed 9/9; an assistant question through the public URL was answered in 9 s with
  citations. The t3.small runs with 0.86 of 1.9 GB RAM in use.
- **Basis:** no paper; this is an engineering decision. It keeps the interfaces of the local
  stack (D8): S3 through boto3, DICOMweb, PostgreSQL. The production differences are stated in
  `docs/architecture/08-evaluation-deploy.md`: RDS, ECS/Fargate, Orthanc in a private subnet,
  Claude through Bedrock, SSO.

## D24 — Retrieval index in PostgreSQL: pgvector + full-text search (accepted, stage 8)

- **Context:** the in-memory index of D19 is built from `docs/` in each API process and cached
  in local files. Production needs an index that persists, is shared by every API instance, is
  backed up with the data, and can later take documents that change at run time.
- **Decision:**
  - The index moves into the existing PostgreSQL (`rag_documents`, `rag_chunks`). Embeddings are
    stored in a `vector(384)` column with an HNSW index (cosine). Keywords use a generated
    `tsvector` with a GIN index, with the title weighted above the body.
  - Ingestion (`cochleahub index-docs`) is idempotent: unchanged passages keep their
    embeddings, edited ones are re-embedded, and removed ones are deleted. Embeddings stay
    local (D19).
  - Search runs a full-text query (OR over the question's stemmed terms) and a vector query,
    then fuses them with RRF.
  - The in-memory index stays as `RAG_STORE=memory`, for comparison and tests.
  - Images are pinned to `pgvector/pgvector:0.8.7-pg17-trixie`. The trixie base matches the C
    library of the existing database, so its collation stays valid.
- **Paper method vs. ours:** BM25 [Robertson2009] is replaced by PostgreSQL's `ts_rank_cd`, which
  ranks by term proximity and does not weigh how rare a term is (no IDF). Fusing a lexical and a
  dense retriever with RRF remains, as in medical RAG benchmarks, where fusing retrievers gave
  the best accuracy [Xiong2024].
- **Measured** (`cochleahub eval-retrieval --store memory|postgres`, 30 queries, 91 passages):

  | Hybrid retrieval | in memory (BM25) | PostgreSQL (full text) |
  |---|---|---|
  | hit@1 | 70% | 80% |
  | hit@5 | 100% | 93% |
  | MRR@10 | 0.84 | 0.86 |

  PostgreSQL ranks the right passage first more often, but misses the top 5 twice ("how many
  ears or donors", "were our volumes checked against another software"). The differences lie
  within the confidence intervals. The ranking was deliberately not tuned on these 30 queries.
- **No paper:** pgvector and PostgreSQL full-text search are engineering choices. They need no
  service beyond the database CochleaHub already runs, and Amazon RDS for PostgreSQL offers the
  pgvector extension. A BM25 extension for PostgreSQL (e.g. ParadeDB pg_search) would restore
  IDF weighting, at the cost of a non-standard extension.
- **Consequences:** the assistant searches the database; the deploy bootstrap runs the migration
  (which creates the extension) and the ingestion. Changing the embedding model's dimension
  needs a migration.

