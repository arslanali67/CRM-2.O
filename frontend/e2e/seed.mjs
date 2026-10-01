// F5 test helper: runs SQL in the E2E stack's Postgres (project crm-e2e). Tests only; the product has no such path.
import { execFileSync } from "node:child_process";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..", "..");

export function sql(statement) {
  return execFileSync("docker", ["compose", "-p", "crm-e2e", "--env-file", join(root, "frontend", "e2e", ".env.e2e"),
    "exec", "-T", "postgres", "psql", "-U", "crm", "-d", "crm", "-tA", "-v", "ON_ERROR_STOP=1", "-c", statement],
    { cwd: root, encoding: "utf8" }).trim();
}
