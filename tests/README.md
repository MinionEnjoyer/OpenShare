# OpenShare test harness

The harness exercises the real FastAPI routes and SQLite queries without requiring Docker or
external services. Each test using `harness` gets:

- a fresh temporary SQLite database with the production migration path applied;
- fresh `files/` and `thumbs/` directories removed by pytest after the test;
- deterministic image, video, PDF, text, model, and waveform processors;
- a `TestClient` running the real application lifespan and middleware;
- helpers for browser-owner and scoped OpenChat service identities.

## Request identities

Use the service identity for the OpenChat upload contract:

```python
response = harness.upload(("pixel.png", PNG_1X1, "image/png"), source="chat")
```

Use the owner identity for browser-only routes such as folder or delete operations:

```python
response = harness.client.post(
    "/folders",
    headers=harness.owner_headers(),
    data={"name": "Images", "parent_id": ""},
)
```

`owner_headers()` includes the trusted Origin required by the CSRF boundary. Passing
`OTHER_OWNER` makes ownership-isolation tests concise. Requests without either identity remain
anonymous and exercise the real 401 path.

## Test groups

- `pytest -m unit` runs pure classification, configuration, and helper tests.
- `pytest -m integration` runs the ASGI/SQLite/storage harness.
- `pytest --cov` enforces the branch-coverage threshold configured in `pyproject.toml`.
- `make test-js` runs browser loading, navigation-timeout, and failure-recovery contracts with
  Node's built-in test runner and no third-party JavaScript test dependencies.

Media processors are faked by default so a malformed placeholder video or PDF is sufficient for
route tests. Tests for the processor implementations themselves should be marked separately and
may require system packages; they should not silently make the default suite depend on ffmpeg,
Poppler, or EGL.
