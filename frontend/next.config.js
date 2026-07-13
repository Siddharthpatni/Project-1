/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Self-contained server bundle: the Docker runner ships only
  // .next/standalone + static assets instead of full node_modules.
  output: "standalone",
  poweredByHeader: false,
  compress: true,
  async rewrites() {
    // IMPORTANT: with `output: "standalone"` this function runs at BUILD time
    // and the destination is baked into the bundle — setting INTERNAL_API_URL
    // on the running container does NOT change it (verified live). The Docker
    // builder stage must set INTERNAL_API_URL (it does: http://api:8000).
    // In the prod stack nginx serves /api/backend/* directly anyway, so this
    // rewrite only carries dev traffic and container-internal SSR fetches.
    const backendUrl =
      process.env.INTERNAL_API_URL ||
      process.env.NEXT_PUBLIC_API_URL ||
      "http://localhost:8000";
    return [
      {
        source: "/api/backend/:path*",
        destination: `${backendUrl}/api/:path*`,
      },
    ];
  },
};

module.exports = nextConfig;
