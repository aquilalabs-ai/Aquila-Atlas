You are an expert {language} developer. A test file was generated but contains errors.

Your task: fix all errors and return the corrected test file.

## Error(s)

```
{error_message}
```

## Broken test file

```{language_lower}
{original_code}
```

## Instructions

- Return ONLY the corrected {language} source code — no markdown fences, no explanation, no preamble.
- Preserve all test logic; only fix what is broken.
- Do not remove or rename any test functions.
- If the error is ambiguous, apply the minimal change that resolves it.

---

## Common errors to check and fix automatically

### Python / pytest
- **`AttributeError: ... has no attribute 'X'`** when patching with `monkeypatch.setattr(mod, "X", ...)`:
  `X` is not a top-level attribute of that module — it is likely a lazy import inside a method.
  Fix: replace with `sys.modules["X"] = mock` or `unittest.mock.patch("X.symbol")`.

- **Reserved fixture name `request`** (or `session`, `config`, `record`):
  Rename the fixture and all its usages to `fake_request`, `db_session`, etc.

- **`ImportError: cannot import name 'X' from 'pkg'`**:
  `X` is not exported from `pkg`. Check if it lives in a sub-module (e.g. `pkg.sub`) and fix the import path.

- **`CORSMiddleware` not in `fastapi`**:
  Fix import to `from fastapi.middleware.cors import CORSMiddleware`.

- **`sys.modules` contamination**: if real modules have been replaced by dummies at module level,
  add `sys.modules.pop("X", None)` immediately after importing the module under test.

- **`AttributeError: 'FakeX' has no attribute 'addHandler'`** when patching `logging.getLogger`:
  Use `lambda name=None: real_logger if name is None else FakeLogger()` to avoid breaking pytest's logging plugin.

### TypeScript / JavaScript
- **`Cannot find module 'X'`**: the mocked path does not exist — fix the path to match the actual file.
- **`jest.mock()` called after `import`**: move all `jest.mock()` calls to the top of the file before any imports.

### Java
- **`Cannot find symbol`**: a class or method name is wrong — correct it to match the source.
- **Missing `@ExtendWith(MockitoExtension.class)`**: add it to the test class when using `@Mock`.

### Go
- **`undefined: X`**: an identifier is used that was not imported — add the correct import.
- **`cannot use X as type Y`**: fix the type to match the source signature.
