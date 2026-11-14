// Fail when a feature or page imports a deep visual primitive instead of the
// project's `src/ui` seam. The seam itself may re-export playbook visuals.
import { existsSync, readdirSync, readFileSync, statSync } from "node:fs";
import { dirname, join, relative } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..", "src");
const forbidden = "cliver-playbook-app-basic/components/ui";
const offenders = [];

function walk(directory) {
  for (const entry of readdirSync(directory)) {
    const path = join(directory, entry);
    if (directory === root && entry === "ui") continue;
    if (statSync(path).isDirectory()) {
      walk(path);
      continue;
    }
    if (!/\.(ts|tsx)$/.test(entry)) continue;
    if (readFileSync(path, "utf8").includes(forbidden)) {
      offenders.push(relative(root, path));
    }
  }
}

if (existsSync(root)) walk(root);

if (offenders.length > 0) {
  console.error("UI seam violation — import from src/ui instead:");
  for (const file of offenders) console.error(`  ${file}`);
  process.exit(1);
}
console.log("ui-seam: OK");
