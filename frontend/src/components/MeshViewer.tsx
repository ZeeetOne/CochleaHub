// 3D view of the segmented structures (D10, D13). Meshes are glTF in patient LPS millimetres,
// downloaded straight from S3 through presigned URLs; distance points use the same frame, so
// a measured distance is drawn exactly where it was computed.
import { Html, Line, OrbitControls, useGLTF } from '@react-three/drei'
import { Canvas } from '@react-three/fiber'
import { Suspense, useMemo, useState } from 'react'
import * as THREE from 'three'
import type { Distance, Schemas } from '../api/client'
import { fmt, rgb } from '../lib/format'

type Mesh = Schemas['Mesh']

// Large structures that hide the inner ear; off by default, shown translucent when on.
const CONTEXT = new Set(['Bone', 'Sinus Dura'])

function StructureMesh({ mesh, opacity }: { mesh: Mesh; opacity: number }) {
  const { scene } = useGLTF(mesh.url)
  const object = useMemo(() => {
    const clone = scene.clone(true)
    const material = new THREE.MeshStandardMaterial({
      color: new THREE.Color(...(mesh.color as [number, number, number])),
      roughness: 0.6,
      metalness: 0.05,
      transparent: opacity < 1,
      opacity,
      depthWrite: opacity === 1,
      side: THREE.DoubleSide,
    })
    clone.traverse((o) => {
      if ((o as THREE.Mesh).isMesh) (o as THREE.Mesh).material = material
    })
    return clone
  }, [scene, mesh.color, opacity])
  return <primitive object={object} />
}

function DistanceMarker({ d }: { d: Distance }) {
  const a = d.point_a_lps_mm as [number, number, number]
  const b = d.point_b_lps_mm as [number, number, number]
  const mid = a.map((v, i) => (v + b[i]) / 2) as [number, number, number]
  return (
    <group>
      <Line points={[a, b]} color="#ffd400" lineWidth={3} depthTest={false} />
      {[a, b].map((p, i) => (
        <mesh key={i} position={p} renderOrder={10}>
          <sphereGeometry args={[0.12, 16, 16]} />
          <meshBasicMaterial color="#ffd400" depthTest={false} />
        </mesh>
      ))}
      <Html position={mid} center>
        <div className="distance-label">
          {d.from_structure} → {d.to_structure}: {fmt(d.distance_mm)} mm
        </div>
      </Html>
    </group>
  )
}

export function MeshViewer({
  meshes,
  center,
  distance,
}: {
  meshes: Mesh[]
  center: [number, number, number]
  distance: Distance | null
}) {
  const [visible, setVisible] = useState(
    () => new Set(meshes.filter((m) => !CONTEXT.has(m.structure)).map((m) => m.structure)),
  )
  const toggle = (name: string) =>
    setVisible((prev) => {
      const next = new Set(prev)
      if (next.has(name)) next.delete(name)
      else next.add(name)
      return next
    })
  const camera = useMemo(
    () => ({
      position: [center[0] + 35, center[1] - 45, center[2] + 20] as [number, number, number],
      up: [0, 0, 1] as [number, number, number], // LPS: +z is superior
      near: 0.1,
      far: 2000,
      fov: 35,
    }),
    [center],
  )

  return (
    <div className="viewer-layout">
      <div className="viewer">
        <Canvas camera={camera}>
          <color attach="background" args={['#111']} />
          <ambientLight intensity={0.6} />
          <directionalLight position={[center[0] + 50, center[1] - 50, center[2] + 80]} intensity={1.6} />
          <directionalLight position={[center[0] - 50, center[1] + 50, center[2] - 40]} intensity={0.5} />
          {meshes
            .filter((m) => visible.has(m.structure))
            .map((m) => (
              <Suspense key={m.structure} fallback={null}>
                <StructureMesh mesh={m} opacity={CONTEXT.has(m.structure) ? 0.18 : 1} />
              </Suspense>
            ))}
          {distance && <DistanceMarker d={distance} />}
          <OrbitControls target={center} makeDefault />
        </Canvas>
        <span className="pane-label">Drag to rotate · scroll to zoom · right-drag to pan · LPS mm</span>
      </div>
      <div className="structure-list" aria-label="Structures">
        {meshes.map((m) => (
          <label key={m.structure} className="check">
            <input type="checkbox" checked={visible.has(m.structure)} onChange={() => toggle(m.structure)} />
            <span className="swatch" style={{ background: rgb(m.color) }} />
            {m.structure}
            {CONTEXT.has(m.structure) && <span className="prov">(translucent)</span>}
          </label>
        ))}
      </div>
    </div>
  )
}
