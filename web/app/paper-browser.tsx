"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import type { IndexData, PaperList } from "@/lib/data";
import { assetSrc } from "@/lib/assets";

type Props = {
  index: IndexData;
  initialList: PaperList | null;
};

export function PaperBrowser({ index, initialList }: Props) {
  const latest = [...index.entries].sort((a, b) => b.date.localeCompare(a.date))[0];
  const [domain, setDomain] = useState(initialList?.domain || latest?.domain || "");
  const [date, setDate] = useState(initialList?.date || latest?.date || "");
  const [list, setList] = useState<PaperList | null>(initialList);
  const [sortMode, setSortMode] = useState("score");

  const dates = useMemo(
    () =>
      index.entries
        .filter((entry) => entry.domain === domain)
        .map((entry) => entry.date)
        .sort((a, b) => b.localeCompare(a)),
    [domain, index.entries]
  );

  async function load(nextDomain: string, nextDate: string) {
    const entry = index.entries.find((item) => item.domain === nextDomain && item.date === nextDate);
    if (!entry) {
      setList(null);
      return;
    }
    const response = await fetch(`/data/${entry.file}`, { cache: "no-store" });
    setList((await response.json()) as PaperList);
  }

  const papers = [...(list?.papers || [])].sort((a, b) => {
    if (sortMode === "topic") return b.scores.topic_relevance - a.scores.topic_relevance;
    if (sortMode === "llm") return b.scores.llm_assessment - a.scores.llm_assessment;
    return b.total_score - a.total_score;
  });

  return (
    <>
      <header className="topbar">
        <div>
          <h1 className="brand">Paper Hunt</h1>
          <p className="subtitle">
            {list ? `${list.display_name} · ${list.date} · ${papers.length} papers` : "No generated data yet"}
          </p>
        </div>
        <div className="filters">
          <select
            className="select"
            value={domain}
            onChange={(event) => {
              const nextDomain = event.target.value;
              const nextDate =
                index.entries
                  .filter((entry) => entry.domain === nextDomain)
                  .map((entry) => entry.date)
                  .sort((a, b) => b.localeCompare(a))[0] || "";
              setDomain(nextDomain);
              setDate(nextDate);
              void load(nextDomain, nextDate);
            }}
          >
            {index.domains.map((item) => (
              <option key={item.id} value={item.id}>
                {item.display_name}
              </option>
            ))}
          </select>
          <select
            className="select"
            value={date}
            onChange={(event) => {
              const nextDate = event.target.value;
              setDate(nextDate);
              void load(domain, nextDate);
            }}
          >
            {dates.map((item) => (
              <option key={item} value={item}>
                {item}
              </option>
            ))}
          </select>
          <select className="select" value={sortMode} onChange={(event) => setSortMode(event.target.value)}>
            <option value="score">Total score</option>
            <option value="llm">LLM score</option>
            <option value="topic">Topic score</option>
          </select>
        </div>
      </header>

      {!papers.length ? (
        <div className="empty">暂无论文数据。首次 GitHub Actions 跑完后，这里会自动显示最新结果。</div>
      ) : (
        <section className="paper-grid">
          {papers.map((paper) => (
            <Link
              className="paper-card"
              href={`/${list?.domain}/${list?.date}/${paper.arxiv_id}`}
              key={paper.arxiv_id}
            >
              <div className="thumb">
                {paper.thumb ? (
                  <img src={assetSrc(paper.thumb)} alt="" loading="lazy" />
                ) : (
                  <div className="thumb-empty">No figure</div>
                )}
              </div>
              <div className="paper-body">
                <div className="score-row">
                  <div className="score">{Math.round(paper.total_score * 100)}</div>
                  <div className="tags">
                    {paper.tags.slice(0, 3).map((tag) => (
                      <span className="tag" key={tag}>
                        {tag}
                      </span>
                    ))}
                  </div>
                </div>
                <h2 className="paper-title-zh">{paper.title_zh || paper.title}</h2>
                <p className="paper-title-en">{paper.title}</p>
                {paper.tldr_zh ? <p className="tldr">{paper.tldr_zh}</p> : null}
                <div className="authors">{paper.authors.slice(0, 4).join(", ")}</div>
              </div>
            </Link>
          ))}
        </section>
      )}
    </>
  );
}
