/** @type {import('next').NextConfig} */
const nextConfig = {
  outputFileTracingIncludes: {
    "/conferences": ["./public/conferences/index.json"],
    "/conferences/*": ["./public/conferences/index.json"]
  }
};

module.exports = nextConfig;
