// Empacota tests/smoke.tsx com o esbuild (já instalado pelo Vite) e executa no Node.
import { build } from "esbuild";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import path from "node:path";

const raiz = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const saida = path.join(raiz, "node_modules", ".cache", "flow-smoke.mjs");

await build({
  entryPoints: [path.join(raiz, "tests", "smoke.tsx")],
  bundle: true,
  platform: "node",
  format: "esm",
  jsx: "automatic",
  outfile: saida,
  logLevel: "warning",
  banner: { js: "import { createRequire } from 'module'; const require = createRequire(import.meta.url);" },
});

const r = spawnSync(process.execPath, [saida], { stdio: "inherit" });
process.exit(r.status ?? 1);
