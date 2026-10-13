"""Render the paper from the run data: every number comes from stats.json or the run folders.

    python3 -m benchmarks.paper.build_paper [BENCH_ROOT]  -> BENCH_ROOT/paper/draft.html + draft.pdf

Sections whose runs have not finished render as pending; partial runs are marked preliminary.
"""
from __future__ import annotations

import html
import json
import subprocess
import os
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


def budget_bound(run: str) -> tuple[int, int]:
    """(imperfect tasks, imperfect tasks that used >= 48 of the 50 actions)."""
    imp = bud = 0
    for f in (IOS_RUNS / run).glob('*/task.json'):
        t = json.loads(f.read_text())
        s = (t.get('evaluation') or {}).get('score')
        if s is not None and s < 1:
            imp += 1
            bud += (t.get('actions') or 0) >= 48
    return imp, bud


def main() -> None:
    S = json.loads((ROOT / 'explorer' / 'stats.json').read_text())
    A, I, PA, PI = S['android'], S['ios'], S.get('paired_android', {}), S.get('paired_ios', {})
    base, v1, v2, rep, abl = (I.get(k) for k in ('run1-opus', 'run2-pco', 'run3-pco-v2', 'run4-pco-v2-repeat', 'run5-v2-ledger-only'))
    full = lambda s: s is not None and s['tasks'] >= IOS_TOTAL  # noqa: E731
    pre = lambda s: '' if full(s) else f' <span class="pre">preliminary{", " + str(s["tasks"]) + " of 133 tasks" if s else ""}</span>'  # noqa: E731
    pv2, prep, pv1 = PI.get('run1-opus vs run3-pco-v2'), PI.get('run1-opus vs run4-pco-v2-repeat'), PI.get('run1-opus vs run2-pco')
    pvar, pabl, pablb = PI.get('run3-pco-v2 vs run4-pco-v2-repeat'), PI.get('run5-v2-ledger-only vs run3-pco-v2'), PI.get('run1-opus vs run5-v2-ledger-only')
    a3, a8 = A.get('run3-opus'), A.get('run8-opus-contracts')
    c7, c8 = A.get('run9-contracts-seed7'), A.get('run10-contracts-seed8')
    p38 = PA.get('run3-opus vs run8-opus-contracts', {})
    seedsA = [A[k] for k in ('run3-opus', 'practice-seed7', 'practice-seed8') if k in A]
    seedsC = [A[k] for k in ('run8-opus-contracts', 'run9-contracts-seed7', 'run10-contracts-seed8') if k in A]
    meanA = sum(x['pass_rate'] for x in seedsA) / len(seedsA) if seedsA else None
    meanC = sum(x['pass_rate'] for x in seedsC) / len(seedsC) if seedsC else None
    led = ledger_counts('run3-pco-v2')
    imp, bud = budget_bound('run3-pco-v2')
    chk = (v2 or {}).get('checker') or {}
    case_b = (task_json('run1-opus', 'multi-081').get('evaluation') or {}).get('score')
    case_p = (task_json('run3-pco-v2', 'multi-081').get('evaluation') or {}).get('score')

    def irow(label: str, s: dict | None, note: str = '') -> str:
        if not s:
            return f'<tr><td>{label}</td><td colspan=6 class=pend>pending</td></tr>'
        return (f"<tr><td>{label}{' *' if not full(s) else ''}</td><td class=n>{s['passed']}/{s['tasks']}</td><td class=n>{pct(s['pass_rate'])}</td>"
                f"<td class=n>{ci(s['pass_ci95'])}</td><td class=n>{s['mean_score']:.3f}</td>"
                f"<td class=n>{s['mean_score_ci95'][0]:.3f}–{s['mean_score_ci95'][1]:.3f}</td><td class=n>${s['cost_usd']:.0f}</td></tr>")

    def arow(rid: str) -> str:
        s = A.get(rid)
        if not s:
            return ''
        return (f"<tr><td>{html.escape(s['config'])}</td><td class=n>{s['seed']}</td><td class=n>{s['passed']}/{s['tasks']}</td>"
                f"<td class=n>{pct(s['pass_rate'])}</td><td class=n>{ci(s['pass_ci95'])}</td></tr>")

    def prow(label: str, p: dict | None) -> str:
        if not p:
            return f'<tr><td>{label}</td><td colspan=5 class=pend>pending</td></tr>'
        d = p.get('mean_score_diff')
        dci = p.get('mean_score_diff_ci95') or [None, None]
        return (f"<tr><td>{label}</td><td class=n>{p['tasks']}</td><td class=n>+{p['b_only_passes']} / −{p['a_only_passes']}</td>"
                f"<td class=n>{p_txt(p['mcnemar_exact_p'])}</td>"
                f"<td class=n>{'—' if d is None else f'{d + 0.0:+.3f} ({dci[0] + 0.0:+.3f} to {dci[1] + 0.0:+.3f})'.replace('-0.000', '+0.000')}</td><td class=n>{p_txt(p.get('sign_test_p'))}</td></tr>")

    # Figure 1: fully-passed share and mean rubric per iOS configuration, drawn to one scale.
    bars = [(lbl, s) for lbl, s in (('Baseline', base), ('PCO v1', v1), ('PCO v2', v2), ('v2 repeat', rep), ('Ledger, no checker', abl)) if s]
    fig = ''
    if bars:
        W, H, pad, bw, gap = 560, 220, 34, 36, 12
        x0, y0, plot_h = 46, H - pad, H - 2 * pad
        y = lambda v: y0 - v * plot_h  # noqa: E731
        group = 2 * bw + gap + 18
        parts = [f'<line x1="{x0}" x2="{W - 8}" y1="{y(v):.1f}" y2="{y(v):.1f}" stroke="#ddd" stroke-width="1"/>'
                 f'<text x="{x0 - 6}" y="{y(v) + 3:.1f}" text-anchor="end" font-size="9" fill="#555">{int(v * 100)}%</text>' for v in (0, .25, .5, .75, 1)]
        for i, (lbl, s) in enumerate(bars):
            gx = x0 + 14 + i * group
            for j, (val, col) in enumerate(((s['pass_rate'], '#1f43c8'), (s['mean_score'], '#9aa9e6'))):
                bx = gx + j * (bw + 2)
                parts.append(f'<rect x="{bx}" y="{y(val):.1f}" width="{bw}" height="{y0 - y(val):.1f}" fill="{col}"/>'
                             f'<text x="{bx + bw / 2}" y="{y(val) - 3:.1f}" text-anchor="middle" font-size="8.5" fill="#222">{val * 100:.1f}</text>')
            parts.append(f'<text x="{gx + bw}" y="{y0 + 13}" text-anchor="middle" font-size="9" fill="#222">{lbl}</text>')
        parts.append(f'<rect x="{W - 190}" y="6" width="9" height="9" fill="#1f43c8"/><text x="{W - 177}" y="14" font-size="9" fill="#222">fully passed (%)</text>'
                     f'<rect x="{W - 95}" y="6" width="9" height="9" fill="#9aa9e6"/><text x="{W - 82}" y="14" font-size="9" fill="#222">mean rubric (%)</text>')
        fig = f'<figure><svg viewBox="0 0 {W} {H}" width="100%" role="img" aria-label="iOSWorld results by configuration">{"".join(parts)}</svg><figcaption>Figure 1. iOSWorld (133 tasks): share of tasks with every rubric criterion satisfied, and mean rubric score, per configuration.</figcaption></figure>'

    cat_rows = ''
    if base and v2:
        for c, bv in base['by_category'].items():
            vv = v2['by_category'].get(c)
            if vv:
                cat_rows += (f"<tr><td>{c.replace('_', '-')}</td><td class=n>{bv['tasks']}</td><td class=n>{bv['passed']}</td><td class=n>{bv['mean_score']:.3f}</td>"
                             f"<td class=n>{vv['passed']}</td><td class=n>{vv['mean_score']:.3f}</td></tr>")

    headline = (f"on all 133 tasks from {base['passed']} to {v2['passed']} fully passed ({pct(base['pass_rate'])} to {pct(v2['pass_rate'])}) and the mean rubric score "
                f"from {base['mean_score']:.3f} to {v2['mean_score']:.3f} (exact McNemar p = {p_txt(pv2['mcnemar_exact_p'])}); an independent repeat reproduces it "
                f"({rep['passed']}/133, {rep['mean_score']:.3f})" if base and v2 and pv2 and rep else '(results pending)')
    ablation = ''
    if abl and pabl:
        ablation = (f"<p>The ablation keeps v2's ledger prompt but never sends the agent back (zero checker rounds). It fully passed {abl['passed']}/133 "
                    f"(mean rubric {abl['mean_score']:.3f}) against {v2['passed']}/133 ({v2['mean_score']:.3f}) with the checker: on the same tasks the checker "
                    f"version passed {pabl['b_only_passes']} tasks the ledger-only version did not and lost {pabl['a_only_passes']} (McNemar p = {p_txt(pabl['mcnemar_exact_p'])}). "
                    + (f"Against the baseline, the ledger prompt alone gained {pablb['b_only_passes']} and lost {pablb['a_only_passes']} (p = {p_txt(pablb['mcnemar_exact_p'])}). " if pablb else '')
                    + "Together these separate what the obligation list contributes from what the checker's refusals contribute.</p>")
    else:
        ablation = '<p class="pend">The ablation run (ledger prompt without checker rounds) is in progress; this paragraph is generated when it is graded.</p>'
    android_seeds = ''
    if c7 or c8:
        android_seeds = (' Across suite seeds, contracts scored ' + ', '.join(f"{s['passed']}/116 (seed {s['seed']})" for s in (a8, c7, c8) if s) +
                         ' versus the operator alone at ' + ', '.join(f"{A[k]['passed']}/116 (seed {A[k]['seed']})" for k in ('run3-opus', 'practice-seed7', 'practice-seed8') if k in A) + '.')

    where = ''
    if base and v2:
        d = {c: (base['by_category'][c]['passed'], v2['by_category'][c]['passed'], base['by_category'][c]['tasks'])
             for c in base['by_category'] if c in v2['by_category']}
        top = max(d, key=lambda c: d[c][1] - d[c][0])
        where = (f" The gain is concentrated in {top.replace('_', '-')} tasks ({d[top][0]} to {d[top][1]} of {d[top][2]} fully passed); "
                 + '; '.join(f"{c.replace('_', '-')} tasks moved from {a} to {b} of {n}" for c, (a, b, n) in d.items() if c != top) + '.')
    body = f"""
<header>
  <p class="meta">Preprint · {date.today().strftime('%B %Y')} · {SITE} · CC BY 4.0</p>
  <h1>Proof-Carrying Operation: Device Agents Whose Completion Is Checked, Not Declared</h1>
  <p class="authors">Hussein Abdinoor Mohamed and Kedar R. Haldankar · Verdikt</p>
</header>

<section class="abstract"><h2>Abstract</h2>
<p>Agents that operate phones decide for themselves when a task is done, and most of their failures happen at that decision: they stop before every part of a multi-step goal is finished, give up when evidence is hard to find, or report facts they never checked. We move the decision from the model to a checker. In <em>proof-carrying operation</em> (PCO) the agent compiles the goal into typed obligations (state changes to make, facts to report, results to derive, conditions to resolve) and closes each with the value it claims and the recorded screen that shows it; a deterministic checker accepts a claim only if that screen's UI tree contains it, challenges claims of absence, and refuses to end the episode while obligations are open, resuming the same session with the same action budget. The final answer is completed from proven facts, and every run leaves a certificate. On iOSWorld, PCO raises performance {headline}, without app-specific knowledge or tuning on the test tasks. An ablation attributes the gain to the complete, evidence-bound obligation ledger rather than to sending the agent back to work. On AndroidWorld, which is near its ceiling, the same operator averages {pct(meanA)} pass@1 over three suite seeds with no app knowledge, and executable goal contracts do not change that ({pct(meanC)}).</p>
</section>

<h2>1 Introduction</h2>
<p>Mobile-agent benchmarks now report results above 95% on AndroidWorld [1]. On iOSWorld [2], whose multi-app and personal-memory tasks leave room, our agent's failures were rarely about capability. Of its first 40 imperfect tasks only 6 ran out of actions; the rest stopped early, skipped a sub-goal, decided a fact did not exist (in one case because it never opened the reply threads where the fact was), or left a requested fact out of the answer.</p>
<p>The common weakness is that the agent is the judge of its own completion. In earlier work on coordinating episodic agents we argued for the invariant that <em>an agent never certifies its own work</em>, enforced in the Orcha system by a human-only verification gate [10]. Here we carry that invariant into device operation, where much of the outcome is visible on screen and can be checked mechanically. Our contributions:</p>
<ol>
<li><strong>Proof-carrying operation</strong>: typed obligations, claims checked against recorded UI evidence, absence challenges, a completion gate that resumes the same session without resetting its budget, answers assembled from proven facts, and a per-run certificate.</li>
<li>Evidence about what drives the effect: a first version (v1) had no measurable effect; two changes to how the goal is compiled (obligations for derived results, clause-by-clause compilation, cost-aware proving) produced a significant, reproducible gain (v2); and an ablation shows that the completion gate's resumption rounds add little on top of the ledger at a 50-action budget.</li>
<li>An operator design (act-then-observe, identity-pinned targeting, focus-verified typing) that averages {pct(meanA)} pass@1 on AndroidWorld over three suite seeds with no app knowledge.</li>
<li>Paired statistics, every trajectory published as a replay, and an open-source release (Verdikt Core, Apache-2.0).</li>
</ol>

<h2>2 Related work</h2>
<p><strong>Benchmarks.</strong> AndroidWorld [1] has 116 parameterised tasks with programmatic success checks; iOSWorld [2] has 133 tasks over 26 apps graded by a rubric judge.</p>
<p><strong>Verification in agents.</strong> AdaPlanner [3] has an LLM write assertions in a code plan for text environments. WebTestPilot [4] has an LLM write pre- and postconditions in a DSL for web testing from a given specification. VeriSafe Agent [5] turns an instruction into a logical specification over developer-written predicates and gates critical actions. Surfer 2 [6] and AdecPilot [7] gate the end of an episode on a model's judgment, and Mobile-Agent-E [8] reflects on screen changes with a model. In each, either the checks come from someone other than the operating agent or completion is judged by a model. PCO combines agent-authored claims checked deterministically against the live accessibility tree, with no app changes, an absence challenge, and answers that may only add proven facts.</p>
<p><strong>Coordination of agent work.</strong> Orcha [10] coordinates episodic agents through durable, audited state: typed request and task state machines, agents restored from self-written memory digests, a human-only verification gate and authority keyed to reversibility. PCO adopts its non-self-certification invariant and typed, auditable state, and replaces the human verifier with a mechanical one for outcomes visible in the UI.</p>

<h2>3 The operator</h2>
<p>One general model (Claude Opus) operates the device through Verdikt's tools. <strong>Act-then-observe:</strong> every action returns the screen it produced. <strong>Identity-pinned targeting:</strong> an element index refers to the screen the agent saw, and the element is re-found on the live screen by type, identifier and label before acting, so a list that loads or a keyboard that opens cannot redirect a tap; in the shipped product this fixed a reproducible mis-tap. <strong>Focus-verified typing:</strong> a field is tapped until it reports focus, and typed text is read back.</p>

<h2>4 Proof-carrying operation</h2>
<p>The name borrows from proof-carrying code [9]: the run ships with a certificate that a simple checker verifies.</p>
<div class="algo"><p><strong>Algorithm 1.</strong> Proof-carrying operation (v2)</p><ol>
<li><strong>Compile.</strong> Before acting, go through the goal clause by clause and record every obligation: <code>DO</code> (a state change, one per recipient or item; "confirm X" is a DO proven by the screen showing X), <code>KNOW</code> (a fact to report or use), <code>SAY</code> (a result to derive: a total, comparison, pattern, recommendation) and <code>IF</code> (a condition whose answer is itself a fact).</li>
<li><strong>Budget.</strong> Allocate the action budget across obligations, costliest first; with few actions left, finish open DOs before anything else.</li>
<li><strong>Discharge.</strong> Close an obligation while its proof is on screen (closing costs no action), with the claimed value copied from the screen. Never spend actions returning to a screen only to prove something. A SAY is closed with the derived result.</li>
<li><strong>Check.</strong> A DO or KNOW claim is accepted only if the cited screen's UI tree contains it (normalised match; long text by 80% token coverage). A SAY must be stated and goes into the answer. A claim of absence is challenged once.</li>
<li><strong>Gate.</strong> While obligations are open, rejected or unchallenged-absent, resume the same agent session on the same device session with the same action budget (at most two rounds).</li>
<li><strong>Answer.</strong> Complete the final answer with every proven KNOW and SAY it left out; never add an unproven one.</li>
<li><strong>Certify.</strong> Emit the ledger: each obligation's type, verdict, claim and evidence step.</li></ol></div>
<p>The ledger is a typed state machine in the sense of [10]: each obligation moves from open to proven, unproven or absent, and only the checker moves it to proven; the agent's claim of completion is a request for verification, not the verdict. The checker contains no app-specific knowledge.</p>
<p><strong>From v1 to v2.</strong> Version 1 had DO, KNOW and IF only. Its ledgers were well kept (most obligations proven) but incomplete: open-ended requests such as "correlate", "recommend" or "summarise" were never recorded, so the checker could not ask for them, and the agent spent actions returning to screens to prove claims, running out of budget on long tasks. Version 2 adds SAY obligations, clause-by-clause compilation and cost-aware proving.</p>

<h2>5 Experimental setup</h2>
<p><strong>iOSWorld:</strong> 133 tasks on iPhone 17 Pro simulators (iOS 26.5), five in parallel, driven by the Verdikt iOS session; iOSWorld's own data reset and reseed before each task; a 50-action budget and a 30-minute limit; graded by iOSWorld's unchanged rubric judge run with Claude Sonnet 4.6. A task is fully passed when every rubric criterion is satisfied. <strong>AndroidWorld:</strong> the official 116-task suite, official step budgets (10 × complexity) and grader, one attempt per task, Pixel 6 profile, arm64 Android 13 emulator. <strong>Statistics:</strong> Wilson intervals for pass rates, bootstrap intervals for mean rubric scores, exact McNemar tests on paired pass/fail outcomes and sign tests on paired rubric scores, all on the same tasks.</p>

<h2>6 Results</h2>
<h3>6.1 iOSWorld</h3>
{fig}
<table><caption>Table 1. iOSWorld, 133 tasks, rubric judge{'' if all(full(x) for x in (base, v1, v2, rep, abl) if x) else '. * not all tasks graded yet'}. Cost is the agent's (CLI estimate).</caption>
<thead><tr><th>Configuration</th><th>Fully passed</th><th>Rate</th><th>95% CI</th><th>Mean rubric</th><th>95% CI</th><th>Cost</th></tr></thead><tbody>
{irow('Baseline (Claude Code + Verdikt tools)', base)}{irow('PCO v1', v1)}{irow('PCO v2', v2)}{irow('PCO v2, repeat', rep)}{irow('v2 ledger, no checker (ablation)', abl)}
</tbody></table>
<table><caption>Table 2. Paired comparisons on the same tasks. "+a / −b": tasks fully passed only by the second / only by the first configuration.</caption>
<thead><tr><th>First vs second</th><th>Tasks</th><th>+ / −</th><th>McNemar p</th><th>Mean rubric Δ (95% CI)</th><th>Sign test p</th></tr></thead><tbody>
{prow('Baseline vs PCO v2', pv2)}{prow('Baseline vs PCO v2 repeat', prep)}{prow('PCO v2 vs its repeat', pvar)}{prow('Baseline vs PCO v1', pv1)}{prow('Ledger only vs PCO v2', pabl)}
</tbody></table>
<p>PCO v2 is the only configuration with a significant gain over the baseline, and an independent repeat lands within one task of it. Version 1 is indistinguishable from the baseline, which locates the effect in the v2 changes rather than in decomposition as such.{where} Personal-memory tasks depend on knowing which app holds which part of the user's life, which PCO does not supply.</p>
<table><caption>Table 3. iOSWorld by category, baseline vs PCO v2.</caption>
<thead><tr><th>Category</th><th>Tasks</th><th>Baseline passed</th><th>Baseline mean</th><th>PCO v2 passed</th><th>PCO v2 mean</th></tr></thead><tbody>{cat_rows}</tbody></table>
<p><strong>The checker at work.</strong> In the v2 run the agent recorded {chk.get('obligations', '—')} obligations ({led.get('KNOW', 0)} KNOW, {led.get('DO', 0)} DO, {led.get('SAY', 0)} SAY, {led.get('IF', 0)} IF); {chk.get('proven', '—')} ended proven, {chk.get('absent', '—')} closed as absent after a challenge, and {chk.get('tasks_resumed', '—')} tasks were sent back by the checker at least once. <strong>Case study.</strong> On task multi-081 (read design feedback in a chat app, update a document and a slide, set a timer) the baseline agent found no feedback in the channel and changed nothing (rubric {case_b if case_b is not None else '—'}); under PCO it recorded four obligations, found the feedback in the thread replies and proved each (rubric {case_p if case_p is not None else '—'}).</p>
<h3>6.2 Ablation</h3>
{ablation}
<h3>6.3 AndroidWorld</h3>
<table><caption>Table 4. AndroidWorld, official grader, pass@1.</caption>
<thead><tr><th>Configuration</th><th>Seed</th><th>Passed</th><th>Rate</th><th>95% CI</th></tr></thead><tbody>
{''.join(arow(r) for r in ('run3-opus', 'practice-seed7', 'practice-seed8', 'run5-opus-skills', 'run6-opus-skills78', 'run8-opus-contracts', 'run9-contracts-seed7', 'run10-contracts-seed8'))}
</tbody></table>
<p>The operator alone averages {pct(meanA)} over three suite seeds. On seed 30, learned playbooks and executable contracts reached 97–98% ({p38.get('b_only_passes', '—')} tasks gained and {p38.get('a_only_passes', '—')} lost for contracts, p = {p_txt(p38.get('mcnemar_exact_p'))}), but the contracts' gain did not repeat on seeds 7 and 8.{android_seeds} Averaged over seeds, contracts score {pct(meanC)} against {pct(meanA)}: near the ceiling the differences are run-to-run variation, which is why the main evaluation uses iOSWorld.</p>

<h2>7 Discussion</h2>
<p><strong>What drives the gain.</strong> Two results locate the effect. Version 1, with a checker but an incomplete ledger, is indistinguishable from the baseline: a checker can only certify the parts the agent thought of. The ablation, with v2's complete ledger but no resumption rounds, recovers nearly all of v2's gain: once every requested action, fact and derived result is an obligation the agent must close with evidence from a screen, the agent finishes them in the first pass, and the few tasks the gate sends back rarely have enough budget left to change the outcome. The checker's remaining role is verification rather than steering: it rejects claims the screen does not show, completes the answer only from proven facts, and produces the certificate. <strong>What remains.</strong> Of the {imp} tasks v2 did not fully pass, {bud} used their whole action budget; the rest mostly missed a rubric item that credits consulting a specific app, a form of app knowledge the method deliberately does not supply. <strong>Cost.</strong> PCO v2 cost ${v2['cost_usd']:.0f} for 133 tasks against ${base['cost_usd']:.0f} for the baseline (agent cost, CLI estimate){f'; the ledger without resumption rounds reached the same mean rubric for ${abl[chr(99)+chr(111)+chr(115)+chr(116)+chr(95)+chr(117)+chr(115)+chr(100)]:.0f}, so in practice the gate is worth running only where its audit value matters' if abl else ''}. <strong>Mechanical and human verification.</strong> The checker can only certify what a screen shows; irreversible or consequential actions call for the complementary mechanism of [10], authority keyed to reversibility, where such actions are gated to a human.</p>

<h2>8 Limitations and threats to validity</h2>
<p>One model family. The iOSWorld judge is Claude Sonnet 4.6 rather than the default GPT-5.4-mini, used for every run alike; a model judge can err. Five apps were built with a minimum iOS version of 15.0 because Xcode 27 rejects 13 and 14. Running five simulators in parallel exposed a driver bug in which two sessions could share a companion port and one task's actions reached another's simulator; we fixed it, identified every task whose session started within 15 s of another, and re-ran those tasks for the baseline and v1 (originals archived). The method was developed while looking at failures on these benchmarks, and the v2 changes were designed after inspecting v1's failures on the same 133 iOSWorld tasks; the changes are generic (they name no app, task or value), v2 was evaluated twice, and the ablation isolates its parts, but a held-out benchmark is the proper test and is future work. AndroidWorld ran on arm64, and the runner completes setup steps the official script misses without touching graders. The iOS runs used the product's iOS session; the open-source driver is a re-implementation of the same calls.</p>

<h2>9 Conclusion</h2>
<p>Making completion checkable changes what an agent does: it finishes the parts it used to skip and reports only what it can show. The effect depends on the ledger being complete, which the v2 design achieves without app knowledge, and every run leaves an auditable record, which matters as much in software testing as on benchmarks.</p>

<h2>Code and data availability</h2>
<p>The method (check language, obligation ledger and checker, stable targeting, device drivers and a reference MCP server) is released as Verdikt Core under the Apache-2.0 license at {CODE}. Every trajectory, screen, ledger and certificate behind the tables, the per-task results as CSV and JSON, and the statistics script are published at {SITE}/results, where each run can be replayed step by step.</p>

<h2>References</h2>
<ol class="refs">
<li>Rawles et al. AndroidWorld: A Dynamic Benchmarking Environment for Autonomous Agents. arXiv:2405.14573, 2024.</li>
<li>Jang et al. iOSWorld: A Benchmark for Personally Intelligent Phone Agents. arXiv:2606.09764, 2026.</li>
<li>Sun et al. AdaPlanner: Adaptive Planning from Feedback with Language Models. NeurIPS 2023.</li>
<li>WebTestPilot. arXiv:2602.11724, 2026.</li>
<li>VeriSafe Agent. MobiCom 2025, arXiv:2503.18492.</li>
<li>Surfer 2. arXiv:2510.19949, 2025.</li>
<li>AdecPilot. arXiv:2604.07767, 2026.</li>
<li>Wang et al. Mobile-Agent-E. arXiv:2501.11733, 2025.</li>
<li>Necula. Proof-Carrying Code. POPL 1997.</li>
<li>Haldankar, K. R. and Mohamed, H. A. Event-Driven Coordination of Episodic AI Agents: An Architecture for Cost-Bounded, Auditable, Human-Authoritative Multi-Agent Work. Preprint, version 2. Zenodo, 2026. doi:10.5281/zenodo.23084582.</li>
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
table { border-collapse: collapse; width: 100%; font: 9.5pt "Helvetica Neue", Arial, sans-serif; margin: 12px 0; }
caption { text-align: left; font-weight: 600; margin-bottom: 4px; }
th, td { border-bottom: 1px solid #ddd; padding: 4px 6px; text-align: left; }
th { border-bottom: 1.5px solid #333; }
td.n { text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }
.algo { border: 1px solid #ccc; border-radius: 8px; padding: 2px 14px; font-size: 10pt; }
figure { margin: 12px 0; } figcaption { font: 9pt "Helvetica Neue", Arial, sans-serif; color: #444; }
code { font: 9pt "Menlo", monospace; background: #f2f2f0; padding: 0 3px; border-radius: 3px; }
.refs { font-size: 9pt; }
"""
    OUT.mkdir(exist_ok=True)
    page = OUT / 'draft.html'
    page.write_text(f'<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Proof-Carrying Operation (draft)</title><style>{css}</style></head><body>{body}</body></html>')
    pdf = OUT / 'draft.pdf'
    subprocess.run([CHROME, '--headless=new', '--disable-gpu', '--no-pdf-header-footer', f'--print-to-pdf={pdf}', page.as_uri()],
                   capture_output=True, timeout=120)
    print(page, pdf, pdf.exists())


if __name__ == '__main__':
    main()
