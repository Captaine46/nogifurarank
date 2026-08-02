from pathlib import Path

import update_pvp_usage as updater


def test_build_steps_runs_index_collection_then_images():
    steps = updater.buildSteps("20260802", 2, 1, 0.8)

    assert [step[1][0] for step in steps] == [
        "nogifura_card_release_index.py",
        "nogifura_pvp_usage.py",
        "nogifura_pvp_x_cards.py",
    ]
    collector = steps[1][1]
    assert collector[collector.index("--snapshot-name") + 1] == "20260802"
    assert "--fetch-personal-ranking" in collector
    assert collector[collector.index("--workers") + 1] == "2"
    assert collector[collector.index("--personal-workers") + 1] == "1"
    assert steps[2][1][steps[2][1].index("--snapshot-dir") + 1] == str(
        Path("pvp_usage_output") / "20260802"
    )


def test_main_refuses_duplicate_collector(monkeypatch):
    monkeypatch.setattr(updater, "collectorIsRunning", lambda: True)

    result = updater.main(["20260802", "--no-open"])

    assert result == 2


def test_main_runs_all_steps_in_order(monkeypatch, tmp_path):
    calls = []

    class Result:
        returncode = 0

    monkeypatch.setattr(updater, "PROJECT_DIR", tmp_path)
    monkeypatch.setattr(updater, "collectorIsRunning", lambda: False)
    monkeypatch.setattr(
        updater.subprocess,
        "run",
        lambda command, **kwargs: calls.append(command) or Result(),
    )

    result = updater.main(["20260802", "--no-open"])

    assert result == 0
    assert [Path(command[2]).name for command in calls] == [
        "nogifura_card_release_index.py",
        "nogifura_pvp_usage.py",
        "nogifura_pvp_x_cards.py",
    ]
