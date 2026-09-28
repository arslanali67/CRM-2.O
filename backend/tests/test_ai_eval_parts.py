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
