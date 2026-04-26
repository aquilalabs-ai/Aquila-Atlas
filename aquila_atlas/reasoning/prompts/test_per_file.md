You are an expert {language} engineer specialising in test-driven development.

Generate a complete {framework} test file for the source file `{file_path}` from repository `{repo_id}`.

Output file: `{output_path}`

{imports_block}

{defines_block}

Source code:
{code_ctx}

## Requirements

- Write idiomatic {language} using {framework} conventions.
- Cover the happy path and at least two edge cases for every public function/method.
- Add mocks or stubs for external dependencies revealed by the imports above.
- Use descriptive test names that read as specifications (e.g. "should return 0 when list is empty").
- Include ONLY the test file content — no explanation text, no markdown fences, no preamble.
- If the source is too simple to test meaningfully, emit a single placeholder test with a TODO comment.

---

## CRITICAL RULES — read before writing a single line

### Import paths
- Use ONLY import paths that appear in the source code shown above or in the imports block.
- Do NOT guess or invent module paths. If you are unsure where a symbol lives, check the imports block and use the exact path shown there.
- Never import a symbol from a parent package (`from pkg import sym`) if the source shows it lives in a sub-module (`from pkg.sub import sym`).

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
- Module-level `sys.modules["X"] = dummy` executes at pytest *collection time* and pollutes every test file collected afterward (alphabetical order).
- If you must stub imports at module level so you can import the module under test, immediately restore the real module right after the import succeeds:
  ```python
  sys.modules["X"] = dummy_x
  from mypackage import module_under_test        # import now uses dummy
  sys.modules.pop("X", None)                     # restore so other files are unaffected
  ```
- Prefer injecting stubs inside an `autouse` fixture instead of at module level.

**Common wrong imports in FastAPI projects:**
- `CORSMiddleware` is NOT in `fastapi` — correct import: `from fastapi.middleware.cors import CORSMiddleware`
- `APIRouter` is in `fastapi`: `from fastapi import APIRouter`

**async tests:**
- Mark async test functions with `@pytest.mark.asyncio`.
- Use `pytest-asyncio` in `asyncio_mode = "auto"` or mark individually — do not mix.

---

## TypeScript / JavaScript rules (apply when {language} is TypeScript or JavaScript)

- `jest.mock()` paths must be real paths that exist in the project. Do NOT invent module paths.
- Use `jest.fn()` rather than `sinon` unless `sinon` appears in the project's imports.
- For async tests, always `await` the function under test and mark the test function `async`.
- Prefer `describe` / `it` blocks with clear nesting over flat `test()` calls for grouping.

---

## Java rules (apply when {language} is Java)

- Use `Mockito.mock(Cls.class)` and `@ExtendWith(MockitoExtension.class)` for unit tests.
- Do not add Spring `@Autowired` / `@SpringBootTest` unless the source file imports Spring.
- Each test class must have a public no-arg constructor or no constructor at all.

---

## Go rules (apply when {language} is Go)

- Table-driven tests with `t.Run(name, func(t *testing.T) {...})` are idiomatic — use them.
- Do not import packages that are not in the source file's import block.
- Use `t.Errorf` not `t.Fatalf` for non-fatal assertion failures.

---

## Rust rules (apply when {language} is Rust)

- Place unit tests in a `#[cfg(test)]` module at the bottom of the same file, or in a separate `tests/` integration test file — never mix.
- Use `assert_eq!` / `assert!` macros, not panics.

---

## General — applies to ALL languages

- Tests must be fully independent: no shared mutable state between test cases.
- Do not test private implementation details not exposed by the public API.
- Do not add `print` / `console.log` / `fmt.Println` debug statements in test code.
- Each test must be runnable in isolation without relying on the execution order of other tests.
