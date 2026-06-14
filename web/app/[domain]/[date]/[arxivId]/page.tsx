import { Suspense } from "react";
import Link from "next/link";
import { notFound } from "next/navigation";
import { assetSrc } from "@/lib/assets";
import { detailParams, readDetail } from "@/lib/data";
import { DetailBackLink } from "./detail-back-link";

type Params = {
  params: Promise<{ domain: string; date: string; arxivId: string }>;
};

function alphaXivUrl(arxivId: string) {
  return `https://www.alphaxiv.org/abs/${encodeURIComponent(arxivId)}`;
}

export function generateStaticParams() {
  return detailParams();
}

export default async function DetailPage({ params }: Params) {
  const { domain, date, arxivId } = await params;
  const paper = readDetail(domain, date, arxivId);
  if (!paper) notFound();

  const dims = [
    ["Novelty", paper.llm_assessment.novelty],
    ["Problem", paper.llm_assessment.problem_significance],
    ["Impact", paper.llm_assessment.potential_impact],
    ["Paradigm", paper.llm_assessment.paradigm_shift],
    ["Lasting", paper.llm_assessment.lasting_value]
  ] as const;
  const [leadFigure, ...otherFigures] = paper.figures;
  const authorAffiliations = paper.author_affiliations || [];

  return (
    <main className="shell">
      <header className="detail-header">
        <Suspense fallback={<Link className="back" href="/">Back to Paper Hunt</Link>}>
          <DetailBackLink />
        </Suspense>
        <div className="detail-meta-row">
          <span>{domain}</span>
          <span>{date}</span>
          <span>{paper.arxiv_id}</span>
          <span>{Math.round((paper.scores.llm_assessment || 0) * 100)} LLM</span>
        </div>
        <div>
          <h1 className="detail-title">{paper.title_zh || paper.title}</h1>
          <p className="detail-title-en">{paper.title}</p>
        </div>
        <div className="authors">{paper.authors.join(", ")}</div>
        {authorAffiliations.length ? (
          <div className="affiliations">
            {authorAffiliations.map((item) => (
              <div className="affiliation-row" key={item.name}>
                <strong>{item.name}</strong>
                <span>{item.affiliations.join("; ")}</span>
              </div>
            ))}
          </div>
        ) : null}
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
          <a className="pill-link primary" href={alphaXivUrl(paper.arxiv_id)} target="_blank" rel="noreferrer">
            了解详情 <span aria-hidden="true">↗</span>
          </a>
        </div>
      </header>

      {leadFigure ? (
        <figure className="lead-figure">
          <a href={assetSrc(leadFigure.src)} target="_blank" rel="noreferrer">
            <img
              src={assetSrc(leadFigure.src)}
              alt={leadFigure.caption_zh || `Page ${leadFigure.page}`}
              loading="eager"
            />
          </a>
          <figcaption>
            Page {leadFigure.page} · {leadFigure.kind} · {Math.round(leadFigure.confidence * 100)}%
            {leadFigure.caption_zh ? ` · ${leadFigure.caption_zh}` : ""}
          </figcaption>
        </figure>
      ) : null}

      <div className="detail-grid">
        <div>
          <section className="section">
            <div className="section-heading">
              <h2>中文摘要</h2>
              <span>Briefing</span>
            </div>
            <p className="prose">{paper.abstract_zh || "暂无中文摘要。"}</p>
          </section>
          <section className="section">
            <div className="section-heading">
              <h2>核心技术点</h2>
              <span>Signals</span>
            </div>
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
            <details className="abstract-disclosure">
              <summary>
                <span>英文摘要</span>
                <small>Expand original abstract</small>
              </summary>
              <p className="prose">{paper.abstract_en}</p>
            </details>
          </section>
        </div>

        <aside>
          <section className="section score-panel">
            <div className="score-head">
              <div>
                <h2>LLM 评估</h2>
                <p>Novelty, impact and topic fit</p>
              </div>
              <strong>{Math.round((paper.scores.llm_assessment || 0) * 100)}</strong>
            </div>
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
            <div className="section-heading">
              <h2>关键图片</h2>
              <span>{paper.figures.length} figures</span>
            </div>
            <div className="gallery">
              {otherFigures.length ? (
                otherFigures.map((figure) => (
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
                <div className="empty">{leadFigure ? "首图已在上方展示。" : "暂无可用图片。"}</div>
              )}
            </div>
          </section>
        </aside>
      </div>
    </main>
  );
}
