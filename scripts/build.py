"""Validate papers.yaml and regenerate README.md and site/data.js from it.

    uv run scripts/build.py          # rewrite the generated files
    uv run scripts/build.py --check  # fail if they are out of date (used in CI)
"""

import argparse
import json
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
REPO = "dipta007/awesome-multimodal-reward"
START, END = "<!-- papers:start -->", "<!-- papers:end -->"
REQUIRED = ["key", "title", "year", "section", "subsection", "links"]
SHOWN_TAGS = ["modality", "roles"]
ROLE_LABEL = {"train": "training", "select": "selection", "data": "data curation", "agent": "agent verification"}
SECTION_NOTES = {
    "foundations": "How reward models and preference optimization work, in text and for non-text outputs.",
    "signal": "What a reward model or judge returns, and how the score is computed.",
    "supervision": "Where the training target comes from.",
    "granularity": "Which part of the output is scored: the whole response, a step, a token or region, or a criterion.",
    "roles": "How the verdict is used: policy training, candidate selection, data curation, or agent verification.",
    "understanding": "Judging text answers against images, video, or audio.",
    "generation": "Scoring generated images, edits, video, audio, 3D assets, and interleaved outputs.",
    "transfer": "Rewards that span understanding and generation, and what transfers between settings.",
    "benchmarks": "How rewards and judges are evaluated, and whether that evaluation predicts downstream use.",
    "failures": "Where judges fail: perception, preference, optimization, and security.",
    "surveys": "Surveys of neighboring topics, compared in Table 3 of the paper.",
}


def load() -> tuple[list[dict], dict]:
    papers = yaml.safe_load((ROOT / "papers.yaml").read_text())
    survey = yaml.safe_load((ROOT / "survey.yaml").read_text())
    return papers, survey


def validate(papers: list[dict], survey: dict) -> list[str]:
    errors, seen = [], set()
    subs = {s["id"]: {x["id"] for x in s["subsections"]} for s in survey["sections"]}
    for i, p in enumerate(papers):
        where = p.get("key") or f"entry {i + 1}"
        for field in REQUIRED:
            if not p.get(field):
                errors.append(f"{where}: missing '{field}'")
        if p.get("key") in seen:
            errors.append(f"{where}: duplicate key")
        seen.add(p.get("key"))
        if p.get("section") not in subs:
            errors.append(f"{where}: unknown section '{p.get('section')}'")
        elif p.get("subsection") not in subs[p["section"]]:
            errors.append(f"{where}: unknown subsection '{p.get('subsection')}' in '{p['section']}'")
        if not isinstance(p.get("year"), int):
            errors.append(f"{where}: year must be a number")
    return errors


def link_of(p: dict) -> str:
    links = p.get("links") or {}
    return links.get("paper") or links.get("arxiv") or (f"https://doi.org/{links['doi']}" if links.get("doi") else "")


def paper_line(p: dict) -> str:
    title = p["title"].rstrip(".")
    name = p.get("name")
    lead = f"**{name}**: " if name and not title.lower().startswith(name.lower()) else ""
    venue = f"{p.get('venue') or ''} {p['year']}".strip()
    extra = f" [[arXiv]({p['links']['arxiv']})]" if p.get("links", {}).get("arxiv") and p["links"]["arxiv"] != link_of(p) else ""
    tags = []
    for kind in SHOWN_TAGS:
        for v in (p.get("tags") or {}).get(kind, []):
            tags.append(ROLE_LABEL.get(v, v) if kind == "roles" else v)
    tag_text = " " + " ".join(f"`{t}`" for t in dict.fromkeys(tags)) if tags else ""
    return f"- {lead}[{title}]({link_of(p)}) ({venue}){extra}{tag_text}"


def anchor(text: str) -> str:
    return re.sub(r"[^a-z0-9 -]", "", text.lower()).replace(" ", "-")


