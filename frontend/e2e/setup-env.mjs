// M31: writes e2e/.env.e2e (git-ignored) for the isolated E2E stack: random test-only secrets,
// a throwaway owner login, its own port and backup folder, no Gmail account and no Gemini key.
import { randomBytes, scryptSync } from "node:crypto";
import { writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const token = (n) => randomBytes(n).toString("base64url");
const password = token(18);
const salt = randomBytes(16);
const hash = scryptSync(password, salt, 32, { N: 2 ** 14, r: 8, p: 1 }); // same format as app/auth.py

const env = {
  ENV_FILE: "frontend/e2e/.env.e2e", // compose paths are relative to the repo root
  WEB_PORT: "3190",
  BACKUP_HOST_DIR: `./e2e-backups/run-${Date.now()}`, // fresh per run: the first test expects "No backup yet."
  OWNER_EMAIL: "e2e-owner@example.com",
  OWNER_PASSWORD_HASH: `scrypt:${salt.toString("hex")}:${hash.toString("hex")}`,
  SESSION_SECRET: token(32),
  POSTGRES_PASSWORD: token(24),
  CREDENTIALS_KEY: randomBytes(32).toString("base64url") + "=", // Fernet key format
  GEMINI_API_KEY: "",
  E2E_PASSWORD: password, // read by the tests only
};
writeFileSync(join(here, ".env.e2e"), Object.entries(env).map(([k, v]) => `${k}=${v}`).join("\n") + "\n");
console.log("wrote e2e/.env.e2e (test-only values)");
