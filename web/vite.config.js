import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// En desarrollo, /api va al servidor Python
export default defineConfig({
  plugins: [react()],
  server: { proxy: { "/api": "http://127.0.0.1:8765" } },
});
