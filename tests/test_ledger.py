"""The proof-carrying operation checker: claims are proven against the cited screen's UI tree."""
import json
from pathlib import Path

from proofop import ledger as pco


def _run(tmp_path: Path, events: list[dict], screens: dict[int, list[str]]) -> Path:
    run = tmp_path / 'runs' / 'r'
    (run / 'screens').mkdir(parents=True)
    for frame, labels in screens.items():
        (run / 'screens' / f'{frame:04d}.tree.json').write_text(json.dumps([{'AXLabel': x} for x in labels]))
    (run / 'progress.json').write_text(json.dumps(events))
    return tmp_path


def ev(c, status, actual=None, frame=None, explanation=None):
    return {'criterion': c, 'status': status, 'actual': actual, 'evidence_frame': frame, 'explanation': explanation}


def test_a_claim_the_screen_shows_is_proven_and_one_it_does_not_is_rejected(tmp_path):
    task = _run(tmp_path, [ev('KNOW: raise', 'pass', '$18M', 3), ev('KNOW: lead investor', 'pass', 'Sequoia', 3)],
                {3: ['Kindling Ventures raised $18M']})
    verdicts = {o['obligation']: o['verdict'] for o in pco.verify(task)['obligations']}
    assert verdicts == {'KNOW: raise': 'proven', 'KNOW: lead investor': 'unproven'}


def test_open_obligations_and_absence_claims_are_challenged_once(tmp_path):
    task = _run(tmp_path, [ev('DO: set alarm', 'running'), ev('KNOW: feedback', 'fail', explanation='not found')], {})
    result = pco.verify(task)
    msg = pco.challenge(result, set())
    assert 'OPEN: DO: set alarm' in msg and 'ABSENCE CHALLENGED: KNOW: feedback' in msg
    assert 'ABSENCE CHALLENGED' not in (pco.challenge(result, {'KNOW: feedback'}) or '')


def test_a_discharged_ledger_needs_no_challenge_and_completes_the_answer(tmp_path):
    task = _run(tmp_path, [ev('KNOW: company', 'pass', 'Kindling Ventures', 1), ev('DO: react', 'pass', 'Celebrate', 1)],
                {1: ['Kindling Ventures', 'Celebrate']})
    result = pco.verify(task)
    assert pco.challenge(result, set()) is None
    assert pco.answer_with_facts('done', result) == 'company: Kindling Ventures'
    cert = pco.certificate(result, rounds=0)
    assert (cert['proven'], cert['unproven'], cert['open']) == (2, 0, 0)


def test_an_empty_ledger_is_sent_back_to_record_obligations(tmp_path):
    task = _run(tmp_path, [], {})
    assert 'no obligations' in pco.challenge(pco.verify(task), set())
