#!/usr/bin/env python3
"""
test_apis.py - check that every metadata source used by paper_renamer.py is working.

Keep this file in the same folder as paper_renamer.py, then run:
    python test_apis.py

It uses the same code and the same saved settings (OpenAlex key, email) as the renamer,
so a PASS here means the renamer can use that source from this computer.
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import paper_renamer as pr

# Known paper used for the checks: Silver et al. (2016), Nature
DOI = "10.1038/nature16961"
TITLE = "Mastering the game of Go with deep neural networks and tree search"
EXPECT = ("Silver", 2016)
# Known arXiv paper: Vaswani et al. (2017)
ARXIV = "1706.03762"
ARXIV_DOI = "10.48550/arXiv.1706.03762"       # a DataCite DOI, not in Crossref
ARXIV_EXPECT = ("Vaswani", 2017)

cfg = pr.load_config()
results = []


def check(label, fn, arg, expect, needs_key=False, is_list=False):
    if needs_key and not cfg.get("openalex_key"):
        results.append((label, "SKIP", "no OpenAlex key saved (set-key openalex YOUR_KEY)"))
        return
    t0 = time.time()
    try:
        out = fn(arg, cfg)
    except pr.NetError as e:
        hint = ""
        if "401" in str(e) or "403" in str(e):
            hint = "  <- key rejected or access blocked"
        elif "429" in str(e):
            hint = "  <- rate limited, try again in a minute"
        results.append((label, "FAIL", f"{e}{hint}"))
        return
    except Exception as e:                                   # unexpected response shape
        results.append((label, "FAIL", f"{type(e).__name__}: {e}"))
        return
    secs = time.time() - t0
    if is_list:
        out = next((m for m in out or [] if m and pr.titles_match(m["title"], arg)), None)
    if not out:
        results.append((label, "FAIL", "reachable, but the test paper was not found"))
        return
    author = (out["authors"] or ["?"])[0]
    got = f"{out['year']} / {author} / {out['title'][:45]}"
    ok = pr.norm(author) == pr.norm(expect[0]) and abs(out["year"] - expect[1]) <= 1
    results.append((label, "PASS" if ok else "WARN", f"{got}   ({secs:.1f}s)" + ("" if ok else "  <- unexpected values")))


print(f"Settings folder: {pr.app_dir()}")
print(f"OpenAlex key: {'set' if cfg.get('openalex_key') else 'NOT set'}   Email: {cfg.get('email') or 'not set'}\n")

check("Crossref          DOI lookup", pr.crossref_doi, DOI, EXPECT)
check("Crossref          title search", pr.crossref_title, TITLE, EXPECT, is_list=True)
check("doi.org           DOI lookup", pr.doiorg_doi, DOI, EXPECT)
check("doi.org           DataCite DOI", pr.doiorg_doi, ARXIV_DOI, ARXIV_EXPECT)
check("OpenAlex          DOI lookup", pr.openalex_doi, DOI, EXPECT, needs_key=True)
check("OpenAlex          title search", pr.openalex_title, TITLE, EXPECT, needs_key=True, is_list=True)
check("Semantic Scholar  DOI lookup", pr.s2_doi, DOI, EXPECT)
check("Semantic Scholar  arXiv lookup", pr.s2_arxiv, ARXIV, ARXIV_EXPECT)
check("Semantic Scholar  title search", pr.s2_title, TITLE, EXPECT, is_list=True)
check("arXiv             ID lookup", pr.arxiv_id, ARXIV, ARXIV_EXPECT)

for label, status, detail in results:
    print(f"[{status}] {label:32} {detail}")

n = {s: sum(r[1] == s for r in results) for s in ("PASS", "WARN", "FAIL", "SKIP")}
print(f"\n{n['PASS']} passed, {n['WARN']} warnings, {n['FAIL']} failed, {n['SKIP']} skipped")
if n["FAIL"] == len(results) - n["SKIP"]:
    print("Everything failed: check your internet connection, VPN or firewall/proxy.")
elif n["FAIL"]:
    print("The renamer still works: it falls back to the sources that passed.")
sys.exit(1 if n["FAIL"] else 0)
