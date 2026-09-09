import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  root: "vercel-app",
  publicDir: "public",
  plugins: [react()],
  define: { __PUBLIC_READ_ONLY__: "true" },
  resolve: { alias: { "@": new URL(".", import.meta.url).pathname } },
  build: {
    outDir: "../vercel-dist",
    emptyOutDir: true,
  },
});
