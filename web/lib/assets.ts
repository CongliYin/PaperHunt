export function assetSrc(src: string): string {
  if (!src) return "";
  if (src.startsWith("http://") || src.startsWith("https://")) return src;
  return `/${src.replace(/^\/+/, "")}`;
}

