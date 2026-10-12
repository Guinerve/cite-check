# cite-check

> Verify that an AI-written report's citations actually say what it claims.

**Status:** v0.1 pipeline built; evaluated on a SYNTHETIC seed set only · Portfolio project #5 · see `../README.md`

## The idea

Paste in a report with citations. For each claim the tool fetches the source, finds the closest passage and judges whether it supports the claim. Output is a red/amber/green annotated report.

## Stack

Python (uv), httpx, pypdf, rapidfuzz, a local embedding model, Ollama (or a small entailment model), pytest.

Python project managed with `uv`; target a one-command run (`uv run ...`).

## Build plan (v1)

- [x] Parse claims and their citations from Markdown/HTML
- [x] Fetch URL or PDF sources, cache them, split into chunks
- [ ] (partly done: word overlap + rapidfuzz only, **no embedding search yet**; no local embedding model is installed) Find the best supporting passage (fuzzy match + embedding search)
- [x] Verdict: supported / partial / unsupported / source unreachable, with the passage shown
- [x] Annotated HTML report output

## Run it

```bash
uv sync
uv run cite-check report.md                    # offline heuristic judge, writes report.check.html
uv run cite-check report.md --llm qwen3:4b       # local Ollama judge
uv run python -m cite_check.evaluate eval/seed_dataset.json
uv run pytest -q    # 16 tests
```

## How I know it's right

**Honest status: the ~40-claim hand-labelled set from the plan does not exist yet.** What exists is a 24-claim *synthetic* seed set (`eval/seed_dataset.json`): four invented documents, with 8 supported, 8 partial (wrong number or overreach) and 8 fabricated claims. It checks that the pipeline works; it says little about real-world accuracy. The heuristic thresholds were adjusted after seeing it, so its numbers are in-sample.

| Judge | Accuracy | supported P / R | partial P / R | unsupported P / R |
|---|---:|---:|---:|---:|
| heuristic (offline) | 87.5 % | 100 % / 88 % | 78 % / 88 % | 88 % / 88 % |
| `qwen3:4b` via Ollama | 83.3 % | 89 % / 100 % | 100 % / 50 % | 73 % / 100 % |

(`eval/seed_results.txt`, `eval/seed_results_qwen3-4b.txt`.)

Where they fail: the heuristic cannot handle paraphrase ("carved out by glaciers" vs "formed by glacial action") and gives fabricated claims partial credit when they share topic words. The LLM catches every fabricated claim and every supported one, but calls wrong numbers `unsupported` ("contradicted") where my labels say `partial`, and once accepted "about 98,000" as supporting "about 150,000". Whether a contradicted number is partial or unsupported is a labelling decision to settle before building the real set.

Parser, fetcher (mocked HTTP), end-to-end verdicts, multi-source claims and the HTML report are covered by 16 unit tests.

## Limits

The pipeline has been run only against mock sources; **it has not been run on a real AI-written report with live URLs**. Sentence-level claim extraction is simple. Exit codes: 0 all supported/partial, 1 something unsupported, 2 no cited claims found, 3 some claims could not be checked (unreachable source or a `[n]` with no reference entry). Unreachable sources are never a silent pass.

Judges support, not truth: a claim can be faithfully cited from a wrong source. Paywalled sources can't be checked.

## Next (tomorrow)

- Take 2–3 real AI-generated reports, hand-label ~40 claims (including fabricated ones) → real precision/recall.
- Decide partial-vs-unsupported for wrong numbers.
- Add embedding retrieval (pull an embedding model into Ollama).
- Run end-to-end on live URLs and look at the HTML report.

## Stretch

Browser extension; link with `claim-ledger`.

## Definition of done

- [ ] Hero GIF or screenshot at the top of this README
- [x] Live demo link or one-command run (`uv run cite-check report.md`; needs a real report, since `examples/sample_report.md` points at a mock URL)
- [ ] "How I know it's right" section filled in with real results
- [ ] Tests passing in CI, badge added
- [ ] "Limits" section written
- [ ] Licence chosen, repo description and topics set
- [ ] Pinned on GitHub profile and added to guinerve.github.io
- [ ] Added to `career-radar/data/cv/portfolio.json`
