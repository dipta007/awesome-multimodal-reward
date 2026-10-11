"""Import the paper list from the survey's LaTeX sources.

Run once by the survey authors:
    uv run --group import scripts/import_survey.py --paper-dir ../multimodal-reward

It writes papers.yaml (one entry per cited paper) and survey.yaml (the survey's fixed views:
sections, taxonomy, method matrix, benchmarks, downstream evidence, failure catalog).
Tags come only from where the survey itself places a paper: Figure 2, Tables 1-6, and the
appendix paragraph headings.
"""

import argparse
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

import yaml
from pylatexenc.latex2text import LatexNodes2Text

LATEX = LatexNodes2Text()
S2 = "https://api.semanticscholar.org/graph/v1/paper"
S2_FIELDS = "title,abstract,externalIds,year,venue"
UA = {"User-Agent": "awesome-multimodal-reward builder"}

# Survey sections in reading order. Subsection ids are stable keys used by the README and the explorer.
SECTIONS = [
    ("foundations", "Foundations", "Section 2, Appendix B", [
        ("rlhf", "From human feedback to reward models"), ("metrics", "Scoring non-text outputs")]),
    ("signal", "Signal construction", "Section 2.2, Appendix C", [
        ("scalar", "Scalar scores"), ("critique", "Generated critique"), ("rubric", "Rubrics and checklists"),
        ("implicit", "Likelihood-derived and implicit rewards"), ("programmatic", "Programmatic checks"),
        ("latent", "Latent scores")]),
    ("supervision", "Supervision", "Section 2.3, Appendix D", [
        ("human", "Human comparisons"), ("ai", "AI feedback"), ("perturbation", "Perturbations"),
        ("verifiable", "Verifiable targets"), ("self", "Self-generated signals")]),
    ("granularity", "Granularity", "Section 2.3, Appendix D", [
        ("outcome", "Outcome"), ("process", "Reasoning or action step"), ("token", "Token or region"),
        ("criterion", "Criterion or dimension")]),
    ("roles", "Deployment roles", "Section 3, Appendix E", [
        ("train", "Policy training"), ("select", "Candidate selection"), ("data", "Data curation"),
        ("agent", "Agent verification")]),
    ("understanding", "Understanding tasks", "Section 4.1, Appendix F", [
        ("hallucination", "Hallucination and grounding"), ("reasoning", "Step-level reasoning"),
        ("video", "Video"), ("audio", "Audio, speech, and omni input"), ("domains", "Domains")]),
    ("generation", "Generation tasks", "Section 4.2, Appendix G", [
        ("t2i", "Text-to-image"), ("editing", "Instruction-guided editing"), ("video", "Text-to-video"),
        ("audio", "Audio and music"), ("3d", "3D generation"), ("interleaved", "Interleaved outputs")]),
    ("transfer", "Transfer and unified rewards", "Section 4.3", [
        ("unified", "Unified and omni rewards"), ("transfer", "Transfer across settings")]),
    ("benchmarks", "Benchmarks and evaluation", "Section 5, Appendix H", [
        ("image", "Image understanding"), ("video", "Video understanding"), ("multilingual", "Multilingual"),
        ("generation", "Generation"), ("omni", "Omni-modal"), ("downstream", "Downstream evidence"),
        ("population", "Annotator population and language"), ("other", "Other evaluation work")]),
    ("failures", "Failure diagnosis", "Section 6, Appendix I", [
        ("perception", "Perception"), ("interaction", "Interaction"), ("criterion", "Criterion"),
        ("population", "Population"), ("optimization", "Optimization"), ("security", "Security")]),
    ("surveys", "Related surveys", "Table 3", [("surveys", "Surveys")]),
]
SECTION_ORDER = {sid: i for i, (sid, *_rest) in enumerate(SECTIONS)}

