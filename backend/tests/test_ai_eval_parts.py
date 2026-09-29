"""M16 eval split over two days (M34): each part is saved; the combined 40-item score decides."""
import json

from scripts import run_ai_eval


def fake_model(wrong_ids):
    items = {(it["subject"], it["body"]): it for it in json.loads(run_ai_eval.SET.read_text(encoding="utf-8"))}

    def analyse(subject, body, received):
        it = items[(subject, body)]
        label = "other" if it["id"] in wrong_ids and it["expected"] != "other" else it["expected"]
        return {"status": "ok", "label": label, "extracted": {}, "dropped": [], "analysed_text": body}
    return analyse


def test_parts_combine_into_one_score(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(run_ai_eval, "RESULTS", tmp_path)
    monkeypatch.setattr(run_ai_eval, "THROTTLE_SECONDS", 0)
    monkeypatch.setattr(run_ai_eval.settings, "GEMINI_API_KEY", "test-key-not-real")
    monkeypatch.setattr(run_ai_eval, "analyse_text", fake_model(wrong_ids={1, 2, 3}))
    assert run_ai_eval.main(["--part", "1"]) == 0
    out = capsys.readouterr().out
    assert "partial result only" in out and "M16 EVAL" not in out
    assert len(json.loads((tmp_path / "part1.json").read_text())["rows"]) == 20
    assert run_ai_eval.main(["--part", "2"]) == 0  # 37/40 = 92.5% >= 90%
    assert "label accuracy: 37/40" in capsys.readouterr().out


def test_combined_score_can_fail(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(run_ai_eval, "RESULTS", tmp_path)
    monkeypatch.setattr(run_ai_eval, "THROTTLE_SECONDS", 0)
    monkeypatch.setattr(run_ai_eval.settings, "GEMINI_API_KEY", "test-key-not-real")
    monkeypatch.setattr(run_ai_eval, "analyse_text", fake_model(wrong_ids={1, 2, 21, 22, 23}))
    run_ai_eval.main(["--part", "2"])
    assert run_ai_eval.main(["--part", "1"]) == 1  # 35/40 = 87.5%
    assert "M16 EVAL: FAIL" in capsys.readouterr().out


def test_quota_exhaustion_stops_at_once_and_saves_nothing(tmp_path, monkeypatch, capsys):
    from app.ai_analysis import AIError
    calls = []

    def limited(subject, body, received):
        calls.append(subject)
        raise AIError("rate limited by Gemini (free tier); will retry")
    monkeypatch.setattr(run_ai_eval, "RESULTS", tmp_path)
    monkeypatch.setattr(run_ai_eval.settings, "GEMINI_API_KEY", "test-key-not-real")
    monkeypatch.setattr(run_ai_eval, "analyse_text", limited)
    assert run_ai_eval.main(["--part", "1"]) == 3
    assert len(calls) == 1 and not list(tmp_path.iterdir())  # one request spent, no result file
    assert "Quota used up" in capsys.readouterr().out


def test_busy_answers_get_two_spaced_retries(tmp_path, monkeypatch):
    from app.ai_analysis import AIError
    waits, calls = [], []

    def busy(subject, body, received):
        calls.append(subject)
        raise AIError("Gemini is busy (HTTP 503); will retry")
    monkeypatch.setattr(run_ai_eval, "RESULTS", tmp_path)
    monkeypatch.setattr(run_ai_eval.settings, "GEMINI_API_KEY", "test-key-not-real")
    monkeypatch.setattr(run_ai_eval, "analyse_text", busy)
    monkeypatch.setattr(run_ai_eval, "THROTTLE_SECONDS", 0)
    monkeypatch.setattr(run_ai_eval.time, "sleep", waits.append)
    run_ai_eval.main(["--part", "1"])
    assert len(calls) == 20 * 3 and waits.count(30) == 20 and waits.count(90) == 20


def test_sample_is_one_item_per_label_and_needs_11_of_12(monkeypatch, capsys):
    seen = []
    monkeypatch.setattr(run_ai_eval, "THROTTLE_SECONDS", 0)
    monkeypatch.setattr(run_ai_eval.settings, "GEMINI_API_KEY", "test-key-not-real")
    good = fake_model(wrong_ids={1})
    monkeypatch.setattr(run_ai_eval, "analyse_text", lambda s, b, r: seen.append((s, b)) or good(s, b, r))
    assert run_ai_eval.main(["--sample"]) == 0  # 11/12
    assert len(seen) == 12
    out = capsys.readouterr().out
    assert "label accuracy: 11/12" in out and "M16 EVAL: PASS" in out
    ids = [int(l.split("#")[1].split()[0]) for l in out.splitlines() if l[:3] in ("ok ", "XX ")]
    assert ids == [1, 6, 9, 13, 16, 19, 22, 25, 28, 32, 35, 38]  # the first item of each label
    monkeypatch.setattr(run_ai_eval, "analyse_text", fake_model(wrong_ids={1, 6}))
    assert run_ai_eval.main(["--sample"]) == 1  # 10/12 fails
