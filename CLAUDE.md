# AGENTS.md
Global source of truth for cross-agent engineering and collaboration rules.
If the current repository contains `PROJECT_CONSTRAINTS.md`, read it first. If it conflicts with this file, `PROJECT_CONSTRAINTS.md` wins.
Apply rules in this order: `PROJECT_CONSTRAINTS.md`, then `Part I`, then `Part II`.

## Part I: Engineering Canon
### Taste
- Data over hidden state. Default to explicit data structures and pure transforms; introduce methods only when state-bound behavior makes the code clearer.
- Explicit over implicit. A few lines of glue code are cheaper than one layer of clever auto-discovery.
- Delete before you modify; modify before you add.
- Narrow over broad. Accept the narrowest useful input types and return the most concrete useful output types.
- Boring over clever. If a design is interesting to explain, it is probably too complicated.
- Optimize for the reader. Saving a future reader 30 seconds is usually worth more than saving the author 5 minutes.
- Prefer local reasoning. A reader should not need to jump across files to understand one function's core behavior.
- Hardcode until the second real value appears. A single-use option is a constant, not configuration.
- Compile-time over runtime. Push checks into types, constructors, and enums before adding runtime flags, strings, or warnings.
- Crash over silent corruption. When state correctness is in doubt, stop immediately rather than continue with possibly wrong data.
- Environment variables are deployment contracts, not application APIs. Read them once at the process boundary, parse them into typed values, and pass those values inward. Nothing below the boundary may read env, infer env, or know which env it runs in.
- A CLI is an adapter: parse input, load config, call pure logic, and render output. Business code must not touch argv, cwd, shell state, process env, or exit codes.
- Configuration priority converges in exactly one place. The chain `flag > env > file > default` is declared once, pruned to the needed sources, and tested. Do not add fallback paths, ambient injection, or casual `unwrap_or` defaults.
- Fallback is a design smell. If a path needs fallback, name the missing abstraction or boundary explicitly and redesign it; do not hide uncertainty behind recovery order.
- Hidden inputs create unknown state. Every runtime input must have one named owner, one validation point, and one typed representation before it reaches business code.
- A process boundary is not a code reuse mechanism.

### Core Principles
- Solve concrete problems before introducing abstractions.
- Make changes easy to test and easy to revert.

### Design
- Each module, function, and type should have one clear reason to change.
- Keep transport, domain logic, and persistence separate.
- Inner functions should accept data and return data; do not perform IO in core transforms.
- Prefer small, orthogonal interfaces over broad manager-style types.
- Do not build god objects coordinating unrelated concerns.
- Each layer should own its own document types. Share only small stable atoms or value objects across layers, and transform explicitly at boundaries.
- When shared metadata or capability declarations appear across schema, API, semantic, and UI layers, pick one source of truth and let other layers project or subset it.
- Do not maintain a second copy of labels, units, route names, or capability declarations when one layer already owns them.

### Language and API Style
- Use language-native idioms instead of imported layering habits.
- Model constraints in types where practical.
- Keep public APIs minimal and stable.
- Do not introduce new layers or types named `service`, `manager`, `factory`, or `coordinator` unless required by a framework or existing external contract.
- Do not introduce an interface/trait/protocol for a single implementation. In Rust, default to concrete structs/functions; a trait requires either 2 real implementations now or a clear second implementation boundary.
- Do not parameterize for one caller or one value. Introduce configuration, generics, or strategy hooks only after a second real case appears.
- Prefer concrete domain handles over free-function soup. If a set of operations shares one boundary or datasource, group it under one owning module or struct.
- Name types by role, not transport jargon. Prefer names such as `Row`, `Query`, `View`, `Spec`, and `Plan`; avoid `Response` for internal non-HTTP types.

### Type Precision
- If two values share the same Rust type but carry different domain meanings, distinguish them in the type system.
- Domain identifiers (addresses, keys, hashes, IDs) must not be raw `String`; wrap them in a newtype.
- Quantities with units (timestamps, durations, amounts, difficulties) must not remain raw integers when two or more coexist in the same type, function, or module.
- If a struct uses a `bool` plus one or more `Option` fields to model mutually exclusive states, replace it with an enum.
- Functions must not return unnamed tuples with more than two elements; introduce a named struct.

### Common Failure Shapes
- One file owns an entire lifecycle because planning, submission, reconciliation, and finalization were not split early.
- State is encoded as `bool + Option + comments` instead of an enum.
- A trait/interface is introduced before a second real implementation exists.
- A single real value is turned into config, generic plumbing, or strategy hooks too early.
- Domain meaning is carried by tuple position or raw primitive types instead of named fields or newtypes.

### Errors
- Library code must return typed errors; do not use `anyhow`/`eyre` across library boundaries.
- `anyhow`/`eyre` are for binary, CLI, and top-level task entrypoints only.
- Add boundary context when an error crosses an IO, network, storage, or process boundary.
- Do not swallow errors or collapse failures into opaque strings.
- Separate external/transport failures from domain/business failures when callers may handle them differently.

### Code Hygiene
- Keep functions focused; split mixed concerns.
- Remove dead code, unused dependencies, and speculative abstractions.
- Choose concise, domain-meaningful names.
- Modules and files must be named by business/domain responsibility.
- Do not use catch-all names like `support`, `common`, `shared`, `util`, `helper`, or `meta` for business logic modules.

