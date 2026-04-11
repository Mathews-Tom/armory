---
name: filesystem
description: 'File and directory operations via Claude Code built-in tools, replacing the Filesystem MCP server. Triggers on: "read this file", "write to file", "edit file", "find files matching", "search for text in files", "list directory", "show directory tree", "rename file".'
metadata:
  version: 1.1.1
  category: content
  tags: [files, directories, search, navigation]
  difficulty: beginner
---

# Filesystem

All file and directory operations use Claude Code's built-in tools. No MCP server
needed — native tools are faster, more capable, and cost zero context tokens when idle.

## Quick Reference

| Filesystem MCP Tool           | Replacement                    | Notes                                                                  |
| ----------------------------- | ------------------------------ | ---------------------------------------------------------------------- |
| `read_file(path)`             | `Read` tool                    | Supports line offset and limit                                         |
| `read_multiple_files(paths)`  | Multiple parallel `Read` calls | Faster than sequential MCP calls                                       |
| `write_file(path, content)`   | `Write` tool                   | Overwrites entire file                                                 |
| `edit_file(path, edits)`      | `Edit` tool                    | Exact string replacement; surgical edits                               |
| `list_directory(path)`        | `Glob` or `Bash ls`            | Glob for patterns, ls for simple listing                               |
| `directory_tree(path)`        | `Bash fd` or `Glob **/*`       | fd is fastest; Glob for pattern filtering                              |
| `search_files(pattern, path)` | `Grep` tool                    | Full regex, file type filters, context lines                           |
| `create_directory(path)`      | `Bash mkdir -p`                | `-p` creates intermediate directories                                  |
| `move_file(src, dst)`         | `Bash mv`                      | Also handles renames                                                   |
| `get_file_info(path)`         | `Bash stat` or `Bash ls -la`   | Size, permissions, timestamps                                          |
| `list_allowed_directories`    | N/A                            | Claude Code operates in the working directory; no sandbox restrictions |

---

## Reading Files

### Read a Single File

Use the `Read` tool with an absolute path:

```text
Read: /path/to/file.py
```

For large files, use offset and limit to read specific sections:

```text
Read: /path/to/file.py (offset: 100, limit: 50)
```

This reads 50 lines starting from line 100. Use this for files with thousands of lines
to avoid flooding context.

### Read Multiple Files in Parallel

Issue multiple `Read` calls in a single response. Claude Code executes them concurrently:

```text
Read: /path/to/file1.py
Read: /path/to/file2.py
Read: /path/to/file3.py
```

Parallel reads are faster than the MCP's `read_multiple_files` which serialized internally.

### Read Images and PDFs

The `Read` tool handles binary formats:

- **Images** (PNG, JPG, SVG): displayed visually
- **PDFs**: extracted text; use `pages: "1-5"` for large documents (max 20 pages per call)

---

## Writing and Editing Files

### Write a New File

Use the `Write` tool to create a file or overwrite an existing one:

```text
Write: /path/to/new-file.py
Content: <full file content>
```

The `Write` tool requires reading the file first if it already exists. For new files,
write directly.

### Edit an Existing File

Use the `Edit` tool for surgical modifications — replace exact string matches:

```text
Edit: /path/to/file.py
old_string: "def old_function():"
new_string: "def new_function():"
```

The `Edit` tool fails if `old_string` is not unique in the file. Provide enough
surrounding context to make the match unique, or use `replace_all: true` for
find-and-replace across the entire file.

**Prefer Edit over Write** for existing files. Edit preserves everything outside the
changed region and shows a clear diff. Write replaces the entire file.

---

## Finding Files

### By Name Pattern (Glob)

```text
Glob: **/*.py           → all Python files recursively
Glob: src/**/*.ts       → TypeScript files under src/
Glob: *.md              → Markdown files in current directory
Glob: **/test_*.py      → test files anywhere in the tree
```

Results are sorted by modification time (most recent first).

### By Content (Grep)

```text
Grep: pattern="def process_data" type="py"
Grep: pattern="TODO|FIXME" glob="*.py"
Grep: pattern="class.*Controller" output_mode="content" -C=2
```

| Grep Parameter   | Purpose                                            |
| ---------------- | -------------------------------------------------- |
| `pattern`        | Regex pattern to match                             |
| `type`           | File type filter (py, js, ts, rust, go, etc.)      |
| `glob`           | Glob pattern filter (`*.tsx`, `src/**/*.py`)       |
| `output_mode`    | `files_with_matches` (default), `content`, `count` |
| `-C`, `-A`, `-B` | Context lines: around, after, before matches       |
| `-i`             | Case-insensitive search                            |

