import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const apiTarget = process.env.JTB_API_PROXY_TARGET || 'http://127.0.0.1:18130';
const adminTarget = process.env.JTB_ADMIN_PROXY_TARGET || 'http://127.0.0.1:18131';

export default defineConfig({
  plugins: [react(), {
    name: 'admin-home-redirect',
    configureServer(server) {
      server.middlewares.use((request, response, next) => {
        if (request.url?.split('?', 1)[0] !== '/admin/home') return next();
        response.writeHead(303, { Location: '/' });
        response.end();
      });
    },
  }],
  server: {
    port: 5173,
    host: "127.0.0.1",
    proxy: {
      // Keep the admin APIs and OA callback on their own backend while both
      // SPAs use this development origin, just as they share container port 80.
      '^/(?:admin/(?:auth|api)|api/(?:admin|feedback-admin|logs|help-resources-admin))(?:/|\\?|$)': {
        target: adminTarget,
        changeOrigin: false,
      },
      // OA returns to the original page. Forward credential-bearing URLs so
      // the backend can validate and clear them before Vite renders the SPA.
      "^/(?!api/|assets/|@)[^?]*\\?(?:[^&]*&)*(?:userid|token)=": {
        target: apiTarget,
        changeOrigin: false,
      },
      "/logged-out": {
        target: apiTarget,
        changeOrigin: false,
      },
      "/auth": {
        target: apiTarget,
        changeOrigin: false,
      },
      "/api": {
        target: apiTarget,
        changeOrigin: false,
      },
    },
  },
});
