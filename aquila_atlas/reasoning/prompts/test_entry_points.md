You are an expert {language} engineer specialising in test-driven development.

Generate a focused {framework} test file for the entry-point function `{function_name}` defined in `{file_path}` (repository `{repo_id}`).

Output file: `{output_path}`

This function has {out_degree} direct callees — mock them where appropriate.

Source code:
{code_ctx}

## Requirements

- Write idiomatic {language} using {framework} conventions.
- Cover the primary success path plus error/boundary conditions.
- Mock or patch all external I/O, network calls, and direct callees so tests run offline and deterministically.
- Use descriptive test names that read as specifications.
- Include ONLY the test file content — no explanation text, no markdown fences, no preamble.

---

## CRITICAL RULES — read before writing a single line

### Import paths
- Use ONLY import paths that appear in the source code shown above.
- Do NOT guess or invent module paths. If you are unsure where a symbol lives, use the exact file path shown in the source context.
- Never import a symbol from a parent package if the source shows it lives in a sub-module.

### Mocking strategy
- When a dependency is imported **at the top level** of the source file (e.g. `import X` or `from X import Y`), patch it as a module attribute: `monkeypatch.setattr(module_under_test, "X", mock)`.
- When a dependency is imported **lazily inside a function or method body** (i.e. `import X` appears inside a `def` or `__init__`), there is NO top-level attribute to patch. You MUST inject it via `sys.modules["X"] = mock_module` before the code runs, or use `unittest.mock.patch("X.symbol")`.
- Never call `monkeypatch.setattr(module, "attr", ...)` for a name that does not exist at the top level of that module — it raises `AttributeError`.

---

## Python / pytest rules (apply when {language} is Python)

**Reserved fixture names — NEVER use these as fixture or parameter names:**
- `request` → use `http_request`, `fake_request`, or similar
- `session` → use `db_session`, `fake_session`, or similar
- `config` → use `app_config`, `fake_config`, or similar
- `record` → use `log_record`, `fake_record`, or similar

**sys.modules contamination:**
- Module-level `sys.modules["X"] = dummy` executes at pytest *collection time* and pollutes every test file collected afterward.
- If you must stub imports at module level, immediately restore afterward:
  ```python
  sys.modules["X"] = dummy_x
  from mypackage import module_under_test
  sys.modules.pop("X", None)   # restore so other test files are unaffected
  ```

**async tests:**
- Mark async test functions with `@pytest.mark.asyncio`.

---

## TypeScript / JavaScript rules (apply when {language} is TypeScript or JavaScript)

- `jest.mock()` paths must be real paths that exist in the project. Do NOT invent module paths.
- For async tests, always `await` the function under test and mark the test function `async`.

---

## Java rules (apply when {language} is Java)

- Use `Mockito.mock(Cls.class)` and `@ExtendWith(MockitoExtension.class)` for unit tests.
- Do not add Spring annotations unless the source file imports Spring.

---

## Go rules (apply when {language} is Go)

- Table-driven tests with `t.Run` are idiomatic — use them.
- Do not import packages that are not in the source file's import block.

---

## General — applies to ALL languages

- Tests must be fully independent: no shared mutable state between test cases.
- Each test must be runnable in isolation without relying on the execution order of other tests.