### Directory Listing

Simple listing:

```bash
ls -la /path/to/directory
```

Recursive tree with `fd`:

```bash
fd . /path/to/directory --type f
```

Tree with depth limit:

```bash
fd . /path/to/directory --type f --max-depth 2
```

Filter by extension:

```bash
fd -e py /path/to/directory
```

---

## File Operations

### Create Directory

```bash
mkdir -p /path/to/new/directory
```

The `-p` flag creates all intermediate directories. Always verify the parent path
exists first with `ls`.

### Move / Rename

```bash
mv /path/to/source.py /path/to/destination.py
```

Rename a file (same directory):

```bash
mv /path/to/old-name.py /path/to/new-name.py
```

Move a directory:

```bash
mv /path/to/source-dir /path/to/destination-dir
```

### Copy

```bash
cp /path/to/source.py /path/to/destination.py
cp -r /path/to/source-dir /path/to/destination-dir
```

### Delete

```bash
rm /path/to/file.py
rm -r /path/to/directory
```

Always confirm with the user before deleting files or directories.

### File Metadata

```bash
stat /path/to/file.py
ls -la /path/to/file.py
wc -l /path/to/file.py
```

| Command  | Returns                                     |
| -------- | ------------------------------------------- |
| `stat`   | Size, permissions, timestamps, inode        |
| `ls -la` | Permissions, owner, size, modification date |
| `wc -l`  | Line count                                  |
| `file`   | MIME type detection                         |

---

## Common Workflows

### Find and Replace Across Files

```bash
# Find all files containing the old string
Grep: pattern="old_function_name" type="py" output_mode="files_with_matches"

# Then Edit each file
Edit: /path/to/file1.py (old_string → new_string, replace_all: true)
Edit: /path/to/file2.py (old_string → new_string, replace_all: true)
```

### Explore an Unfamiliar Codebase

1. Check project structure: `fd . --type f --max-depth 2`
2. Read configuration: `Read: package.json` or `Read: pyproject.toml`
3. Find entry points: `Grep: pattern="def main|if __name__" type="py"`
4. Read key files identified above

### Find Large Files

```bash
fd --type f --exec stat -f '%z %N' {} \; | sort -rn | head -20
```

---

## Error Handling

| Error                       | Cause                                   | Resolution                                        |
| --------------------------- | --------------------------------------- | ------------------------------------------------- |
| Read: file not found        | Path incorrect or file deleted          | Verify with `ls` or `Glob`                        |
| Edit: old_string not unique | Multiple matches in the file            | Add more surrounding context to make it unique    |
| Edit: old_string not found  | Content changed since last read         | Re-read the file, then retry with current content |
| Write: file not read first  | Attempting to overwrite without reading | Read the file first, then Write                   |
| Permission denied           | Insufficient OS permissions             | Check with `ls -la`; use `chmod` if appropriate   |
| Glob: no files found        | Pattern too restrictive                 | Broaden the pattern; check path spelling          |

---

## Limitations

- **Read** returns up to 2000 lines by default. Use offset/limit for larger files.
- **Read** truncates lines longer than 2000 characters.
- **Edit** requires exact string matching — whitespace and indentation must match precisely.
- **Write** overwrites the entire file. No append mode. To append, read first, then write
  the combined content.
- **Glob** only matches files, not directories. Use `Bash ls` or `fd` to list directories.
- **PDF reading** is limited to 20 pages per call. Specify page ranges for large documents.

---

## Calibration Rules

1. **Read before Edit.** Always read a file before editing it. The Edit tool enforces this.
2. **Edit over Write for existing files.** Edit is surgical and shows diffs. Write is a
   full replacement — use it only for new files or complete rewrites.
3. **Glob over Bash for file search.** Glob is optimized for pattern matching. Only fall
   back to `fd` or `find` for queries Glob cannot express (size filters, date filters).
4. **Grep over Bash for content search.** Grep is optimized for ripgrep-based search with
   proper permissions. Never use `grep` or `rg` via Bash.
5. **Parallel reads for multiple files.** Issue all Read calls in a single response for
   concurrent execution.
6. **Always use absolute paths.** Claude Code tools require absolute paths. Never pass
   relative paths to Read, Write, or Edit.
