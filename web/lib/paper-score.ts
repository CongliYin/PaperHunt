import type { PaperCard } from "./data";

export function paperScore(card: PaperCard): number {
  if (card.schema === 2 && card.score !== undefined) return card.score;
  const fraction = card.schema === 2 ? (card.value ?? 0) / 6 : card.total_score;
  return Math.round(fraction * 100);
}
