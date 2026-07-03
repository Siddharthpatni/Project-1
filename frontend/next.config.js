/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Self-contained server bundle: the Docker runner ships only
  // .next/standalone + static assets instead of full node_modules.
  output: "standalone",
  poweredByHeader: false,
  compress: true,
  async rewrites() {
    // Server-side rewrites run INSIDE the Docker container, so we need
    // the Docker service name ("api") not "localhost".
    // INTERNAL_API_URL is set in docker-compose.yml for the container.
    // NEXT_PUBLIC_API_URL is for browser-side requests (localhost:8000).
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
