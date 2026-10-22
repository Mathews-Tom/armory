import ts from "typescript";
import { posix } from "node:path";
import { isBuiltin } from "node:module";

type Reference = {
  typeOnly: boolean;
  specifier: string;
  runtimeBuiltin: boolean;
};
type Analysis = { imports: Reference[]; forbidden: string[] };
type Request = {
  action: "analyze" | "bundle";
  files: Record<string, string>;
  entry?: string;
};

const UNSUPPORTED_LOADERS: Readonly<Record<string, true>> = {
  require: true, createRequire: true, eval: true, Function: true,
};
const COMPUTED_RUNTIME_ROOTS: Readonly<Record<string, true>> = {
  globalThis: true, global: true, module: true,
};

// Parse, never execute, feature code. In particular comments/string contents do
// not hide real imports or masquerade as executable module loads.
function analyze(path: string, text: string): Analysis {
  const source = ts.createSourceFile(path, text, ts.ScriptTarget.Latest, true);
  const diagnostics = (
    source as ts.SourceFile & { parseDiagnostics: readonly ts.Diagnostic[] }
  ).parseDiagnostics;
  const diagnostic = diagnostics[0];
  if (diagnostic) {
    throw new Error(`${path}: ${ts.flattenDiagnosticMessageText(diagnostic.messageText, " ")}`);
  }
  const result: Analysis = { imports: [], forbidden: [] };
  function reference(
    specifier: ts.Expression, typeOnly: boolean, attributes?: ts.ImportAttributes,
  ): void {
    if (!ts.isStringLiteral(specifier)) {
      result.forbidden.push("nonliteral module reference");
      return;
    }
    if (attributes && (
      attributes.elements.length !== 1 || attributes.elements.some((attribute) =>
        attribute.name.text !== "type" || !ts.isStringLiteral(attribute.value) ||
        attribute.value.text !== "json" || !specifier.text.endsWith(".json")
      )
    )) {
      result.forbidden.push("import/export attributes or executable macros");
    }
    result.imports.push({
      typeOnly, specifier: specifier.text, runtimeBuiltin: isRuntimeBuiltin(specifier.text),
    });
  }
  function visit(node: ts.Node): void {
    if (ts.isImportDeclaration(node)) {
      const clause = node.importClause;
      const bindings = clause?.namedBindings;
      const typeOnly = !!clause?.isTypeOnly || !!(
        clause && !clause.name && bindings && ts.isNamedImports(bindings) &&
        bindings.elements.length && bindings.elements.every((item) => item.isTypeOnly)
      );
      reference(node.moduleSpecifier, typeOnly, node.attributes);
    } else if (ts.isExportDeclaration(node) && node.moduleSpecifier) {
      const bindings = node.exportClause;
      const typeOnly = node.isTypeOnly || !!(
        bindings && ts.isNamedExports(bindings) && bindings.elements.length &&
        bindings.elements.every((item) => item.isTypeOnly)
      );
      reference(node.moduleSpecifier, typeOnly, node.attributes);
    } else if (ts.isImportTypeNode(node)) {
      if (ts.isLiteralTypeNode(node.argument)) reference(node.argument.literal, true);
      else result.forbidden.push("computed import type");
    } else if (ts.isImportEqualsDeclaration(node)) {
      result.forbidden.push("import equals/require");
    } else if (ts.isCallExpression(node) && node.expression.kind === ts.SyntaxKind.ImportKeyword) {
      result.forbidden.push("dynamic import()");
    } else if (ts.isIdentifier(node) && Object.hasOwn(UNSUPPORTED_LOADERS, node.text)) {
      // Refuse aliases of loaders too, not only direct call expressions.
      result.forbidden.push(`dynamic loader ${node.text}`);
    } else if (ts.isElementAccessExpression(node)) {
      const argument = node.argumentExpression;
      let receiver = node.expression;
      while (ts.isPropertyAccessExpression(receiver) || ts.isElementAccessExpression(receiver)) {
        receiver = receiver.expression;
      }
      if (
        ts.isMetaProperty(receiver) ||
        (ts.isIdentifier(receiver) && Object.hasOwn(COMPUTED_RUNTIME_ROOTS, receiver.text))
      ) {
        result.forbidden.push("computed runtime module access");
      }
      if (ts.isStringLiteral(argument) && Object.hasOwn(UNSUPPORTED_LOADERS, argument.text)) {
        result.forbidden.push(`computed loader ${argument.text}`);
      }
    }
    ts.forEachChild(node, visit);
  }
  visit(source);
  return result;
}

