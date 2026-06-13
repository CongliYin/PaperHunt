import { PaperBrowser } from "./paper-browser";
import { readIndex, readList } from "@/lib/data";

export default function HomePage() {
  const index = readIndex();
  const latest = [...index.entries].sort((a, b) => b.date.localeCompare(a.date))[0];
  const initialList = latest ? readList(latest.file) : null;

  return (
    <main className="shell">
      <PaperBrowser index={index} initialList={initialList} />
    </main>
  );
}

