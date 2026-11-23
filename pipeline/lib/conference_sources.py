"""Official conference catalogues. Listing discovery is separate from abstract hydration."""

import json
import re
import xml.etree.ElementTree as ET
from collections import defaultdict
from urllib.parse import parse_qs, urljoin, urlsplit

import requests
import yaml
from bs4 import BeautifulSoup

from .edition_sources import digest

VENUES = ("EMNLP", "ACL", "NAACL", "ICLR", "NeurIPS", "ICML", "SIGIR", "RecSys")
PDF_HOSTS = {
    "aclanthology.org",
    "openreview.net",
    "proceedings.neurips.cc",
    "papers.nips.cc",
    "proceedings.iclr.cc",
    "proceedings.mlr.press",
    "raw.githubusercontent.com",
    "dl.acm.org",
}


def safe_pdf(url):
    parts = urlsplit(url or "")
    return (
        parts.scheme == "https" and parts.hostname in PDF_HOSTS and not parts.username
    )


def plain(html):
    return BeautifulSoup(html or "", "html.parser").get_text(" ", strip=True)


def arxiv_id(value):
    match = re.fullmatch(
        r"(?:https?://arxiv.org/(?:abs|pdf)/|arXiv:)?(\d{4}\.\d{4,5})(?:v\d+)?(?:\.pdf)?",
        str(value or ""),
        re.I,
    )
    return match[1] if match else ""


def clean_title(title):
    return re.sub(r"[^\w]+", " ", title.casefold()).strip()


def record(
    venue,
    year,
    track,
    title,
    authors,
    url,
    *,
    abstract="",
    pdf="",
    doi="",
    forum="",
    arxiv="",
    published="",
    local_id="",
):
    allowed = PDF_HOSTS | {
        "doi.org",
        "recsys.acm.org",
        "sigir2025.dei.unipd.it",
        "sigir2026.org",
    }
    parts = urlsplit(url)
    if parts.scheme != "https" or parts.hostname not in allowed or parts.username:
        raise ValueError("Unexpected official publication URL")
    return dict(
        id=local_id or url,
        venue=venue,
        year=year,
        track=track,
        title=title.strip(),
        authors=authors,
        url=url,
        abstract=abstract.strip(),
        pdf=pdf if safe_pdf(pdf) else "",
        doi=(doi or "").removeprefix("https://doi.org/").lower(),
        forum=forum,
        arxiv=arxiv,
        published=str(published),
    )


def get(url, **params):
    r = requests.get(
        url,
        params=params,
        timeout=(8, 25),
        headers={
            "User-Agent": "PaperHunt/1.0 (+https://github.com/CongliYin/PaperHunt)"
        },
    )
    r.raise_for_status()
    return r


def acl_volume(xml, venue, year, findings=False):
    out = []
    root = ET.fromstring(xml)
    for vol in root.findall("volume"):
        vid = vol.attrib["id"]
        if findings and vid != venue.lower():
            continue
        if not findings and vid not in {"main", "long", "short", "industry"}:
            continue
        track = (
            "Findings"
            if findings
            else {
                "industry": "Industry",
                "main": "Main",
                "short": "Short",
                "long": "Long",
            }[vid]
        )
        for paper in vol.findall("paper"):
            title = "".join(paper.find("title").itertext())
            if paper.find("retraction") is not None or re.search(
                r"^\s*\[?(withdrawn|retracted)\b", title, re.I
            ):
                continue
            identifier = f"{root.attrib['id']}-{vid}.{paper.attrib['id']}"
            url = f"https://aclanthology.org/{identifier}/"
            authors = [
                " ".join(filter(None, (a.findtext("first"), a.findtext("last"))))
                for a in paper.findall("author")
            ]
            abstract = paper.find("abstract")
            out.append(
                record(
                    venue,
                    year,
                    track,
                    title,
                    authors,
                    url,
                    abstract="".join(abstract.itertext())
                    if abstract is not None
                    else "",
                    doi=paper.findtext("doi", ""),
                    pdf=url[:-1] + ".pdf",
                    published=vol.findtext("meta/year", ""),
                )
            )
    return out


