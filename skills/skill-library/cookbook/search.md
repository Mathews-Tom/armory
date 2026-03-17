# Search Recipe

## Steps

1. **Fetch catalog** — use cached `/tmp/armory-catalog.yaml` if < 10 min old; missing = expired, re-fetch from remote.

2. **Search `name` and `description` fields** for keyword matches against the user query.

3. **Rank by weighted scoring:**

   | Match Type                  | Weight  | Example                                              |
   | --------------------------- | ------- | ---------------------------------------------------- |
   | Exact name match            | 10      | query `"test-harness"` → skill `"test-harness"`      |
   | Name substring match        | 5       | query `"test"` → skill `"test-harness"`              |
   | Description token match     | 2/token | query `"testing"` → description contains `"testing"` |
   | Description substring match | 1       | query `"bench"` → description contains `"benchmark"` |
   - Matching is case-insensitive.
   - Scores accumulate across fields.

4. **Display top 10 matches** with name, version, score, and truncated description (first 80 chars).

5. **Suggest** `/library use <name>` for any result.
