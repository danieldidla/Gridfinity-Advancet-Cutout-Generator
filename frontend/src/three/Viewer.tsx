import { Canvas } from '@react-three/fiber'
import { Grid, OrbitControls } from '@react-three/drei'
import { Suspense, useEffect, useMemo, useRef, useState } from 'react'
import * as THREE from 'three'
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js'
import { fetchPreview } from '../lib/api'
import { binSize, binTopZ } from '../lib/defaults'
import type { BinSettings, Cutout, Point } from '../lib/types'

interface ViewerProps {
  bin: BinSettings
  cutouts: Cutout[]
  selectedId: string | null
  /** Set while the user drags, so we show the proxy and hold off on rebuilding. */
  dragging: boolean
  showGrid: boolean
  onStatus: (status: { loading: boolean; error: string | null }) => void
  onCanvasReady?: (canvas: HTMLCanvasElement) => void
}

const loader = new GLTFLoader()

/** Geometry is authored with Z up; three.js is Y up, so the model is laid down. */
const MODEL_ROTATION: [number, number, number] = [-Math.PI / 2, 0, 0]

function useModel(bin: BinSettings, cutouts: Cutout[], dragging: boolean,
                  onStatus: ViewerProps['onStatus']) {
  const [geometry, setGeometry] = useState<THREE.BufferGeometry | null>(null)
  const etag = useRef<string | null>(null)
  const controller = useRef<AbortController | null>(null)
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)

  const payload = useMemo(
    () => JSON.stringify({ bin, cutouts: cutouts.filter((c) => c.enabled) }),
    [bin, cutouts],
  )

  useEffect(() => {
    // While a drag is in flight the proxy outline carries the feedback; kicking
    // off a rebuild per pointer move would only queue up work we throw away.
    if (dragging) return
    if (timer.current) clearTimeout(timer.current)

    timer.current = setTimeout(() => {
      controller.current?.abort()
      const abort = new AbortController()
      controller.current = abort
      onStatus({ loading: true, error: null })

      fetchPreview(JSON.parse(payload), etag.current, abort.signal)
        .then(({ buffer, etag: nextEtag }) => {
          etag.current = nextEtag
          if (!buffer) { onStatus({ loading: false, error: null }); return }
          const gltf = loader.parse(buffer, '', (parsed) => {
            let found: THREE.BufferGeometry | null = null
            parsed.scene.traverse((node) => {
              if (!found && node instanceof THREE.Mesh) found = node.geometry
            })
            if (found) {
              const g = found as THREE.BufferGeometry
              g.computeVertexNormals()
              setGeometry((previous) => { previous?.dispose(); return g })
            }
            onStatus({ loading: false, error: null })
          }, (error) => {
            onStatus({ loading: false, error: String(error) })
          })
          return gltf
        })
        .catch((error: unknown) => {
          if (error instanceof DOMException && error.name === 'AbortError') return
          onStatus({
            loading: false,
            error: error instanceof Error ? error.message : 'Vorschau fehlgeschlagen',
          })
        })
    }, 120)

    return () => { if (timer.current) clearTimeout(timer.current) }
  }, [payload, dragging, onStatus])

  useEffect(() => () => { controller.current?.abort() }, [])
  return geometry
}

/** Flat translucent footprint of a cutout, moved live while dragging. */
function CutoutProxy({ cutout, bin, highlighted }: {
  cutout: Cutout; bin: BinSettings; highlighted: boolean
}) {
  const shape = useMemo(() => {
    if (cutout.polygon.length < 3) return null
    const path = new THREE.Shape()
    cutout.polygon.forEach(([x, y]: Point, index) => {
      if (index === 0) path.moveTo(x, y)
      else path.lineTo(x, y)
    })
    path.closePath()
    for (const hole of cutout.holes) {
      if (hole.length < 3) continue
      const cut = new THREE.Path()
      hole.forEach(([x, y], index) => {
        if (index === 0) cut.moveTo(x, y)
        else cut.lineTo(x, y)
      })
      cut.closePath()
      path.holes.push(cut)
    }
    return path
  }, [cutout.polygon, cutout.holes])

  const geometry = useMemo(() => {
    if (!shape) return null
    return new THREE.ExtrudeGeometry(shape, {
      depth: Math.max(0.4, cutout.depth), bevelEnabled: false,
    })
  }, [shape, cutout.depth])

  useEffect(() => () => geometry?.dispose(), [geometry])
  if (!geometry) return null

  const top = binTopZ(bin)
  return (
    <mesh
      geometry={geometry}
      rotation={MODEL_ROTATION}
      position={[cutout.x, top - cutout.depth, -cutout.y]}
      renderOrder={2}
    >
      <meshStandardMaterial
        color={highlighted ? '#45bda6' : '#7dd3c0'}
        transparent
        opacity={highlighted ? 0.55 : 0.3}
        depthWrite={false}
      />
    </mesh>
  )
}

function Scene({ bin, cutouts, selectedId, dragging, showGrid, onStatus }: ViewerProps) {
  const geometry = useModel(bin, cutouts, dragging, onStatus)
  const { width, depth } = binSize(bin)
  const radius = Math.max(width, depth, binTopZ(bin))

  return (
    <>
      <ambientLight intensity={0.55} />
      <directionalLight position={[80, 160, 90]} intensity={2.1} castShadow={false} />
      <directionalLight position={[-90, 60, -70]} intensity={0.7} />
      <hemisphereLight args={['#9fb7c9', '#20242f', 0.5]} />

      {geometry && (
        <mesh geometry={geometry} rotation={MODEL_ROTATION} castShadow receiveShadow>
          {/* Flat shading, not smoothed normals: this is a CAD solid, and
              averaging normals across a triangulated flat floor smears the
              lighting into visible streaks. */}
          <meshStandardMaterial color="#c8ced8" roughness={0.62} metalness={0.06}
                                flatShading />
        </mesh>
      )}

      {dragging && cutouts
        .filter((c) => c.enabled && c.polygon.length >= 3)
        .map((c) => (
          <CutoutProxy key={c.id} cutout={c} bin={bin} highlighted={c.id === selectedId} />
        ))}

      {showGrid && (
        <Grid
          args={[420, 420]}
          cellSize={42}
          cellColor="#39414f"
          sectionSize={210}
          sectionColor="#4d5a72"
          fadeDistance={radius * 7}
          fadeStrength={1.2}
          infiniteGrid
          position={[0, -0.02, 0]}
        />
      )}

      <OrbitControls
        makeDefault
        enableDamping
        dampingFactor={0.12}
        minDistance={radius * 0.6}
        maxDistance={radius * 9}
        target={[0, binTopZ(bin) * 0.3, 0]}
      />
    </>
  )
}

export default function Viewer(props: ViewerProps) {
  const { width, depth } = binSize(props.bin)
  const radius = Math.max(width, depth, 60)

  return (
    <Canvas
      shadows={false}
      dpr={[1, 2]}
      gl={{ antialias: true, preserveDrawingBuffer: true }}
      // Deliberately steep: the pockets are the point, and a low three-quarter
      // view hides them behind the near wall.
      camera={{ position: [radius * 0.62, radius * 1.15, radius * 0.95], fov: 40, near: 1, far: 4000 }}
      onCreated={({ gl }) => props.onCanvasReady?.(gl.domElement)}
    >
      <color attach="background" args={['#14171f']} />
      <Suspense fallback={null}>
        <Scene {...props} />
      </Suspense>
    </Canvas>
  )
}
