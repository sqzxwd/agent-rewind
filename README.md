<div align="center">

# ⏪ agent-rewind

### Git-less Time Machine & Workspace Sandbox for AI Agents

[![Python 3.14+](https://img.shields.io/badge/python-3.14+-3776AB.svg?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg?style=flat-square)](LICENSE)
[![Storage: Content-Addressable](https://img.shields.io/badge/storage-SHA--256%20Deduplication-success.svg?style=flat-square)](src/storage/engine.py)
[![Rollback: Instant](https://img.shields.io/badge/rollback-Instant%201--Click-orange.svg?style=flat-square)](src/cli.py)
[![Code Style: Modern](https://img.shields.io/badge/built%20with-Typer%20%7C%20Rich%20%7C%20Watchfiles-8A2BE2.svg?style=flat-square)](pyproject.toml)

<p align="center">
  <b>Never let an autonomous AI agent ruin your codebase again.</b><br>
  Instant, zero-friction shadow snapshots, colored terminal diffs, and 1-click workspace rollbacks.
</p>

---

</div>

## 💥 The Problem

Autonomous AI coding agents (**Google Antigravity**, **Claude Code**, **Cursor**, **Aider**) are remarkably capable, but they are prone to architectural drift:

- 🌪️ **Chaotic multi-file edits:** Agents touch dozens of files simultaneously, leaving half-finished refactors across the tree.
- 🕳️ **Uncommitted state traps:** When an agent goes off the rails, `git stash` and `Ctrl+Z` are useless if the prior work wasn't already staged or committed.
- 🗑️ **Orphaned artifacts:** Agents frequently leave behind test scripts, temporary logs, and unexpected files that pollute the project workspace.
- 🐌 **Git friction:** Creating temporary git branches or WIP commits for every single agent step clutters git history and slows down iterations.

---

## 🛡️ The Solution: `agent-rewind`

`agent-rewind` is an open-source, git-less time machine and sandbox built specifically for AI-assisted workflows:

- ⚡ **Zero Git Overhead:** Operates entirely within a lightweight local hidden store (`.rewind/`), preserving your real Git commit history.
- 📦 **SHA-256 Content-Addressable Deduplication:** Identical files and untouched files across snapshots share the same immutable content objects. Massive space savings.
- 🧼 **Clean Sandbox Rollback:** Rolling back doesn't just revert modified files — it detects and purges all phantom files and directories spawned by the agent.
- 👁️ **Autonomous Watcher Daemon:** Uses `watchfiles` with intelligent debouncing (1–2s) to automatically capture checkpoints whenever the agent pauses its editing flurry.
- 🎨 **Visual Rich Terminal Experience:** Inspect changes with high-visibility colorized line-by-line diffs and formatted snapshot tables.

---

## 🚀 Quickstart

### Installation

Requires **Python 3.14+**. Install directly from the repository in editable mode:

```bash
# Clone the repository
git clone https://github.com/your-username/agent-rewind.git
cd agent-rewind

# Install in editable mode
pip install -e .
```

Or install dependencies into your environment:

```bash
pip install typer rich watchfiles pytest
```

---

## 💻 CLI Commands

```text
 Usage: agent-rewind [OPTIONS] COMMAND [ARGS]...

 Git-less time-machine and sandbox for AI agents.

 Commands:
   snap      Create a manual checkpoint snapshot.
   list      List all recorded snapshots.
   rollback  Safely roll back codebase to a snapshot.
   diff      Colorized line-by-line diff against snapshot.
   watch     Run background daemon monitoring agent edits.
```

### 1. `agent-rewind snap [msg]`
Create a manual checkpoint snapshot before handing off tasks to an agent.

```bash
agent-rewind snap "Before refactoring authentication module"
```

Output:
```text
✓ Snapshot created: a4f81c9d (18 files, 142.4 KB)
  Message: Before refactoring authentication module
```

---

### 2. `agent-rewind list`
View a beautifully formatted chronological history of all recorded checkpoints with timestamps, affected files count, and footprint.

```bash
agent-rewind list
```

```text
                       📦 agent-rewind snapshot history                        
╭──────────┬─────────────────────┬──────────────────────────┬───────┬──────────┬──────────╮
│ ID       │ Timestamp           │ Message                  │ Files │ Affected │ Size     │
├──────────┼─────────────────────┼──────────────────────────┼───────┼──────────┼──────────┤
│ a4f81c9d │ 2026-11-11 19:40:12 │ Baseline before agent    │    18 │       18 │ 142.4 KB │
│ c7b203fe │ 2026-11-11 19:42:55 │ agent step: mod 3 files  │    20 │        3 │ 145.1 KB │
╰──────────┴─────────────────────┴──────────────────────────┴───────┴──────────┴──────────╯
```

---

### 3. `agent-rewind diff <id>`
Inspect exactly what the AI agent changed compared to any checkpoint with colored line-by-line unified diffs.

```bash
agent-rewind diff a4f81c9d
```

```text
Showing changes between workspace and snapshot a4f81c9d:

src/auth/jwt.py ──────────────────────────────────────────────────────────────
--- snapshot:a4f81c9d/src/auth/jwt.py
+++ workspace/src/auth/jwt.py
@@ -14,2 +14,3 @@
 def verify_token(token: str) -> bool:
-    return decode(token, SECRET)
+    if not token:
+        raise ValueError("Missing token")
+    return decode(token, SECRET)

agent_junk.tmp ────────────────────────────────────────────────────────────────
--- /dev/null
+++ workspace/agent_junk.tmp
@@ -0,0 +1 @@
+temporary agent scratchpad
```

---

### 4. `agent-rewind rollback <id>`
Safely restore the workspace to a pristine checkpoint in one click. All corrupted files are reverted, and all agent-created clutter is automatically deleted.

```bash
agent-rewind rollback a4f81c9d
```

Prompt:
```text
⚠️  Roll back to snapshot 'a4f81c9d' (Baseline before agent)? Modified files will be overwritten and untracked files deleted. [y/N]: y
✓ Successfully restored workspace to snapshot a4f81c9d!
```

> **Pro-Tip:** Pass `--yes` (or `-y`) to skip the confirmation prompt inside automated scripts or agent hooks:
> ```bash
> agent-rewind rollback a4f81c9d --yes
> ```

---

### 5. `agent-rewind watch`
Start the background daemon. It monitors your workspace asynchronously and creates automatic snapshots during 1–2 second editing pauses, tracking every agent iteration without requiring manual action.

```bash
agent-rewind watch --debounce 1.5
```

```text
╭─────────────────────────────────────────────────────────────────────────────╮
│ 👁 agent-rewind daemon active                                                │
│ Watching workspace: /Users/developer/my-project                              │
│ Debounce: 1.5s | Press Ctrl+C to stop                                       │
╰─────────────────────────────────────────────────────────────────────────────╯
📸 Snapshot captured: b1904a8e (agent step: modified 3 files)
📸 Snapshot captured: e43a1219 (agent step: modified 1 files)
```

---

## 🏗️ How It Works Under The Hood

```
.rewind/
├── objects/
│   ├── 4f53cda18c2baa0c0354...   # Deduplicated raw file content (SHA-256)
│   └── 9a1120fef73199b0c20a...   # Shared across identical versions
└── snapshots/
    ├── a4f81c9d.json              # File manifest, permissions, and metadata
    └── c7b203fe.json              # Parent snapshot links & changed file counts
```

1. **Intelligent In-Place Filtering:** Automatically prunes `.git`, `.venv`, `__pycache__`, `node_modules`, `.pytest_cache`, and OS files during traversals so scanning stays lightning-fast even on massive projects.
2. **SHA-256 Storage Engine:** If 5 files share identical content, only **1 file** is stored in `.rewind/objects/`. If 10 snapshots have the same unchanged dependencies, they reuse the exact same blocks.
3. **Atomic File Writes:** Snapshot metadata and objects are written via atomic temporary files, preventing corrupted states during sudden terminations.

---

## 🧪 Running Tests

A comprehensive suite with 100% passing tests covers snapshot creation, deduplication, diff verification, rollback hygiene, directory pruning, and async daemon debouncing:

```bash
pytest -v
```

```text
tests/test_rewind.py::test_create_snapshot PASSED                        [ 12%]
tests/test_rewind.py::test_deduplication PASSED                          [ 25%]
tests/test_rewind.py::test_rollback_modified_and_deleted_files PASSED    [ 37%]
tests/test_rewind.py::test_compute_diff PASSED                           [ 50%]
tests/test_rewind.py::test_list_snapshots_and_history PASSED             [ 62%]
tests/test_rewind.py::test_auto_ignore_rules PASSED                      [ 75%]
tests/test_rewind.py::test_watcher_daemon PASSED                         [ 87%]
tests/test_rewind.py::test_cli_interface PASSED                          [100%]

============================== 8 passed in 0.31s ===============================
```

---

## 📄 License

Distributed under the [MIT License](LICENSE).
