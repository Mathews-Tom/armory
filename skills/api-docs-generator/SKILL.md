---
name: api-docs-generator
description: 'Audits and enhances FastAPI and REST API documentation: missing descriptions, response codes, examples, docstrings, Pydantic models, OpenAPI spec. Triggers on: "generate API docs", "document this API", "OpenAPI for", "FastAPI docs", "document endpoints", "swagger docs".'
metadata:
  version: 1.1.1
  category: review
  tags: [api, documentation, openapi, fastapi]
  difficulty: intermediate
  phase: ship
---

# API Docs Generator

Audits API endpoint documentation for completeness, generates enhanced docstrings with
proper parameter descriptions and examples, documents all response codes, and produces
Pydantic model examples — bridging the gap between auto-generated OpenAPI specs and
genuinely useful API documentation.

## Reference Files

| File                                | Contents                                                                | Load When                     |
| ----------------------------------- | ----------------------------------------------------------------------- | ----------------------------- |
| `references/fastapi-patterns.md`    | FastAPI-specific documentation patterns, Path/Query/Body parameter docs | FastAPI endpoint              |
| `references/example-generation.md`  | Creating realistic field examples, model_config patterns                | Example values needed         |
| `references/response-codes.md`      | Standard HTTP response documentation, error response schemas            | Response documentation needed |
| `references/openapi-enhancement.md` | OpenAPI spec enrichment, tag organization, schema documentation         | OpenAPI spec review           |

## Prerequisites

- Access to the API source code (route definitions, models)
- Framework identification (FastAPI, Flask, Django REST, Express)

## Workflow

### Phase 1: Analyze Endpoints

1. **Inventory endpoints** — List all routes with HTTP method, path, handler function.
2. **Identify models** — Request bodies (Pydantic models, dataclasses), response models,
   query parameters, path parameters.
3. **Map dependencies** — Authentication requirements, middleware, shared dependencies.
4. **Read existing docs** — Current docstrings, OpenAPI metadata, inline documentation.

### Phase 2: Audit Documentation

For each endpoint, check:

| Check                  | What to Verify                                   | Common Gap               |
| ---------------------- | ------------------------------------------------ | ------------------------ |
| Endpoint description   | Handler has a docstring                          | Missing or "TODO"        |
| Parameter descriptions | Each param has `description=`                    | Path params undocumented |
| Request example        | Body model has `example=` or `json_schema_extra` | No request example       |
| Response model         | `response_model=` specified                      | Returns raw dict         |
| Error responses        | 4xx/5xx documented with `responses=`             | Only 200 documented      |
| Tags                   | Endpoint assigned to a tag group                 | Untagged endpoints       |

### Phase 3: Generate Enhancements

1. **Docstrings** — Write clear endpoint descriptions that explain purpose, not
   implementation. Include Raises section for documented errors.
2. **Parameter metadata** — Add `description`, `example`, `ge`/`le`/`regex` to
   Path, Query, Body parameters.
3. **Model examples** — Add `Field(example=...)` and `model_config` with `json_schema_extra`.
4. **Error responses** — Document every possible error status code with response schema.
5. **Tags** — Group endpoints by resource or feature area.

### Phase 4: Output

Produce a coverage report and enhanced code.

## Output Format

````
## API Documentation Audit

### Coverage Summary
| Metric | Count | Documented | Coverage |
|--------|-------|------------|----------|
| Endpoints | {N} | {M} | {%} |
| Parameters | {N} | {M} | {%} |
| Response codes | {N} | {M} | {%} |
| Models with examples | {N} | {M} | {%} |

### Gaps Identified

| # | Endpoint | Issue | Severity |
|---|----------|-------|----------|
| 1 | `{METHOD} {path}` | {issue} | {High/Medium/Low} |

### Enhanced Code

#### `{METHOD} {path}`

```python
@router.{method}(
    "{path}",
    response_model={ResponseModel},
    summary="{Short summary}",
    responses={{
        404: {{"description": "{Not found description}"}},
        422: {{"description": "Validation error"}},
    }},
    tags=["{tag}"],
)
async def {handler}(
    {param}: {type} = Path(..., description="{description}", example={example}),
) -> {ResponseModel}:
    """
    {Full description of what this endpoint does.}

    {Additional context about behavior, side effects, or important notes.}

    Raises:
        404: {Entity} not found
        403: Insufficient permissions
    """
````

#### Model: `{ModelName}`

```python
class {ModelName}(BaseModel):
    {field}: {type} = Field(..., description="{description}", example={example})

    model_config = ConfigDict(
        json_schema_extra={{
            "example": {{
                "{field}": {example_value},
            }}
        }}
    )
```

```text

## Calibration Rules

1. **Describe behavior, not implementation.** "Retrieves the user's profile" is good.
   "Calls `db.query(User).filter_by(id=id).first()`" is implementation leakage.
2. **Realistic examples.** `"alice@example.com"` not `"string"`. `42` not `0`.
   Examples serve as documentation — they should look like real data.
3. **Document every error code.** If the endpoint can return 404, document it. Users
   should never encounter an undocumented error response.
4. **Consistent style.** All endpoints in the same API should use the same documentation
   patterns — same tag naming, same description style, same example format.
5. **Don't duplicate the type system.** If the parameter type is `int`, don't write
   "An integer" as the description. Write what the integer represents: "Unique user
   identifier."

## Error Handling

| Problem | Resolution |
|---------|------------|
| Non-FastAPI framework | Adapt patterns. Document the HTTP contract regardless of framework. |
| No type hints on handlers | Infer types from usage, document uncertainty, suggest adding type hints. |
| Massive API (50+ endpoints) | Prioritize undocumented and public endpoints. Batch output by resource. |
| Generated API (OpenAPI → code) | Document at the spec level, not the generated code level. |
| Authentication varies by endpoint | Document auth requirements per endpoint group. |

## When NOT to Generate

Push back if:
- The API design itself is wrong (bad URL patterns, wrong HTTP methods) — fix the API first
- The user wants SDK generation from OpenAPI — different tool
- The code is a prototype that will change significantly — document after stabilization
```
