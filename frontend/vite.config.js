import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    // Allow Vite dev server to read files outside the project root
    // (HelpPage imports docs/user-manual.md from the repo root).
    fs: { allow: ['..'] },
  },
  build: {
    outDir: 'dist',
    sourcemap: false,
  },
})
