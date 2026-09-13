/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // The browser never talks to a provider or to storage directly — only to our
  // API. Keeping the base URL server-side-configurable keeps it that way.
  env: { API_BASE_URL: process.env.API_BASE_URL ?? 'http://127.0.0.1:8000' },
};
export default nextConfig;
