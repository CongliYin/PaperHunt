import fs from "node:fs";
import path from "node:path";

export type Publication = {
  venue: string;
  year: number;
  track: string;
  url: string;
  pdf: string;
  published: string;
  first_seen: string;
};
export type ConferencePaper = {
  key: string;
  title: string;
  authors: string[];
  domain: string;
  score: number;
  reason: string;
  abstract: string;
  evidence: string;
  result: string;
  daily: string | null;
  publications: Publication[];
};
export type Volume = {
  venue: string;
  year: number;
  status: string;
  processed?: number;
  total?: number;
  accepted?: number;
  missing?: number;
  updated: string;
};

export function conferences(): {
  volumes: Record<string, Volume>;
  papers: ConferencePaper[];
} {
  const file = path.join(process.cwd(), "public", "conferences", "index.json");
  return fs.existsSync(file)
    ? JSON.parse(fs.readFileSync(file, "utf8"))
    : { volumes: {}, papers: [] };
}
export const domainNames: Record<string, string> = {
  "agent-harness-evolution": "Agent 演化",
  "agent-memory": "Agent 记忆",
  "agent-e-commerce": "电商交互导购",
  "agent-multimodal": "多模态 Agent",
};
