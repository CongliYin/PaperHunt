import type { PaperCard } from "./data";

export function paperScore(card: PaperCard): number {
  const fraction = card.schema === 2 ? card.value / 6 : card.total_score;
  return Math.round(fraction * 100);
}
