const apiBase = process.env.API_BASE_URL;
if (!apiBase) throw new Error('Set API_BASE_URL to the HTTPS Render origin.');
const apiOrigin = new URL(apiBase);
if (apiOrigin.protocol !== 'https:' || apiOrigin.origin !== apiBase.replace(/\/$/, '')) {
  throw new Error('API_BASE_URL must be an HTTPS origin without a path or credentials.');
}

export const config = {
  framework: null,
  buildCommand: 'mkdir -p .vercel-static/assets && cp frontend/index.html .vercel-static/ && cp frontend/app.js frontend/styles.css frontend/studio.css .vercel-static/assets/ && cp -R frontend/assets .vercel-static/assets/',
  outputDirectory: '.vercel-static',
  rewrites: [
    { source: '/api/:path*', destination: `${apiOrigin.origin}/api/:path*` },
    { source: '/docs', destination: `${apiOrigin.origin}/docs` },
    { source: '/openapi.json', destination: `${apiOrigin.origin}/openapi.json` },
  ],
};
