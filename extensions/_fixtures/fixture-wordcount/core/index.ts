/** Pure word counting shared by the OMP adapter, the Claude mod and the helper. */
export function countWords(text: string): number {
  const trimmed = text.trim();
  return trimmed === "" ? 0 : trimmed.split(/\s+/u).length;
}

export function formatCount(count: number): string {
  return `${count} ${count === 1 ? "word" : "words"}`;
}
