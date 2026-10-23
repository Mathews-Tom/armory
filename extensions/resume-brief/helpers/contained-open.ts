import { dlopen, ptr, toArrayBuffer } from "bun:ffi";
import { close, constants } from "node:fs";
import { open } from "node:fs/promises";
import { getSystemErrorName, promisify } from "node:util";

const closeDescriptor = promisify(close);
// These libc flags are absent from Node's portable fs.constants declarations.
const CLOSE_ON_EXEC = process.platform === "darwin" ? 0x1000000 : 0o2000000;
const signature = { args: ["i32", "ptr", "i32"], returns: "i32" } as const;
const native = process.platform === "darwin"
  ? dlopen("/usr/lib/libSystem.B.dylib", { openat: signature, __error: { args: [], returns: "ptr" } })
  : process.platform === "linux"
    ? dlopen("libc.so.6", { openat: signature, __errno_location: { args: [], returns: "ptr" } })
    : unsupported();

function unsupported(): never {
  throw new Error("Resume Brief source containment requires macOS or Linux openat support");
}

function openAt(directory: number, name: string, flags: number): number {
  const encoded = Buffer.from(`${name}\0`);
  const descriptor = native.symbols.openat(directory, ptr(encoded), flags);
  if (descriptor >= 0) return descriptor;
  const address = "__error" in native.symbols ? native.symbols.__error() : native.symbols.__errno_location();
  if (address === null) throw new Error("openat failed without an errno address");
  const errno = new Int32Array(toArrayBuffer(address, 0, 4))[0];
  if (errno === undefined || errno <= 0) throw new Error("openat returned an invalid errno");
  throw Object.assign(new Error("repository source could not be opened without following links"), { code: getSystemErrorName(-errno) });
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
