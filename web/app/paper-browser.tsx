"use client";

import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import type { IndexData, PaperCard, PaperList } from "@/lib/data";
import { assetSrc } from "@/lib/assets";

type Props = {
  index: IndexData;
  initialList: PaperList | null;
  initialDomain: string;
  initialDates: string[];
  initialSort: string;
};

type VisiblePaper = PaperCard & {
  sourceDomain: string;
  sourceDate: string;
};

export function PaperBrowser({ index, initialList, initialDomain, initialDates, initialSort }: Props) {
  const router = useRouter();
  const datePickerRef = useRef<HTMLDivElement>(null);
  const latest = [...index.entries].sort((a, b) => b.date.localeCompare(a.date))[0];
  const [domain, setDomain] = useState(initialDomain || initialList?.domain || latest?.domain || "");
  const [selectedDates, setSelectedDates] = useState<string[]>(
    initialDates.length ? normalizeDates(initialDates) : initialList?.date ? [initialList.date] : latest?.date ? [latest.date] : []
  );
  const [list, setList] = useState<PaperList | null>(initialList);
  const [visiblePapers, setVisiblePapers] = useState<VisiblePaper[]>(() => toVisiblePapers(initialList));
  const [sortMode, setSortMode] = useState(initialSort || "score");
  const [dateMenuOpen, setDateMenuOpen] = useState(false);

  const dates = useMemo(
    () =>
      index.entries
        .filter((entry) => entry.domain === domain)
        .map((entry) => entry.date)
        .sort((a, b) => b.localeCompare(a)),
    [domain, index.entries]
  );

  const dateSummary = summarizeDates(selectedDates);

  useEffect(() => {
    if (!dateMenuOpen) return;

    function onPointerDown(event: PointerEvent) {
      const target = event.target;
      if (target instanceof Node && datePickerRef.current && !datePickerRef.current.contains(target)) {
        setDateMenuOpen(false);
      }
    }

    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") setDateMenuOpen(false);
    }

    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [dateMenuOpen]);

  async function loadDates(nextDomain: string, nextDates: string[]) {
    const normalizedDates = normalizeDates(nextDates);
    const entries = normalizedDates
      .map((nextDate) => index.entries.find((item) => item.domain === nextDomain && item.date === nextDate))
      .filter((entry): entry is IndexData["entries"][number] => Boolean(entry));

    if (!entries.length) {
      setList(null);
      setVisiblePapers([]);
      return;
    }

    const lists = await Promise.all(
      entries.map(async (entry) => {
        const response = await fetch(`/data/${entry.file}`, { cache: "no-store" });
        return (await response.json()) as PaperList;
      })
    );
    const [first] = lists;
    setList({
      ...first,
      date: summarizeDates(normalizedDates),
      papers: lists.flatMap((item) => item.papers)
    });
    setVisiblePapers(lists.flatMap(toVisiblePapers));
  }

  function updateBrowserUrl(nextDomain: string, nextDates: string[], nextSort: string) {
    router.replace(homeHref(nextDomain, nextDates, nextSort), { scroll: false });
  }

  function applyDates(nextDates: string[]) {
    const normalizedDates = normalizeDates(nextDates);
    setSelectedDates(normalizedDates);
    updateBrowserUrl(domain, normalizedDates, sortMode);
    void loadDates(domain, normalizedDates);
  }

  function applyDateRange(fromDate: string, toDate: string) {
    applyDates(datesInRange(dates, fromDate, toDate));
  }

  const papers = [...visiblePapers].sort((a, b) => {
    if (sortMode === "topic") return b.scores.topic_relevance - a.scores.topic_relevance;
    if (sortMode === "llm") return b.scores.llm_assessment - a.scores.llm_assessment;
    return b.total_score - a.total_score;
  });
  const latestDate = dates[0] || "";
  const oldestDate = dates[dates.length - 1] || "";
  const dateOptions = useMemo(() => normalizeDates([...dates, ...selectedDates]).sort((a, b) => a.localeCompare(b)), [dates, selectedDates]);
  const selectedOldestDate = selectedDates[selectedDates.length - 1] || oldestDate;
  const selectedLatestDate = selectedDates[0] || latestDate;
  const returnHref = homeHref(domain, selectedDates, sortMode);

  return (
    <>
      <header className="topbar">
        <div className="masthead">
          <p className="eyebrow">AI paper briefing</p>
          <h1 className="brand">Paper Hunt</h1>
          <p className="subtitle">每日筛选值得追踪的论文，用更少噪音发现更高信号。</p>
          <div className="meta-strip">
            <span>{list?.display_name || "No domain"}</span>
            <span>{dateSummary || "No date"}</span>
            <span>{papers.length} papers</span>
          </div>
        </div>
        <div className="filters">
          <label className="filter-field">
            <span>Domain</span>
            <select
              className="select"
              value={domain}
              onChange={(event) => {
                const nextDomain = event.target.value;
                setDomain(nextDomain);
                setDateMenuOpen(false);
                updateBrowserUrl(nextDomain, selectedDates, sortMode);
                void loadDates(nextDomain, selectedDates);
              }}
            >
              {index.domains.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.display_name}
                </option>
              ))}
            </select>
          </label>
          <div className="filter-field">
            <span>Range</span>
            <div className="date-picker" ref={datePickerRef}>
              <button
                className="date-trigger"
                type="button"
                aria-expanded={dateMenuOpen}
                onClick={() => setDateMenuOpen((open) => !open)}
              >
                <span>{dateSummary || "Select date range"}</span>
              </button>
              {dateMenuOpen ? (
                <div className="date-menu">
                  <div className="date-shortcuts" aria-label="Quick date ranges">
                    <button type="button" onClick={() => applyDates(latestDate ? [latestDate] : [])}>
                      Latest
                    </button>
                    <button type="button" onClick={() => applyDates(dates.slice(0, 3))}>
                      Last 3
                    </button>
                    <button type="button" onClick={() => applyDates(dates)}>
                      All
                    </button>
                  </div>
                  <div className="date-range-fields date-range-selects">
                    <label>
                      <span>From</span>
                      <select
                        value={selectedOldestDate}
                        onChange={(event) => applyDateRange(event.target.value, selectedLatestDate)}
                      >
                        {dateOptions.map((date) => (
                          <option key={date} value={date}>
                            {date}
                          </option>
                        ))}
                      </select>
                    </label>
                    <label>
                      <span>To</span>
                      <select
                        value={selectedLatestDate}
                        onChange={(event) => applyDateRange(selectedOldestDate, event.target.value)}
                      >
                        {dateOptions.map((date) => (
                          <option key={date} value={date}>
                            {date}
                          </option>
                        ))}
                      </select>
                    </label>
                  </div>
                  <div className="date-range-note">{selectedDates.length} dates selected</div>
                </div>
              ) : null}
            </div>
          </div>
          <label className="filter-field">
            <span>Sort</span>
            <select
              className="select"
              value={sortMode}
              onChange={(event) => {
                const nextSort = event.target.value;
                setSortMode(nextSort);
                updateBrowserUrl(domain, selectedDates, nextSort);
              }}
            >
              <option value="score">Score</option>
              <option value="llm">AI review</option>
              <option value="topic">Topic match</option>
            </select>
          </label>
        </div>
      </header>

      {!papers.length ? (
        <div className="empty">暂无论文数据。首次 GitHub Actions 跑完后，这里会自动显示最新结果。</div>
      ) : (
        <section className="paper-list">
          {papers.map((paper) => (
            <article className="paper-row" key={`${paper.sourceDomain}-${paper.sourceDate}-${paper.arxiv_id}`}>
              <Link className="row-thumb" href={detailHref(paper, returnHref)}>
                {paper.thumb ? <img src={assetSrc(paper.thumb)} alt="" loading="lazy" /> : <span>No figure</span>}
              </Link>
              <div className="row-main">
                <div className="row-meta">
                  <span>{paper.arxiv_id}</span>
                  <span>{paper.sourceDate}</span>
                  <span>Score {Math.round(paper.total_score * 100)}</span>
                </div>
                <Link className="paper-title-link" href={detailHref(paper, returnHref)}>
                  <h2 className="paper-title-zh">{paper.title_zh || paper.title}</h2>
                </Link>
                <p className="paper-title-en">{paper.title}</p>
                {paper.tldr_zh ? <p className="tldr">{paper.tldr_zh}</p> : null}
                <div className="tags">
                  {paper.tags.slice(0, 3).map((tag) => (
                    <span className="tag" key={tag}>
                      {tag}
                    </span>
                  ))}
                </div>
              </div>
              <div className="row-side">
                <div className="authors">{paper.authors.slice(0, 3).join(", ")}</div>
              </div>
            </article>
          ))}
        </section>
      )}
    </>
  );
}

