import js from "@eslint/js";
import { defineConfig } from "eslint/config";
import tseslint from "typescript-eslint";

// Claude Code mod test-kit cases import 'claude-code/testing', which only the
// claude binary provides; `claude plugin test` runs them, not tsc or bun test.
const CLAUDE_TEST_KIT = "**/claude-code/mod-checks/**";

export default defineConfig(
  { ignores: ["node_modules/"] },
  js.configs.recommended,
  tseslint.configs.strict,
  {
    rules: {
      "@typescript-eslint/consistent-type-imports": "error",
    },
  },
  {
    // Shared core: deterministic rules over immutable inputs. No host, runtime,
    // filesystem, network, process or clock effects.
    files: ["**/core/**/*.ts"],
    rules: {
      "no-restricted-imports": [
        "error",
        { patterns: [{ regex: "^(?!\\.{1,2}/)", message: "core imports only relative pure modules" }] },
      ],
      "no-restricted-globals": [
        "error",
        "Bun",
        "process",
        "require",
        "fetch",
        "setTimeout",
        "setInterval",
        "setImmediate",
        "queueMicrotask",
        "Date",
        "performance",
        "crypto",
        "navigator",
      ],
      "no-restricted-syntax": ["error", { selector: "ImportExpression", message: "core uses static imports" }],
      "no-restricted-properties": ["error", { object: "Math", property: "random", message: "core is deterministic" }],
    },
  },
  {
    // Claude Code mods: static relative imports only, effects through `$`.
    files: ["**/claude-code/**/*.ts"],
    ignores: [CLAUDE_TEST_KIT],
    rules: {
      "no-restricted-imports": [
        "error",
        {
          patterns: [
            {
              regex: "^(?!\\.{1,2}/|claude-code$)",
              message: "a hooks module imports only its own files or 'claude-code'",
            },
          ],
        },
      ],
      "no-restricted-globals": [
        "error",
        "Bun",
        "process",
        "require",
        "setTimeout",
        "setInterval",
        "setImmediate",
        "fetch",
      ],
      "no-restricted-syntax": [
        "error",
        { selector: "ImportExpression", message: "a hooks module imports its files with import declarations" },
      ],
    },
  },
);
