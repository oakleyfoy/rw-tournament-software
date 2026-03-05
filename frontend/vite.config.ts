import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { VitePWA } from 'vite-plugin-pwa'

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [
    react(),
    VitePWA({
      registerType: 'autoUpdate',
      includeAssets: ['assets/racquetwar-icon.svg', 'assets/racquetwar-logo.svg'],
      manifest: {
        name: 'RacquetWar Draws & Schedule',
        short_name: 'RacquetWar',
        description: 'Tournament draws and schedule on mobile home screen.',
        theme_color: '#102f73',
        background_color: '#ffffff',
        display: 'standalone',
        scope: '/',
        start_url: '/',
        icons: [
          {
            src: '/assets/racquetwar-icon.svg',
            sizes: '192x192',
            type: 'image/svg+xml',
            purpose: 'any',
          },
          {
            src: '/assets/racquetwar-icon.svg',
            sizes: '512x512',
            type: 'image/svg+xml',
            purpose: 'any maskable',
          },
        ],
      },
      workbox: {
        cleanupOutdatedCaches: true,
        navigateFallback: '/index.html',
        globPatterns: ['**/*.{js,css,html,ico,png,svg,json,webmanifest}'],
      },
    }),
  ],
  server: {
    port: 3000,
    host: '127.0.0.1', // Listen on IPv4 localhost
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
})

