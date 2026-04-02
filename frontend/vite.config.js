import react from "@vitejs/plugin-react";
import { execSync } from "node:child_process";
import { defineConfig } from "vitest/config";
import pkg from "./package.json";
function resolveGitCommitShort() {
    try {
        return execSync("git rev-parse --short HEAD", { stdio: ["ignore", "pipe", "ignore"] })
            .toString()
            .trim();
    }
    catch (_a) {
        return "unknown";
    }
}
var appVersion = pkg.version;
var appCommit = resolveGitCommitShort();
var appBuildTime = new Date().toISOString();
export default defineConfig({
    base: "/app/",
    define: {
        __APP_VERSION__: JSON.stringify(appVersion),
        __APP_COMMIT__: JSON.stringify(appCommit),
        __APP_BUILD_TIME__: JSON.stringify(appBuildTime),
    },
    plugins: [react()],
    server: {
        host: "127.0.0.1",
        port: 5173,
        proxy: {
            "/api": {
                target: "http://127.0.0.1:8000",
                changeOrigin: true,
            },
        },
    },
    preview: {
        host: "127.0.0.1",
        port: 4173,
    },
    build: {
        outDir: "dist",
        sourcemap: true,
    },
    test: {
        environment: "jsdom",
        globals: true,
        setupFiles: "./src/test/setup.ts",
    },
});
