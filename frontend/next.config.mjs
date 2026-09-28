// Browser calls /api/* on the same origin; Next proxies them to FastAPI,
// so the session cookie stays first-party and no CORS is needed.
// Rewrites are resolved at build time, so API_URL must be set when building.
const apiUrl = process.env.API_URL || "http://api:8000";

// M30: security headers on every response (pages and proxied /api/*).
// Next's app router injects inline bootstrap scripts, hence 'unsafe-inline' for scripts.
const CSP = [
  "default-src 'self'",
  "script-src 'self' 'unsafe-inline'",
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data:",
  "connect-src 'self'",
  "object-src 'none'",
  "base-uri 'self'",
  "form-action 'self'",
  "frame-ancestors 'none'",
].join("; ");

const SECURITY_HEADERS = [
  { key: "Content-Security-Policy", value: CSP },
  { key: "X-Frame-Options", value: "DENY" },
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "Referrer-Policy", value: "no-referrer" },
];

export default {
  poweredByHeader: false,
  async headers() {
    return [{ source: "/:path*", headers: SECURITY_HEADERS }];
  },
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${apiUrl}/:path*` }];
  },
};
