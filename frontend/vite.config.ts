/// <reference types="vitest/config" />
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
    coverage: {
      provider: 'v8',
      reporter: ['text', 'lcov'],
      // These files are unstyled config/typing boilerplate with nothing
      // meaningful to unit-test on their own; excluding them keeps the
      // report focused on the actual dashboard code (api/, components/,
      // pages/).
      exclude: ['src/main.tsx', 'src/vite-env.d.ts', '**/*.d.ts', 'src/test/**'],
    },
  },
})
