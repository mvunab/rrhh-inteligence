import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// En desarrollo /api va a la API local; en Docker lo hace nginx (web/nginx.conf).
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: process.env.API_BASE_URL ?? 'http://localhost:8000',
        changeOrigin: true,
        rewrite: (ruta) => ruta.replace(/^\/api/, ''),
      },
    },
  },
})
