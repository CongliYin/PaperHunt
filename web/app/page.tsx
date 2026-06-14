import { PaperBrowser } from "./paper-browser";
import { readIndex, readList, type PaperList } from "@/lib/data";

type PageProps = {
  searchParams?: Promise<Record<string, string | string[] | undefined>>;
};

export default async function HomePage({ searchParams }: PageProps) {
  const index = readIndex();
  const query = (await searchParams) || {};
  const preferredDomain = "agent-harness-evolution";
  const requestedDomain = valueOf(query.domain);
  const availableDomains = new Set(index.domains.map((item) => item.id));
  const fallbackLatest = [...index.entries].sort((a, b) => b.date.localeCompare(a.date))[0];
  const preferredLatest = [...index.entries]
    .filter((entry) => entry.domain === preferredDomain)
    .sort((a, b) => b.date.localeCompare(a.date))[0];
  const initialDomain =
    requestedDomain && availableDomains.has(requestedDomain)
      ? requestedDomain
      : preferredLatest?.domain || fallbackLatest?.domain || "";
  const domainDates = index.entries
    .filter((entry) => entry.domain === initialDomain)
    .map((entry) => entry.date)
    .sort((a, b) => b.localeCompare(a));
  const from = valueOf(query.from);
  const to = valueOf(query.to);
  const initialDates = from && to ? datesInRange(domainDates, from, to) : domainDates.slice(0, 1);
  const initialEntries = initialDates
    .map((date) => index.entries.find((entry) => entry.domain === initialDomain && entry.date === date))
    .filter((entry): entry is (typeof index.entries)[number] => Boolean(entry));
  const initialLists = initialEntries.map((entry) => readList(entry.file));
  const initialList = combineLists(initialLists);
  const initialSort = validSort(valueOf(query.sort)) || "score";

  return (
    <main className="shell">
      <PaperBrowser
        index={index}
        initialList={initialList}
        initialDomain={initialDomain}
        initialDates={initialDates}
        initialSort={initialSort}
      />
    </main>
  );
}

function valueOf(value: string | string[] | undefined): string {
  return Array.isArray(value) ? value[0] || "" : value || "";
}

function validSort(value: string): string {
  return ["score", "llm", "topic"].includes(value) ? value : "";
}

function datesInRange(dates: string[], fromDate: string, toDate: string): string[] {
  const [start, end] = fromDate <= toDate ? [fromDate, toDate] : [toDate, fromDate];
  return dates.filter((item) => item >= start && item <= end);
}

function combineLists(lists: PaperList[]): PaperList | null {
  const [first] = lists;
  if (!first) return null;
  return {
    ...first,
    date: lists.map((item) => item.date).join(", "),
    papers: lists.flatMap((item) => item.papers)
  };
}
