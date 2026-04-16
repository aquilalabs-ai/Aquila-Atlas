## Skill: Architecture exploration

You are answering a structural or architectural question.

The system message already contains pre-fetched code context — read it first
and use it to build your answer.

### Tool budget — STRICT LIMIT: 4 tool calls maximum

You **must** synthesize your final answer after at most 4 tool calls.
Do not exhaust your budget on low-value calls — plan before calling.

**Entry-point questions** ("what are the entry points", "how do they work", "how does this codebase work"):
- Call `repo_overview` **once**. It returns top entry points + call chains in a single call.
- Do NOT call `list_entry_points` + `call_chain` separately — that is the slow path.
- After `repo_overview`, synthesize immediately unless one specific entry point needs deeper exploration.

**Module / structure questions** ("what modules exist", "describe the folder structure", "what files are there"):
- Call `module_map` **once**. It returns all files grouped by package with entity counts.
- No semantic search needed.

**General structural questions**:
1. Start from the pre-fetched context in the system message.
2. If graph tools are available, call `read-cypher` for 1-2 targeted traversals
   (callers, callees, import chains) — schema context is automatically provided.
3. Use `semantic_search` only if the pre-fetched context is clearly missing something.
4. Synthesize after ≤ 4 calls total.

### Tool parameter reference
- `repo_overview` — parameters: `repo_id`, optional `max_entry_points` (default 3, max 5).
- `module_map` — parameter: `repo_id`.
- `get-schema` — no required parameters.
- `read-cypher` — parameter: `query` (the Cypher read query string; schema context automatically retrieved).
- `semantic_search` — parameters: `query`, `repo_id`, optional `top_k`, `chunk_type`.
- `file_reader` — parameters: `file_path`, `repo_id`.
- `list_entry_points` — parameter: `repo_id` (use `repo_overview` instead for entry-point questions).
- `call_chain` — parameters: `start_function`, `repo_id`, optional `max_depth` (default 5, keep ≤ 4).
- `git_log` — parameters: `repo_id`, optional `limit` (default 20), optional `file_path`.
- `git_status` — parameter: `repo_id`.
- `git_diff` — parameters: `repo_id`, optional `ref1` (default "HEAD"), `ref2`, `file_path`.
- `git_blame` — parameters: `repo_id`, `file_path`, optional `start_line`, `end_line`.

### Git queries
For questions about commit history, recent changes, who modified a file, or working-tree
status, use the git tools directly — do NOT call `semantic_search` for these.
- "show recent commits" → `git_log`  (local + GitHub)
- "what changed / git status / latest commit / branches" → `git_status`  (local + GitHub)
- "diff between X and Y" → `git_diff`  (local + GitHub; leave ref2 empty to see what HEAD introduced)
- "who changed line N of file F / git blame" → `git_blame`  (local only)
  - If GitHub repo: suggest `git_log` with `file_path` filter + `git_diff` on the commit instead.

If a git tool returns an error, report it to the user verbatim — do not retry with a different tool.