function isRuntimeBuiltin(specifier: string): boolean {
  return isBuiltin(specifier) || specifier === "bun" || specifier.startsWith("bun:");
}

function resolve(files: Record<string, string>, importer: string, specifier: string): string {
  if (!specifier.startsWith("./") && !specifier.startsWith("../")) {
    throw new Error(`${importer}: unapproved dependency ${specifier}`);
  }
  const target = posix.normalize(posix.join(posix.dirname(importer), specifier));
  const candidates = [target, `${target}.ts`, `${target}.js`, `${target}.mjs`, `${target}.json`, `${target}/index.ts`, `${target}/index.js`, `${target}/index.mjs`];
  const found = candidates.find((path) => Object.hasOwn(files, path));
  if (!found) throw new Error(`${importer}: dependency ${specifier} is not an approved input`);
  return found;
}

const request = JSON.parse(await Bun.stdin.text()) as Request;
if (request.action === "analyze") {
  const analyses: Record<string, Analysis> = {};
  for (const [path, text] of Object.entries(request.files)) analyses[path] = analyze(path, text);
  process.stdout.write(JSON.stringify(analyses));
} else if (request.action === "bundle" && request.entry) {
  const entry = request.entry;
  // This closure check finishes before Bun sees an entrypoint. All loads are
  // subsequently served from this immutable snapshot, never the feature tree.
  const visited = new Set<string>();
  function validate(path: string): void {
    if (visited.has(path)) return;
    visited.add(path);
    const text = request.files[path];
    if (text === undefined) throw new Error(`${path}: missing approved input`);
    if (path.endsWith(".json")) {
      JSON.parse(text);
      return;
    }
    const analysis = analyze(path, text);
    if (analysis.forbidden.length) throw new Error(`${path}: ${analysis.forbidden.join(", ")}`);
    for (const ref of analysis.imports) {
      if (path.startsWith("core/") && ref.runtimeBuiltin) {
        throw new Error(`${path}: core may not import runtime builtins`);
      }
      if (!ref.runtimeBuiltin) {
        const target = resolve(request.files, path, ref.specifier);
        if (path.startsWith("core/") && !target.startsWith("core/")) {
          throw new Error(`${path}: core may only import its pure source tree`);
        }
        validate(target);
      }
    }
  }
  validate(entry);
  const result = await Bun.build({
    entrypoints: [entry],
    root: import.meta.dir,
    target: "bun",
    format: "esm",
    sourcemap: "none",
    plugins: [{
      name: "approved-extension-inputs",
      setup(build) {
        build.onResolve({ filter: /.*/ }, (args) => {
          if (isRuntimeBuiltin(args.path)) return { path: args.path, external: true };
          const path = args.kind === "entry-point-build"
            ? entry
            : resolve(request.files, args.importer, args.path);
          if (!visited.has(path)) throw new Error(`unvalidated bundle input ${path}`);
          return { path, namespace: "armory-input" };
        });
        build.onLoad({ filter: /.*/, namespace: "armory-input" }, (args) => {
          const contents = request.files[args.path];
          if (!visited.has(args.path) || contents === undefined) throw new Error(`unvalidated bundle load ${args.path}`);
          const loader = args.path.endsWith(".json") ? "json" : args.path.endsWith(".ts") ? "ts" : "js";
          return { contents, loader };
        });
      },
    }],
  });
  const output = result.outputs[0];
  if (!result.success || result.outputs.length !== 1 || !output) {
    throw new Error(result.logs.map(String).join("\n") || "bundle did not produce exactly one module");
  }
  process.stdout.write(await output.text());
} else {
  throw new Error("invalid extension build input request");
}