### Testing and Verification
- Add tests for deterministic logic.
- Keep live or external integration tests out of the default local path.
- Make failures actionable.
- Skip live tests gracefully when credentials are absent.
- Run the narrowest relevant tests first, then broader tests needed for confidence.
- Public typed APIs should have shape-level guards when callers depend on response structure, not only value assertions.
- Before merge, ensure formatting, linting, and tests are clean.
- Before committing Rust code, ensure `cargo clippy --all-targets` passes.
- Before committing code, ensure the full relevant test suite passes.

### Conditional Rules
#### When touching state machines, retries, or async orchestration
- Name states explicitly.
- Define restart, retry, and duplicate-handling behavior.
- Do not mix transitions, IO, and persistence in one function.

#### When introducing new persistence or schema fields
- Define units, nullability, and ownership explicitly.
- Avoid ambiguous raw primitives when domain meaning differs.

#### When adding config
- Justify the second real value.
- If there is only one real value, keep it as a constant.

#### When a feature has both primary and recovery paths
- Keep the externally visible capability surface consistent across both paths.
- Do not let a recovery or tool path lag behind the contract exposed to callers.

### AI and Code Size Rules
- When a normal hand-written source file exceeds 500 lines, consider splitting it. 800 lines is the hard limit unless the file is generated, schema-only, or test fixture data.
- Prefer functions under 80 lines; 120 is the hard limit for normal functions.
- Treat large AI-generated files as a review failure even if they appear correct.
- If AI generates more than 300-500 lines of core logic in one pass, stop and split the work.
- For locks, async control flow, state machines, retry logic, payout, or settlement, do not accept one large-file AI patch without manual decomposition.

### Rule-to-Check Bias
- Prefer rules that can be checked mechanically.
- If a rule is high-frequency and checkable, add a script or CI check instead of repeating review comments.
- Prefer lightweight checks that run often over heavyweight gates that nobody runs locally.

### Review Heuristics
- Is this the simplest design that works?
- Are types and errors explicit?
- Can another engineer understand it in one pass?
- Can any abstraction be deleted without losing value?
- Did this change concentrate too much complexity into one file or one object?
- If a repo has `PROJECT_CONSTRAINTS.md`, apply its priority order first during review.

### Commits
- Keep commits focused and coherent.
- Describe why, not only what.
- Include verification commands and observed results when useful.
- Bad case: never put literal `\n` escapes into commit message bodies; write real line breaks so the body renders correctly in `git log`.

## Part II: Agent, Collaboration, and Workflow
### Session Startup
Read `PROJECT_CONSTRAINTS.md` first, then only the minimum relevant local context files.

### Local Context and Memory
- Load only the minimum local context needed.
- Write down anything that must survive the session.

### Safety and Boundaries
- Do not exfiltrate private data.
- Do not run destructive commands without asking.
- Prefer recoverable deletion mechanisms when available.
- Be explicit when a task affects external systems.

### Workflow Rules
- Before designing a solution, research community and Linux/Rust style best practices. Do not invent patterns the ecosystem already solves.
- Never start development directly on `master` or `main`. Create a repo-local `.dev/` worktree and a short-lived branch first.
- Use `git worktree` under repo-local `.dev/` for non-trivial feature, refactor, and debug branches.
- Name temporary worktree branches as `<type>/<short-kebab-scope>` and matching paths as `.dev/<short-kebab-scope>`.
- Prefer short, stable scope names; do not leave scratch or timestamp-style branches behind.
- After cherry-pick, merge, or rebase, remove the worktree and delete the temporary branch when it is no longer needed.
- Before merging a branch into `master`, do an autosquash pass: fold fixup/noise commits, remove obsolete comments, and keep only comments that preserve durable rationale or constraints.
- Keep commits small, reviewable, and single-scope.
- When a refactor is intentionally partial, state the exact scope and deferred areas explicitly. Do not describe a main-path cleanup as a repo-wide rollout.
- Do not revert unrelated user changes in a dirty worktree.
- Commit messages must use `<type>(<scope>): <summary>` with `-` bullets in the body.

### Documentation Layout
- Keep one canonical file per topic. Put docs under a flat `docs/` and keep stable entry points at the repo root.
- Keep `README.md` as a link hub, not a full manual.
- Documentation language policy is repo-specific. If `PROJECT_CONSTRAINTS.md` defines a canonical language or mirror policy, follow it.
- Do not create mirrored language files unless the repository policy requires them.

### Language Policy
- Use English only for all project artifacts. Chinese text is prohibited everywhere, including but not limited to code comments, documentation, UI copy, logs, errors, commit messages, branch names, pull request titles, pull request descriptions, pull request comments, issue titles, issue descriptions, issue comments, review comments, changelogs, and release notes.
- Do not add bilingual text as a workaround. Translate existing Chinese into English when touching nearby text.
- Preserve Chinese only when it is required as external source data, a literal user-provided value, or a compatibility fixture; isolate it from project-authored prose and explain the reason in English.

### Response Style
- Reply in English unless the user clearly asks for another language.
- Keep responses compact, tight, and well-knit.
- Prefer fewer sections and fewer blank lines.
- Avoid scroll-heavy routine updates and overly sparse formatting.

### Repo Projection Rules
- This file is the global source of truth for agent and engineering rules.