def render_readme(papers: list[dict], survey: dict) -> str:
    by_key = {p["key"]: p for p in papers}
    out = []
    counts = {s["id"]: sum(1 for p in papers if p["section"] == s["id"]) for s in survey["sections"]}
    out.append("## Contents\n")
    for s in survey["sections"]:
        if counts[s["id"]]:
            out.append(f"- [{s['title']}](#{anchor(s['title'])}) ({counts[s['id']]})")
    out.append("")
    for s in survey["sections"]:
        if not counts[s["id"]]:
            continue
        out.append(f"## {s['title']}\n")
        out.append(f"{SECTION_NOTES.get(s['id'], '')} Survey: {s['where']}.\n")
        if s["id"] == "benchmarks":
            out.append(benchmark_table(survey, by_key))
        if s["id"] == "failures":
            out.append(failure_table(survey, by_key))
        for sub in s["subsections"]:
            items = [p for p in papers if p["section"] == s["id"] and p["subsection"] == sub["id"]]
            if not items:
                continue
            if len(s["subsections"]) > 1:
                out.append(f"### {sub['title']}\n")
            out += [paper_line(p) for p in sorted(items, key=lambda p: (-p["year"], p["title"].lower()))]
            out.append("")
    return "\n".join(out).rstrip() + "\n"


def cite(by_key: dict, key: str) -> str:
    p = by_key.get(key)
    if not p:
        return key
    first = (p.get("authors") or ["?"])[0].split()[-1]
    return f"[{first} et al., {p['year']}]({link_of(p)})"


def benchmark_table(survey: dict, by_key: dict) -> str:
    rows = ["| Benchmark | Input to output | Format | Labels | Scale | Metric |", "|---|---|---|---|---|---|"]
    for b in survey["benchmarks"]:
        p = by_key.get(b["key"], {})
        rows.append(f"| [{b['name']}]({link_of(p)}) | {b['input_output']} | {b['format']} | {b['labels']} | {b['scale']} | {b['metric']} |")
    return "**Benchmarks at a glance** (Table 6 of the survey)\n\n" + "\n".join(rows) + "\n"


def failure_table(survey: dict, by_key: dict) -> str:
    mark = {"fail": "fails", "either": "either", None: ""}
    rows = ["| Group | Failure | Perception | Preference | Recommended practice | Example study |", "|---|---|---|---|---|---|"]
    for f in survey["failures"]:
        rows.append(f"| {f['group']} | {f['name']} | {mark[f['perception']]} | {mark[f['preference']]} | {f['practice']} | {cite(by_key, f['example'])} |")
    note = ("**Failure catalog** (Table 2 of the survey). \"fails\" marks the question that fails: perception (did the judge "
            "obtain the relevant evidence?) or preference (did it apply the intended criterion?). \"either\" marks settings "
            "that can amplify or exploit either error.\n\n")
    return note + "\n".join(rows) + "\n"


def render_data(papers: list[dict], survey: dict) -> str:
    payload = {"repo": REPO, "survey": survey, "papers": papers}
    return "window.SURVEY_DATA = " + json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + ";\n"


def splice(readme: str, body: str, count: int) -> str:
    if START not in readme or END not in readme:
        raise SystemExit(f"README.md needs the markers {START} and {END}")
    head, rest = readme.split(START, 1)
    _, tail = rest.split(END, 1)
    head = re.sub(r"\d+ papers", f"{count} papers", head, count=1)
    return f"{head}{START}\n{body}{END}{tail}"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    papers, survey = load()
    errors = validate(papers, survey)
    if errors:
        print("papers.yaml has problems:\n  " + "\n  ".join(errors))
        sys.exit(1)
    readme_path, data_path = ROOT / "README.md", ROOT / "site" / "data.js"
    readme = splice(readme_path.read_text(), render_readme(papers, survey), len(papers))
    data = render_data(papers, survey)
    if args.check:
        stale = [str(p.relative_to(ROOT)) for p, new in [(readme_path, readme), (data_path, data)]
                 if not p.exists() or p.read_text() != new]
        if stale:
            print("Out of date: " + ", ".join(stale) + ". Run: uv run scripts/build.py")
            sys.exit(1)
        print(f"ok: {len(papers)} papers")
        return
    readme_path.write_text(readme)
    data_path.write_text(data)
    print(f"wrote README.md and site/data.js ({len(papers)} papers)")


if __name__ == "__main__":
    main()
