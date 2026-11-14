import { mkdir, readFile, writeFile } from "node:fs/promises";
import openapiTS, { astToString } from "openapi-typescript";

const schemaURL = new URL("../../../contracts/openapi.yaml", import.meta.url);
const outputURL = new URL("../src/contracts/schema.d.ts", import.meta.url);
const header =
  "// Generated from contracts/openapi.yaml by `pnpm contracts:generate`.\n" +
  "// Do not edit by hand; run `make contracts` after changing a fragment.\n\n";

const ast = await openapiTS(schemaURL);
const expected = header + astToString(ast);

if (process.argv.includes("--check")) {
  let current = "";
  try {
    current = await readFile(outputURL, "utf8");
  } catch {
    // A missing generated file is stale by definition.
  }
  if (current !== expected) {
    console.error(
      "src/contracts/schema.d.ts is stale; run `pnpm contracts:generate`",
    );
    process.exit(1);
  }
} else {
  await mkdir(new URL("../src/contracts/", import.meta.url), { recursive: true });
  await writeFile(outputURL, expected);
  console.log("src/contracts/schema.d.ts generated");
}
