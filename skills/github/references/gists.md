# Gists

GitHub gist operations via `gh gist` — create, list, view, edit, delete.

## Create

Create a public gist from a file:

```bash
gh gist create --public --desc "Rate limiter implementation" rate_limiter.py
```

Create from stdin:

```bash
echo '{"key": "value"}' | gh gist create --filename config.json
```

## List, View, Edit, Delete

```bash
gh gist list --limit 10
gh gist view abc123def456
gh gist edit abc123def456 --add new_file.py
gh gist delete abc123def456
```