def proceedings(venue, year):
    host = "proceedings.iclr.cc" if venue == "ICLR" else "proceedings.neurips.cc"
    url = f"https://{host}/paper_files/paper/{year}"
    page = BeautifulSoup(get(url).content, "html.parser")
    main = page.select_one('a[href*="-main-conference"]')
    if main:
        url = urljoin(url, main["href"])
        page = BeautifulSoup(get(url).content, "html.parser")
    # Bulk abstracts are available on the official virtual programme. Admit only
    # entries in the proceedings; match metadata by exact title AND author.
    programme = defaultdict(list)
    try:
        h = venue.lower()
        data = get(
            f"https://{h}.cc/static/virtual/data/{h}-{year}-orals-posters.json"
        ).json()
        for item in data["results"]:
            if item.get("visible") and str(item.get("decision", "")).lower().startswith(
                "accept"
            ):
                programme[clean_title(item["name"])].append(item)
    except (requests.RequestException, ValueError, KeyError):
        pass  # Resolve individual proceedings pages during hydration instead.
    rows = []
    for a in page.select('a[href*="-Abstract"]'):
        href = a["href"]
        if not re.search(
            r"-Abstract(?:-Conference|-Datasets_and_Benchmarks(?:_Track)?)?\.html$",
            href,
        ):
            continue
        title = a.get_text(" ", strip=True)
        author_el = a.find_parent("li")
        listing = clean_title(author_el.get_text(" ", strip=True)) if author_el else ""
        matches = [
            v
            for v in programme[clean_title(title)]
            if v.get("authors") and clean_title(v["authors"][0]["fullname"]) in listing
        ]
        item = matches[0] if len(matches) == 1 else {}
        link = item.get("paper_url") or ""
        forum = (
            (parse_qs(urlsplit(link).query).get("id") or [""])[0]
            if urlsplit(link).hostname == "openreview.net"
            else ""
        )
        preprint = arxiv_id(link) or arxiv_id(item.get("url"))
        track = (
            "Datasets and Benchmarks" if "Datasets_and_Benchmarks" in href else "Main"
        )
        if venue == "ICLR":
            track = next(
                (
                    t
                    for t in ("Oral", "Spotlight", "Poster")
                    if t.lower() in item.get("decision", "").lower()
                ),
                track,
            )
        rows.append(
            record(
                venue,
                year,
                track,
                title,
                [a["fullname"] for a in item.get("authors", [])],
                urljoin(url, href),
                abstract=item.get("abstract") or "",
                forum=forum,
                pdf=f"https://openreview.net/pdf?id={forum}"
                if forum
                else urljoin(
                    url,
                    href.replace("/hash/", "/file/")
                    .replace("-Abstract", "-Paper")
                    .replace(".html", ".pdf"),
                ),
                arxiv=preprint,
            )
        )
    return rows


def iclr(year):
    venue = f"ICLR.cc/{year}/Conference"
    rows = []
    offset = 0
    while True:
        data = get(
            "https://api2.openreview.net/notes",
            **{
                "content.venueid": venue,
                "limit": 500,
                "offset": offset,
                "sort": "id:asc",
            },
        ).json()
        notes = data["notes"]
        for note in notes:
            c = {
                k: v["value"]
                for k, v in note["content"].items()
                if isinstance(v, dict) and "value" in v
            }
            if (
                c.get("venueid") != venue
                or note.get("ddate")
                or re.search("withdraw|reject|desk reject", c.get("venue", ""), re.I)
            ):
                continue
            forum = note["forum"]
            track = next(
                (
                    t
                    for t in ("Oral", "Spotlight", "Poster")
                    if t.lower() in c.get("venue", "").lower()
                ),
                "Main",
            )
            rows.append(
                record(
                    "ICLR",
                    year,
                    track,
                    c["title"],
                    c["authors"],
                    f"https://openreview.net/forum?id={forum}",
                    abstract=c.get("abstract", ""),
                    arxiv=arxiv_id(c.get("arxiv_id") or c.get("arxiv", "")),
                    doi=c.get("doi", ""),
                    pdf=f"https://openreview.net/pdf?id={forum}",
                    forum=forum,
                )
            )
        offset += len(notes)
        if offset >= data["count"]:
            return rows
        if not notes:
            raise ValueError("Incomplete OpenReview pagination")


