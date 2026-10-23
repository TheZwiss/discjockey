/// <reference types="vitest/config" />
import { defineConfig } from 'vite';
import { svelte } from '@sveltejs/vite-plugin-svelte';
import { fileURLToPath } from 'node:url';

const here = (p: string) => fileURLToPath(new URL(p, import.meta.url));

export default defineConfig({
  base: './',
  plugins: [svelte()],
  resolve: {
    alias: {
      $lib: here('./src/lib'),
      $fixtures: here('../tests/fixtures'),
    },
  },
  build: {
    outDir: '../discjockey/hub/static',
    emptyOutDir: true,
    target: 'safari17',
    sourcemap: false,
  },
  server: {
    port: 5170,
    fs: { allow: ['..'] },
  },
  test: {
    environment: 'node',
    include: ['src/**/*.test.ts'],
  },
});
