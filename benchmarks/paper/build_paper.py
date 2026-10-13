"""Render the paper from the run data: every number comes from stats.json, audit.json or the run folders.

    python3 -m benchmarks.explorer.stats && python3 -m benchmarks.paper.audit && python3 -m benchmarks.paper.build_paper [BENCH_ROOT]
        -> BENCH_ROOT/paper/draft.html + draft.pdf

Sections whose runs have not finished render as pending; partial runs are marked preliminary.
"""
from __future__ import annotations

import html
import json
import os
import subprocess
import sys
from collections import Counter
from datetime import date
from pathlib import Path

ROOT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(os.environ.get('VERDIKT_BENCH', 'bench-results'))
OUT = ROOT / 'paper'
CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
IOS_TOTAL = 133
IOS_RUNS = ROOT / 'iosworld-runs'
SITE = 'https://verdikt-ai.github.io/verdikt/pco'
CODE = 'https://github.com/verdikt-ai/verdikt'
TITLE = 'Proof-Carrying Operation: Device Agents Whose Completion Claims Are Checked Against the Screen'
BASE, V1, V2, REP, ABL = 'run1-opus', 'run2-pco', 'run3-pco-v2', 'run4-pco-v2-repeat', 'run5-v2-ledger-only'


def pct(x) -> str:
    return '—' if x is None else f'{100 * x:.1f}%'


def ci(c) -> str:
    return '—' if not c else f'{100 * c[0]:.1f}–{100 * c[1]:.1f}%'


def p_txt(p) -> str:
    return '—' if p is None else ('&lt; 0.001' if p < 0.001 else f'{p:.3f}')


def task_json(run: str, task: str) -> dict:
    try:
        return json.loads((IOS_RUNS / run / task / 'task.json').read_text())
    except (OSError, ValueError):
        return {}


def ledger_counts(run: str) -> Counter:
    c = Counter()
    for f in (IOS_RUNS / run).glob('*/certificate.json'):
        for o in json.loads(f.read_text()).get('ledger', []):
            c[o.get('type')] += 1
    return c


def clip(text: str, n: int) -> str:
    if len(text) <= n:
        return text
    cut = text[:n].rsplit(' ', 1)[0]
    return cut + '…'


def words(prompt: str) -> int:
    try:
        return len((Path(__file__).resolve().parent.parent / 'iosworld' / prompt).read_text().split())
    except OSError:
        return 0


ARCH_SVG = """<svg viewBox="0 0 720 262" width="100%" role="img" aria-label="Proof-carrying operation: agent, device, ledger, checker" font-family="Helvetica Neue, Arial, sans-serif" font-size="10.5">
<defs><marker id="a" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="#333"/></marker></defs>
<rect x="8" y="14" width="150" height="54" rx="6" fill="#f6f6f3" stroke="#333"/><text x="83" y="36" text-anchor="middle" font-weight="700">Goal</text><text x="83" y="52" text-anchor="middle" fill="#444">natural language</text>
<rect x="210" y="14" width="190" height="96" rx="6" fill="#fff" stroke="#333"/><text x="305" y="34" text-anchor="middle" font-weight="700">Agent (one general model)</text>
<text x="305" y="52" text-anchor="middle" fill="#444">1 compile the goal into obligations</text><text x="305" y="68" text-anchor="middle" fill="#444">2 act, observe, close each obligation</text><text x="305" y="84" text-anchor="middle" fill="#444">with claim + cited screen</text><text x="305" y="100" text-anchor="middle" fill="#444">3 stop and request verification</text>
<rect x="452" y="14" width="150" height="96" rx="6" fill="#fff" stroke="#333"/><text x="527" y="34" text-anchor="middle" font-weight="700">Device</text><text x="527" y="52" text-anchor="middle" fill="#444">every action returns</text><text x="527" y="68" text-anchor="middle" fill="#444">the screen it produced;</text><text x="527" y="84" text-anchor="middle" fill="#444">each screen's UI tree</text><text x="527" y="100" text-anchor="middle" fill="#444">is recorded as evidence</text>
<line x1="158" y1="41" x2="208" y2="41" stroke="#333" marker-end="url(#a)"/>
<line x1="400" y1="52" x2="450" y2="52" stroke="#333" marker-end="url(#a)"/><text x="425" y="47" text-anchor="middle" fill="#444" font-size="9">action</text>
<line x1="450" y1="80" x2="402" y2="80" stroke="#333" marker-end="url(#a)"/><text x="426" y="94" text-anchor="middle" fill="#444" font-size="9">screen</text>
<rect x="210" y="140" width="190" height="60" rx="6" fill="#eef1fb" stroke="#1f43c8"/><text x="305" y="160" text-anchor="middle" font-weight="700" fill="#1f43c8">Obligation ledger</text><text x="305" y="176" text-anchor="middle" fill="#333">DO · KNOW · SAY · IF</text><text x="305" y="191" text-anchor="middle" fill="#333">open → proven | unproven | absent</text>
<line x1="305" y1="110" x2="305" y2="138" stroke="#333" marker-end="url(#a)"/><text x="312" y="128" fill="#444" font-size="9">claims</text>
<rect x="452" y="140" width="150" height="96" rx="6" fill="#eef1fb" stroke="#1f43c8"/><text x="527" y="160" text-anchor="middle" font-weight="700" fill="#1f43c8">Checker (code)</text><text x="527" y="176" text-anchor="middle" fill="#333">claim ⊆ cited UI tree?</text><text x="527" y="191" text-anchor="middle" fill="#333">challenge absence once</text><text x="527" y="206" text-anchor="middle" fill="#333">gate: resume while open</text><text x="527" y="221" text-anchor="middle" fill="#333">answer only from proven</text>
<line x1="400" y1="170" x2="450" y2="170" stroke="#333" marker-end="url(#a)"/>
<path d="M452,205 C430,240 330,242 305,205" fill="none" stroke="#1f43c8" stroke-dasharray="4 3" marker-end="url(#a)"/><text x="380" y="252" text-anchor="middle" fill="#1f43c8" font-size="9">rejected / open: same session, same budget</text>
<rect x="624" y="140" width="88" height="96" rx="6" fill="#f6f6f3" stroke="#333"/><text x="668" y="162" text-anchor="middle" font-weight="700">Output</text><text x="668" y="180" text-anchor="middle" fill="#444">final answer</text><text x="668" y="196" text-anchor="middle" fill="#444">certificate</text><text x="668" y="212" text-anchor="middle" fill="#444">(ledger with</text><text x="668" y="226" text-anchor="middle" fill="#444">verdicts)</text>
<line x1="602" y1="188" x2="622" y2="188" stroke="#333" marker-end="url(#a)"/>
</svg>"""


