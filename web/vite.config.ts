import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { tanstackRouter } from '@tanstack/router-plugin/vite'

export default defineConfig({
  plugins: [tanstackRouter({ target: 'react', autoCodeSplitting: true }), react()],
  server: {
    // keep the browser's Host: the api's check_origin compares it to the Origin header
    proxy: { '/api': { target: 'http://localhost:8000', changeOrigin: false } },
  },
})
