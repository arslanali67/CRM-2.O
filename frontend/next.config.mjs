// Browser calls /api/* on the same origin; Next proxies them to FastAPI,
// so the session cookie stays first-party and no CORS is needed.
// Rewrites are resolved at build time, so API_URL must be set when building.
const apiUrl = process.env.API_URL || "http://api:8000";

export default {
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${apiUrl}/:path*` }];
  },
};