# Appendix paragraph heading -> (section, subsection).
APPENDIX_PARAGRAPHS = {
    "From human feedback to reward models": ("foundations", "rlhf"),
    "Scoring non-text outputs": ("foundations", "metrics"),
    "Formal setup": ("foundations", "rlhf"),
    "Discriminative scalar rewards": ("signal", "scalar"),
    "Generative scoring and critique": ("signal", "critique"),
    "Rubric and checklist rewards": ("signal", "rubric"),
    "Implicit and policy-derived rewards": ("signal", "implicit"),
    "Programmatic checks and learned reconstruction proxies": ("signal", "programmatic"),
    "Latent and native-space rewards": ("signal", "latent"),
    "Human preference": ("supervision", "human"),
    "AI feedback and distillation": ("supervision", "ai"),
    "Perturbation and counterfactual supervision": ("supervision", "perturbation"),
    "Verifiable ground truth": ("supervision", "verifiable"),
    "Self-generated supervision": ("supervision", "self"),
    "Granularity: outcome, process, token, dimension": ("granularity", None),
    "Train-time reward": ("roles", "train"),
    "Inference-time judge": ("roles", "select"),
    "Data-time filter": ("roles", "data"),
    "Agent-time verifier": ("roles", "agent"),
    "Hallucination and grounding": ("understanding", "hallucination"),
    "Step-level reasoning": ("understanding", "reasoning"),
    "Video": ("understanding", "video"),
    "Audio, speech, and omni input": ("understanding", "audio"),
    "Domains": ("understanding", "domains"),
    "Text-to-image": ("generation", "t2i"),
    "Instruction-guided editing": ("generation", "editing"),
    "Text-to-video": ("generation", "video"),
    "Audio and music": ("generation", "audio"),
    "3D generation": ("generation", "3d"),
    "Interleaved outputs": ("generation", "interleaved"),
    "Further benchmarks": ("benchmarks", "other"),
    "Meta-evaluation and the benchmark-to-downstream gap": ("benchmarks", "downstream"),
}
RESEARCH_QUESTIONS = {  # Appendix J question -> the topic it discusses
    "Test perception and evidence use separately": ("failures", "perception"),
    "Report controlled contrasts": ("failures", "interaction"),
    "Connect benchmarks to downstream decisions": ("benchmarks", "downstream"),
    "Measure robustness under optimization": ("failures", "optimization"),
    "Test omni-modal transfer with matched coverage": ("transfer", "transfer"),
    "Give every interleaved component a learning signal": ("generation", "interleaved"),
    "Specify the annotator population": ("failures", "population"),
    "Decide when process feedback is useful": ("granularity", "process"),
    "Measure the full cost of a useful judgment": ("roles", "select"),
    "Evaluate the reward as an attack surface": ("failures", "security"),
}
APPENDIX_INTROS = {  # text before the first paragraph heading of an appendix section
    "05_form.tex": ("signal", None), "06_supervision.tex": ("supervision", None), "07_roles.tex": ("roles", None),
    "08_understanding.tex": ("understanding", None), "09_generation.tex": ("generation", None),
    "10_benchmarks.tex": ("benchmarks", "other"), "11_failures.tex": ("failures", "criterion"),
}
GENERIC_LABELS = {"Decoding", "beam search", "perceptual bias", "Position bias", "agent leniency", "Reward hacking",
                  "score inflation"}
FAILURE_PARAGRAPHS = {  # Appendix I paragraph -> Table 2 row names
    "Blind judging": ["Blind judging"], "Perceptual misreading": ["Perceptual misreading"],
    "Granularity blindness": ["Granularity blindness"],
    "Response anchoring and narrative plausibility": ["Response anchoring", "Narrative plausibility"],
    "Position, verbosity, and self-preference": ["Position, verbosity", "Self-preference"],
    "Agent leniency": ["Agent leniency"], "Cultural miscalibration": ["Cultural miscalibration"],
    "Cross-lingual brittleness": ["Cross-lingual brittleness"], "Population collapse": ["Population collapse"],
    "Reward hacking": ["Reward hacking"], "Reward-model blind spot": ["Reward-model blind spot"],
    "Optimizer-induced hacking": ["Optimizer-induced hacking"], "Rubric hacking": ["Rubric hacking"],
    "Multi-reward collapse": ["Multi-reward collapse"], "Adversarial fragility": ["Adversarial fragility"],
    "Preference poisoning": ["Preference poisoning"],
}
# Main-text file -> section (the survey's own placement, used when nothing more specific exists).
MAIN_FILES = {
    "02_background.tex": "foundations", "05_form.tex": "signal", "06_supervision.tex": "supervision",
    "07_roles.tex": "roles", "08_understanding.tex": "understanding", "10_benchmarks.tex": "benchmarks",
    "11_failures.tex": "failures",
}
# Figure 2 leaf label -> (section, subsection).
FIGURE_LEAVES = {
    "Scalar scores": ("signal", "scalar"), "Generated critique": ("signal", "critique"),
    "Rubric": ("signal", "rubric"), "Likelihood-derived score": ("signal", "implicit"),
    "Programmatic check": ("signal", "programmatic"), "Latent score": ("signal", "latent"),
    "Human comparisons": ("supervision", "human"), "AI feedback": ("supervision", "ai"),
    "Perturbations": ("supervision", "perturbation"), "Verifiable targets": ("supervision", "verifiable"),
    "Self-generated signals": ("supervision", "self"),
    "Outcome": ("granularity", "outcome"), "Reasoning / action step": ("granularity", "process"),
    "Token / region": ("granularity", "token"), "Criterion / dimension": ("granularity", "criterion"),
    "Policy training": ("roles", "train"), "Candidate selection": ("roles", "select"),
    "Data curation": ("roles", "data"), "Agent verification": ("roles", "agent"),
    "Non-text evidence": ("understanding", None), "Non-text output": ("generation", None),
    "Both (unified, omni)": ("transfer", "unified"), "Transfer across settings": ("transfer", "transfer"),
    "Benchmarks": ("benchmarks", None), "Downstream evidence": ("benchmarks", "downstream"),
    "Annotator population, language": ("benchmarks", "population"),
    "Perception": ("failures", "perception"), "Preference": ("failures", "criterion"),
    "Optimization": ("failures", "optimization"), "Security": ("failures", "security"),
}
# Method-table construction value -> signal subsection.
CONSTRUCTION = [("rubric", "rubric"), ("latent", "latent"), ("implicit", "implicit"), ("likelihood", "implicit"),
                ("programmatic", "programmatic"), ("verifier", "programmatic"), ("generative", "critique"),
                ("discriminative", "scalar")]
