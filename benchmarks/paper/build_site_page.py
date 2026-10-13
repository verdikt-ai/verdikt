"""The paper's landing page (verdikt-ai.github.io/verdikt/pco) from the same statistics as the paper.

    python3 -m benchmarks.paper.build_site_page [BENCH_ROOT]  -> BENCH_ROOT/site/pco/index.html
"""
from __future__ import annotations

import html
import json
import os
import sys
from datetime import date
from pathlib import Path

ROOT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(os.environ.get('VERDIKT_BENCH', 'bench-results'))
OUT = ROOT / 'site' / 'pco'
SITE = 'https://verdikt-ai.github.io/verdikt/pco'
CODE = 'https://github.com/verdikt-ai/verdikt'
TITLE = 'Proof-Carrying Operation: Device Agents Whose Completion Claims Are Checked Against the Screen'
AUTHORS = ['Hussein Abdinoor Mohamed', 'Kedar R. Haldankar']
DOI = '10.5281/zenodo.23349257'  # filled in once Zenodo assigns it
PREPRINT = 'https://doi.org/10.5281/zenodo.23349257'  # the arXiv abstract page, e.g. https://arxiv.org/abs/2610.xxxxx; the paper is read there, not hosted here


def main() -> None:
    S = json.loads((ROOT / 'explorer' / 'stats.json').read_text())
    I, P = S['ios'], S['paired_ios']
    b, v2, rep, abl = I['run1-opus'], I['run3-pco-v2'], I['run4-pco-v2-repeat'], I['run5-v2-ledger-only']
    p = P['run1-opus vs run3-pco-v2']
    A = S['android']
    meanA = sum(A[k]['pass_rate'] for k in ('run3-opus', 'practice-seed7', 'practice-seed8')) / 3
    year = date.today().year
    bib = (f"@misc{{mohamed{year}pco,\n  title  = {{{TITLE}}},\n  author = {{{' and '.join(AUTHORS)}}},\n"
           f"  year   = {{{year}}},\n  note   = {{Preprint}},\n  url    = {{{PREPRINT or SITE}}}" + (f",\n  doi    = {{{DOI}}}" if DOI else '') + "\n}")
    stats = [(f"{v2['passed']}/133", f"iOSWorld tasks fully passed with PCO, from {b['passed']} (McNemar p = {p['mcnemar_exact_p']:.3f})"),
             (f"{rep['passed']}/133", 'in an independent repeat run'),
             (f"{v2['mean_score']:.3f}", f"mean rubric score, from {b['mean_score']:.3f}"),
             (f"{100 * meanA:.1f}%", 'AndroidWorld pass@1 averaged over three seeds, no app knowledge')]
    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>Proof-Carrying Operation</title>
<meta name="description" content="Device agents whose completion claims are checked by code against the recorded accessibility tree of the screen they cite, with every run leaving an auditable certificate.">
<meta name="citation_title" content="{html.escape(TITLE)}">{''.join(f'<meta name="citation_author" content="{a}">' for a in AUTHORS)}
<meta name="citation_publication_date" content="{date.today().isoformat()}">
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Archivo:wdth,wght@112..125,600..800&family=Hanken+Grotesk:wght@400;500;600&family=JetBrains+Mono:wght@400;500&display=swap">
<style>
:root {{ --bg:#f3f4f1; --surface:#fff; --line:#d9ddd5; --ink:#111412; --muted:#5f665f; --faint:#8d948c; --signal:#1f43c8;
  --display:"Archivo","Helvetica Neue",Arial,sans-serif; --body:"Hanken Grotesk",-apple-system,"Segoe UI",sans-serif; --mono:"JetBrains Mono",ui-monospace,Menlo,monospace; }}
