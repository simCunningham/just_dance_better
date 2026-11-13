import { networkInterfaces } from 'node:os'
import basicSsl from '@vitejs/plugin-basic-ssl'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

const lan = Object.values(networkInterfaces()).flat().find(a => a?.family === 'IPv4' && !a.internal)?.address ?? ''

export default defineConfig({
  plugins: [react(), ...(process.env.LAN ? [basicSsl()] : [])],
  define: { __LAN__: JSON.stringify(lan) },
  server: {
    host: true,
    allowedHosts: true,
    proxy: { '/api': { target: 'http://127.0.0.1:8000', ws: true, rewrite: path => path.replace(/^\/api/, '') } },
  },
})
