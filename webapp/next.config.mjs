/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "export",
  webpack: (config) => {
    // pdf.js worker needs to be copied to static
    config.resolve.alias.canvas = false;
    return config;
  },
};

export default nextConfig;
