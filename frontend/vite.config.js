import { defineConfig } from 'vite';
import { svelte } from '@sveltejs/vite-plugin-svelte';

// Tauri から読み込むので相対パスで出力し、開発サーバーは固定ポート
export default defineConfig({
  plugins: [svelte()],
  base: './',
  clearScreen: false,
  server: { port: 5173, strictPort: true },
  build: { target: 'es2021', outDir: 'dist', emptyOutDir: true },
});
