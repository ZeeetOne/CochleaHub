// CBCT slice viewer over DICOMweb with Cornerstone3D, the rendering library behind OHIF
// [Ziegler2020] (D10). The series is fetched from Orthanc through the same-origin /dicom-web
// proxy (D17) and shown as axial / coronal / sagittal reformats of one volume, so the X/Y/Z
// folders of the dataset are not needed (D8).
import {
  Enums,
  RenderingEngine,
  cache,
  eventTarget,
  init as csInit,
  setVolumesForViewports,
  volumeLoader,
  type Types,
} from '@cornerstonejs/core'
import { init as dicomLoaderInit, wadors } from '@cornerstonejs/dicom-image-loader'
import {
  PanTool,
  StackScrollTool,
  ToolGroupManager,
  WindowLevelTool,
  ZoomTool,
  addTool,
  Enums as ToolEnums,
  init as toolsInit,
} from '@cornerstonejs/tools'
import { useEffect, useRef, useState } from 'react'
import type { Schemas } from '../api/client'

type Series = Schemas['ImagingSeries']

let initialised: Promise<void> | null = null
function initCornerstone() {
  initialised ??= (async () => {
    csInit()
    dicomLoaderInit({ maxWebWorkers: Math.min(navigator.hardwareConcurrency || 2, 4) })
    toolsInit()
    for (const tool of [WindowLevelTool, PanTool, ZoomTool, StackScrollTool]) addTool(tool)
  })()
  return initialised
}

type DicomJson = Record<string, { vr: string; Value?: unknown[] }>

/** One WADO-RS metadata request for the whole series, registered per frame so the
 * loader does not have to fetch headers again (as OHIF does). */
async function imageIdsFor(root: string, s: Series): Promise<string[]> {
  const base = new URL(root, window.location.origin).href.replace(/\/$/, '')
  const seriesUrl = `${base}/studies/${s.study_instance_uid}/series/${s.series_instance_uid}`
  const res = await fetch(`${seriesUrl}/metadata`, { headers: { Accept: 'application/dicom+json' } })
  if (!res.ok) throw new Error(`DICOMweb metadata: HTTP ${res.status}`)
  const instances = (await res.json()) as DicomJson[]
  return instances.map((m) => {
    const sop = m['00080018'].Value![0] as string
    const imageId = `wadors:${seriesUrl}/instances/${sop}/frames/1`
    wadors.metaDataManager.add(imageId, m as never)
    return imageId
  })
}

const VIEWS = [
  { id: 'axial', label: 'Axial', orientation: Enums.OrientationAxis.AXIAL },
  { id: 'coronal', label: 'Coronal', orientation: Enums.OrientationAxis.CORONAL },
  { id: 'sagittal', label: 'Sagittal', orientation: Enums.OrientationAxis.SAGITTAL },
] as const

export function CtViewer({ root, series }: { root: string; series: Series }) {
  const refs = useRef<(HTMLDivElement | null)[]>([])
  const [state, setState] = useState<{ phase: 'loading' | 'ready' | 'error'; detail?: string }>({
    phase: 'loading',
  })
  const [progress, setProgress] = useState(0)

  useEffect(() => {
    let cancelled = false
    const engineId = `ct-${series.series_instance_uid}`
    const groupId = `tools-${series.series_instance_uid}`
    const volumeId = `cornerstoneStreamingImageVolume:${series.series_instance_uid}`
    let engine: RenderingEngine | null = null
    let onImage: ((e: Event) => void) | null = null

    ;(async () => {
      try {
        await initCornerstone()
        const imageIds = await imageIdsFor(root, series)
        if (cancelled) return
        engine = new RenderingEngine(engineId)
        engine.setViewports(
          VIEWS.map((v, i) => ({
            viewportId: v.id,
            type: Enums.ViewportType.ORTHOGRAPHIC,
            element: refs.current[i]!,
            defaultOptions: { orientation: v.orientation, background: [0, 0, 0] as Types.Point3 },
          })),
        )
        const group = ToolGroupManager.createToolGroup(groupId)!
        for (const v of VIEWS) group.addViewport(v.id, engineId)
        group.addTool(WindowLevelTool.toolName)
        group.addTool(PanTool.toolName)
        group.addTool(ZoomTool.toolName)
        group.addTool(StackScrollTool.toolName)
        const B = ToolEnums.MouseBindings
        group.setToolActive(WindowLevelTool.toolName, { bindings: [{ mouseButton: B.Primary }] })
        group.setToolActive(PanTool.toolName, { bindings: [{ mouseButton: B.Auxiliary }] })
        group.setToolActive(ZoomTool.toolName, { bindings: [{ mouseButton: B.Secondary }] })
        group.setToolActive(StackScrollTool.toolName, { bindings: [{ mouseButton: B.Wheel }] })

        const volume = await volumeLoader.createAndCacheVolume(volumeId, { imageIds })
        if (cancelled) return
        const ids = new Set(imageIds)
        let loaded = 0
        onImage = (e: Event) => {
          const imageId = (e as CustomEvent<{ image?: { imageId: string } }>).detail.image?.imageId
          if (imageId && ids.has(imageId)) setProgress(++loaded / ids.size)
        }
        eventTarget.addEventListener(Enums.Events.IMAGE_LOADED, onImage)
        ;(volume as unknown as { load: () => void }).load()
        // initial window/level is the one stored by the scanner (WindowCenter/Width)
        await setVolumesForViewports(engine, [{ volumeId }], VIEWS.map((v) => v.id))
        engine.render()
        if (!cancelled) setState({ phase: 'ready' })
      } catch (e) {
        if (!cancelled) setState({ phase: 'error', detail: e instanceof Error ? e.message : String(e) })
      }
    })()

    return () => {
      cancelled = true
      if (onImage) eventTarget.removeEventListener(Enums.Events.IMAGE_LOADED, onImage)
      ToolGroupManager.destroyToolGroup(groupId)
      engine?.destroy()
      if (cache.getVolume(volumeId)) cache.removeVolumeLoadObject(volumeId)
    }
  }, [root, series])

  return (
    <div>
      <div className="mpr">
        {VIEWS.map((v, i) => (
          <div key={v.id} className="pane" onContextMenu={(e) => e.preventDefault()}>
            <span className="pane-label">{v.label}</span>
            <div ref={(el) => { refs.current[i] = el }} style={{ width: '100%', height: '100%' }} />
          </div>
        ))}
      </div>
      <p className="prov" style={{ marginTop: 8 }}>
        {state.phase === 'error' && <span role="status">Viewer error: {state.detail}. </span>}
        {state.phase !== 'error' &&
          (progress < 1 ? `Streaming ${series.n_instances} slices… ${Math.round(progress * 100)}% · ` : '')}
        Scroll: slice · left-drag: window/level · middle-drag: pan · right-drag: zoom ·{' '}
        {series.rows}×{series.columns}×{series.n_instances} voxels at {series.pixel_spacing_mm} mm
      </p>
    </div>
  )
}
