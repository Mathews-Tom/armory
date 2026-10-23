import { dlopen, ptr, toArrayBuffer } from "bun:ffi";
import { close, closeSync, constants, openSync } from "node:fs";
import { open } from "node:fs/promises";
import { getSystemErrorName, promisify } from "node:util";

const closeDescriptor = promisify(close);
// These libc flags are absent from Node's portable fs.constants declarations.
const CLOSE_ON_EXEC = process.platform === "darwin" ? 0x1000000 : 0o2000000;
const bindings = {
  openat: { args: ["i32", "ptr", "i32", "u32"], returns: "i32" },
  mkdirat: { args: ["i32", "ptr", "u32"], returns: "i32" },
  linkat: { args: ["i32", "ptr", "i32", "ptr", "i32"], returns: "i32" },
  unlinkat: { args: ["i32", "ptr", "i32"], returns: "i32" },
  closedir: { args: ["ptr"], returns: "i32" },
} as const;
const directoryBindings = {
  fdopendir: { args: ["i32"], returns: "ptr" },
  readdir: { args: ["ptr"], returns: "ptr" },
} as const;
const darwinBindings = {
  ...bindings,
  mkostempsat_np: { args: ["i32", "ptr", "i32", "i32"], returns: "i32" },
  __error: { args: [], returns: "ptr" },
} as const;
const native = process.platform === "darwin"
  ? process.arch === "x64"
    ? dlopen("/usr/lib/libSystem.B.dylib", {
      ...darwinBindings,
      "fdopendir$INODE64": directoryBindings.fdopendir,
      "readdir$INODE64": directoryBindings.readdir,
    })
    : dlopen("/usr/lib/libSystem.B.dylib", { ...darwinBindings, ...directoryBindings })
  : process.platform === "linux"
    ? dlopen("libc.so.6", { ...bindings, ...directoryBindings, __errno_location: { args: [], returns: "ptr" } })
    : unsupported();
// Intel Darwin's bare symbols use legacy dirents, unlike the INODE64 decoder.
const openDirectoryStream = "fdopendir$INODE64" in native.symbols ? native.symbols["fdopendir$INODE64"] : native.symbols.fdopendir;
const readDirectoryStream = "readdir$INODE64" in native.symbols ? native.symbols["readdir$INODE64"] : native.symbols.readdir;

function unsupported(): never {
  throw new Error("Resume Brief source containment requires macOS or Linux openat support");
}

function errnoSlot(): Int32Array {
  const address = "__error" in native.symbols ? native.symbols.__error() : native.symbols.__errno_location();
  if (address === null) throw new Error("filesystem operation failed without an errno address");
  return new Int32Array(toArrayBuffer(address, 0, 4));
}

function nativeError(operation: string): Error {
  const errno = errnoSlot()[0];
  if (errno === undefined || errno <= 0) throw new Error(`${operation} returned an invalid errno`);
  return Object.assign(new Error(`${operation} failed without following links`), { code: getSystemErrorName(-errno) });
}

function checkNative(result: number, operation: string): void {
  if (result !== 0) throw nativeError(operation);
}

export function openAt(directory: number, name: string, flags: number, mode = 0): number {
  const encoded = Buffer.from(`${name}\0`);
  const descriptor = native.symbols.openat(directory, ptr(encoded), flags | CLOSE_ON_EXEC, mode);
  if (descriptor < 0) throw nativeError("openat");
  return descriptor;
}

/** Darwin openat is variadic: use its public fixed-ABI 0600 creation API. */
export function createTemporary(directory: number, name: string): { descriptor: number; name: string } {
  if ("mkostempsat_np" in native.symbols) {
    const template = Buffer.from(`${name}-XXXXXX\0`);
    const descriptor = native.symbols.mkostempsat_np(directory, ptr(template), 0, CLOSE_ON_EXEC);
    if (descriptor < 0) throw nativeError("mkostempsat_np");
    return { descriptor, name: template.subarray(0, template.indexOf(0)).toString("utf8") };
  }
  return {
    descriptor: openAt(directory, name, constants.O_CREAT | constants.O_EXCL | constants.O_WRONLY | constants.O_NOFOLLOW, 0o600),
    name,
  };
}