ROLE_WORDS = {"judge": "select", "train": "train", "data": "data", "agent": "agent"}
GRANULARITY_WORDS = {"outcome": "outcome", "process": "process", "step": "process", "token": "token",
                     "region": "token", "criterion": "criterion", "dimension": "criterion"}
MODALITY_WORDS = ["image", "video", "audio", "speech", "music", "3d", "layout", "text", "omni", "interleaved",
                  "action", "gui", "web", "robot"]
SUPERVISION_WORDS = [("human", "human"), ("expert", "human"), ("ai ", "ai"), ("ai-", "ai"), ("gpt", "ai"),
                     ("distill", "ai"), ("perturb", "perturbation"), ("counterfactual", "perturbation"),
                     ("answer", "verifiable"), ("rule", "verifiable"), ("verif", "verifiable"),
                     ("monte carlo", "verifiable"), ("self", "self"), ("rollout", "self")]
FAILURE_GROUPS = {"Perception": "perception", "Interaction": "interaction", "Criterion": "criterion",
                  "Population": "population", "Optimization": "optimization", "Security": "security"}


def live(path: Path) -> str:
    t = re.sub(r"\\iffalse.*?\\fi\b", "", path.read_text(), flags=re.S)
    return "\n".join(l for l in t.split("\n") if not l.lstrip().startswith("%"))


def plain(s: str) -> str:
    return re.sub(r"\s+", " ", LATEX.latex_to_text(s)).strip()


def cite_keys(text: str) -> list[str]:
    keys = []
    for m in re.finditer(r"\\cite\w*\*?(?:\[[^\]]*\])*\{([^}]*)\}", text):
        keys += [k.strip() for k in m.group(1).split(",") if k.strip()]
    return keys


def braced(text: str, start: int) -> tuple[str, int]:
    depth = 0
    for i in range(start, len(text)):
        depth += {"{": 1, "}": -1}.get(text[i], 0)
        if depth == 0:
            return text[start + 1 : i], i + 1
    raise ValueError("unbalanced braces")


def parse_bib(text: str) -> dict[str, dict]:
    entries = {}
    for m in re.finditer(r"@(\w+)\s*\{\s*([^,\s]+)\s*,", text):
        body, end = braced(text, text.index("{", m.start()))
        fields, pos = {}, body.index(",") + 1
        while f := re.compile(r"\s*(\w+)\s*=\s*").match(body, pos):
            if f.end() >= len(body):
                break
            if body[f.end()] == "{":
                value, pos = braced(body, f.end())
            else:
                v = re.compile(r"[\w.-]+").match(body, f.end())
                value, pos = v.group(0), v.end()
            fields[f.group(1).lower()] = value
            pos = re.compile(r"\s*,?").match(body, pos).end()
        entries[m.group(2)] = {"type": m.group(1).lower(), "fields": fields, "raw": text[m.start():end].strip()}
    return entries


