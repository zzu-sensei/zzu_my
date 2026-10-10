# AGENTS

## Project Overview

- This repository is `zzupy`, a Python library that wraps Zhengzhou University mobile-app and web services, plus the Vercel-hosted web client (`api/` + `src/`) and Zensical documentation (`docs/`). The Android client is a separate repository — see below.
- Main public modules live under `zzupy/app`, `zzupy/web`, and `zzupy/aio`.
- Sync and async clients intentionally mirror each other. When changing behavior in `zzupy/app` or `zzupy/web`, check whether the same change is also needed in the corresponding `zzupy/aio` module.
- Data contracts are centralized in `zzupy/model`. Shared helpers live in `zzupy/utils.py`, and project-specific exceptions live in `zzupy/exception.py`.

## Offline Self-Checks (read this first)

- There is **no pytest suite**. Tests are standalone scripts under `scripts/` that use plain `assert` and a `main()` function.
- Run them all before considering a change done:

  ```bash
  uv run python scripts/run_tests.py          # all self-checks
  uv run python scripts/run_tests.py plan     # only files matching "plan"
  uv run python scripts/run_tests.py -v       # show full output
  ```

- When you add a feature, add `scripts/test_<feature>.py` with a `main()` that calls each case explicitly and prints a Chinese summary line. The runner auto-discovers `scripts/test_*.py`.
- A test that cannot fail is worthless. When fixing a bug, first reproduce the failure (for example, temporarily revert the fix and confirm the new assertion fails), then restore the fix.
- Anything requiring a real login (MFA, live pages) is **not** part of `scripts/test_*.py`. Put those in `scripts/dev/`, which is excluded from the runner.

## Stack And Tooling

- Python packaging is defined in `pyproject.toml`; the build backend is Hatchling.
- Use `uv` for environment management, installs, and project commands.
- Common commands:
  - `uv sync --extra develop,docs`
  - `uv build`
  - `ruff format zzupy`
  - `ruff check zzupy`
  - `ty check zzupy`
  - `uv run python scripts/run_tests.py`
- Lint scope is `zzupy` only. `api/index.py` intentionally has a few `E402` findings from its `sys.path.insert` pattern; leave them.
- Docs use **Zensical** (`zensical.toml`, not MkDocs). Update `docs/` and `zensical.toml` nav for user-facing changes, and keep `llms.txt` in sync when project guidance changes.

## Android Client Lives Elsewhere

- The Android client is a **separate repository**: <https://github.com/zzu-sensei/zzu-life-android>. It is not a subdirectory here any more.
- Its Python side (`mobile_zzupy.py`, `mobile_plan_page.py`) **reimplements** logic from `zzupy/app`, `zzupy/web`, and `zzupy/plan.py`, because `zzupy.logging` needs `loguru`, which is not bundled into the app. This repository cannot import or test the mobile code.
- When you change a shared rule (plan parsing, pass/fail classification, grade-point maths), change it in **both** repositories and keep their tests in sync. The mobile parser guards itself with `scripts/test_mobile_plan.py` over there.
- Do not re-add `flutter-app/`, Android build config, or APK workflows to this repository.

## Code Conventions

- Follow the existing Chinese-first documentation style for docstrings, logs, and user-facing error messages unless a file already uses another style.
- Keep implementations simple and explicit. This codebase prefers straightforward `httpx2` request flows over heavy abstraction.
- Reuse the existing exception types from `zzupy/exception.py` instead of raising generic exceptions for domain failures.
- Preserve the current logging style with `loguru`, including request/response diagnostics where a module already uses them.
- Keep type hints modern and consistent with the codebase, including `| None` unions and Pydantic v2 APIs such as `model_validate`.
- Put schema parsing and normalization in models or small helpers when possible; avoid duplicating response-shape handling across clients.

## API Client Guidance

- Most clients wrap reverse-engineered upstream services. Avoid speculative refactors that might change request headers, params, cookie handling, or encryption details unless required.
- Preserve login state behavior, token refresh flows, and context-manager semantics (`__enter__`, `__exit__`, `close`, `logout`) when modifying clients.
- When adding a new campus service, prefer matching the existing layout: client in `zzupy/app` or `zzupy/web`, async counterpart in `zzupy/aio`, models in `zzupy/model` if needed, and exports in the relevant `__init__.py`.
- If a response is validated with Pydantic in the sync client, keep the async client aligned.

### Traps Already Paid For

These were discovered against live responses. Do not "simplify" them away:

- **EAMS pages inline data as JavaScript object literals, not JSON.** They use single quotes, unquoted keys, and `$`-prefixed keys (`{'$type':'ResultType'}`), so `json.loads` can never work. Use `zzupy/web/jsdata.py` (or the mobile twin) — a parser that accepts **data literals only** and raises on functions or variable references instead of evaluating them.
- **The school's "not passed" course result is `UNREPAIRED`**, not `FAILED`. Matching only `FAILED` silently lists zero failed courses. The three real values are `PASSED`, `UNREPAIRED`, `TAKING`.
- **Plan credit fields are `credits` / `subModuleNum`**, not `requiredCredits` / `requiredCourseNum`. Different endpoints in the same system use different names.
- **Reusing a CAS token requires restoring MFA state too**, or `login()` raises `MFAError`. See `_cas_from_session` in `api/index.py`.
- **Grade point averages must be credit-weighted.** A plain arithmetic mean is wrong.
- **Parent and child plan modules are separate credit buckets.** Skipping a node because it has children silently drops its required credits.

## Documentation And Release Notes

- Public surface changes should usually update `README.md` and the relevant usage docs under `docs/usage/`.
- Keep repository-level AI/discovery metadata in sync when relevant: `llms.txt` for project guidance, `context7.json` for Context7 ownership metadata, and the README badges/links for external documentation indexes such as DeepWiki.
- API reference pages are generated from code, so exported symbols and docstrings matter.
- Prefer small, targeted documentation commits when changing repository metadata or discovery files so ownership/verification changes stay easy to audit.
- Versioning and release automation are handled through `python-semantic-release`; do not manually change release flow unless the task explicitly requires it.

## Workspace Hygiene

- The working tree may contain unrelated user changes or untracked files. Do not remove or overwrite them unless the user explicitly asks.
- In particular, check `git status` before broad edits, and limit changes to files relevant to the task.
- Never commit captured pages, session caches, or anything containing a real student's name, ID, grades, or credentials. Debug dumps go outside the repo and must be deleted after use.

