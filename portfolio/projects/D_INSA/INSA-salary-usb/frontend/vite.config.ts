import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "path";

export default defineConfig({
  test: {
    setupFiles: ["./src/test/setup.ts"],
  },
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  build: {
    chunkSizeWarningLimit: 700,
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (!id.includes("node_modules")) return undefined;
          if (id.includes("/antd/") || id.includes("@ant-design/")) return "antd";
          if (id.includes("/react-router") || id.includes("/react-dom/") || id.includes("/react/")) {
            return "react-vendor";
          }
          if (id.includes("@tanstack/react-query")) return "query";
          if (id.includes("@fullcalendar/")) return "fullcalendar";
          if (id.includes("/dayjs/") || id.includes("/rc-")) return "antd-deps";
          return "vendor";
        },
      },
    },
  },
  server: {
    host: true,
    port: 5173,
    strictPort: true,
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
        // 실제 접속 PC IP를 X-Forwarded-For로 넘긴다. 백엔드는 --proxy-headers로 기동.
        xfwd: true,
      },
    },
  },
});