def table_rows(path: Path) -> list[tuple[str | None, str]]:
    """Live table rows as (group, row) pairs; the group is the last \\multicolumn italic heading."""
    t, out = live(path), []
    for tm in re.finditer(r"\\begin\{table\*?\}.*?\\end\{table\*?\}", t, re.S):
        group = None
        for line in tm.group(0).split("\n"):
            if g := re.search(r"\\multicolumn\{\d+\}\{(?:[^{}]|\{\})*\}\{\\textit\{([^}]*)\}\}", line):
                group = plain(g.group(1))
            elif "\\\\" in line and "cite" in line:
                out.append((group, line.strip()))
    return out


def cells(row: str) -> list[str]:
    return [c.strip() for c in re.sub(r"\\\\\s*$", "", row).split("&")]


def words_in(text: str, table) -> list[str]:
    low = f" {text.lower()} "
    found = [v for w, v in (table.items() if isinstance(table, dict) else table) if w in low]
    return list(dict.fromkeys(found))


def modality_list(text: str) -> list[str]:
    low = text.lower().replace("3d/emb.", "3d")
    return [m for m in MODALITY_WORDS if re.search(rf"\b{re.escape(m)}\b", low)]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--paper-dir", type=Path, default=Path("../multimodal-reward"))
    ap.add_argument("--out", type=Path, default=Path("."))
    ap.add_argument("--skip-fetch", action="store_true", help="reuse cached abstracts only")
    args = ap.parse_args()
    p = args.paper_dir

    bib = parse_bib((p / "references.bib").read_text() + "\n" + (p / "additional_references.bib").read_text())
    files = sorted((p / "sections").glob("*.tex")) + sorted((p / "appendix").glob("*.tex"))
    files = [f for f in files if f.name != "00_navigation.tex"]
    cited = []
    for f in files:
        cited += cite_keys(live(f))
    keys = list(dict.fromkeys(cited))
    missing = [k for k in keys if k not in bib]
    if missing:
        raise SystemExit(f"keys missing from the bib: {missing}")

    placements: dict[str, list[tuple[int, str, str | None]]] = defaultdict(list)  # key -> (priority, section, sub)
    tags: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    names: dict[str, str] = {}

    def tag(key, kind, *values):
        for v in values:
            if v and v not in tags[key][kind]:
                tags[key][kind].append(v)

    # Figure 2 (forest in the introduction).
    intro = live(p / "sections/01_intro.tex")
    forest = intro[intro.find("\\begin{forest}"): intro.find("\\end{forest}")]
    taxonomy, branch, group = [], None, None
    for line in forest.split("\n"):
        s = line.strip()
        if m := re.match(r"\[\{(What defines a reward|How a reward is validated)\}", s):
            group = {"name": m.group(1), "branches": []}
            taxonomy.append(group)
        elif m := re.match(r"\[\{([^\\}]+)\\\\\(\\S\\ref\{([^}]+)\}\)\}", s):
            branch = {"name": m.group(1), "ref": m.group(2), "leaves": []}
            group["branches"].append(branch)
        elif (m := re.match(r"\[\{([^}]+)\}\s*$", s)) and branch is not None:
            branch["leaves"].append({"name": m.group(1), "works": []})
        elif "citep" in s and branch is not None:
            leaf = branch["leaves"][-1]
            for label, key in re.findall(r"(?:\[\{|, )([^,{}\[]+?) \\citep\{([^}]+)\}", s):
                leaf["works"].append({"name": plain(label), "key": key})
                if plain(label) not in GENERIC_LABELS:
                    names.setdefault(key, plain(label))
                sec, sub = FIGURE_LEAVES[leaf["name"]]
                placements[key].append((40, sec, sub))
                if sec in ("signal", "supervision", "granularity", "roles"):
                    tag(key, sec, sub)
                if sec in ("understanding", "generation"):
                    tag(key, "direction", sec)

    # Tables 4 and 5: method matrix.
    methods = []
    for tab_index, (group_name, row) in enumerate(table_rows(p / "sections/tab_methods.tex")):
        c = cells(row)
        key = cite_keys(c[0])[0]
        name = plain(re.sub(r"\\mbox\{\\citep\{[^}]*\}\}|\\citep\{[^}]*\}", "", c[0]))
        construction, supervision, granularity, modality, roles = (plain(x) for x in c[1:6])
        direction = "understanding" if key in [k for k in cite_keys(live(p / "sections/tab_methods.tex").split("\\end{table*}")[0])] else "generation"
        methods.append({"key": key, "name": name, "direction": direction, "construction": construction,
                        "supervision": supervision, "granularity": granularity, "modality": modality, "roles": roles})
        names.setdefault(key, name)
        sig = next((sub for w, sub in CONSTRUCTION if w in construction.lower()), None)
        placements[key].append((30, "signal", sig))
        tag(key, "signal", *[sub for w, sub in CONSTRUCTION if w in construction.lower()])
        tag(key, "supervision", *words_in(supervision, SUPERVISION_WORDS))
        tag(key, "granularity", *words_in(granularity, GRANULARITY_WORDS))
        tag(key, "modality", *modality_list(modality))
        tag(key, "roles", *[ROLE_WORDS[r.strip()] for r in roles.split(",") if r.strip() in ROLE_WORDS])
        tag(key, "direction", direction if "both" not in modality.lower() else None)
        if "both" in modality.lower():
            tag(key, "direction", "understanding", "generation")
        tag(key, "kind", "method")

    # Table 6: benchmarks.
    benchmarks = []
    bench_group = {"Image understanding": "image", "Video understanding": "video", "Multilingual": "multilingual",
                   "Generation": "generation", "Omni-modal": "omni"}
    for group_name, row in table_rows(p / "sections/tab_bench.tex"):
        c = cells(row)
        key = cite_keys(c[0])[0]
        name = plain(re.sub(r"\\mbox\{\\citep\{[^}]*\}\}|\\citep\{[^}]*\}", "", c[0])).replace("*", "")
        io, fmt, labels, scale, metric = (plain(x) for x in c[1:6])
        note = "text-only" if "textsuperscript{a}" in c[0] else ("scores generators" if "textsuperscript{b}" in c[0] else None)
        benchmarks.append({"key": key, "name": re.sub(r"[ab]$", "", name).strip(), "group": group_name,
                           "input_output": io, "format": fmt, "labels": labels, "scale": scale, "metric": metric,
                           "note": note})
        names.setdefault(key, re.sub(r"[ab]$", "", name).strip())
        placements[key].append((80, "benchmarks", bench_group.get(group_name)))
        tag(key, "kind", "benchmark")
        tag(key, "modality", *modality_list(io))
        tag(key, "direction", "generation" if group_name == "Generation" else "understanding")

    # Table 1: downstream evidence (defined in the generation section file).
    evidence = []
    for group_name, row in table_rows(p / "sections/09_generation.tex"):
        c = cells(row)
        key = cite_keys(c[0])[0]
        evidence.append({"key": key, "name": plain(re.sub(r"\\citep\{[^}]*\}", "", c[0])), "use": group_name,
                         "setting": plain(c[1]), "link": plain(re.sub(r"\\textsuperscript\{[^}]*\}", "", c[2])),
                         "holds": plain(c[3])})
        placements[key].append((70, "benchmarks", "downstream"))

    # Table 2: failure catalog.
    failures = []
    for group_name, row in table_rows(p / "sections/tab_failures.tex"):
        c = cells(row)
        if len(c) < 6:
            continue
        group_label = plain(c[0]) or failures[-1]["group"]
        key = cite_keys(c[5])[0]
        marks = ["fail" if "qfail" in x else ("either" if "qamp" in x else None) for x in c[2:4]]
        failures.append({"group": group_label, "name": plain(c[1]), "perception": marks[0], "preference": marks[1],
                         "practice": plain(c[4]), "example": key, "text_only": "dag" in c[5], "evidence": []})
        placements[key].append((60, "failures", FAILURE_GROUPS[group_label]))
        tag(key, "failure", plain(c[1]))

    # Table 3: related surveys.
    surveys = []
    columns = ["Und.", "Gen.", "Video", "Audio", "3D/emb.", "Reward design", "Judges", "Deployment roles",
               "Hacking/failures", "Validation tied to use"]
    for group_name, row in table_rows(p / "sections/tab_surveys.tex"):
        c = cells(row)
        key = cite_keys(c[0])[0]
        marks = {col: ("yes" if "\\cm" in v else ("passing" if "circ" in v else None)) for col, v in zip(columns, c[1:])}
        surveys.append({"key": key, "group": group_name, "marks": marks})
        placements[key].append((90, "surveys", "surveys"))
        tag(key, "kind", "survey")

    # Appendix paragraphs and main-text sections.
    for f in files:
        text = live(f)
        if f.parent.name == "appendix":
            first = re.search(r"\\paragraph\{", text)
            if f.name in APPENDIX_INTROS and first:
                sec, sub = APPENDIX_INTROS[f.name]
                for k in cite_keys(text[: first.start()]):
                    placements[k].append((10, sec, sub))
            for pm in re.finditer(r"\\paragraph\{([^}]*)\}(.*?)(?=\\paragraph\{|\\section\{|\Z)", text, re.S):
                head = plain(pm.group(1)).rstrip(".")
                head = re.sub(r"^\d+\.\s*", "", head)
                body_keys = cite_keys(pm.group(2))
                if head in APPENDIX_PARAGRAPHS:
                    sec, sub = APPENDIX_PARAGRAPHS[head]
                    for k in body_keys:
                        placements[k].append((20, sec, sub))
                        if sec in ("signal", "supervision", "roles") and sub:
                            tag(k, sec, sub)
                        if sec in ("understanding", "generation"):
                            tag(k, "direction", sec)
                            tag(k, "modality", *{"video": ["video"], "audio": ["audio"], "3d": ["3d"],
                                                 "t2i": ["image"], "editing": ["image"],
                                                 "interleaved": ["interleaved"]}.get(sub, []))
                elif head in RESEARCH_QUESTIONS:
                    for k in body_keys:
                        placements[k].append((10, *RESEARCH_QUESTIONS[head]))
                elif head in FAILURE_PARAGRAPHS:
                    for k in body_keys:
                        for row in failures:
                            if row["name"] in FAILURE_PARAGRAPHS[head]:
                                placements[k].append((15, "failures", FAILURE_GROUPS[row["group"]]))
                                if k not in row["evidence"]:
                                    row["evidence"].append(k)
                                tag(k, "failure", row["name"])
        elif f.name in MAIN_FILES:
            sec = MAIN_FILES[f.name]
            for k in cite_keys(text):
                placements[k].append((5, sec, None))
        elif f.name == "09_generation.tex":
            head, tail = text.split("\\subsection{Transfer Across Settings}")
            for k in cite_keys(head):
                placements[k].append((5, "generation", None))
                tag(k, "direction", "generation")
            for k in cite_keys(tail):
                placements[k].append((5, "transfer", "transfer"))

    # Cited only in Section 7, about process versus outcome labels.
    placements["ong2025training"].append((10, "granularity", "process"))

    # Primary placement: highest-priority source; ties broken by count, then reading order.
    def primary(key):
        pl = placements.get(key)
        if not pl:
            return "foundations", "rlhf"
        best = max(pr for pr, *_ in pl)
        top = [(s, sub) for pr, s, sub in pl if pr == best]
        counts = Counter(top)
        (sec, sub), _ = max(counts.items(), key=lambda kv: (kv[1], -SECTION_ORDER[kv[0][0]]))
        if sub is None:  # most frequent specific subsection of the same section, else the first subsection
            subs = Counter(s2 for pr, s1, s2 in pl if s1 == sec and s2)
            sub = subs.most_common(1)[0][0] if subs else dict((s, x) for s, *_r, x in SECTIONS)[sec][0][0]
        return sec, sub

    abstracts = fetch_abstracts(keys, bib, args.out / "data/cache", skip=args.skip_fetch)

    papers = []
    for key in keys:
        e, f = bib[key], bib[key]["fields"]
        sec, sub = primary(key)
        venue = plain(f.get("booktitle") or f.get("journal") or "")
        arxiv = arxiv_id(f) or abstracts.get(key, {}).get("arxiv")
        preprint = bool(re.search(r"arxiv|preprint", venue, re.I))
        entry = {
            "key": key,
            "name": names.get(key),
            "title": plain(f["title"]),
            "authors": [plain(a) for a in re.split(r"\s+and\s+", f.get("author", ""))],
            "year": int(re.sub(r"\D", "", f.get("year", "0")) or 0),
            "venue": "arXiv" if preprint else short_venue(venue),
            "peer_reviewed": not preprint,
            "section": sec,
            "subsection": sub,
            "tags": {k: v for k, v in sorted(tags[key].items()) if v},
            "links": {k: v for k, v in {
                "paper": f.get("url") or (f"https://doi.org/{f['doi']}" if f.get("doi") else None),
                "arxiv": f"https://arxiv.org/abs/{arxiv}" if arxiv else None,
                "doi": f.get("doi")}.items() if v},
            "abstract": abstracts.get(key, {}).get("abstract"),
            "bibtex": e["raw"],
        }
        papers.append(entry)
    papers.sort(key=lambda x: (SECTION_ORDER[x["section"]], x["subsection"], -x["year"], x["title"].lower()))

    survey = {
        "title": "From Perception to Preference: A Critical Survey of Multimodal Reward Models and Judges",
        "sections": [{"id": sid, "title": t, "where": w, "subsections": [{"id": a, "title": b} for a, b in subs]}
                     for sid, t, w, subs in SECTIONS],
        "taxonomy": taxonomy,
        "methods": methods,
        "benchmarks": benchmarks,
        "evidence": evidence,
        "failures": failures,
        "surveys": {"columns": columns, "rows": surveys},
    }
    dump(args.out / "papers.yaml", papers)
    dump(args.out / "survey.yaml", survey)
    by = Counter(x["section"] for x in papers)
    print(f"papers={len(papers)} abstracts={sum(1 for x in papers if x['abstract'])} "
          f"methods={len(methods)} benchmarks={len(benchmarks)} failures={len(failures)} surveys={len(surveys)}")
    print("by section:", dict(sorted(by.items(), key=lambda kv: SECTION_ORDER[kv[0]])))


