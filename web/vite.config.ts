import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    host: "127.0.0.1",
    proxy: {
      // OA returns to the original page. Forward credential-bearing URLs so
      // the backend can validate and clear them before Vite renders the SPA.
      "^/(?!api/|assets/|@)[^?]*\\?(?:[^&]*&)*(?:userid|token)=": {
        target: "http://127.0.0.1:18130",
        changeOrigin: false,
      },
      "/logged-out": {
        target: "http://127.0.0.1:18130",
        changeOrigin: false,
      },
      "/auth": {
        target: "http://127.0.0.1:18130",
        changeOrigin: false,
      },
      "/api": {
        target: "http://127.0.0.1:18130",
        changeOrigin: false,
      },
    },
  },
});
