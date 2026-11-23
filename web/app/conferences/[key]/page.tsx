import Link from "next/link";
import { notFound } from "next/navigation";
import { conferences, domainNames } from "@/lib/conferences";

export default async function ConferenceDetail({
  params,
}: {
  params: Promise<{ key: string }>;
}) {
  const { key } = await params;
  const paper = conferences().papers.find((p) => p.key === key);
  if (!paper) notFound();
  return (
    <main className="shell">
      <nav className="library-nav">
        <Link href="/conferences">← 顶会论文</Link>
      </nav>
      <header className="detail-header">
        <p>
          {domainNames[paper.domain]} · 评分 {paper.score}/100
        </p>
        <h1 className="detail-title">{paper.title}</h1>
        <p>{paper.authors.join(", ")}</p>
      </header>
      <section className="section">
        <h2>正式发表记录</h2>
        {paper.publications.map((v) => (
          <p key={v.url + v.track}>
            <a href={v.url}>
              {v.venue} {v.year} · {v.track} · 官方记录 ↗
            </a>
            {v.pdf && (
              <>
                {" "}
                · <a href={v.pdf}>PDF ↗</a>
              </>
            )}
          </p>
        ))}
        {paper.daily && <Link href={paper.daily}>查看日报记录</Link>}
      </section>
      <section className="section">
        <h2>入选依据</h2>
        <p>{paper.reason}</p>
        <blockquote>{paper.evidence}</blockquote>
        <blockquote>{paper.result}</blockquote>
      </section>
      <section className="section">
        <h2>摘要</h2>
        <p className="prose">{paper.abstract}</p>
      </section>
    </main>
  );
}
