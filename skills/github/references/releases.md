# Releases

GitHub release operations via `gh release` — create, list, view, edit, upload assets, and delete.

## Create

Create a release with auto-generated notes:

```bash
gh release create v1.2.0 --repo owner/repo --generate-notes
```

Create with title, notes, and binary assets:

```bash
gh release create v1.2.0 --repo owner/repo \
  --title "v1.2.0 — Rate Limiter" \
  --notes "Adds token bucket rate limiting to all API endpoints" \
  ./dist/app-linux-amd64 ./dist/app-darwin-arm64
```

Create a prerelease:

```bash
gh release create v2.0.0-rc1 --repo owner/repo --prerelease --generate-notes
```

## List and View

```bash
gh release list --repo owner/repo --limit 5
gh release view v1.2.0 --repo owner/repo
```

## Edit and Upload Assets

```bash
gh release edit v1.2.0 --repo owner/repo --draft=false --prerelease=false
```

Upload additional assets to an existing release:

```bash
gh release upload v1.2.0 --repo owner/repo ./dist/app-windows-amd64.exe
```

## Delete

```bash
gh release delete v1.0.0-beta --repo owner/repo --yes
```