def short_venue(v: str) -> str:
    rules = [(r"Computer Vision and Pattern Recognition", "CVPR"), (r"International Conference on Computer Vision", "ICCV"),
             (r"European Conference on Computer Vision", "ECCV"), (r"Neural Information Processing", "NeurIPS"),
             (r"International Conference on Learning Representations", "ICLR"),
             (r"International Conference on Machine Learning", "ICML"), (r"Annual Meeting of the Association", "ACL"),
             (r"Empirical Methods", "EMNLP"), (r"North American Chapter", "NAACL"), (r"Findings of the Association", "Findings"),
             (r"AAAI", "AAAI"), (r"Language Modeling", "COLM"), (r"Transactions on Machine Learning Research", "TMLR"),
             (r"IJCAI|International Joint Conference on Artificial", "IJCAI"), (r"Robotics: Science and Systems", "RSS"),
             (r"Winter Conference on Applications of Computer Vision", "WACV"), (r"British Machine Vision", "BMVC"),
             (r"Multimedia and Expo", "ICME"), (r"Nations of the Americas Chapter", "NAACL"),
             (r"Asia-Pacific Chapter", "IJCNLP-AACL"), (r"Acoustics, Speech and Signal Processing", "ICASSP"),
             (r"SIGKDD", "KDD"), (r"Advances in Language and Vision Research", "ALVR"),
             (r"Conference on Multimedia Retrieval", "ICMR"), (r"ACM International Conference on Multimedia", "ACM MM"),
             (r"Transactions on Visualization and Computer Graphics", "TVCG"),
             (r"Journal of Artificial Intelligence Research", "JAIR")]
    for pat, short in rules:
        if re.search(pat, v):
            return short
    return v


