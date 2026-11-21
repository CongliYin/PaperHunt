import { paperScore } from "./paper-score";
import fs from "node:fs";
import path from "node:path";

export type IndexData = {
  source_events?: string;
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

type CardFields = {
  arxiv_id: string;
  title: string;
  title_zh: string;
  authors: string[];

  tags: string[];
  tldr_zh: string;
  detail_file: string;
  thumb: string;
};

export type PaperCard = CardFields & ({
  schema?: 1;
  total_score: number;
  scores: { topic_relevance: number; llm_assessment: number; other: number };
} | {
  schema: 2;
  domain: string;
  edition: string;
  fit: number;
  value?: number; // Earlier six-point editions
  score?: number;
  reason: string;
  source: "arxiv" | "hf";
});

type Review = { F: number; M: number; E: number; U: number; reason: string; quote: string };
export type PaperDetail = {
  score?: number;
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

  enriched?: Record<string, unknown>;
  figures: Array<{
    src: string;
    page: number;
    kind: string;
    confidence: number;
    caption_zh?: string;
  }>;
} & ({
  schema?: 1;
  llm_assessment: Record<string, number | string>;
  scores: Record<string, number>;
} | {
  schema: 2;
  review_domains: Record<string, Review>;
  evidence_scope: string;
  primary_domain: string;
  source: "hf" | "arxiv";
  hf_dates?: string[];
});

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
  const index = readIndex();
  const entry = index.entries.find(e => e.domain === domain && e.date === date);
  const card = entry && readList(entry.file).papers.find(p => p.arxiv_id === arxivId);
  if (card) {
    const detail = readJson<PaperDetail | null>(card.detail_file, null);
    if (detail?.schema === 2 && index.source_events) {
      const events = readJson<Record<string, string[]>>(index.source_events, {});
      detail.hf_dates = events[arxivId] || [];
    }
    if (detail) detail.score = paperScore(card);
    return detail;
  }
  // Legacy bookmarks survive a historical replay that changes the day's shortlist.
  if (!/^[a-z0-9-]+$/.test(domain) || !/^\d{4}-\d{2}-\d{2}$/.test(date) || !/^\d{4}\.\d{4,5}$/.test(arxivId)) return null;
  return readJson<PaperDetail | null>(path.join(domain, date, arxivId + ".json"), null);
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
