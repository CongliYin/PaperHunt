import Link from "next/link";
import { LibraryNav } from "../library-nav";
import { conferences, domainNames } from "@/lib/conferences";

const stages: Record<string, string> = {
  queued: "等待同步",
  complete: "已扫描",
  partial: "回填中",
  pending: "待公开",
  retry: "待重试",
};

export default async function ConferencePage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const q = await searchParams;
  const data = conferences();
  const volumes = Object.values(data.volumes).sort(
    (a, b) => b.year - a.year || a.venue.localeCompare(b.venue),
  );
  const publications = data.papers.flatMap((p) => p.publications);
  const filters = [
    {
      id: "venue",
      label: "会议",
      values: Array.from(new Set(volumes.map((v) => v.venue))).sort(),
    },
    {
      id: "year",
      label: "年份",
      values: Array.from(new Set(volumes.map((v) => String(v.year))))
        .sort()
        .reverse(),
    },
    { id: "domain", label: "研究方向", values: Object.keys(domainNames) },
    {
      id: "track",
      label: "Track",
      values: Array.from(new Set(publications.map((v) => v.track))).sort(),
    },
  ];
  const papers = data.papers.filter(
    (p) =>
      (!q.domain || p.domain === q.domain) &&
      p.publications.some(
        (v) =>
          (!q.venue || v.venue === q.venue) &&
          (!q.year || String(v.year) === q.year) &&
          (!q.track || v.track === q.track),
      ),
  );
  return (
    <main className="shell" aria-label="顶会论文">
      <LibraryNav current="/conferences" />
      <form action="/conferences" className="conference-filters">
        {filters.map((f) => (
          <label className="filter-field" key={f.id}>
            <span>{f.label}</span>
            <select
              className="select"
              name={f.id}
              defaultValue={String(q[f.id] || "")}
            >
              <option value="">全部</option>
              {f.values.map((v) => (
                <option value={v} key={v}>
                  {domainNames[v] || v}
                </option>
              ))}
            </select>
          </label>
        ))}
        <button className="select" type="submit">
          筛选
        </button>
      </form>
      <p>{papers.length} 篇</p>
      {papers.map((p) => (
        <article key={p.key} className="conference-paper">
          <div className="row-meta">
            <span>
              {p.publications
                .map((v) => [v.venue, v.year, "·", v.track].join(" "))
                .join(" / ")}
            </span>
            <span>{domainNames[p.domain]}</span>
            <span>评分 {p.score}/100</span>
          </div>
          <h2>
            <Link href={"/conferences/" + p.key}>{p.title}</Link>
          </h2>
          <p>{p.reason}</p>
        </article>
      ))}
      {!papers.length && <p className="empty">当前条件下暂无已入选论文。</p>}
      <details>
        <summary>各届同步进度</summary>
        {volumes.length ? (
          volumes.map((v) => (
            <p key={v.venue + v.year}>
              {v.venue} {v.year} · {stages[v.status]} · 已处理{" "}
              {v.processed ?? 0}/{v.total ?? "待确认"} · 入选 {v.accepted ?? 0}{" "}
              · 待补摘要 {v.missing ?? 0} ·{" "}
              {v.updated.slice(0, 10) || "尚未同步"}
            </p>
          ))
        ) : (
          <p>等待首次同步。</p>
        )}
      </details>
    </main>
  );
}