@media (prefers-color-scheme: dark) {{ :root:not([data-theme="light"]) {{ --bg:#0c0e0d; --surface:#141716; --line:#272c29; --ink:#e8ebe7; --muted:#a0a8a1; --faint:#727a73; --signal:#7d97ff; color-scheme:dark; }} }}
* {{ box-sizing:border-box; }} html,body {{ margin:0; background:var(--bg); color:var(--ink); }}
body {{ font:17px/1.6 var(--body); -webkit-font-smoothing:antialiased; }}
.wrap {{ max-width:860px; margin:0 auto; padding-inline:20px; padding-block:64px 96px; }}
.label {{ font:500 11.5px var(--mono); letter-spacing:.08em; text-transform:uppercase; color:var(--faint); }}
h1 {{ font-family:var(--display); font-stretch:115%; font-weight:800; font-size:clamp(32px,5vw,52px); line-height:1.02; letter-spacing:-.02em; margin:14px 0 18px; text-wrap:balance; }}
.authors {{ font-size:18px; margin:0 0 4px; }} .aff {{ color:var(--muted); margin:0 0 28px; }}
.btns {{ display:flex; gap:10px; flex-wrap:wrap; margin-bottom:44px; }}
.btns a {{ font:500 14px var(--mono); text-decoration:none; color:var(--ink); border:1px solid var(--ink); border-radius:999px; padding:9px 16px; }}
.soon {{ font:500 14px var(--mono); color:var(--muted); border:1px dashed var(--line); border-radius:999px; padding:9px 16px; }}
.btns a.primary {{ background:var(--ink); color:var(--bg); }} .btns a:focus-visible {{ outline:2px solid var(--signal); outline-offset:2px; }}
.stats {{ display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); border-top:1px solid var(--ink); margin-bottom:44px; }}
@media (max-width:700px) {{ .stats {{ grid-template-columns:repeat(2,minmax(0,1fr)); }} }}
.stat {{ padding:14px 14px 0 0; }} .stat b {{ display:block; font-family:var(--display); font-stretch:112%; font-size:30px; font-variant-numeric:tabular-nums; }}
.stat span {{ font-size:13.5px; color:var(--muted); }}
h2 {{ font-family:var(--display); font-stretch:112%; font-size:22px; margin:40px 0 10px; }}
p {{ max-width:68ch; }} a {{ color:var(--signal); }}
pre {{ background:var(--surface); border:1px solid var(--line); border-radius:12px; padding:16px; overflow-x:auto; font:13px/1.5 var(--mono); }}
button {{ font:500 13px var(--mono); border:1px solid var(--line); background:var(--surface); color:var(--ink); border-radius:8px; padding:6px 12px; cursor:pointer; }}
</style></head><body><main class="wrap">
<span class="label">Preprint · {date.today().strftime('%B %Y')}</span>
<h1>{html.escape(TITLE)}</h1>
<p class="authors">{' · '.join(AUTHORS)}</p><p class="aff">Verdikt</p>
<div class="btns">{f'<a class="primary" href="{PREPRINT}">Read the preprint</a>' if PREPRINT else '<span class="soon">Preprint on arXiv: coming soon</span>'}<a href="results/">Explore every run</a><a href="results/#/data">Data &amp; statistics</a><a href="{CODE}">Code (Apache-2.0)</a>{f'<a href="https://doi.org/{DOI}">doi:{DOI}</a>' if DOI else ''}</div>
<div class="stats">{''.join(f'<div class="stat"><b>{v}</b><span>{html.escape(t)}</span></div>' for v, t in stats)}</div>
<h2>Abstract</h2>
<p>Agents that operate phones decide for themselves when a task is done, and most of their failures happen at that decision: they stop before every part of a multi-step goal is finished, give up when evidence is hard to find, or report facts they never checked. We move the decision from the model to a checker. In proof-carrying operation (PCO) the agent compiles the goal into typed obligations and closes each with the value it claims and the recorded screen that shows it; a deterministic checker accepts a claim only if that screen's UI tree contains it, challenges claims of absence, and completes the final answer only from proven facts. On iOSWorld, PCO raises the share of fully passed tasks from {b['passed']}/133 to {v2['passed']}/133 and the mean rubric score from {b['mean_score']:.3f} to {v2['mean_score']:.3f} (exact McNemar p = {p['mcnemar_exact_p']:.3f}), an independent repeat reproduces it ({rep['passed']}/133), and an ablation attributes the gain to the complete, evidence-bound obligation ledger. On AndroidWorld the same operator averages {100 * meanA:.1f}% pass@1 over three seeds with no app knowledge.</p>
<h2>Cite</h2>
<pre id="bib">{html.escape(bib)}</pre>
<button type="button" id="copy">Copy BibTeX</button> <span id="copied" class="label" hidden>copied</span>
</main>
<script>
document.getElementById('copy').onclick = () => {{
  const t = document.getElementById('bib').textContent, ok = () => {{ document.getElementById('copied').hidden = false; }};
  if (navigator.clipboard) navigator.clipboard.writeText(t).then(ok, () => {{ const r = document.createRange(); r.selectNode(document.getElementById('bib')); getSelection().removeAllRanges(); getSelection().addRange(r); }});
}};
</script></body></html>"""
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / 'index.html').write_text(page)
    (OUT / 'paper.pdf').unlink(missing_ok=True)
    print(OUT / 'index.html')


if __name__ == '__main__':
    main()
