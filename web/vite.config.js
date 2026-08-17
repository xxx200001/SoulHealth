import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'
import path from 'node:path'

// 后端端口只在一处配置：根目录 .env 的 SOULHEALTH_PORT（默认 8002）。
// 开发期 vite 把 /api 代理到后端；生产期 npm run build 产出 web/dist，
// 由后端直接托管，单端口访问，不再需要代理。
export default defineConfig(({ mode }) => {
  const rootDir = path.resolve(__dirname, '..')
  const env = loadEnv(mode, rootDir, '')
  const port = env.SOULHEALTH_PORT || '8002'
  return {
    envDir: '..',
    plugins: [vue()],
    server: {
      host: true,
      port: 5173,
      allowedHosts: true,
      proxy: { '/api': `http://127.0.0.1:${port}` },
    },
    build: { outDir: 'dist', emptyOutDir: true },
  }
})

