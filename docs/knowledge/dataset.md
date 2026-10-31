# The OpenEar dataset and specimen ZETA

Background for the assistant's retrieval corpus (D19).

## What ZETA is

ZETA is one specimen of the OpenEar library [Sieber2019]: a single cadaveric human temporal bone
(right ear) from one donor. It is not a patient cohort. The dataset is large (about 10 GB
extracted) because the same bone was imaged many times at high resolution, not because it holds
many ears: about 90 % of the size is 222 microscope photographs of physical slices.

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
  meshes lie on average 0.05-0.1 mm from the dataset's published meshes (D7).
- Not done: an independent check of anatomical accuracy. CochleaHub uses the dataset's
  segmentation as given (D2); it does not segment the CT itself.

## Folders

- 01_CBCT_Unembedded, 02_CBCT_Embedded: CBCT DICOM series. X/Y/Z folders are the same scan
  resliced; CochleaHub archives the axial series in Orthanc (481 and 401 slices).
- 03_Microslicing_Raw: 222 slice photographs (.tif).
- 04_Reconstruction_Microslicing, 05_Registred_Slicer_Volumes: reconstructed and registered
  volumes at 0.125 mm, plus the accuracy analysis.
- 06_Segmentation: 13-structure segmentation at 0.125 mm.
- 07_3D_Models: one surface mesh per structure.

## Segmented structures

Scala Tympani, Scala Vestibuli, Malleus, Incus, Stapes, Cochleovestibular nerve, Facial Nerve,
Chorda Tympani, Bone, Tympanic Membrane, External Auditory Canal, Sinus Dura, Carotis Interna.
The "Scala Vestibuli" label appears to include the vestibule and semicircular canals (152 mm³,
18 mm long), so cochlear dimensions use the scala tympani only (D5).

## Limits for interpretation

- One specimen: no statistics across ears are possible from CochleaHub data alone; comparisons
  use published ranges from other studies.
- Cadaveric and embedded: tissue handling can change geometry slightly.
- CBCT at 0.125 mm is finer than typical clinical CT, so values may not transfer one-to-one to
  clinical scans.
