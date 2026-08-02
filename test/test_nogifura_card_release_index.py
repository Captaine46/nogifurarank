import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import nogifura_card_release_index as release_index


def _write_master(path: Path, rows):
    path.mkdir(parents=True, exist_ok=True)
    source = path / "SubUnitAvatar.json"
    source.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    return source


def test_index_records_release_and_index_dates(tmp_path):
    master = tmp_path / "master"
    _write_master(
        master,
        [
            {
                "Id": 1001,
                "Title": "[新カード]",
                "Name": "乃木坂花子",
                "Rarity": 6,
                "StartAt": "2026-07-01T17:00:00+09:00",
            },
            {"Id": 1002, "StartAt": "0001-01-01T00:00:00+09:00"},
        ],
    )
    output = tmp_path / "card_release_index.json"
    now = datetime(2026, 8, 2, 12, 0, tzinfo=ZoneInfo("Asia/Tokyo"))

    index, refreshed = release_index.ensureCardReleaseIndex(master, output, now=now)

    assert refreshed is True
    assert index["sourceField"] == "SubUnitAvatar.StartAt"
    assert index["cardCount"] == 2
    assert index["releaseDateKnownCount"] == 1
    assert index["releaseDateUnknownCount"] == 1
    assert index["newCardCount"] == 2
    assert index["cards"][0]["cardName"] == "[新カード] 乃木坂花子"
    assert index["cards"][0]["rarity"] == "LR"
    assert index["cards"][0]["releasedAt"] == "2026-07-01T17:00:00+09:00"
    assert index["cards"][0]["firstIndexedAt"] == "2026-08-02T12:00:00+09:00"
    assert index["cards"][1]["releasedAt"] is None


def test_unchanged_master_reuses_index_without_rewriting(tmp_path):
    master = tmp_path / "master"
    _write_master(
        master,
        [{"Id": 1, "StartAt": "2026-07-01T17:00:00+09:00"}],
    )
    output = tmp_path / "card_release_index.json"
    firstNow = datetime(2026, 8, 2, 12, 0, tzinfo=ZoneInfo("Asia/Tokyo"))
    secondNow = datetime(2026, 8, 3, 12, 0, tzinfo=ZoneInfo("Asia/Tokyo"))
    first, firstRefreshed = release_index.ensureCardReleaseIndex(master, output, firstNow)
    firstMtime = output.stat().st_mtime_ns

    second, secondRefreshed = release_index.ensureCardReleaseIndex(master, output, secondNow)

    assert firstRefreshed is True
    assert secondRefreshed is False
    assert second["indexedAt"] == first["indexedAt"]
    assert output.stat().st_mtime_ns == firstMtime


def test_changed_master_adds_new_card_and_preserves_first_index_date(tmp_path):
    master = tmp_path / "master"
    source = _write_master(
        master,
        [{"Id": 1, "StartAt": "2026-07-01T17:00:00+09:00"}],
    )
    output = tmp_path / "card_release_index.json"
    firstNow = datetime(2026, 8, 2, 12, 0, tzinfo=ZoneInfo("Asia/Tokyo"))
    release_index.ensureCardReleaseIndex(master, output, firstNow)
    source.write_text(
        json.dumps(
            [
                {"Id": 1, "StartAt": "2026-07-01T17:00:00+09:00"},
                {"Id": 2, "StartAt": "2026-08-03T17:00:00+09:00"},
            ]
        ),
        encoding="utf-8",
    )
    secondNow = datetime(2026, 8, 3, 12, 0, tzinfo=ZoneInfo("Asia/Tokyo"))

    index, refreshed = release_index.ensureCardReleaseIndex(master, output, secondNow)

    assert refreshed is True
    assert index["newCardCount"] == 1
    assert index["updatedCardCount"] == 0
    by_id = {row["avatarId"]: row for row in index["cards"]}
    assert by_id[1]["firstIndexedAt"] == "2026-08-02T12:00:00+09:00"
    assert by_id[2]["firstIndexedAt"] == "2026-08-03T12:00:00+09:00"
