// Committed stub — empty on purpose. In the Docker image,
// docker-entrypoint.sh overwrites this file at container startup with the
// real API_BASE_URL from the environment. For `npm run dev`/`npm run
// build` outside Docker, this stays empty and src/api/client.ts falls
// back to VITE_API_BASE_URL (or its own hardcoded default) instead.
window.__APP_CONFIG__ = {};