def recsys(year):
    suffix = "accepted-contributions/" if year == 2025 else "contributions/"
    url = f"https://recsys.acm.org/recsys{year % 100:02d}/{suffix}"
    soup = BeautifulSoup(get(url).content, "html.parser")
    rows = []
    for label in soup.select("p"):
        m = re.search(
            rf"list of all (full|long|short) papers accepted for recsys {year}\b",
            label.get_text(" ", strip=True),
            re.I,
        )
        if not m:
            continue
        for li in label.find_next("ul").find_all("li", recursive=False):
            a = li.find("a")
            title = " ".join(
                t.strip() for t in a.find_all(string=True, recursive=False)
            ).strip()
            author = a.find("em")
            authors = re.split(
                r",\s*| and ",
                re.sub(
                    r"\s*\([^()]*\)",
                    "",
                    ""
                    if not author
                    else author.get_text(strip=True).removeprefix("by "),
                ),
            )
            body = li.select_one("div p")
            link = li.select_one('a[href*="10.1145/"]')
            doi = re.search(r"10\.1145/[\d.]+", link["href"])[0] if link else ""
            rows.append(
                record(
                    "RecSys",
                    year,
                    "Short" if m[1].lower() == "short" else "Long",
                    title,
                    authors,
                    "https://doi.org/" + doi
                    if doi
                    else url + next(iter(a.get("rel", [])), ""),
                    abstract=body.get_text(" ", strip=True) if body else "",
                    doi=doi,
                    pdf="https://dl.acm.org/doi/pdf/" + doi if doi else "",
                    local_id=f"recsys:{year}:" + digest([title, authors]),
                )
            )
    return rows


def sigir(year):
    url = {
        2025: "https://sigir2025.dei.unipd.it/accepted-papers.html",
        2026: "https://sigir2026.org/",
    }[year]
    soup = BeautifulSoup(get(url).content, "html.parser")
    rows = []
    if year == 2026:
        for script in soup.find_all("script"):
            text = script.string or ""
            if text.startswith("self.__next_f.push(") and "[fp]" in text:
                chunk = json.loads(text[len("self.__next_f.push(") : -1])[1]
                if "<h2>Full Papers</h2>" in chunk:
                    soup = BeautifulSoup(chunk, "html.parser")
                    break
    for h in soup.select("h2"):
        section = h.get_text(" ", strip=True).casefold()
        if section not in {"full papers", "short papers"}:
            continue
        for tag in h.find_next_siblings():
            if tag.name in {"h1", "h2"}:
                break
            for item in (
                tag.select("li.accepted-paper-item") if tag.name == "ul" else [tag]
            ):
                title = item.select_one(".accepted-paper-title, i")
                if title is None:
                    continue
                author = item.select_one(".accepted-paper-author")
                names = (
                    author.get_text(strip=True)
                    if author
                    else item.get_text(" ", strip=True).split(
                        title.get_text(strip=True), 1
                    )[-1]
                )
                authors = [a.strip() for a in names.split(",") if a.strip()]
                name = title.get_text(" ", strip=True)
                rows.append(
                    record(
                        "SIGIR",
                        year,
                        "Long" if section == "full papers" else "Short",
                        name,
                        authors,
                        url,
                        local_id=f"sigir:{year}:" + digest([name, authors]),
                    )
                )
    return rows


