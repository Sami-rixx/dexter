# Testing & Feedback Guide

This is the **Testing Team's** playbook for reviewing Dexter's answers —
it implements sections 6.3 and 12 of `ARCHITECTURE.md`. The weekly loop
described here **is** the entire QA process for v1: no dashboard, no web UI.

---

## 1. What you review each week

The patron runs (or gives you) a **review export** for a given day: every
student question, the knowledge snippets the bot injected, the model used,
latency and status — with **aliases only** (`Student-NN`), never real names
or raw Telegram IDs.

## 2. How to produce an export

On the machine that runs the bot (the database never leaves it):

```bash
# Yesterday's exchanges (Nairobi day):
python logger/review_export.py --date 2026-09-08

# Choose a different database or output folder:
python logger/review_export.py --date 2026-09-08 --db data/shule.db --out-dir data/exports
```

This writes to `data/exports/`:

| File | Purpose |
|---|---|
| `review_YYYY-MM-DD.md` | Human-readable — annotate this one |
| `review_YYYY-MM-DD.csv` | Same rows for spreadsheets |

The Markdown file includes a short "how to review" cheat-sheet at the top.

## 3. How to annotate

For each exchange in the export, judge the answer and mark one of:

- **Answer wrong, `snippet_ids` empty or `match_scores` low** → the
  retriever never found the right knowledge file. Flag as *retriever gap*
  (include the question wording — it becomes a test case).
- **Answer wrong, good `match_scores`** → the knowledge file's content or
  the persona's tone needs fixing. Flag as *content* or *tone*.
- **`status: quota_exhausted` / `error`** → quota or API trouble. Flag as
  *quota/API* for the patron.
- **Answer good** → no action; the counter of good answers is still useful.

Annotate directly in the Markdown (or the CSV) and send the file to the
patron. The patron turns annotations into GitHub issues or direct fixes;
fact errors in `config/topics/` are fixed by the Research Team via PR, and
`/reload` ships the update without a restart.

## 4. Retention

Exchanges are kept at most **90 days**, then purged
(`python logger/review_export.py --purge-old`). The annotated export is the
permanent record — keep those.

## 5. Automated tests (developers)

The test suites are for code changes; they need no Telegram token and no
Gemini key (external APIs are mocked):

```bash
python -m unittest test_bot_core test_step2 test_step3 test_step4 test_step5
# or simply:
python -m unittest discover -p "test_*.py"
```

Coverage includes rate-limiting concurrency, the privacy boundary
(no raw chat IDs), retrieval relevance against the real knowledge files,
malformed knowledge handling, and end-to-end message flow with a mocked
Gemini. **No live Telegram or Gemini verification is claimed by these
tests** — live classroom pilots are reviewed through the export loop above.

---

*Owned by the Testing Team. Edits via PR to the patron.*
