import { countWords } from "../core/index.ts";

const text = process.argv.slice(2).join(" ");
process.stdout.write(`${JSON.stringify({ words: countWords(text) })}\n`);
