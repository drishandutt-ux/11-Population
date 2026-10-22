/** @type {import('next').NextConfig} */
const nextConfig = {
  // Local dev only: two `next dev` servers on this folder otherwise share .next and serve each
  // other's chunks (compiled against the other server's API base). Unset → the default .next.
  distDir: process.env.NEXT_DIST_DIR || ".next",
  env: {
    NEXT_PUBLIC_API_URL: process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000",
    NEXT_PUBLIC_WS_URL: process.env.NEXT_PUBLIC_WS_URL || "ws://localhost:8000",
    // Supabase Auth ("11 Minds Population" project). Both must be set at BUILD time or sign-in is off.
    NEXT_PUBLIC_SUPABASE_URL: process.env.NEXT_PUBLIC_SUPABASE_URL || "",
    NEXT_PUBLIC_SUPABASE_ANON_KEY: process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY || "",
  },
};

module.exports = nextConfig;
