import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  // OpenShare mounts the compiled app below FastAPI's /static/react route.
  // Keep Vite's lazy-chunk preloads on that same public base instead of /assets.
  base: '/static/react/',
  plugins: [react()],
  build: {
    outDir: '../static/react',
    emptyOutDir: true,
    cssCodeSplit: false,
    rollupOptions: {
      input: 'src/main.tsx',
      output: {
        entryFileNames: 'assets/openshare.js',
        chunkFileNames: 'assets/[name]-[hash].js',
        assetFileNames: (asset) => asset.name?.endsWith('.css')
          ? 'assets/openshare.css'
          : 'assets/[name]-[hash][extname]',
      },
    },
  },
  test: {
    environment: 'jsdom',
    environmentOptions: {
      jsdom: { url: 'http://localhost/' },
    },
    setupFiles: './src/testSetup.ts',
  },
});
