import ts from "typescript";
import { posix } from "node:path";
import { isBuiltin } from "node:module";

type Reference = {
  typeOnly: boolean;
  specifier: string;
  runtimeBuiltin: boolean;
};
type ClaudeAnalysis = {
  effects: { permission: string; label: string }[];
  forbidden: string[];
};
type Analysis = { imports: Reference[]; forbidden: string[]; claude: ClaudeAnalysis };
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
  const result: Analysis = {
    imports: [], forbidden: [], claude: { effects: [], forbidden: [] },
  };
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
  if (path.startsWith("hooks/")) result.claude = analyzeClaudePermissions(source);
  return result;
}

type Callback = ts.FunctionDeclaration | ts.FunctionExpression | ts.ArrowFunction;
type Capability = { kind: "registrar" | "api"; path: string[]; owner: Callback };
const CLAUDE_PERMISSIONS: Readonly<Record<string, string>> = {
  "fs.read": "fs.read",
  "fs.list": "fs.read",
  "fs.exists": "fs.read",
  "fs.stat": "fs.read",
  "fs.ancestors": "fs.read",
  "fs.write": "fs.write",
  "process.run": "process.spawn",
  "process.spawn": "process.spawn",
  "http.fetch": "network",
};

// This is a deliberately bounded capability analysis, not a sandbox. Bind
// identifiers with TypeScript's lexical binder, propagate only explicit local
// aliases, and reject transfers whose effects cannot be resolved statically.
function analyzeClaudePermissions(source: ts.SourceFile): ClaudeAnalysis {
  const options: ts.CompilerOptions = {
    noLib: true, noResolve: true, allowJs: true, checkJs: false,
    target: ts.ScriptTarget.Latest, module: ts.ModuleKind.ESNext,
  };
  // The checker supplies lexical identity only. It must never resolve or read
  // feature imports (or any other filesystem input) outside this snapshot.
  const program = ts.createProgram([source.fileName], options, {
    getSourceFile: (name) => name === source.fileName ? source : undefined,
    getDefaultLibFileName: () => "",
    writeFile: () => { throw new Error("permission analysis cannot emit files"); },
    getCurrentDirectory: () => "",
    getDirectories: () => [],
    fileExists: (name) => name === source.fileName,
    readFile: (name) => name === source.fileName ? source.text : undefined,
    getCanonicalFileName: (name) => name,
    useCaseSensitiveFileNames: () => true,
    getNewLine: () => "\n",
  });
  if (program.getSourceFile(source.fileName) !== source) {
    throw new Error(`${source.fileName}: permission analysis lost its immutable source`);
  }
  const checker = program.getTypeChecker();
  const capabilities = new Map<ts.Symbol, Capability>();
  const registeredCalls = new Set<ts.CallExpression>();
  const roots = new Set<Callback>();
  const callbackSymbols = new Set<ts.Symbol>();
  const forbidden = new Set<string>();
  const effects = new Map<string, string>();
  let changed: boolean;
  function reject(node: ts.Node, reason: string): void {
    const line = source.getLineAndCharacterOfPosition(node.getStart(source)).line + 1;
    forbidden.add(`line ${line}: ${reason}`);
  }
  function unwrap(node: ts.Expression): ts.Expression {
    while (
      ts.isParenthesizedExpression(node) || ts.isAsExpression(node) ||
      ts.isTypeAssertionExpression(node) || ts.isNonNullExpression(node) ||
      ts.isSatisfiesExpression(node)
    ) node = node.expression;
    return node;
  }
  function symbolAt(node: ts.Identifier): ts.Symbol | undefined {
    return ts.isShorthandPropertyAssignment(node.parent)
      ? checker.getShorthandAssignmentValueSymbol(node.parent)
      : checker.getSymbolAtLocation(node);
  }
  function capability(node: ts.Expression): Capability | undefined {
    node = unwrap(node);
    if (ts.isIdentifier(node)) {
      const symbol = symbolAt(node);
      return symbol && capabilities.get(symbol);
    }
    if (ts.isPropertyAccessExpression(node)) {
      const base = capability(node.expression);
      if (base) return { ...base, path: [...base.path, node.name.text] };
    }
    return undefined;
  }
  function bind(name: ts.BindingName, value: Capability): void {
    if (ts.isIdentifier(name)) {
      const symbol = checker.getSymbolAtLocation(name);
      if (!symbol) {
        reject(name, "unresolved Claude API binding");
        return;
      }
      const previous = capabilities.get(symbol);
      if (!previous) {
        capabilities.set(symbol, value);
        changed = true;
      } else if (
        previous.kind !== value.kind || previous.owner !== value.owner ||
        previous.path.join(".") !== value.path.join(".")
      ) reject(name, "ambiguous Claude API binding");
      return;
    }
    if (value.kind === "registrar" || ts.isArrayBindingPattern(name)) {
      reject(name, "unsupported Claude API destructuring");
      return;
    }
    for (const element of name.elements) {
      const property = element.propertyName ?? element.name;
      if (
        element.dotDotDotToken || element.initializer ||
        !(ts.isIdentifier(property) || ts.isStringLiteral(property))
      ) {
        reject(element, "computed, rest, or default Claude API destructuring");
        continue;
      }
      bind(element.name, { ...value, path: [...value.path, property.text] });
    }
  }
  function callback(node: ts.Expression, seen = new Set<ts.Symbol>()): Callback | undefined {
    node = unwrap(node);
    if (ts.isArrowFunction(node) || ts.isFunctionExpression(node)) return node;
    if (!ts.isIdentifier(node)) return undefined;
    const symbol = checker.getSymbolAtLocation(node);
    if (!symbol || seen.has(symbol)) return undefined;
    seen.add(symbol);
    callbackSymbols.add(symbol);
    for (const declaration of symbol.declarations ?? []) {
      if (ts.isFunctionDeclaration(declaration) && declaration.body) return declaration;
      if (ts.isVariableDeclaration(declaration) && declaration.initializer) {
        // Mutable callback identity is not statically resolvable.
        if (!(declaration.parent.flags & ts.NodeFlags.Const)) return undefined;
        return callback(declaration.initializer, seen);
      }
    }
    return undefined;
  }
  function seed(fn: Callback, kind: Capability["kind"]): void {
    roots.add(fn);
    if (fn.name) {
      const symbol = checker.getSymbolAtLocation(fn.name);
      if (symbol) callbackSymbols.add(symbol);
    }
    const parameter = fn.parameters[0];
    if (!parameter) return;
    if (parameter.dotDotDotToken || parameter.initializer) {
      reject(parameter, "rest or default Claude API parameter");
      return;
    }
    bind(parameter.name, { kind, path: [], owner: fn });
  }
  const moduleSymbol = checker.getSymbolAtLocation(source);
  const exported = moduleSymbol &&
    checker.getExportsOfModule(moduleSymbol).find((symbol) => symbol.name === "register");
  if (exported) {
    const symbol = exported.flags & ts.SymbolFlags.Alias
      ? checker.getAliasedSymbol(exported) : exported;
    let register: Callback | undefined;
    for (const declaration of symbol.declarations ?? []) {
      if (ts.isFunctionDeclaration(declaration) && declaration.body) register = declaration;
      else if (ts.isVariableDeclaration(declaration) && declaration.initializer) {
        if (declaration.parent.flags & ts.NodeFlags.Const) register = callback(declaration.initializer);
      }
    }
    if (register) seed(register, "registrar");
    else reject(source, "unresolved exported Claude register function");
  }
  function walk(node: ts.Node, visit: (node: ts.Node) => void): void {
    if (ts.isTypeNode(node)) return;
    visit(node);
    ts.forEachChild(node, (child) => walk(child, visit));
  }
  // Iterate to cover aliases and callbacks declared before their use. No
  // assignment-based or interprocedural inference is silently assumed.
  do {
    changed = false;
    walk(source, (node) => {
      if (ts.isVariableDeclaration(node) && node.initializer) {
        const value = capability(node.initializer);
        if (value) bind(node.name, value);
      }
      if (!ts.isCallExpression(node)) return;
      const value = capability(node.expression);
      if (!value || value.kind !== "registrar" || value.path.length) return;
      const last = node.arguments[node.arguments.length - 1];
      const fn = last && callback(last);
      if (
        !fn || (node.arguments.length !== 2 && node.arguments.length !== 3) ||
        node.arguments.some(ts.isSpreadElement)
      ) {
        reject(node, "unresolved Claude hook callback registration");
      } else {
        registeredCalls.add(node);
        seed(fn, "api");
      }
    });
  } while (changed);
  function declarationName(node: ts.Node): boolean {
    const parent = node.parent;
    return (
      ((ts.isVariableDeclaration(parent) || ts.isParameter(parent) ||
        ts.isBindingElement(parent) || ts.isFunctionDeclaration(parent) ||
        ts.isFunctionExpression(parent)) && parent.name === node) ||
      (ts.isBindingElement(parent) && parent.propertyName === node) ||
      (ts.isPropertyAccessExpression(parent) && parent.name === node) ||
      ((ts.isPropertyAssignment(parent) || ts.isMethodDeclaration(parent) ||
        ts.isPropertyDeclaration(parent)) && parent.name === node)
    );
  }
  walk(source, (node) => {
    // Arrows inherit `arguments`; ordinary functions establish their own binding.
    if (ts.isIdentifier(node) && node.text === "arguments" && !declarationName(node)) {
      for (let parent: ts.Node | undefined = node.parent; parent; parent = parent.parent) {
        if (!ts.isFunctionLike(parent) || ts.isArrowFunction(parent)) continue;
        if (roots.has(parent as Callback)) {
          reject(node, "unresolved Claude API access through arguments");
        }
        break;
      }
    }
    if (!ts.isExpression(node) || declarationName(node)) return;
    const value = capability(node);
    if (!value) return;
    // Closures can transfer the API without mentioning it at the eventual
    // callsite. Keep this boundary explicit rather than pretending to infer it.
    for (let parent: ts.Node | undefined = node.parent; parent; parent = parent.parent) {
      if (ts.isFunctionLike(parent)) {
        if (parent !== value.owner) reject(node, "Claude API capture by a nested function");
        break;
      }
    }
    const key = value.path.join(".");
    const effectNamespace = value.path[0] === "fs" || value.path[0] === "process" ||
      value.path[0] === "http";
    if (value.kind === "api") {
      const permission = CLAUDE_PERMISSIONS[key];
      if (permission) effects.set(key, permission);
      else if (value.path.length > 1 && effectNamespace) {
        reject(node, `unsupported Claude API effect $.${key}`);
      }
    }
    const parent = node.parent;
    if (
      (ts.isParenthesizedExpression(parent) || ts.isAsExpression(parent) ||
        ts.isTypeAssertionExpression(parent) || ts.isNonNullExpression(parent) ||
        ts.isSatisfiesExpression(parent)) && parent.expression === node
    ) return;
    if (ts.isPropertyAccessExpression(parent) && parent.expression === node) {
      if (value.kind === "registrar") reject(parent, "Claude registrar property discovery");
      return;
    }
    if (ts.isElementAccessExpression(parent) && parent.expression === node) {
      reject(parent, "computed Claude API access");
      return;
    }
    if (ts.isVariableDeclaration(parent) && parent.initializer === node) return;
    if (ts.isCallExpression(parent) && parent.expression === node) {
      if (value.kind === "registrar") {
        if (!registeredCalls.has(parent)) reject(parent, "unresolved Claude hook registration");
      } else if (value.path.length < 2 && (!value.path.length || effectNamespace)) {
        reject(parent, "unresolved Claude API call");
      }
      return;
    }
    if (ts.isExpressionStatement(parent)) return;
    reject(node, "Claude API escape or unsupported transfer");
  });
  // A mutable callback can otherwise overwrite the injected API before it is
  // used. Reject every write to a tracked binding, including ordinary RHSs.
  walk(source, (node) => {
    if (ts.isBinaryExpression(node) &&
      node.operatorToken.kind >= ts.SyntaxKind.FirstAssignment &&
      node.operatorToken.kind <= ts.SyntaxKind.LastAssignment
    ) {
      walk(node.left, (target) => {
        if (!ts.isIdentifier(target) || declarationName(target)) return;
        const symbol = symbolAt(target);
        if (symbol && (capabilities.has(symbol) || callbackSymbols.has(symbol))) {
          reject(node, "assignment to a Claude API or callback binding");
        }
      });
    } else if (ts.isPrefixUnaryExpression(node) || ts.isPostfixUnaryExpression(node)) {
      const symbol = ts.isIdentifier(node.operand) ? symbolAt(node.operand) : undefined;
      if (capability(node.operand) || (symbol && callbackSymbols.has(symbol))) {
        reject(node, "mutation of a Claude API or callback binding");
      }
    }
  });
  return {
    effects: [...effects].map(([label, permission]) => ({ permission, label: `$.${label}` })),
    forbidden: [...forbidden],
  };
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