def arxiv_id(f: dict) -> str | None:
    sources = [f.get("eprint", "")]
    sources += [f.get(x, "") for x in ("journal", "doi") if "arxiv" in f.get(x, "").lower()]
    sources += [f.get("url", "")] if "arxiv.org" in f.get("url", "") else []
    for s in sources:
        if m := re.search(r"(\d{4}\.\d{4,5})", s):
            return m.group(1)
    return None


class SourceExhausted(Exception):
    """The server asked for a wait longer than MAX_WAIT: its quota is used up for now."""


MAX_WAIT = 600


def fetch(url: str, data: bytes | None = None, as_json: bool = True):
    """GET or POST with unlimited retries on rate limits, server errors, and network errors."""
    attempt = 0
    while True:
        try:
            req = urllib.request.Request(url, data=data, headers={**UA, "Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=120) as r:
                body = r.read()
            return json.loads(body) if as_json else body.decode()
        except urllib.error.HTTPError as e:
            if e.code in (400, 403, 404):
                return None
            if e.code not in (429, 500, 502, 503, 504):
                raise
            retry_after = int(e.headers.get("Retry-After") or 0)
            if retry_after > MAX_WAIT:
                raise SourceExhausted(f"{url.split('/')[2]} asks to wait {retry_after}s")
            wait = retry_after or min(120, 5 * 2 ** min(attempt, 5))
            reason = e.code
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            wait, reason = min(120, 5 * 2 ** min(attempt, 5)), type(e).__name__
        attempt += 1
        print(f"  retry {attempt} in {wait}s ({reason}): {url[:90]}", flush=True)
        time.sleep(wait)


get_json = fetch


def fetch_abstracts(keys, bib, cache_dir: Path, skip: bool) -> dict[str, dict]:
    """Abstracts from the arXiv API (batched), then OpenAlex (DOI, then title), then Semantic Scholar."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file = cache_dir / "abstracts.json"
    cache = json.loads(cache_file.read_text()) if cache_file.exists() else {}
    if skip:
        return cache
    need = lambda: [k for k in keys if not (cache.get(k) or {}).get("abstract")]
    save = lambda: cache_file.write_text(json.dumps(cache, indent=1, ensure_ascii=False))

    by_arxiv = {arxiv_id(bib[k]["fields"]): k for k in need() if arxiv_id(bib[k]["fields"])}
    ids = list(by_arxiv)
    for i in range(0, len(ids), 50):
        chunk = ids[i : i + 50]
        url = f"http://export.arxiv.org/api/query?id_list={','.join(chunk)}&max_results={len(chunk)}"
        xml = fetch(url, as_json=False) or ""
        for entry in re.findall(r"<entry>(.*?)</entry>", xml, re.S):
            aid = re.search(r"<id>https?://arxiv.org/abs/([^<v]+)", entry)
            summ = re.search(r"<summary>(.*?)</summary>", entry, re.S)
            if aid and summ and aid.group(1) in by_arxiv:
                cache[by_arxiv[aid.group(1)]] = {"abstract": re.sub(r"\s+", " ", summ.group(1)).strip(), "arxiv": aid.group(1)}
        time.sleep(3)
    save()

    # arXiv title search: most published papers in this field also have an arXiv version.
    for k in need():
        title = plain(bib[k]["fields"]["title"])
        words = re.findall(r"[A-Za-z0-9]+", title)
        q = urllib.parse.quote("ti:\"" + " ".join(words) + "\"")
        xml = fetch(f"http://export.arxiv.org/api/query?search_query={q}&max_results=3", as_json=False) or ""
        time.sleep(3)
        for entry in re.findall(r"<entry>(.*?)</entry>", xml, re.S):
            t_hit = re.sub(r"\s+", " ", re.search(r"<title>(.*?)</title>", entry, re.S).group(1))
            if similar(t_hit, title):
                aid = re.search(r"<id>https?://arxiv.org/abs/([^<v]+)", entry).group(1)
                summ = re.search(r"<summary>(.*?)</summary>", entry, re.S).group(1)
                cache[k] = {"abstract": re.sub(r"\s+", " ", summ).strip(), "arxiv": aid}
                save()
                break
    print(f"after arXiv title search: {len(keys) - len(need())}/{len(keys)} abstracts", flush=True)

    # Semantic Scholar, then OpenAlex, for the rest. A source whose quota is used up is skipped.
    for k in need():
        title = plain(bib[k]["fields"]["title"])
        try:
            r = fetch(f"{S2}/search/match?query={urllib.parse.quote(title)}&fields={S2_FIELDS}")
        except SourceExhausted as e:
            print(f"  skipping Semantic Scholar: {e}", flush=True)
            break
        time.sleep(2)
        hit = (r or {}).get("data", [None])[0] if r else None
        if hit and hit.get("abstract") and similar(hit.get("title", ""), title):
            cache[k] = {"abstract": hit["abstract"], "arxiv": (hit.get("externalIds") or {}).get("ArXiv")}
            save()
    for k in need():
        f = bib[k]["fields"]
        title = plain(f["title"])
        try:
            oa = fetch(f"https://api.openalex.org/works/doi:{urllib.parse.quote(f['doi'])}?mailto=iamclaudecode@gmail.com") if f.get("doi") and "arXiv" not in f["doi"] else None
            if not (oa and oa.get("abstract_inverted_index")):
                q = urllib.parse.quote(re.sub(r"[^\w\s-]", " ", title))
                res = fetch(f"https://api.openalex.org/works?search={q}&per-page=3&mailto=iamclaudecode@gmail.com") or {}
                oa = next((w for w in res.get("results", []) if similar(w.get("title") or "", title) and w.get("abstract_inverted_index")), None)
        except SourceExhausted as e:
            print(f"  skipping OpenAlex: {e}", flush=True)
            break
        if oa and oa.get("abstract_inverted_index"):
            words = sorted((pos, w) for w, ps in oa["abstract_inverted_index"].items() for pos in ps)
            cache[k] = {"abstract": " ".join(w for _, w in words), "arxiv": None}
            save()
    save()
    return cache


def similar(a: str, b: str) -> bool:
    norm = lambda s: set(re.findall(r"[a-z0-9]+", s.lower()))
    x, y = norm(a), norm(b)
    return len(x & y) / max(1, len(x | y)) > 0.7


def dump(path: Path, obj) -> None:
    class Dumper(yaml.SafeDumper):
        pass
    Dumper.add_representer(str, lambda d, s: d.represent_scalar("tag:yaml.org,2002:str", s, style="|" if "\n" in s else None))
    path.write_text(yaml.dump(obj, Dumper=Dumper, sort_keys=False, allow_unicode=True, width=120))


if __name__ == "__main__":
    main()
