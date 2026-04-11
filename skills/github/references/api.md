# API: REST and GraphQL

Raw API access via `gh api` — REST methods, pagination, rate limit, and GraphQL. For GraphQL cost model, bulk queries, mutations, and rate limit management, see `graphql-queries.md`.

## REST: GET

```bash
gh api repos/owner/repo/pulls/55 --jq '{title: .title, state: .state, author: .user.login}'
```

## REST: POST

```bash
gh api repos/owner/repo/issues/42/comments -f body="Automated comment from CI triage"
```

## REST: PATCH

```bash
gh api repos/owner/repo/issues/42 -X PATCH -f state="closed"
```

## Pagination

Paginate through all results automatically:

```bash
gh api repos/owner/repo/issues --paginate --jq '.[].number'
```

## Rate Limit Check

```bash
gh api rate_limit --jq '{core: .resources.core, graphql: .resources.graphql}'
```

## GraphQL Queries

Inline GraphQL query:

```bash
gh api graphql -f query='
  query {
    repository(owner: "owner", name: "repo") {
      issues(first: 5, states: OPEN) {
        nodes {
          number
          title
        }
      }
    }
  }
' --jq '.data.repository.issues.nodes[] | "\(.number) \(.title)"'
```

See `graphql-queries.md` for cost model, bulk queries, mutations, and rate
limit management patterns.

## REST vs GraphQL Decision Table

| Scenario                                       | Use             | Reason                                                  |
| ---------------------------------------------- | --------------- | ------------------------------------------------------- |
| Fetch a single resource (one PR, one issue)    | REST (`gh api`) | Simple, predictable, low overhead                       |
| Fetch nested or related data in one round-trip | GraphQL         | Avoids N+1 requests; select only needed fields          |
| Bulk operations across many resources          | GraphQL         | Query complexity points are cheaper than REST calls     |
| Creating or updating a resource (mutation)     | Either          | REST: `-X POST/PATCH`; GraphQL: `mutation {}` block     |
| Rate-limit-sensitive pipeline or script        | REST            | REST has a simple 5000 req/hr counter; easier to budget |
| ProjectV2 board operations                     | GraphQL         | ProjectV2 has no REST API; GraphQL only                 |
