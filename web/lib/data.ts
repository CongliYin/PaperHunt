import fs from "node:fs";
import path from "node:path";

export type IndexData = {
  generated_at: string;
  domains: Array<{ id: string; display_name: string }>;
  entries: Array<{ domain: string; date: string; paper_count: number; file: string }>;
};

export type PaperList = {
  domain: string;
  display_name: string;
  date: string;
  generated_at: string;
  papers: PaperCard[];
};

export type PaperCard = {
  arxiv_id: string;
  title: string;
  title_zh: string;
  authors: string[];
  total_score: number;
  scores: { topic_relevance: number; llm_assessment: number; other: number };
  tags: string[];
  tldr_zh: string;
  detail_file: string;
  thumb: string;
};

export type PaperDetail = {
  arxiv_id: string;
  title: string;
  title_zh: string;
  authors: string[];
  author_affiliations?: Array<{ name: string; affiliations: string[] }>;
  published_at: string;
  abs_url: string;
  pdf_url: string;
  links: { github?: string | null; project_page?: string | null };
  abstract_en: string;
  abstract_zh: string;
  key_points_zh: string[];
  llm_assessment: Record<string, number | string>;
  scores: Record<string, number>;
  enriched: Record<string, unknown>;
  figures: Array<{
    src: string;
    page: number;
    kind: string;
    confidence: number;
    caption_zh?: string;
  }>;
};

const publicDir = path.join(process.cwd(), "public");
const dataDir = path.join(publicDir, "data");

export function readIndex(): IndexData {
  return readJson<IndexData>("index.json", {
    generated_at: "",
    domains: [],
    entries: []
  });
}

export function readList(file: string): PaperList {
  return readJson<PaperList>(file, {
    domain: "",
    display_name: "",
    date: "",
    generated_at: "",
    papers: []
  });
}

export function readDetail(domain: string, date: string, arxivId: string): PaperDetail | null {
  const rel = path.join(domain, date, `${arxivId}.json`);
  const full = path.join(dataDir, rel);
  if (!fs.existsSync(full)) return null;
  return JSON.parse(fs.readFileSync(full, "utf8")) as PaperDetail;
}

export function detailParams(): Array<{ domain: string; date: string; arxivId: string }> {
  const index = readIndex();
  const params: Array<{ domain: string; date: string; arxivId: string }> = [];
  for (const entry of index.entries) {
    const list = readList(entry.file);
    for (const paper of list.papers) {
      params.push({
        domain: entry.domain,
        date: entry.date,
        arxivId: paper.arxiv_id
      });
    }
  }
  return params;
}

function readJson<T>(rel: string, fallback: T): T {
  const full = path.join(dataDir, rel);
  if (!fs.existsSync(full)) return fallback;
  return JSON.parse(fs.readFileSync(full, "utf8")) as T;
}
