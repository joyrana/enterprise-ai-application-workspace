// Fails with a non-zero exit code when a freshly generated file differs from the committed one.
import { readFileSync, rmSync } from "node:fs";

const [committed, fresh] = process.argv.slice(2);
const same = readFileSync(committed, "utf8") === readFileSync(fresh, "utf8");
rmSync(fresh);
if (!same) {
  console.error(`${committed} is stale. Run \`npm run gen:api\` after exporting contracts.`);
  process.exit(1);
}
console.log(`${committed} is up to date.`);
