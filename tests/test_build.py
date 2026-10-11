import json
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import build  # noqa: E402


def load():
    return build.load()


def test_papers_validate():
    papers, survey = load()
    assert build.validate(papers, survey) == []


def test_generated_files_are_current():
    result = subprocess.run([sys.executable, str(ROOT / "scripts/build.py"), "--check"], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


def test_survey_views_point_to_listed_papers():
    papers, survey = load()
    keys = {p["key"] for p in papers}
    referenced = [m["key"] for m in survey["methods"]] + [b["key"] for b in survey["benchmarks"]]
    referenced += [e["key"] for e in survey["evidence"]] + [f["example"] for f in survey["failures"]]
    referenced += [w["key"] for g in survey["taxonomy"] for br in g["branches"] for leaf in br["leaves"] for w in leaf["works"]]
    assert set(referenced) <= keys


def test_site_data_is_valid_json():
    text = (ROOT / "site/data.js").read_text()
    payload = json.loads(text[text.index("{"): text.rindex("}") + 1])
    assert len(payload["papers"]) == len(yaml.safe_load((ROOT / "papers.yaml").read_text()))
