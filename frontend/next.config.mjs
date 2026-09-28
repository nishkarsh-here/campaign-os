/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // The browser never talks to a provider or to storage directly — only to our
  // API. Keeping the base URL server-side-configurable keeps it that way.
  env: {
    API_BASE_URL: process.env.API_BASE_URL ?? 'http://127.0.0.1:8000',
    // Public Supabase configuration. The anon key is publishable by design —
    // it identifies the project and carries no privilege. The service-role key
    // is server-side only and must never appear here.
    SUPABASE_URL: process.env.SUPABASE_URL ?? '',
    SUPABASE_ANON_KEY: process.env.SUPABASE_ANON_KEY ?? '',
  },
};
export default nextConfig;