def catalogue(venue, year):
    if venue in {"ACL", "EMNLP", "NAACL"}:
        base = f"https://raw.githubusercontent.com/acl-org/acl-anthology/master/data/xml/{year}."
        rows = acl_volume(get(base + venue.lower() + ".xml").content, venue, year)
        try:
            findings = get(base + "findings.xml").content
        except requests.HTTPError as exc:
            if exc.response.status_code != 404:
                raise
        else:
            rows += acl_volume(findings, venue, year, True)
    elif venue == "ICML":
        volume = {2025: 267, 2026: 306}.get(year)
        if not volume:
            index = BeautifulSoup(
                get("https://proceedings.mlr.press/").content, "html.parser"
            )
            for li in index.select("li"):
                if re.search(rf"\bICML {year}\b", li.get_text(" ", strip=True)):
                    a = li.select_one("a[href]")
                    match = re.fullmatch(r"/?v(\d+)/?", a["href"]) if a else None
                    if match:
                        volume = int(match[1])
                        break
            if not volume:
                raise ValueError("Awaiting official ICML volume")

        data = yaml.load(
            get(
                f"https://proceedings.mlr.press/v{volume}/assets/bib/citeproc.yaml"
            ).content,
            Loader=getattr(yaml, "CSafeLoader", yaml.SafeLoader),
        )
        rows = []
        for p in data:
            if "International Conference on Machine Learning" not in p.get(
                "container-title", ""
            ):
                raise ValueError("Unexpected PMLR volume")
            if not p.get("author") or p.get("volume") != volume:
                continue
            rows.append(
                record(
                    venue,
                    year,
                    "Main",
                    plain(p["title"]),
                    [
                        " ".join(filter(None, (a.get("given"), a.get("family"))))
                        for a in p["author"]
                    ],
                    p["URL"],
                    pdf=p.get("PDF", ""),
                    abstract=plain(p.get("abstract", "")),
                    published=p.get("published", ""),
                )
            )
    elif venue == "ICLR":
        try:
            rows = iclr(year)
        except requests.RequestException:
            rows = []
        if not rows:
            rows = proceedings(venue, year)
    elif venue == "NeurIPS":
        rows = proceedings(venue, year)
    elif venue == "SIGIR":
        rows = sigir(year)
    elif venue == "RecSys":
        rows = recsys(year)
    else:
        raise ValueError("Unknown venue")
    rows = [
        p
        for p in rows
        if not re.search(r"^\s*\[?(withdrawn|retracted)\b", p["title"], re.I)
    ]
    if not rows:
        raise ValueError("No verified research track available")
    unique = {}
    for row in rows:
        prior = unique.get(row["id"])
        if prior and (prior["track"], prior["doi"]) != (row["track"], row["doi"]):
            raise ValueError("Conflicting official IDs in catalogue")
        unique[row["id"]] = row
    return list(unique.values())


def hydrate(p):
    """Resolve missing metadata; use a DOI match only with venue, title and author evidence."""
    if p["abstract"]:
        return p
    if p["venue"] == "SIGIR":
        data = get(
            "https://api.crossref.org/works",
            **{
                "query.bibliographic": p["title"] + " " + p["authors"][0],
                "filter": f"type:proceedings-article,from-pub-date:{p['year']}-01-01,until-pub-date:{p['year']}-12-31",
                "rows": 3,
            },
        ).json()
        for work in data["message"]["items"]:
            volume = " ".join(work.get("container-title", []))
            if "International ACM SIGIR Conference" not in volume or clean_title(
                work["title"][0]
            ) != clean_title(p["title"]):
                continue
            author = work.get("author", [{}])[0].get("family", "")
            if (
                not author
                or clean_title(author) not in clean_title(p["authors"][0]).split()
            ):
                continue
            doi = work["DOI"]
            p = dict(
                p,
                doi=doi,
                url="https://doi.org/" + doi,
                pdf="https://dl.acm.org/doi/pdf/" + doi,
                abstract=plain(work.get("abstract", "")),
            )
            break
        else:
            return p
        if p["abstract"]:
            return p
    soup = BeautifulSoup(get(p["url"]).content, "html.parser")
    el = soup.select_one(
        'meta[name="citation_abstract"],meta[name="description"][content],div.abstractInFull'
    )
    heading = next(
        (
            h
            for h in soup.select("h2,h3,h4")
            if h.get_text(strip=True).lower() == "abstract"
        ),
        None,
    )
    body = heading.find_next_sibling("p") if heading else None
    abstract = body.get_text(" ", strip=True) if body else ""
    if not abstract and el and el.get("name") == "citation_abstract":
        abstract = el.get("content", "")
    if not abstract:
        div = soup.select_one("div.abstractInFull, #abstract .abstract-content")
        if div:
            abstract = div.get_text(" ", strip=True)
    pdf = soup.select_one('meta[name="citation_pdf_url"]')
    link = soup.select_one('a[href*="openreview.net/forum?id="]')
    return dict(
        p,
        abstract=abstract,
        authors=p["authors"]
        or [m.get("content", "") for m in soup.select('meta[name="citation_author"]')],
        pdf=urljoin(p["url"], pdf["content"])
        if pdf and safe_pdf(urljoin(p["url"], pdf["content"]))
        else p["pdf"],
        forum=link["href"].split("id=")[1].split("&")[0] if link else p["forum"],
    )
