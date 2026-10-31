Local backend: retrieve before generating, plus a grounding guard

- Retrieve first: the specimen list and the top documentation passages for the question are
  given to the model with the question (retrieve-then-generate, Lewis2020), so it no longer has
  to decide to call search_docs. In the baseline it skipped the search on the CT-viewer question
  and answered from memory.
- Grounding guard: if the answer contains numbers that no source backs, it is sent back once with
  those numbers. If they remain, the answer says they could not be verified.

Same 25 cases, same model (qwen3.5:4b), same judge. Commit 3de20fa.

Result: better on answerable questions (15/15 vs 14/15) and grounding (25/25 vs 24/25), but
worse on refusals (2/5 vs 4/5). The retrieved passages explain that cochlear dimension A is used
to estimate duct length and electrode length; in refusal cases the model declined and then
repeated that guidance (partial refusal). Median latency 133 s vs 93 s: fewer rounds (1 vs 2)
but a longer first prompt. The run was interrupted once by low memory; errors-interrupted.jsonl
lists the two attempts that failed then (not scored), both re-run.
