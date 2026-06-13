import Link from "next/link";
import { notFound } from "next/navigation";
import { assetSrc } from "@/lib/assets";
import { detailParams, readDetail } from "@/lib/data";

type Params = {
  params: { domain: string; date: string; arxivId: string };
};

export function generateStaticParams() {
  return detailParams();
}

export default function DetailPage({ params }: Params) {
  const paper = readDetail(params.domain, params.date, params.arxivId);
  if (!paper) notFound();

  const dims = [
    ["Novelty", paper.llm_assessment.novelty],
    ["Problem", paper.llm_assessment.problem_significance],
    ["Impact", paper.llm_assessment.potential_impact],
    ["Paradigm", paper.llm_assessment.paradigm_shift],
    ["Lasting", paper.llm_assessment.lasting_value]
  ] as const;

  return (
    <main className="shell">
      <header className="detail-header">
        <Link className="back" href="/">
          ← Paper Hunt
        </Link>
        <div>
          <h1 className="detail-title">{paper.title_zh || paper.title}</h1>
          <p className="detail-title-en">{paper.title}</p>
        </div>
        <div className="authors">{paper.authors.join(", ")}</div>
        <div className="link-row">
          <a className="pill-link" href={paper.abs_url} target="_blank" rel="noreferrer">
            arXiv
          </a>
          <a className="pill-link" href={paper.pdf_url} target="_blank" rel="noreferrer">
            PDF
          </a>
          {paper.links.github ? (
            <a className="pill-link" href={paper.links.github} target="_blank" rel="noreferrer">
              GitHub
            </a>
          ) : null}
          {paper.links.project_page ? (
            <a className="pill-link" href={paper.links.project_page} target="_blank" rel="noreferrer">
              Project
            </a>
          ) : null}
        </div>
      </header>

      <div className="detail-grid">
        <div>
          <section className="section">
            <h2>中文摘要</h2>
            <p className="prose">{paper.abstract_zh || "暂无中文摘要。"}</p>
          </section>
          <section className="section">
            <h2>核心技术点</h2>
            {paper.key_points_zh.length ? (
              <ul className="points">
                {paper.key_points_zh.map((point) => (
                  <li key={point}>{point}</li>
                ))}
              </ul>
            ) : (
              <p className="prose">暂无核心技术点。</p>
            )}
          </section>
          <section className="section">
            <details>
              <summary>英文摘要</summary>
              <p className="prose">{paper.abstract_en}</p>
            </details>
          </section>
        </div>

        <aside>
          <section className="section score-panel">
            <h2>LLM 评估</h2>
            {dims.map(([label, raw]) => {
              const value = typeof raw === "number" ? raw : 0;
              return (
                <div className="bar-row" key={label}>
                  <span>{label}</span>
                  <div className="bar">
                    <span style={{ width: `${Math.round(value * 100)}%` }} />
                  </div>
                  <strong>{Math.round(value * 100)}</strong>
                </div>
              );
            })}
            <p className="comment">{String(paper.llm_assessment.comment_zh || paper.llm_assessment.comment || "")}</p>
          </section>

          <section className="section">
            <h2>关键图片</h2>
            <div className="gallery">
              {paper.figures.length ? (
                paper.figures.map((figure) => (
                  <figure className="figure" key={figure.src}>
                    <a href={assetSrc(figure.src)} target="_blank" rel="noreferrer">
                      <img src={assetSrc(figure.src)} alt={figure.caption_zh || `Page ${figure.page}`} loading="lazy" />
                    </a>
                    <figcaption>
                      Page {figure.page} · {figure.kind} · {Math.round(figure.confidence * 100)}%
                      {figure.caption_zh ? ` · ${figure.caption_zh}` : ""}
                    </figcaption>
                  </figure>
                ))
              ) : (
                <div className="empty">暂无可用图片。</div>
              )}
            </div>
          </section>
        </aside>
      </div>
    </main>
  );
}
