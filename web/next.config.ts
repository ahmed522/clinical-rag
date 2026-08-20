import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // The local MVP is commonly opened through 127.0.0.1 while Next's dev
  // server also advertises localhost. Next 16 blocks its development chunks
  // when that origin is not explicitly trusted, leaving client-only auth
  // pages frozen on their server-rendered loading state.
  allowedDevOrigins: ["127.0.0.1", "localhost"],
};

export default nextConfig;
