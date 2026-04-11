# Repositories

GitHub repository operations via `gh repo` — create, fork, clone, view, edit, archive, delete.

## Create

Create a new public repository:

```bash
gh repo create owner/new-repo --public --description "Service for handling webhooks"
```

Create from a template:

```bash
gh repo create owner/new-service --template owner/service-template --public --clone
```

## Fork and Clone

```bash
gh repo fork owner/repo --clone
gh repo clone owner/repo
```

## View and List

```bash
gh repo view owner/repo
gh repo view owner/repo --json name,description,defaultBranchRef --jq '.defaultBranchRef.name'
```

List repos in an org:

```bash
gh repo list some-org --limit 50 --json name,isArchived \
  --jq '.[] | select(.isArchived == false) | .name'
```

## Edit Settings

```bash
gh repo edit owner/repo --description "Updated description" --enable-issues --enable-wiki=false
```

## Archive and Delete

```bash
gh repo archive owner/repo --yes
gh repo delete owner/repo --yes
```
