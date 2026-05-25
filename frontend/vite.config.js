import path from 'node:path';
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
export default defineConfig({
    plugins: [react()],
    resolve: {
        alias: { '@': path.resolve(__dirname, './src') },
    },
    server: {
        host: true,
        port: 5173,
        proxy: {
            '/api': 'http://localhost:4246',
            '/ws': { target: 'ws://localhost:4246', ws: true },
        },
    },
});
