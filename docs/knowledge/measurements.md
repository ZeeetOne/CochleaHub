# What CochleaHub measures and why

Background for the assistant's retrieval corpus (D19). Numbers for a specimen always come from
the API, never from this page; this page explains what the numbers mean.

## Cochlear implant context

A cochlear implant electrode array is inserted into the scala tympani, one of the fluid-filled
ducts of the cochlea, to stimulate the auditory nerve. Before surgery, cochlear size helps choose
the electrode length, and the position of nearby structures (facial nerve, chorda tympani)
matters for the surgical approach. CochleaHub is a research tool on cadaveric data: it explains
measurements, it does not recommend treatment for a patient.

## Structure volume

Volume of a segmented structure in mm³, counted from voxels of the 0.125 mm segmentation (one
voxel = 0.001953 mm³). Scala tympani volume is related to electrode insertion force; published
adult cadaveric micro-CT values span 23-50 mm³ (µL) [Dhanasingh2021]. Volumes are identical to
3D Slicer's Segment Statistics because both count the same voxels (validation, D7).

## Surface area

Area of the smoothed surface mesh in mm² (marching cubes + Taubin smoothing, D13). Thin
structures (stapes, chorda tympani) are sensitive to smoothing, so their area can differ from
3D Slicer by more than 10 %; the QC flag AREA_METHOD_SENSITIVE marks this. Bone and sinus dura
are meshed on a coarser grid, so no area is reported for them.

## Length, width, thickness

Edges of the structure's oriented bounding box, longest first. They describe overall shape; they
are not anatomical landmark measurements.

## Cochlear dimensions A, B and height

In clinical practice, A is the basal-turn diameter (round window to the opposite wall), B the
perpendicular width and H the cochlear height, measured on CT from anatomical landmarks. A is
used to estimate cochlear duct length and therefore electrode length [Schurzig2018,
Breitsprecher2022]. Published HRCT ranges in 36 ears of implant candidates aged 2-17:
A 8.17-9.33 mm, B 5.73-7.50 mm, H 2.80-3.72 mm [Zahara2019].

CochleaHub uses a landmark-free proxy: the oriented bounding box of the scala tympani (D5),
because the dataset's "Scala Vestibuli" label also covers the vestibule and semicircular canals.
The proxy is not identical to the landmark method; a value outside the published range is a QC
warning (OUT_OF_PUBLISHED_RANGE), not an error.

## Minimum distances between critical structures

Shortest distance between two surface meshes in mm, with the two closest points (LPS
coordinates) so the dashboard can draw the segment (D6).

- Facial nerve to scala tympani / scala vestibuli: how close the facial nerve runs to the
  cochlea and labyrinth. Injury to the facial nerve can cause facial palsy, so proximity matters
  for surgical planning [Noble2008].
- Chorda tympani to scala tympani: proximity of the chorda tympani to the cochlea.
- Facial nerve to chorda tympani: about 0 mm by anatomy, because the chorda tympani branches off
  the facial nerve. It is the branch point, not the width of the facial recess.

## Connected components

How many separate pieces a structure's segmentation has. A structure that should be one piece
but has stray voxels gets an info-level FRAGMENTED flag; it is a data-quality signal, not
anatomy.

## Quality-control flags (D14)

Every pipeline run is checked automatically. Severities: error (result unusable), warning (use
with care), info (worth knowing). Codes:

- RUN_NOT_COMPLETED, STRUCTURE_FAILED: the pipeline did not finish a run or a structure.
- FRAGMENTED: more than one connected component.
- MESH_NOT_WATERTIGHT, MESH_VOLUME_MISMATCH: the surface mesh is open or its volume differs
  from the voxel volume by more than 2 %.
- SLICER_VOXEL_MISMATCH, SLICER_VOLUME_MISMATCH: voxel count or volume differs from 3D Slicer
  (tolerance 1 %).
- AREA_METHOD_SENSITIVE: surface area differs from 3D Slicer by more than 10 %.
- SLICER_REFERENCE_MISSING: no Slicer reference was available.
- SURFACE_DEVIATES_FROM_DATASET_MESH: mean distance to the dataset's published mesh exceeds one
  voxel per meshing step.
- OUT_OF_PUBLISHED_RANGE: a value lies outside a published population range.

QC status of a run: pass (no flags above info), pass_with_warnings, or fail (any error).

## Provenance

Every result belongs to a pipeline run that records its pipeline version, start time and QC
status [Margeta2022]. Answers should quote the run and version they come from.
