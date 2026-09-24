# Committee-seats benchmark: reading board committee membership out of DEF 14A proxy statements

A small, fully specified test: given a US proxy statement (SEC form DEF 14A) as filed, name every board committee each director nominee sits on, and who chairs it. 27 filings from the 2026 proxy season, 426 in-scope seats, hand-verified ground truth, and a scorer.

It exists because the same fact — "this director sits on the Audit Committee" — is stated by these filings in at least five ways a machine cannot read the same way: a tick image with no alt text, a Unicode bullet, a letter code, the word `Member`, or a JPEG of the whole table. See the accompanying article for the survey.

## What is in the folder

| Path | What it is |
|---|---|
| `ground_truth/committee_seats.json` | The 27 fixtures: the filing (CIK, accession, URL, filing date), the slate of directors standing for election, every committee seat the filing states (director, committee, role), plus out-of-scope seats (directors the filing says are leaving; seats stated only in a picture) and roles stated as taking effect after the meeting. |
| `filings/manifest.json` | The 27 filings' identifiers and sec.gov URLs. |
| `filings/fetch.py` | Downloads the 27 primary HTML documents from sec.gov into `filings/` (set `SEC_USER_AGENT` first — the SEC's fair-access policy). The HTML is not redistributed here; it is a few minutes to fetch. |
| `converter.py` | The authors' HTML-to-text converter, ported to Python: plain text with the document's block structure, and every committee-table mark rewritten in its cell as `[mark <glyph or image stem> \| row <director> \| column <committee>]`. `python3 converter.py filing.htm > filing.txt`. On all 27 filings it emits the same 1,040 mark and image lines as the production converter, line for line. Needs `beautifulsoup4` and, for browser-grade parsing, `html5lib` (`pip install -r requirements.txt`). |
| `score.py` | The scorer. `python3 score.py predictions.json` prints the per-filing and pooled table below. No dependencies beyond Python 3.9+. |
| `examples/reference_predictions.json` | One system's output on the panel (the authors' extraction, September 2026), in the prediction format. |
| `examples/reference_output.txt` | What `score.py` prints for it. |

## The task

For each filing, produce the directors named in it with, per director, the committees the filing places them on and their role on each (member or chair). Read the filing as filed — the HTML the SEC serves, images and all. How you read it is the experiment: text conversion, a vision model over rendered pages, a hybrid.

The reference pipeline is: `filings/fetch.py` → `converter.py` on each filing → your model over the text (the authors use one research pass and one structuring pass, full text inline) → a predictions file → `score.py`. Swap any stage. To measure what the marks are worth, run your model on `converter.py --no-marks` output too: on this panel the authors' model still found 424 of 426 seats from the plain text, because most filings restate the roster in prose and the model knows well-known boards — and the two it lost were a newly appointed director's seats, stated only in the grid.

## The prediction format

```json
{
  "amazon": {
    "directors": [
      {
        "name": "Wendell P. Weeks",
        "committeeMembership": "member",
        "committees": [{ "name": "Audit Committee", "role": "Member" }]
      }
    ]
  }
}
```

- The top-level key is the fixture `key` from the ground truth (`amazon`, `johnson_johnson`, …).
- `committees[].name` is the committee as the filing names it; `role` is the role text (`Member`, `Chair`, `Chairman`, `Co-Chair`, `Member; designated Chair effective …` — the scorer reads the role stated first).
- `committeeMembership` is a tristate: `"member"` when the director sits on at least one committee, `"none"` when the filing places them on no committee, `""` when your system could not tell. An empty `committees` list is not read as "none"; only the stated `"none"` is. This distinction is the benchmark's second question: does the reader know the difference between *no committee* and *I could not find one*?

## Scoring

`score.py` matches your seats to the ground truth by name and reports, per filing and pooled:

- **seats** — in-scope ground-truth seats found (director matched and committee matched). In scope = the director is on the slate. Seats of directors the filing says are leaving, and seats stated only in a picture, are reported beside the score, never counted against it.
- **roles** — of the seats found, the role equals the ground truth (chair vs member).
- **chairs** — in-scope chairs found with role chair.
- **extras** — predicted seats of slate directors that match no ground-truth seat (an invented seat is the costly error for anyone applying a rule to it).
- **ahead** — a role the filing states as taking effect at or after the meeting, reported as current; reported, not asserted.
- **status** — the `committeeMembership` your system gave to slate directors the filing places on no committee: `none` is right, `""` is honest, `member` is a contradiction.

Matching is deliberately loose on spelling and strict on identity. A director matches by surname and given name or initial, but two directors of one surname, or a father and son of one name, match only on the full given name and the generational suffix. A committee matches by its words, by a filing's own abbreviation (`RCS` for the Regulatory Compliance & Sustainability Committee) or by a prefix (`Nomin. Comm`), never by a bare substring; and where a filing has two committees one of whose names contains the other's (`Executive Committee`, `Executive Compensation Committee`), only an exact match counts. A Wilson 95% interval is printed under each pooled rate; on one filing the counts are small, so read the rows, not the totals.

Reference output on the authors' system (`examples/reference_output.txt`):

```
POOLED                                    100% 426/426   100% 426/426   100% 100/100     0   0/28    0/3     0
Wilson 95%                                99–100            99–100            96–100
```

## How the ground truth was made

Two kinds of fixture, named by the `truth` field:

- **`text-cited`** (14 filings — the prose rosters, and one picture-only filing): every seat was read off the filing's text and carries the 1-based line number of `converter.py`'s output for that filing and a verbatim quote from that line, checked mechanically. The line numbers hold for `converter.py` (its output is line-identical to the authors' converter on every filing); the quotes are the filing's words and can be searched for in any conversion.
- **`verified-reading`** (13 filings whose roster is a membership matrix): the seats were read from the table's HTML by a dedicated model pass and verified against seats and chairs counted by hand per committee, with spot checks by hand. They carry no line or quote.

The `shape` field describes where and how each filing states its roster; `notes` record slate exclusions and the verification. Corrections are welcome — a ground truth of 454 seats will have a wrong one somewhere; three were found and fixed while building it.

## What the panel covers, and does not

27 filings, 15 large issuers and 12 smaller ones, one filing each, chosen for how the roster is stated: 13 membership matrices (tick images, chair glyphs, letter codes, words), 13 prose rosters (biography cards, per-committee lists, report signature blocks, ownership-table footnotes), 1 picture-only filing. It is a panel of layouts, not a sample of the market; rates on it say how a reader copes with each shape, not how often each shape occurs.

## Licence and citation

Code (`converter.py`, `score.py`, `filings/fetch.py`) is released under the MIT License (`LICENSE`). The ground truth, the manifest and the reference predictions are released under CC BY 4.0 (`LICENSE-DATA`). Both are provided as is, without warranty of any kind: this is a test set for reading software, not investment, legal or governance advice. The filings are public records of the U.S. Securities and Exchange Commission and are not redistributed; company and director names appear only as the filings state them.

If you use the panel, cite it as: *Committee-seats benchmark: board committee membership in DEF 14A filings, 2026 proxy season* (Proxywise AI, 2026), with the repository URL.

© 2026 Proxywise AI.
