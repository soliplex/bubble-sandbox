---
name: bwrap-sandbox
description: Write and execute Python code in a bubblewrap sandbox. Inputs live in read-only volumes under /sandbox/volumes; scratch work goes in /sandbox/work.
---

# Sandbox

This skill runs Python in a bubblewrap sandbox. Use it to compute results from files.

## When to use the sandbox

Use the sandbox if **any** of these is true:

- The task references a file under `/sandbox/volumes/thread/` or `/sandbox/volumes/room/`.
- The task asks for a number, count, table, or other value derived from data.
- You were about to state a computed result without actually computing it.

Do NOT use the sandbox if **any** of these is true:

- The question is about definitions, explanations, or concepts.
- The answer is already stated in the conversation.
- The task is to write code for the user to run, not to execute code yourself.
- The task is vague ("analyze the files", "take a look") with no concrete question. Ask the user what they want to know before running anything.

## File layout

- `/sandbox/work/` — read/write scratch space inside the sandbox. Intermediate artifacts written by a script go here.
- `/sandbox/volumes/thread/` — read-only; files the user uploaded to this thread. Usually the task inputs.
- `/sandbox/volumes/room/` — read-only; files shared across the room. Often contain rules, formulas, or reference data required for a correct answer.

## Workflow

**Scripts at a glance** (invoke via the `run_script` tool):

- `scripts/list_environments.sh` — no arguments; prints JSON of configured environments.
- `scripts/list_volume.sh <thread|room>` — prints absolute file paths in that volume.
- `scripts/run.sh <env> -- <cmd> [args...]` — run an arbitrary shell command in the sandbox. The `<env>` positional and the literal `--` separator are required; passing just a file path will fail with a usage error.
- `scripts/run_python.sh <env> --code "<python source>"` — run Python source, passed as one argv string.

`thread` and `room` are mounted automatically for every script.

Every `run_script` tool call must include **both** fields: `script` (the path, e.g. `scripts/run_python.sh`) and `arguments` (the argv string). Omitting `script` fails validation — putting the script path into `arguments` instead will not work.

1. **Pick an environment.** Run `scripts/list_environments.sh`. It prints JSON shaped like:

   ```json
   {"environments": [{"name": "bare", "description": "Minimal Python", "dependencies": ["pandas"]}]}
   ```

   Apply these rules in order:
   - If `environments` is `[]`, stop and tell the user the skill is not configured — do not proceed.
   - If exactly one environment is listed, use its `name`.
   - Otherwise, pick the first environment whose `dependencies` include a library the task needs (e.g. `pandas` for tabular data, `numpy` for numeric work, `pillow` for images). If none match, use the `name` of the first entry in the list.

2. **List files in BOTH volumes.** This step is mandatory — do not skip it, even if the task seems to only involve one volume. Run both:

   ```
   scripts/list_volume.sh thread
   scripts/list_volume.sh room
   ```

   Each script prints one absolute path per line (from `find`), or nothing if the volume is empty:

   ```
   /sandbox/volumes/thread/orders.csv
   /sandbox/volumes/thread/notes.txt
   ```

   If both commands print no files, proceed without inputs.

3. **Read only the files you need.** Do not dump every file — pick the ones the task actually requires. If `room` has any files, read them too: they often contain rules or reference data the task depends on.

   To peek at a file's shape before writing analysis code, use `scripts/run.sh <env> -- head -n 5 <path>` (or `wc -l`, `file`, etc.). For anything beyond a quick peek — parsing, filtering, joining — read it inside a `scripts/run_python.sh --code` call in step 4 rather than running `cat` on the whole file.

4. **Run a Python script in the sandbox.** Pass the source as a single argument after `--code`:

   ```
   scripts/run_python.sh <env> --code "<python source>"
   ```

   The source is one argv string — do **not** use shell heredocs (`<<'PY' … PY`) or redirection; the skill runner does not invoke a shell, so those tokens would be passed through as literal arguments and the call would fail. Write the whole program as a single quoted string, and use real newlines (embedded `\n` or a multi-line string) to separate statements. `;` only works for simple statements — compound statements like `def`, `class`, `with`, `for`, `if`, `try` must start on their own line.

   Start from this skeleton and replace the `TODO`:

   ```python
   from pathlib import Path

   # Inputs (read-only): /sandbox/volumes/thread/, /sandbox/volumes/room/
   # Scratch (read-write): /sandbox/work/

   # TODO: read inputs, apply any rules from room files, compute `result`.

   print(result)
   ```

   If the script is already saved on the host (e.g. `task.py`), pass its path as the second argument instead: `scripts/run_python.sh <env> task.py`. Output is your script's raw stdout; on failure, a line `Exited with code: <N>` is prepended before the traceback, and `<truncated>` is appended if the output was cut off.

5. **On failure.**
   - Change exactly one thing per retry.
   - After 3 failed runs, stop. Report the error to the user (paste the `Exited with code: <N>` line and the traceback) instead of retrying further.

## Output

- Print the answer to stdout. Only stdout is shown to the user.
- If the answer is more than ~20 rows or lines, print a short summary (head, counts, totals) and write the full detail to a file under `/sandbox/work/`.
- Do not print narration lines like "Loading data…" or "Processing…". Just run the script.
- After the script succeeds, report the result to the user in one or two sentences.

## Example

Task: user uploads `orders.csv` and asks "what's the total order value?". A full run looks like:

1. `scripts/list_environments.sh` — shows one environment named `default` with `pandas` in its dependencies. Use it.
2. `scripts/list_volume.sh thread` — lists `/sandbox/volumes/thread/orders.csv`. `scripts/list_volume.sh room` — prints no files. Continue with just the thread input.
3. Run:

   ```
   scripts/run_python.sh default --code "import pandas as pd; df = pd.read_csv('/sandbox/volumes/thread/orders.csv'); print(f\"Total: {df['amount'].sum():.2f}\")"
   ```

   — prints `Total: 48215.00`.
4. Report to the user: "Total order value: $48,215.00."