function toVisiblePapers(list: PaperList | null): VisiblePaper[] {
  if (!list) return [];
  return list.papers.map((paper) => {
    const [sourceDomain, sourceDate] = paper.detail_file.split("/");
    return {
      ...paper,
      sourceDomain: sourceDomain || list.domain,
      sourceDate: sourceDate || list.date
    };
  });
}

function normalizeDates(dates: string[]): string[] {
  return Array.from(new Set(dates)).sort((a, b) => b.localeCompare(a));
}

function summarizeDates(dates: string[]): string {
  const normalizedDates = normalizeDates(dates);
  if (!normalizedDates.length) return "";
  if (normalizedDates.length === 1) return formatDateLabel(normalizedDates[0]);
  return `${normalizedDates[normalizedDates.length - 1]} ~ ${normalizedDates[0]}`;
}

function datesInRange(dates: string[], fromDate: string, toDate: string): string[] {
  const normalizedDates = normalizeDates(dates);
  if (!fromDate || !toDate) return [];
  const [start, end] = fromDate <= toDate ? [fromDate, toDate] : [toDate, fromDate];
  return normalizedDates.filter((item) => item >= start && item <= end);
}

function formatDateLabel(date: string): string {
  return date;
}

function homeHref(domain: string, dates: string[], sortMode: string): string {
  const normalizedDates = normalizeDates(dates);
  const params = new URLSearchParams();
  if (domain) params.set("domain", domain);
  if (normalizedDates.length) {
    params.set("from", normalizedDates[normalizedDates.length - 1]);
    params.set("to", normalizedDates[0]);
  }
  if (sortMode && sortMode !== "score") params.set("sort", sortMode);
  const query = params.toString();
  return query ? `/?${query}` : "/";
}

function detailHref(paper: VisiblePaper, returnHref: string): string {
  const params = new URLSearchParams({ returnTo: returnHref });
  return `/${paper.sourceDomain}/${paper.sourceDate}/${paper.arxiv_id}?${params.toString()}`;
}
