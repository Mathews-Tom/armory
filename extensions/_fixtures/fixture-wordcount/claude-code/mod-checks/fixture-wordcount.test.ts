import { expect, test } from "claude-code/testing";

test("/armory-fixture-wordcount reports the word count", async ($) => {
  const answer = await $.command.run({ command: "armory-fixture-wordcount", args: "one two  three" });
  expect(answer.text).toBe("3 words");
});
