/** @type {import('next').NextConfig} */
const nextConfig = {
  outputFileTracingIncludes: {
    "/conferences": ["./public/conferences/index.json"],
    "/conferences/*": ["./public/conferences/index.json", "./public/conferences/papers/*.json"]
  }
};

module.exports = nextConfig;
