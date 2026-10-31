# CochleaHub user guide

Background for the assistant's retrieval corpus (D19).

## Pages

- Overview: number of specimens, QC errors and warnings of the latest runs, service status
  (database, object store, DICOM archive), and the specimen list.
- Specimen: 3D anatomy viewer, critical distances, cochlear size against the published range, CT
  slices and the structure measurement table.
- Compare: one metric across specimens against a published range where one exists.
- Operations: pipeline runs, QC flags with a severity filter, and validation charts against 3D
  Slicer and the dataset's meshes.
- Assistant: questions about the data and the methods, answered with sources.

## 3D anatomy viewer

Drag to rotate, scroll to zoom, right-drag to pan. Tick structures on the right to show or hide
them. Bone and sinus dura are hidden by default and translucent when shown, because they hide
the inner ear. Click a row in "Critical distances" to draw that distance as a yellow segment
between its two closest points. Coordinates are patient LPS millimetres, superior up.

## CT viewer

Choose a series and press "Load CT". The series streams from the DICOM archive over DICOMweb and
is shown as axial, coronal and sagittal views of one volume. Mouse wheel: change slice. Left
drag: window/level. Middle drag: pan. Right drag: zoom. A link with `?ct=<series>` opens the
viewer directly. The initial window/level is the one stored by the scanner.

## Reading the charts

Each chart has a table with the same numbers next to it. A shaded band is a published range or a
QC tolerance; a dot is a measured value. Volumes use a logarithmic axis because they span four
orders of magnitude. QC states always show an icon and a label.

## Provenance

Every page shows which pipeline run and version its numbers come from. A newer failed run never
replaces the results of the latest completed run.

## The assistant

The assistant answers from the API (measurements, distances, QC, validation) and from this
documentation, and cites both. It says when data are missing instead of guessing, and it does not
give medical advice or patient-specific recommendations. Two backends exist: Claude (cloud, via
the Claude API or Amazon Bedrock in an EU region) and a local open-weight model that runs inside
the hospital network.
