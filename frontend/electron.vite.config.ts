import { defineConfig } from 'electron-vite'
import { resolve } from 'path'
import react from '@vitejs/plugin-react'

export default defineConfig({
  main: {
    build: {
      lib: {
        entry: resolve(__dirname, 'src/main.ts')
      },
      rollupOptions: {
        external: ['electron']
      }
    }
  },
  preload: {
    build: {
      lib: {
        entry: resolve(__dirname, 'src/preload.ts'),
        formats: ['cjs']
      },
      rollupOptions: {
        external: ['electron']
      }
    }
  },
  renderer: {
    root: resolve(__dirname, 'src/renderer'),
    plugins: [react()],
    base: './'
  }
})
