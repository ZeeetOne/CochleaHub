# The OpenEar dataset and specimens ZETA and EPSILON

Background for the assistant's retrieval corpus (D19).

## What ZETA is

CochleaHub holds two specimens of the OpenEar library [Sieber2019], ZETA and EPSILON. Each is a
single cadaveric human temporal bone. The library has eight bones (Alpha to Theta) from four
adult donors. ZETA is a right ear (its CBCT folder says "rechts"). The dataset does not state
EPSILON's side, so CochleaHub reports it as unknown. Two specimens are not a patient cohort.
Each specimen was large (about 11 GB extracted) because the same bone was imaged many times at
high resolution, not because it holds many ears. About 90 % of that size was microscope
photographs of physical slices, which CochleaHub does not use or keep.

## How the reference segmentation was made

1. The bone was scanned with cone-beam CT (CBCT), before and after embedding in resin.
2. The embedded bone was cut into thin slices (micro-slicing); each slice was photographed.
3. The photographs were stacked into a 3D volume and registered to the CBCT.
4. Thirteen structures were segmented with the slice photographs as reference, which show
   anatomy far more clearly than CT.
5. An accuracy analysis compares CBCT-based and histology-based geometry.

This kind of reference is not available for living patients, which is why a single specimen is
still valuable for checking measurement methods.

## What CochleaHub validated, and what it did not

- Verified: the measurement code reproduces 3D Slicer's voxel volumes exactly, and our surface
  meshes lie on average 0.05-0.1 mm from the dataset's published meshes (D7). This holds for
  both specimens.
- Not done: an independent check of anatomical accuracy. CochleaHub uses the dataset's
  segmentation as given (D2); it does not segment the CT itself.

## Folders

- 01_CBCT_Unembedded, 02_CBCT_Embedded: CBCT DICOM series. X/Y/Z folders are the same scan
  resliced; CochleaHub archives the axial series in Orthanc (481 and 401 slices).
- 03_Microslicing_Raw, 04_Reconstruction_Microslicing: slice photographs and their 3D
  reconstruction. Not used by CochleaHub and not kept.
- 05_Registred_Slicer_Volumes: CBCT registered to the slices at 0.125 mm, plus the accuracy
  analysis.
- 06_Segmentation: 13-structure segmentation at 0.125 mm.
- 07_3D_Models: one surface mesh per structure.

## Segmented structures

Scala Tympani, Scala Vestibuli, Malleus, Incus, Stapes, Cochleovestibular nerve, Facial Nerve,
Chorda Tympani, Bone, Tympanic Membrane, External Auditory Canal, Sinus Dura, Carotis Interna.
The "Scala Vestibuli" label appears to include the vestibule and semicircular canals (ZETA
152 mm³ and 18 mm long, EPSILON 167 mm³), so cochlear dimensions use the scala tympani only
(D5). The two specimens name some structures differently (EPSILON: "Carotis", "EAC",
"Sinus - Dura", "Vestibulcochlear Nerve"). CochleaHub maps every label onto one list of 13
coded structures and shows the names above. A label it does not know is flagged for review
rather than guessed (D26).

## Limits for interpretation

- Two specimens: no statistics across ears are possible from CochleaHub data alone; comparisons
  use published ranges from other studies. Differences between ZETA and EPSILON can reflect
  anatomy or how each was segmented.
- Cadaveric and embedded: tissue handling can change geometry slightly.
- CBCT at 0.125 mm is finer than typical clinical CT, so values may not transfer one-to-one to
  clinical scans.