/** Create/open by pinned ancestors; no pathname is resolved after a parent check. */
export function openDirectory(path: string, create = false): number {
  let descriptor = openSync("/", constants.O_RDONLY | constants.O_DIRECTORY | constants.O_NOFOLLOW | CLOSE_ON_EXEC);
  try {
    for (const part of path.split("/").filter(Boolean)) {
      let next: number;
      try { next = openAt(descriptor, part, constants.O_RDONLY | constants.O_DIRECTORY | constants.O_NOFOLLOW); } catch (error) {
        if (!create || !(error instanceof Error) || !("code" in error) || error.code !== "ENOENT") throw error;
        const encoded = Buffer.from(`${part}\0`);
        if (native.symbols.mkdirat(descriptor, ptr(encoded), 0o700) !== 0) {
          const failure = nativeError("mkdirat");
          if (!("code" in failure) || failure.code !== "EEXIST") throw failure;
        }
        next = openAt(descriptor, part, constants.O_RDONLY | constants.O_DIRECTORY | constants.O_NOFOLLOW);
      }
      closeSync(descriptor);
      descriptor = next;
    }
    const result = descriptor;
    descriptor = -1;
    return result;
  } finally {
    if (descriptor >= 0) closeSync(descriptor);
  }
}

export function linkAt(directory: number, from: string, to: string): void {
  const source = Buffer.from(`${from}\0`);
  const target = Buffer.from(`${to}\0`);
  checkNative(native.symbols.linkat(directory, ptr(source), directory, ptr(target), 0), "linkat");
}

export function unlinkAt(directory: number, name: string): void {
  const encoded = Buffer.from(`${name}\0`);
  checkNative(native.symbols.unlinkat(directory, ptr(encoded), 0), "unlinkat");
}

const nameDecoder = new TextDecoder("utf-8", { fatal: true });

/** POSIX directory stream owns a separate descriptor and closes on early return. */
export function* directoryNames(directory: number): Generator<string> {
  const descriptor = openAt(directory, ".", constants.O_RDONLY | constants.O_DIRECTORY | constants.O_NOFOLLOW);
  const stream = openDirectoryStream(descriptor);
  if (stream === null) {
    const error = nativeError("fdopendir");
    closeSync(descriptor);
    throw error;
  }
  try {
    for (;;) {
      errnoSlot()[0] = 0;
      const entry = readDirectoryStream(stream);
      if (entry === null) {
        if (errnoSlot()[0] !== 0) throw nativeError("readdir");
        return;
      }
      const header = new DataView(toArrayBuffer(entry, 0, 18));
      const recordLength = header.getUint16(16, true);
      const offset = process.platform === "darwin" ? 21 : 19;
      if (recordLength <= offset || recordLength > 4096) throw new Error("invalid native directory entry");
      const bytes = new Uint8Array(toArrayBuffer(entry, offset, recordLength - offset));
      const end = bytes.indexOf(0);
      if (end < 0) throw new Error("unterminated native directory entry");
      const name = nameDecoder.decode(bytes.subarray(0, end));
      if (name !== "." && name !== "..") yield name;
    }
  } finally {
    checkNative(native.symbols.closedir(stream), "closedir");
  }
}

/** Pin every directory, including root ancestors; never follow a swapped link. */
export async function openRepositoryFile(root: string, relative: string): Promise<number> {
  const rootHandle = await open("/", constants.O_RDONLY | constants.O_DIRECTORY | constants.O_NOFOLLOW);
  const directories: number[] = [];
  try {
    let parent = rootHandle.fd;
    const parts = [...root.split("/").filter(Boolean), ...relative.split("/")];
    const leaf = parts.pop();
    if (leaf === undefined) throw new Error("repository source has no leaf");
    for (const part of parts) {
      const next = openAt(parent, part, constants.O_RDONLY | constants.O_DIRECTORY | constants.O_NOFOLLOW | CLOSE_ON_EXEC);
      directories.push(next);
      parent = next;
    }
    return openAt(parent, leaf, constants.O_RDONLY | constants.O_NOFOLLOW | constants.O_NONBLOCK | CLOSE_ON_EXEC);
  } finally {
    for (let index = directories.length - 1; index >= 0; index--) {
      const descriptor = directories[index];
      if (descriptor !== undefined) await closeDescriptor(descriptor);
    }
    await rootHandle.close();
  }
}
