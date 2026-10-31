import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// The browser only ever talks to this origin: /api goes to FastAPI and /dicom-web to Orthanc's
// DICOMweb plugin, so Orthanc is never reached directly (D8, D17). In production the edge
// (CloudFront / load balancer) does the same routing.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': 'http://localhost:8000',
      '/dicom-web': 'http://localhost:8042',
    },
  },
  // Cornerstone's image loader ships web workers and must not be pre-bundled; its WASM codec
  // wrappers are CommonJS and must be, so the dev server can serve them as ES modules.
  optimizeDeps: {
    exclude: ['@cornerstonejs/dicom-image-loader'],
    include: [
      'dicom-parser',
      'pako',
      '@cornerstonejs/codec-libjpeg-turbo-8bit/decodewasmjs',
      '@cornerstonejs/codec-charls/decodewasmjs',
      '@cornerstonejs/codec-openjpeg/decodewasmjs',
      '@cornerstonejs/codec-openjph/wasmjs',
      '@cornerstonejs/codec-libjxl/decodewasmjs',
    ],
  },
  worker: { format: 'es' },
})