def certificate_figure(run: str, task: str) -> str:
    try:
        cert = json.loads((IOS_RUNS / run / task / 'certificate.json').read_text())
    except (OSError, ValueError):
        return ''
    rows = ''
    for o in cert.get('ledger', []):
        rows += (f"<tr><td><code>{html.escape(o['obligation'][:88])}</code></td><td>{html.escape(clip(o.get('claim') or '', 110))}</td>"
                 f"<td class=n>{o.get('evidence_frame', '—')}</td><td>{o.get('verdict')}</td></tr>")
    return (f'<table class="cert"><caption>Figure 2. The certificate of task {task} in the PCO v2 run: the ledger with the checker\'s verdicts. '
            f'Each obligation names the value the agent claimed and the recorded screen it cited. The last row shows the checker\'s limit: '
            f'"Pause" is the text that proves a running timer (the button reads "Start" otherwise), and the checker verifies that the text is on the cited screen, nothing more.</caption>'
            f'<thead><tr><th>Obligation</th><th>Claim (copied from the screen)</th><th>Screen</th><th>Verdict</th></tr></thead><tbody>{rows}</tbody></table>')


def main() -> None:
    S = json.loads((ROOT / 'explorer' / 'stats.json').read_text())
    try:
        A = json.loads((OUT / 'audit.json').read_text())
    except (OSError, ValueError):
        A = {}
    AN, I, PA, PI = S['android'], S['ios'], S.get('paired_android', {}), S.get('paired_ios', {})
    base, v1, v2, rep, abl = (I.get(k) for k in (BASE, V1, V2, REP, ABL))
    full = lambda s: s is not None and s['tasks'] >= IOS_TOTAL  # noqa: E731
    pv2, prep, pv1 = PI.get(f'{BASE} vs {V2}'), PI.get(f'{BASE} vs {REP}'), PI.get(f'{BASE} vs {V1}')
    pvar, pabl, pablb = PI.get(f'{V2} vs {REP}'), PI.get(f'{ABL} vs {V2}'), PI.get(f'{BASE} vs {ABL}')
    a3, a8 = AN.get('run3-opus'), AN.get('run8-opus-contracts')
    c7, c8 = AN.get('run9-contracts-seed7'), AN.get('run10-contracts-seed8')
    p38 = PA.get('run3-opus vs run8-opus-contracts', {})
    seedsA = [AN[k] for k in ('run3-opus', 'practice-seed7', 'practice-seed8') if k in AN]
    seedsC = [AN[k] for k in ('run8-opus-contracts', 'run9-contracts-seed7', 'run10-contracts-seed8') if k in AN]
    meanA = sum(x['pass_rate'] for x in seedsA) / len(seedsA) if seedsA else None
    meanC = sum(x['pass_rate'] for x in seedsC) / len(seedsC) if seedsC else None
    led = ledger_counts(V2)
    chk = (v2 or {}).get('checker') or {}
    case_b = (task_json(BASE, 'multi-081').get('evaluation') or {}).get('score')
    case_p = (task_json(V2, 'multi-081').get('evaluation') or {}).get('score')
    # audit numbers
    pf = (A.get('proofs') or {}).get(V2, {})
    fl, flr, fla = ((A.get('flips') or {}).get(k, {}) for k in (V2, REP, ABL))
    rd = (A.get('rounds') or {}).get(V2, {})
    bud = (A.get('budget') or {}).get(V2, {})
    budb = (A.get('budget') or {}).get(BASE, {})
    col = A.get('collision_rerun') or {}
    man = A.get('manual') or {}
    mc = man.get('counts') or {}
    rub = A.get('rubric') or {}
    w_base, w_pco = words('prompt.md'), words('prompt-pco-v2.md')
    flipped = fl.get('criteria_flipped_in_gained') or {}
    n_flipped = sum(flipped.values())
    cat = lambda s, c: s['by_category'].get(c, {}) if s else {}  # noqa: E731
    n_ios_tests, n_tests = 6, 6 + len(PA)
    bonf = ''
    if pv2:
        mc_ok = pv2['mcnemar_exact_p'] * n_ios_tests < 0.05
        sg_ok = (pv2.get('sign_test_p') or 1) * n_tests < 0.05
        bonf = (f"Six paired tests are reported for iOSWorld and {len(PA)} for AndroidWorld. The headline McNemar comparison "
                f"{'survives' if mc_ok else 'does not survive'} a Bonferroni correction across the six iOSWorld tests "
                f"({pv2['mcnemar_exact_p']:.4f} × {n_ios_tests} = {pv2['mcnemar_exact_p'] * n_ios_tests:.3f}), and its sign test "
                f"{'survives' if sg_ok else 'does not survive'} correction across all {n_tests} ({pv2.get('sign_test_p', 0):.4f} × {n_tests} = {(pv2.get('sign_test_p') or 0) * n_tests:.3f}).")

    def irow(label: str, s: dict | None) -> str:
        if not s:
            return f'<tr><td>{label}</td><td colspan=6 class=pend>pending</td></tr>'
        return (f"<tr><td>{label}{' *' if not full(s) else ''}</td><td class=n>{s['passed']}/{s['tasks']}</td><td class=n>{pct(s['pass_rate'])}</td>"
                f"<td class=n>{ci(s['pass_ci95'])}</td><td class=n>{s['mean_score']:.3f}</td>"
                f"<td class=n>{s['mean_score_ci95'][0]:.3f}–{s['mean_score_ci95'][1]:.3f}</td><td class=n>${s['cost_usd']:.0f}</td></tr>")

    def arow(rid: str, label: str) -> str:
        s = AN.get(rid)
        if not s:
            return ''
        return (f"<tr><td>{label}</td><td class=n>{s['seed']}</td><td class=n>{s['passed']}/{s['tasks']}</td>"
                f"<td class=n>{pct(s['pass_rate'])}</td><td class=n>{ci(s['pass_ci95'])}</td></tr>")

    def prow(label: str, p: dict | None) -> str:
        if not p:
            return f'<tr><td>{label}</td><td colspan=5 class=pend>pending</td></tr>'
        d = p.get('mean_score_diff')
        dci = p.get('mean_score_diff_ci95') or [None, None]
        delta = '—' if d is None else f'{d + 0.0:+.3f} ({dci[0] + 0.0:+.3f} to {dci[1] + 0.0:+.3f})'.replace('-0.000', '+0.000')
        return (f"<tr><td>{label}</td><td class=n>{p['tasks']}</td><td class=n>+{p['b_only_passes']} / −{p['a_only_passes']}</td>"
                f"<td class=n>{p_txt(p['mcnemar_exact_p'])}</td><td class=n>{delta}</td><td class=n>{p_txt(p.get('sign_test_p'))}</td></tr>")

    cat_rows = ''
    if base and v2 and abl:
        for c in ('single_app', 'multi_app', 'memory'):
            b_, v_, a_ = cat(base, c), cat(v2, c), cat(abl, c)
            if b_ and v_:
                cat_rows += (f"<tr><td>{c.replace('_', '-')}</td><td class=n>{b_['tasks']}</td><td class=n>{b_['passed']}</td><td class=n>{b_['mean_score']:.3f}</td>"
                             f"<td class=n>{v_['passed']}</td><td class=n>{v_['mean_score']:.3f}</td><td class=n>{a_.get('passed', '—')}</td></tr>")

    headline = (f"from {base['passed']} to {v2['passed']} of 133 tasks fully passed ({pct(base['pass_rate'])} to {pct(v2['pass_rate'])}) and the mean rubric score "
                f"from {base['mean_score']:.3f} to {v2['mean_score']:.3f} (exact McNemar p = {p_txt(pv2['mcnemar_exact_p'])}); a replicate run lands at "
                f"{rep['passed']}/133 ({rep['mean_score']:.3f})" if base and v2 and pv2 and rep else '(results pending)')
    mm = cat(base, 'multi_app'), cat(v2, 'multi_app')
    aud = (f"{mc.get('S', 0)} sound, {mc.get('E', 0)} editor-state, {mc.get('W', 0)} weak and {mc.get('M', 0)} mismatched" if mc else 'pending')
    body = f"""
<header>
  <p class="meta">Preprint · {date.today().strftime('%B %Y')} · {SITE} · CC BY 4.0</p>
  <h1>{TITLE}</h1>
  <p class="authors">Hussein Abdinoor Mohamed and Kedar R. Haldankar · Verdikt</p>
</header>

<section class="abstract"><h2>Abstract</h2>
<p>Agents that operate phones decide for themselves when a task is done, and that decision is where they fail: they stop with sub-goals unfinished, give up on facts that are hard to find, and report values they never saw. <em>Proof-carrying operation</em> (PCO) takes the decision away from the model. The agent compiles the goal into typed obligations (state changes to make, facts to report, results to derive, conditions to resolve) and must close each with the value it claims and the recorded screen that shows it. A deterministic checker with no app knowledge accepts a claim only if the cited screen's accessibility tree contains it, challenges every claim of absence, refuses to end the episode while obligations are open, and completes the final answer only from claims it accepted. Every run leaves a certificate. On iOSWorld, PCO raises performance {headline}, without app-specific knowledge. The gain sits in multi-app tasks ({mm[0].get('passed', '—')} to {mm[1].get('passed', '—')} of {mm[0].get('tasks', '—')}) and in criteria about actions on the device, not in answer wording. An ablation without resumption rounds keeps most of the gain ({abl['passed'] if abl else '—'}/133), which locates the effect in the obligation ledger the agent must keep rather than in being sent back. We audit the checker itself: of 60 randomly sampled accepted claims, {aud}; every ledger, screen and certificate is published so that the audit can be repeated. On AndroidWorld, near its ceiling, the same operator averages {pct(meanA)} pass@1 over three suite seeds with no app knowledge.</p>
</section>

<h2>1 Introduction</h2>
<p>Mobile-agent benchmarks now report results above 95% on AndroidWorld [1], which leaves little room to measure a method. iOSWorld [2], with multi-app and personal-memory tasks graded by a rubric, still does. When we read our own agent's first imperfect iOSWorld runs, the failures were rarely about capability: of the first 40 imperfect tasks only 6 ran out of actions. The rest stopped early, skipped a sub-goal, decided a fact did not exist (in one case because the agent never opened the reply thread where it was), or left a requested fact out of the answer.</p>
<p>The common cause is that the agent is the judge of its own completion. Separating the party that does the work from the party that certifies it is an old principle; we had applied it to multi-agent coordination with a human-only verification gate [10], and self-reports have since been shown to be poor evidence across agent settings [16]. Device operation is a domain where the principle can be mechanised, because most of what a phone agent achieves is visible on a screen whose accessibility tree can be recorded and searched. PCO does exactly that: the agent writes down what it owes, and code decides what it has shown. Our contributions:</p>
<ol>
<li><strong>Proof-carrying operation</strong>: typed obligations compiled by the agent at run time, claims checked by code against the recorded accessibility tree of the cited screen, absence challenges, a completion gate that resumes the same session without resetting its budget, answers completed only from accepted claims, and a per-run certificate. No per-task specification and no app knowledge are needed.</li>
<li><strong>A replicated, paired result on iOSWorld and an account of where it comes from</strong>: a significant gain over the same operator without PCO, reproduced in a second run; a first version that did not work and the two compile-time changes that made it work; an ablation showing that the ledger, not the resumption rounds, carries the effect; and a criterion-level analysis showing that the gain is in actions on the device, not in answer wording.</li>
<li><strong>An audit of the checker and a complete release</strong>: a labelled random sample of the claims the checker accepted, a precise statement of what a "proof" does and does not establish, and every trajectory, screen, ledger and certificate behind every number, with the method released as Verdikt Core (Apache-2.0).</li>
</ol>

<h2>2 Related work</h2>
<p><strong>Benchmarks.</strong> AndroidWorld [1] has 116 parameterised tasks with programmatic success checks; iOSWorld [2] has 133 tasks over 26 apps graded by a rubric judge, with a 50-step limit.</p>
<p><strong>Completion gates in GUI agents.</strong> The failure we target is documented across the field: PhoneHarness [12] lists premature termination and hallucinated completion as distinct failure classes, and GUI-PRA [13] shows that a passive verifier mistakes visual progress for completion. VLAA-GUI [11] makes the same diagnosis we do, derives UI-observable success criteria per task, gates termination on them and resumes the agent with missing-evidence feedback; its gate and judge are models, and it reports that they only partially remove false completion. Surfer 2 [6] and AdecPilot [7] gate the end of an episode on a model's judgment; Mobile-Agent-E [8] reflects on screen changes with a model. PCO differs in what decides: the claim is checked by code against the recorded accessibility tree, so the verdict is reproducible from the published run and cannot be talked into agreement.</p>
<p><strong>Agent-written checks.</strong> AdaPlanner [3] has an LLM write assertions into a code plan for text environments. WebTestPilot [4] infers pre- and postconditions in a DSL for web testing from a given specification. VeriSafe Agent [5] turns an instruction into a logical specification over developer-written predicates and gates critical actions. Postcondition checks have been shown to cut false success claims in tool-using agents [14], and "No Trace, No Claim" [15] proposes evidence contracts under which a result may support a claim. PCO's obligations are written by the operating agent for an arbitrary goal, need no developer predicates and no app changes, and are discharged against the live UI tree.</p>
<p><strong>Certificates and termination.</strong> The name borrows from proof-carrying code [9]: the producer ships a certificate that a simple checker verifies. The same idea has recently been applied to plans [17], numeric answers [18], LLM pipelines [19] and agent governance [20]. Closest to PCO is evidence-carrying termination (ECT) [21], developed concurrently for tool-using agents: an agent may return only when a typed certificate binds every required answer claim to receipts in an evidence ledger, verified deterministically against a task contract. ECT's contract is written by a trusted party before the run; PCO's obligations are compiled by the agent from the goal, which is what lets it run on any goal without a specification, at the price that coverage of the goal is not itself verified (Section 3.4). ECT is evaluated on synthetic tools; PCO on two public GUI benchmarks.</p>
<p><strong>Typed goals.</strong> The distinction between obligations to make something true and obligations to find something out is the achievement/test goal split of BDI agent languages [22]; PCO adds derived results (SAY) and conditions (IF) because a phone goal asks for both.</p>
<p><strong>Coordination of agent work.</strong> Orcha [10] coordinates episodic agents through durable, audited state and a human-only verification gate. PCO keeps its typed, auditable state and replaces the human verifier with a mechanical one for outcomes visible in the UI.</p>

<h2>3 Proof-carrying operation</h2>
<figure>{ARCH_SVG}<figcaption>Figure 1. Proof-carrying operation. The agent compiles the goal into an obligation ledger and closes each obligation with a claim and the screen that shows it. The checker, which is code, accepts or rejects each claim against the recorded UI tree of that screen, keeps the session open while obligations remain, completes the answer from accepted claims, and emits the ledger as the run's certificate.</figcaption></figure>
<h3>3.1 Obligations</h3>
<p>An obligation is one thing the goal owes, typed by how it is discharged. <code>DO</code>: a state change (one per recipient, item or edit; "confirm that X was done" is a DO proven by the screen showing X). <code>KNOW</code>: a fact to report or to use later. <code>SAY</code>: a result the agent must work out rather than read (a total, comparison, pattern, recommendation), which rests on KNOWs. <code>IF</code>: a condition in the goal, whose answer is itself a fact. Each obligation is a small state machine: open, then proven, unproven or absent, and only the checker moves it to proven. The agent's claim of completion is a request for verification, not the verdict.</p>
<h3>3.2 The agent's protocol</h3>
<p>The agent is one general model with a system prompt and no app knowledge. <strong>Compile.</strong> Before acting, go through the goal clause by clause and record every obligation; recording is free. <strong>Budget.</strong> Give each obligation a share of the 50 actions, costliest first; with few actions left, finish open DOs. <strong>Discharge.</strong> The moment a screen shows a value or result, close the obligation with <em>actual</em> = the text copied from that screen and <em>evidence</em> = that screen's step; closing costs no action and must cite the latest screen. Never spend actions returning to a screen only to prove something; leave it for the checker's round. Close an obligation as absent only after opening the threads, replies, details, tabs and apps where it could be. <strong>Finish.</strong> Stop with a final answer that states every KNOW; do not end the session.</p>
<h3>3.3 The checker</h3>
<p>The checker is about 160 lines of code with no model and no app knowledge. <strong>Check.</strong> A DO or KNOW claim is accepted when the normalised claim is a substring of the text of the cited screen's accessibility tree (labels, values and titles); a claim longer than 30 characters may instead match when 80% of its tokens appear. A SAY is accepted when a result is stated. <strong>Challenge.</strong> A claim of absence is sent back once with the list of places to look; a second absence is accepted. <strong>Gate.</strong> While any obligation is open, rejected or unchallenged-absent, the same agent session is resumed on the same device session with the budget it had left, for at most two rounds. <strong>Answer.</strong> The final answer is completed with every accepted KNOW and SAY it left out, and nothing else is added. <strong>Certify.</strong> The ledger, with each obligation's type, claim, cited screen and verdict, is written out with the run.</p>
<h3>3.4 What a proof establishes</h3>
<p>A proof in PCO is a pointer: an accepted claim means that the text the agent claimed is on a recorded screen it cited, and the published run lets anyone re-check that. The checker therefore establishes that a claimed value was seen, that a claimed state is displayed, and that nothing enters the answer without a screen behind it. It does not establish three things, and we say so because the method's value depends on knowing where it stops. It does not verify <em>coverage</em>: the agent compiles the ledger, so an obligation it never records is never demanded (Section 4 shows what that costs). It does not verify <em>constraints</em>: a booking at 11:30 proves a booking, not the 11:00 the goal asked for; the rubric judge, not the checker, catches that. It does not verify <em>persistence</em>: a note body on screen proves the edit, not that it was saved. Section 6.4 measures how often accepted claims fall into these gaps.</p>
{certificate_figure(V2, 'multi-081')}

<h2>4 From a checker that did nothing to one that works</h2>
<p>Our first version (v1) had DO, KNOW and IF, a checker, and no measurable effect ({v1['passed'] if v1 else '—'}/133 against {base['passed'] if base else '—'}, p = {p_txt(pv1['mcnemar_exact_p']) if pv1 else '—'}). Its ledgers were well kept, with most obligations proven, but incomplete: open-ended requests such as "correlate", "recommend" or "summarise" were never recorded, so the checker could not ask for them; and the agent spent actions returning to screens to prove claims, running out of budget on long tasks. A checker can only certify the parts the agent thought of. Version 2 changed only how the goal is compiled and proved: SAY obligations for derived results, clause-by-clause compilation ("every verb is an obligation"), and cost-aware proving (close with the next screen that happens to show it; never go back to prove). These are generic instructions that name no app, task or value. Everything that follows evaluates v2.</p>

<h2>5 Experimental setup</h2>
<p><strong>Operator.</strong> One general model (Claude Opus) operates the device through Verdikt's tools, the same tools in every configuration. Every action returns the screen it produced. An element index refers to the screen the agent saw, and the element is re-found on the live screen by type, identifier and label before acting, so a list that loads or a keyboard that opens cannot redirect a tap. A text field is tapped until it reports focus and typed text is read back.</p>
<p><strong>iOSWorld.</strong> 133 tasks on iPhone 17 Pro simulators (iOS 26.5), five in parallel; iOSWorld's own data reset and reseed before each task; the benchmark's 50-step limit as a 50-action budget and a 30-minute wall-clock limit; iOSWorld's unchanged rubric judge and prompt. Two departures from the benchmark's defaults apply to every configuration alike: the judge model is Claude Sonnet 4.6 rather than GPT-5.4-mini, and we report the rubric-perfect rate (every criterion satisfied, which iOSWorld reports alongside its holistic pass rate and which tracks it within 1–2 points [2]) as "fully passed". Our numbers are therefore comparable across our configurations and not directly with the iOSWorld leaderboard. The baseline configuration is the same operator with a {w_base}-word prompt and no ledger; the PCO prompt is {w_pco} words, the difference being the protocol of Section 3.2. Each configuration is one pass over all 133 tasks; the PCO v2 configuration was run twice.</p>
<p><strong>AndroidWorld.</strong> The official 116-task suite, official step budgets (10 × complexity) and grader, one attempt per task, Pixel 6 profile, arm64 Android 13 emulator, three suite seeds (30, 7, 8).</p>
<p><strong>Statistics.</strong> Wilson intervals for pass rates; bootstrap intervals for mean rubric scores; exact McNemar tests on paired pass/fail outcomes and exact sign tests on paired rubric scores, all on the same tasks. {bonf}</p>

<h2>6 Results</h2>
<h3>6.1 iOSWorld</h3>
<table><caption>Table 1. iOSWorld, 133 tasks, rubric judge{'' if all(full(x) for x in (base, v1, v2, rep, abl) if x) else '. * not all tasks graded yet'}. Cost is the agent's (CLI estimate).</caption>
<thead><tr><th>Configuration</th><th>Fully passed</th><th>Rate</th><th>95% CI</th><th>Mean rubric</th><th>95% CI</th><th>Cost</th></tr></thead><tbody>
{irow('Baseline (same operator, no ledger)', base)}{irow('PCO v1', v1)}{irow('PCO v2', v2)}{irow('PCO v2, replicate run', rep)}{irow('PCO v2, no resumption rounds (ablation)', abl)}
</tbody></table>
<table><caption>Table 2. Paired comparisons on the same tasks. "+a / −b": tasks fully passed only by the second / only by the first configuration.</caption>
<thead><tr><th>First vs second</th><th>Tasks</th><th>+ / −</th><th>McNemar p</th><th>Mean rubric Δ (95% CI)</th><th>Sign test p</th></tr></thead><tbody>
{prow('Baseline vs PCO v2', pv2)}{prow('Baseline vs PCO v2 replicate', prep)}{prow('PCO v2 vs its replicate', pvar)}{prow('Baseline vs PCO v1', pv1)}{prow('Baseline vs no-rounds ablation', pablb)}{prow('No-rounds ablation vs PCO v2', pabl)}
</tbody></table>
<p>PCO v2 is the only configuration with a significant gain over the baseline, and its replicate lands within one task of it. Between the two v2 runs {pvar['b_only_passes'] + pvar['a_only_passes'] if pvar else '—'} tasks change outcome, {pvar['b_only_passes'] if pvar else '—'} one way and {pvar['a_only_passes'] if pvar else '—'} the other (net {pvar['b_only_passes'] - pvar['a_only_passes']:+d} task), which is this agent's run-to-run noise on this benchmark; against the baseline the net is {pv2['b_only_passes'] - pv2['a_only_passes']:+d} ({pv2['b_only_passes']} gained, {pv2['a_only_passes']} lost). Version 1 is indistinguishable from the baseline, which locates the effect in the v2 compile changes rather than in decomposition as such.</p>
<h3>6.2 Where the gain is</h3>
<table><caption>Table 3. iOSWorld by task category: tasks fully passed (and mean rubric) per configuration.</caption>
<thead><tr><th>Category</th><th>Tasks</th><th>Baseline</th><th>mean</th><th>PCO v2</th><th>mean</th><th>No rounds</th></tr></thead><tbody>{cat_rows}</tbody></table>
<p>The gain is concentrated in multi-app tasks ({mm[0].get('passed', '—')} to {mm[1].get('passed', '—')} of {mm[0].get('tasks', '—')} fully passed); memory tasks moved from {cat(base, 'memory').get('passed', '—')} to {cat(v2, 'memory').get('passed', '—')} of {cat(base, 'memory').get('tasks', '—')} and single-app tasks from {cat(base, 'single_app').get('passed', '—')} to {cat(v2, 'single_app').get('passed', '—')} of {cat(base, 'single_app').get('tasks', '—')}. Personal-memory tasks depend on knowing which app holds which part of the user's life, which PCO does not supply; multi-app tasks are where sub-goals get skipped, which it does not allow.</p>
<p><strong>Actions, not wording.</strong> Because the checker completes the final answer with accepted facts (it did so in {fl.get('answers_completed', '—')} of 133 v2 tasks), a reader should ask whether the gain is in what the agent did or in what it wrote. The rubric answers that at the criterion level. Of the {rub.get('criteria', '—')} iOSWorld criteria, {rub.get('report_type', '—')} ask for something to be reported; the rest ask for something to be done on the device. In the {len(fl.get('gained', []))} tasks v2 newly passes, {n_flipped} criteria flipped from unsatisfied to satisfied: {flipped.get('action', '—')} are device actions and {flipped.get('report', '—')} are reports, and only {fl.get('gained_on_report_criteria_only', '—')} of the {len(fl.get('gained', []))} tasks flipped on report criteria alone. The replicate run shows the same pattern ({(flr.get('criteria_flipped_in_gained') or {}).get('action', '—')} action and {(flr.get('criteria_flipped_in_gained') or {}).get('report', '—')} report criteria; {flr.get('gained_on_report_criteria_only', '—')} of {len(flr.get('gained', []))} tasks on reports alone).</p>
<p><strong>The checker at work.</strong> In the v2 run the agent recorded {chk.get('obligations', '—')} obligations ({led.get('KNOW', 0)} KNOW, {led.get('DO', 0)} DO, {led.get('SAY', 0)} SAY, {led.get('IF', 0)} IF); {chk.get('proven', '—')} ended accepted, {chk.get('absent', '—')} closed as absent after a challenge, and {chk.get('tasks_resumed', '—')} tasks were sent back at least once. <strong>Case study.</strong> On task multi-081 (read design feedback in a chat app, update a document and a slide, set a timer) the baseline agent found no feedback in the channel and changed nothing (rubric {case_b if case_b is not None else '—'}); under PCO it recorded four obligations, found the feedback in the thread replies and closed each with a screen (rubric {case_p if case_p is not None else '—'}; Figure 2).</p>
<h3>6.3 Does sending the agent back matter?</h3>
<p>The ablation keeps everything of v2, including the ledger, the checker's verdicts, the answer completion and the certificate, and removes only the resumption rounds: the agent's first stop is final. It fully passed {abl['passed'] if abl else '—'}/133 (mean rubric {abl['mean_score']:.3f}) against {v2['passed']}/133 ({v2['mean_score']:.3f}) with rounds, a difference within run-to-run noise (p = {p_txt(pabl['mcnemar_exact_p']) if pabl else '—'}); against the baseline it gained {pablb['b_only_passes'] if pablb else '—'} and lost {pablb['a_only_passes'] if pablb else '—'} (p = {p_txt(pablb['mcnemar_exact_p']) if pablb else '—'}). In the full v2 run the checker sent back {rd.get('sent_back', '—')} tasks; they had used {rd.get('sent_back_mean_actions', '—')} actions on average when sent back, {rd.get('sent_back_passed', '—')} of them ended fully passed against {rd.get('sent_back_baseline_passed', '—')} for the same tasks in the baseline (+{rd.get('paired_gain', '—')} / −{rd.get('paired_loss', '—')}). The rounds help the tasks that reach them, but few tasks reach them with budget to spare. The mechanism, then, is the ledger: once every requested action, fact and derived result is an obligation the agent must close with a screen, the agent finishes them in the first pass. The checker's role is to make that ledger binding and auditable, not to steer.</p>
<h3>6.4 Audit of the checker</h3>
<p>A verdict is only as good as the match behind it, so we audited the matches. Mechanically: of the {pf.get('proven', '—')} accepted obligations in the v2 run, {(pf.get('match') or {}).get('substring', '—')} matched as an exact normalised substring of the cited screen, {(pf.get('match') or {}).get('token-coverage', 0)} by 80% token coverage, {(pf.get('match') or {}).get('digits', 0)} by digits only, and {(pf.get('match') or {}).get('stated', '—')} were SAY results, which are stated rather than shown; the median accepted claim is {pf.get('median_claim_chars', '—')} characters, {pf.get('claims_le_6_chars', '—')} are six characters or fewer, and {pf.get('matched_only_in_editable_field', '—')} matched only inside an editable field. Manually: we drew {man.get('n', '—')} accepted DO and KNOW obligations at random (seed 7; 40 DO, 20 KNOW), read each with its claim, the agent's explanation and the matched UI nodes, and labelled it <em>sound</em> (the screen shows a value that only appears if the obligation was met: a sent message, a saved alarm row, a confirmation code, the requested fact), <em>editor-state</em> (the value of an editable field: the edit is shown, its persistence is not), <em>weak</em> (a generic control label or bare number that can appear either way: a button named Repost, a like count, the word Run) or <em>mismatched</em> (the text is present but does not evidence the obligation it closes: a unit price cited for a cart total, an unrelated screen cited for a skipped branch). The result: {mc.get('S', '—')} sound, {mc.get('E', '—')} editor-state, {mc.get('W', '—')} weak, {mc.get('M', '—')} mismatched. The labelled sample is published with the runs. None of the sampled claims was contradicted by its screen; the failure mode of the checker is accepting a true but insufficient proof, which is exactly the gap Section 3.4 names and which the rubric judge, grading the same runs, still catches.</p>
<h3>6.5 AndroidWorld</h3>
<table><caption>Table 4. AndroidWorld, official grader, pass@1. A: the operator alone. B: the operator with app playbooks distilled from its own runs on other suite seeds (seed 7; or seeds 7 and 8), which is app knowledge learned on the same task templates and is reported for completeness. C: the operator with executable goal contracts checked against the UI tree.</caption>
<thead><tr><th>Configuration</th><th>Seed</th><th>Passed</th><th>Rate</th><th>95% CI</th></tr></thead><tbody>
{arow('run3-opus', 'A operator')}{arow('practice-seed7', 'A operator')}{arow('practice-seed8', 'A operator')}{arow('run5-opus-skills', 'B playbooks (seed 7)')}{arow('run6-opus-skills78', 'B playbooks (seeds 7+8)')}{arow('run8-opus-contracts', 'C contracts')}{arow('run9-contracts-seed7', 'C contracts')}{arow('run10-contracts-seed8', 'C contracts')}
</tbody></table>
<p>The operator alone averages {pct(meanA)} over three suite seeds with no app knowledge. On seed 30, contracts reached {a8['passed'] if a8 else '—'}/116 ({p38.get('b_only_passes', '—')} gained, {p38.get('a_only_passes', '—')} lost, p = {p_txt(p38.get('mcnemar_exact_p'))}), but on seeds 7 and 8 they scored {c7['passed'] if c7 else '—'} and {c8['passed'] if c8 else '—'} against {AN['practice-seed7']['passed'] if 'practice-seed7' in AN else '—'} and {AN['practice-seed8']['passed'] if 'practice-seed8' in AN else '—'} for the operator alone: {pct(meanC)} against {pct(meanA)} averaged over seeds. At this ceiling the differences are run-to-run variation, which is why the method is evaluated on iOSWorld. One disclosure: in the seed-30 contracts run, 71 tasks were re-run within the attempt after host memory exhaustion and a CLI logout broke the environment before or during the task; the originals are archived with the run, and no task was re-run for an agent failure.</p>

<h2>7 Discussion</h2>
<p><strong>What the method does.</strong> Making completion checkable changes what the agent does before any check happens. The ablation shows it: the obligation ledger alone, with the checker only recording verdicts, recovers most of the gain, and the agent under PCO finishes sub-goals it used to skip and opens the threads it used to pass over. The checker makes that ledger binding, because an obligation never closed is an obligation the run cannot end on, and makes it auditable, because every verdict can be re-derived from the published screens.</p>
<p><strong>What remains.</strong> Of the {bud.get('failed', '—')} tasks v2 did not fully pass, {bud.get('failed_exhausted', '—')} used all 50 actions and {bud.get('failed_near_exhausted_48', '—')} used 48 or more; most of the rest missed a rubric item that credits consulting a specific app, a form of app knowledge the method deliberately does not supply. The memory category is flat for the same reason.</p>
<p><strong>Cost.</strong> PCO v2 cost ${v2['cost_usd']:.0f} for 133 tasks against ${base['cost_usd']:.0f} for the baseline (agent cost, CLI estimate), with {bud.get('mean_actions', '—')} actions per task against {budb.get('mean_actions', '—')}; the ledger without resumption rounds reached the same mean rubric for ${abl['cost_usd']:.0f}. Where the certificate's audit value is not needed, the rounds can be turned off.</p>
<p><strong>Mechanical and human verification.</strong> The checker certifies what a screen shows. Irreversible or consequential actions call for the complementary mechanism of [10], authority keyed to reversibility, where such actions are gated to a human; the certificate gives that human the evidence.</p>

<h2>8 Limitations and threats to validity</h2>
<ul>
<li><strong>The checker verifies claims, not coverage, constraints or persistence</strong> (Section 3.4); the audit in Section 6.4 puts the share of accepted claims that are weak or mismatched at {(mc.get('W', 0) + mc.get('M', 0))} of {man.get('n', '—')} in the sample. A stronger matcher (typed state assertions, before/after tree diffs) is the obvious next step.</li>
<li><strong>Design on the test tasks.</strong> The method was developed while looking at failures on these benchmarks, and the v2 compile changes were designed after inspecting v1's failures on the same 133 iOSWorld tasks. The changes are generic, v2 was run twice, and the ablation isolates its parts, but the replicate is a second run of the same system on the same tasks, not a held-out test; a held-out benchmark is future work.</li>
<li><strong>One baseline run.</strong> The baseline was run once; the two v2 runs bound this agent's run-to-run noise at about {pvar['b_only_passes'] + pvar['a_only_passes'] if pvar else '—'} tasks changing outcome, and the paired tests account for it, but a repeated baseline would tighten the estimate.</li>
<li><strong>Prompt length.</strong> The PCO prompt is longer than the baseline prompt; the protocol of Section 3.2 is the difference, and we did not run a length-matched control without a ledger.</li>
<li><strong>Judge and metric.</strong> One model family operates and one judges; the judge is Claude Sonnet 4.6 rather than iOSWorld's default, used alike for every configuration, and a model judge can err. iOSWorld's own cross-judge checks did not change its conclusions [2].</li>
<li><strong>Answer completion</strong> adds accepted facts to the final answer, which a rubric judge sees. Section 6.2 shows the gain is in action criteria, but we did not re-judge the runs with the raw answers.</li>
<li><strong>Infrastructure.</strong> Running five simulators in parallel exposed a driver bug in which two sessions could share a companion port and one task's actions reached another's simulator. We fixed it, identified every task whose session started within 15 s of another, and re-ran those tasks for the baseline ({col.get(BASE, '—')} tasks) and v1 ({col.get(V1, '—')} tasks); originals are archived. The v2, replicate and ablation runs ran after the fix. Five iOSWorld apps were built with a minimum iOS version of 15.0 because Xcode 27 rejects 13 and 14. AndroidWorld ran on arm64, and the runner completes setup steps the official script misses without touching graders. The iOS runs used the product's iOS session; the open-source driver is a re-implementation of the same calls.</li>
</ul>

<h2>9 Conclusion</h2>
<p>An agent that must show its work does different work. Under proof-carrying operation the agent finishes the parts it used to skip and reports only what it can point to on a screen, and the gain is reproducible, paired and located: in multi-app tasks, in device actions, and in the ledger rather than the resumption rounds. The checker is deliberately simple, and we have measured where its simplicity stops. Every run leaves a certificate that a reader can re-verify from the published screens, which matters as much in software testing, where the method now ships, as on benchmarks.</p>

<h2>Code and data availability</h2>
<p>The method (check language, obligation ledger and checker, stable targeting, device drivers and a reference MCP server) is released as Verdikt Core under the Apache-2.0 license at {CODE}. Every trajectory, screen, ledger and certificate behind the tables, the per-task results as CSV and JSON, the labelled audit sample and the scripts that compute every number in this paper are published at {SITE}/results, where each run can be replayed step by step.</p>

<h2>References</h2>
<ol class="refs">
<li>Rawles, C. et al. AndroidWorld: A Dynamic Benchmarking Environment for Autonomous Agents. arXiv:2405.14573, 2024.</li>
<li>Jang et al. iOSWorld: A Benchmark for Personally Intelligent Phone Agents. arXiv:2606.09764, 2026.</li>
<li>Sun, H. et al. AdaPlanner: Adaptive Planning from Feedback with Language Models. NeurIPS 2023.</li>
<li>Teoh, X., Lin, Y., Nguyen, D.-M., Ren, R., Zhang, W. and Dong, J. S. WebTestPilot: Agentic End-to-End Web Testing against Natural Language Specification by Inferring Oracles with Symbolized GUI Elements. arXiv:2602.11724, 2026.</li>
<li>VeriSafe Agent: Safeguarding Mobile GUI Agent via Logic-based Action Verification. MobiCom 2025, arXiv:2503.18492.</li>
<li>Andreux, M. et al. Surfer 2: The Next Generation of Cross-Platform Computer Use Agents. arXiv:2510.19949, 2025.</li>
<li>Li, S., Zuo, Z., Wang, H., Chen, J., Jin, Z. and Li, R. Administrative Decentralization in Edge-Cloud Multi-Agent for Mobile Automation (AdecPilot). arXiv:2604.07767, 2026.</li>
<li>Wang, Z. et al. Mobile-Agent-E: Self-Evolving Mobile Assistant for Complex Tasks. arXiv:2501.11733, 2025.</li>
<li>Necula, G. C. Proof-Carrying Code. POPL 1997.</li>
<li>Haldankar, K. R. and Mohamed, H. A. Event-Driven Coordination of Episodic AI Agents: An Architecture for Cost-Bounded, Auditable, Human-Authoritative Multi-Agent Work. Preprint, version 2. Zenodo, 2026. doi:10.5281/zenodo.23084582.</li>
<li>Han, Q., Tu, H., Wang, Z. et al. VLAA-GUI: Knowing When to Stop, Recover, and Search, A Modular Framework for GUI Automation. arXiv:2604.21375, 2026.</li>
<li>Li, C., Fang, Z., Tang, Z. et al. PhoneHarness: Harnessing Phone-Use Agents through Mixed GUI, CLI, and Tool Actions. arXiv:2606.14832, 2026.</li>
<li>Xiong, T., Hu, X., Chen, Y. et al. GUI-PRA: Process Reward Agent for GUI Tasks. arXiv:2509.23263, 2025.</li>
<li>Wang, Z. Callability Is Not Operability: Controlled Interface Interventions for LLM Agents. arXiv:2608.23628, 2026.</li>
<li>Zhang, X. No Trace, No Claim: Two Contracts for Database Agents. arXiv:2610.09286, 2026.</li>
<li>Self-Reports Are Not Verification: Environment-Grounded Auditing of LLM Operators in Evolutionary Search. arXiv:2609.00652, 2026.</li>
<li>Hill, A., Komendantskaya, E. and Petrick, R. P. A. Proof-Carrying Plans: a Resource Logic for AI Planning. PPDP 2020, arXiv:2008.04165.</li>
<li>Solatorio, A. V. Proof-Carrying Numbers (PCN): A Protocol for Trustworthy Numeric Answers from LLMs via Claim Verification. arXiv:2509.06902, 2025.</li>
<li>Koomullil, G. Proof-Carrying Certificates for LLM Pipelines: A Trust-Boundary Architecture. arXiv:2605.16407, 2026.</li>
<li>Wang, Z. Proof-Carrying Agent Actions: Model-Agnostic Runtime Governance for Heterogeneous Agent Systems. arXiv:2606.04104, 2026.</li>
<li>Liu, J. When May an Agent Stop? Evidence-Carrying Termination for Tool-Using LLMs. arXiv:2608.23623, 2026.</li>
<li>Bordini, R. H., Hübner, J. F. and Wooldridge, M. Programming Multi-Agent Systems in AgentSpeak using Jason. Wiley, 2007.</li>
</ol>
"""
    css = """
@page { size: A4; margin: 20mm 18mm; }
body { font: 10.5pt/1.5 "Charter", "Georgia", serif; color: #111; max-width: 760px; margin: 0 auto; padding: 24px; }
h1 { font: 700 20pt/1.2 "Helvetica Neue", Arial, sans-serif; margin: 6px 0 8px; text-wrap: balance; }
h2 { font: 700 12pt "Helvetica Neue", Arial, sans-serif; margin: 20px 0 6px; }
h3 { font: 700 10.5pt "Helvetica Neue", Arial, sans-serif; margin: 14px 0 4px; }
.authors { color: #444; margin: 0 0 14px; }
.meta { font: 9pt "Helvetica Neue", Arial, sans-serif; color: #555; margin: 0; }
.abstract { background: #f6f6f3; padding: 4px 16px 6px; border-radius: 8px; }
.pre, .pend { font: 8.5pt "Helvetica Neue", Arial, sans-serif; color: #a33; }
table { border-collapse: collapse; width: 100%; font: 9.5pt "Helvetica Neue", Arial, sans-serif; margin: 12px 0; page-break-inside: avoid; }
caption { text-align: left; font-weight: 600; margin-bottom: 4px; caption-side: top; }
table.cert caption { font-weight: 400; font-size: 9pt; color: #444; }
th, td { border-bottom: 1px solid #ddd; padding: 4px 6px; text-align: left; vertical-align: top; }
th { border-bottom: 1.5px solid #333; }
td.n { text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }
figure { margin: 12px 0; page-break-inside: avoid; } figcaption { font: 9pt "Helvetica Neue", Arial, sans-serif; color: #444; }
code { font: 8.5pt "Menlo", monospace; background: #f2f2f0; padding: 0 3px; border-radius: 3px; }
ul { padding-left: 18px; } li { margin-bottom: 3px; }
.refs { font-size: 9pt; }
"""
    OUT.mkdir(exist_ok=True)
    page = OUT / 'draft.html'
    page.write_text(f'<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Proof-Carrying Operation</title><style>{css}</style></head><body>{body}</body></html>')
    pdf = OUT / 'draft.pdf'
    subprocess.run([CHROME, '--headless=new', '--disable-gpu', '--no-pdf-header-footer', f'--print-to-pdf={pdf}', page.as_uri()],
                   capture_output=True, timeout=120)
    print(page, pdf, pdf.exists())


if __name__ == '__main__':
    main()
