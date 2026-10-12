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
uv run pytest -q    # 17 tests
```

## End-to-end check

Run on 2026-10-13 against live Wikipedia URLs with `--llm qwen3:4b` (`examples/sample_report.md`, 6 claims: 3 true, 2 fabricated, 1 dead link): supported 3, unsupported 2 (it caught "designed by Albert Einstein, opened 1950" because the source says Dorman Long, 1932), unreachable 1; exit code 3 with a warning. Looking at the HTML report found two bugs, now fixed: the citation anchor text ("Wikipedia") was left inside the claim, and source links were unreadable blue on the dark theme.

## How I know it's right

**Two evaluation sets, and the second changes the story.**

1. `eval/seed_dataset.json`: 24 claims on four *invented* documents. Claims there are near-verbatim, so it flatters the offline heuristic: **87.5 %** accuracy for the heuristic, 83.3 % for `qwen3:4b`. It is useful as a regression test, not as evidence.
2. `eval/real_dataset.json` (built by `scripts/build_real_set.py`): **30 claims against 8 real Wikipedia lead sections** (CC BY-SA 4.0). *Supported* claims are genuine LLM paraphrases (`llama3.2:3b`) of source sentences; *partial* claims are a source sentence with one number changed, or a paraphrase that added a detail the source doesn't contain; *unsupported* claims are sentences from a different article cited against this one. I read every paraphrase: 4 added unsupported detail and were relabelled partial, 1 changed the subject and was dropped. Labels are correct by construction, but these are not natural AI-report claims, and it is still only 30 claims.

| Judge on the real set | Accuracy | supported P / R | partial P / R | unsupported P / R |
|---|---:|---:|---:|---:|
| offline heuristic | **60.0 %** | 100 % / **9 %** | 75 % / 82 % | 47 % / 100 % |
| `qwen3:4b` | 73.3 % | 73 % / 100 % | 100 % / 27 % | 67 % / 100 % |
| `qwen3:4b` + number check | 80.0 % | 91 % / 91 % | 86 % / 55 % | 67 % / 100 % |

(`eval/real_results_*.txt`.)

What this shows:

- **The offline heuristic does not work on paraphrase** (supported recall 9 %): "holds the distinction of being Australia's longest river at approximately 2,508 kilometers" scores as unrelated to "It is Australia's longest river, spanning 2,508 km". Treat it as a no-LLM fallback for near-verbatim claims only. Embedding retrieval is the obvious next step.
- **The LLM judge reads paraphrase well but waves through added detail**: 4 of 11 partial claims (a made-up year, distance and "no reported incidents") were accepted as fully supported. The "number check" row downgrades a *supported* verdict to partial when the claim contains a number absent from every retrieved passage. **I designed that check after seeing these misses, so 80 % is partly in-sample.** It cannot catch an added non-numeric fact ("no reported incidents" still gets through).
- Claims with a **changed number** are mostly called `unsupported` by the LLM (the source states a different figure). Whether that is `partial` or `unsupported` is a labelling decision I still have not settled; it costs the partial recall above.

Parser, fetcher (mocked HTTP), end-to-end verdicts, multi-source claims and the HTML report are covered by 17 unit tests.

## Limits

The pipeline has been run only against mock sources; **it has not been run on a real AI-written report with live URLs**. Sentence-level claim extraction is simple. Exit codes: 0 all supported/partial, 1 something unsupported, 2 no cited claims found, 3 some claims could not be checked (unreachable source or a `[n]` with no reference entry). Unreachable sources are never a silent pass.

Judges support, not truth: a claim can be faithfully cited from a wrong source. Paywalled sources can't be checked.

## Next (tomorrow)

- Hand-label claims from 2–3 *real* AI-generated reports (the current real set is built from Wikipedia sentences, not natural report claims).
- Decide partial-vs-unsupported for wrong numbers.
- Add embedding retrieval (pull an embedding model into Ollama): the lexical heuristic fails on paraphrase.

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
