import json
from pathlib import Path

from PIL import Image

import nogifura_pvp_x_cards as xcards


def test_rarity_colors_keep_game_palette():
    assert xcards.RARITY_COLORS["LR"][0] == "#F2D75C"
    assert xcards.RARITY_COLORS["UR"][0] == "#EAD8FF"
    assert xcards.RARITY_COLORS["SSR"][0] == "#FFE0CC"


def test_top_chart_places_rarity_before_member_card_and_keeps_short_bar():
    assert xcards.TOP_COLUMN_CENTERS["rarity"] < xcards.TOP_CARD_IMAGE_X
    assert xcards.TOP_CARD_IMAGE_X < xcards.TOP_CARD_TEXT_X
    assert xcards.TOP_BAR_RIGHT - xcards.TOP_BAR_LEFT == 470


def test_japan_date_omits_time():
    assert xcards._japanDate("2026-08-02T15:54:29+00:00") == "2026/08/03"


def test_select_card_rows_limits_to_top_50():
    stats = {"cards": [{"name": f"card-{i}"} for i in range(60)]}

    rows = xcards.selectCardRows(stats, 50)

    assert len(rows) == 50
    assert rows[0]["name"] == "card-0"
    assert rows[-1]["name"] == "card-49"


def test_attach_release_dates_matches_avatar_id():
    rows = [
        {"avatarId": 10, "name": "known"},
        {"avatarId": 11, "name": "unknown"},
    ]
    releases = [
        {"avatarId": 10, "releasedAt": "2026-07-01T17:00:00+09:00"}
    ]

    result = xcards.attachReleaseDates(rows, releases)

    assert result[0]["releasedAt"] == "2026-07-01T17:00:00+09:00"
    assert result[1]["releasedAt"] is None
    assert "releasedAt" not in rows[0]


def test_select_monthly_comparison_rows_includes_new_and_dropped_cards():
    current = {
        "cards": [
            {"avatarId": 1, "name": "up", "deckCount": 30, "deckUsageRate": 30.0},
            {"avatarId": 2, "name": "down", "deckCount": 10, "deckUsageRate": 10.0},
            {"avatarId": 3, "name": "new", "deckCount": 8, "deckUsageRate": 8.0},
        ]
    }
    previous = {
        "cards": [
            {"avatarId": 1, "name": "up", "deckCount": 20, "deckUsageRate": 20.0},
            {"avatarId": 2, "name": "down", "deckCount": 25, "deckUsageRate": 25.0},
            {"avatarId": 4, "name": "dropped", "deckCount": 6, "deckUsageRate": 6.0},
        ]
    }

    result = xcards.selectMonthlyComparisonRows(current, previous, 25)

    assert [row["avatarId"] for row in result["rises"]] == [1, 3]
    assert result["rises"][0]["delta"] == 10.0
    assert result["rises"][0]["countDelta"] == 10
    assert result["rises"][1]["previousRate"] is None
    assert result["rises"][1]["isNew"] is True
    assert [row["avatarId"] for row in result["falls"]] == [2, 4]
    assert result["falls"][0]["delta"] == -15.0
    assert result["falls"][0]["countDelta"] == -15
    assert result["falls"][1]["currentRate"] == 0.0
    assert result["falls"][1]["isDropped"] is True


def test_find_previous_month_snapshot_uses_latest_snapshot_in_previous_month(tmp_path):
    current = tmp_path / "20260901"
    older = tmp_path / "20260802"
    latest = tmp_path / "20260830"
    incomplete = tmp_path / "20260831"
    wrongMonth = tmp_path / "20260731"
    for path, generatedAt in (
        (current, "2026-09-01T05:00:00+09:00"),
        (older, "2026-08-02T05:00:00+09:00"),
        (latest, "2026-08-30T05:00:00+09:00"),
        (wrongMonth, "2026-07-31T05:00:00+09:00"),
    ):
        path.mkdir()
        stats = {"deckCount": 1, "cards": []}
        scope = {"defense": stats, "attack": stats}
        (path / "summary.json").write_text(
            json.dumps(
                {
                    "generatedAt": generatedAt,
                    "datasets": {
                        "pvp": {"scopes": {"all": scope}},
                        "personal": {"scopes": {"all": scope}},
                    },
                }
            ),
            encoding="utf-8",
        )
    incomplete.mkdir()
    (incomplete / "summary.json").write_text(
        json.dumps({"generatedAt": "2026-08-31T05:00:00+09:00"}),
        encoding="utf-8",
    )

    result = xcards.findPreviousMonthSnapshot(
        current, "2026-09-01T05:00:00+09:00"
    )

    assert result == latest


def test_render_x_card_writes_2000_by_2600_png(tmp_path):
    icon = tmp_path / "icon.png"
    Image.new("RGB", (80, 80), "purple").save(icon)
    rows = [
        {
            "name": "[Monopoly] 遠藤さくら",
            "rarity": "LR",
            "deckCount": 55,
            "deckUsageRate": 55.0,
            "image": "icon.png",
            "releasedAt": "2026-05-21T17:00:00+09:00",
        }
    ]
    output = tmp_path / "card.png"

    xcards.renderXCard(
        rows=rows,
        snapshotDir=tmp_path,
        outputPath=output,
        sourceTitle="お見立て会 TOP20",
        mode="defense",
        deckCount=100,
        generatedAt="2026-07-11T13:38:04+09:00",
        axisMax=60,
    )

    with Image.open(output) as image:
        assert image.size == (2000, 2600)
        assert image.format == "PNG"


def test_render_monthly_comparison_card_writes_2000_by_2600_png(tmp_path):
    output = tmp_path / "monthly.png"
    comparison = {
        "rises": [
            {
                "avatarId": 1,
                "name": "上昇カード",
                "rarity": "LR",
                "currentRate": 20.0,
                "previousRate": 10.0,
                "delta": 10.0,
                "currentCount": 20,
                "previousCount": 10,
                "countDelta": 10,
                "image": None,
                "imageSource": "current",
                "isNew": False,
                "isDropped": False,
            }
        ],
        "falls": [
            {
                "avatarId": 2,
                "name": "低下カード",
                "rarity": "UR",
                "currentRate": 5.0,
                "previousRate": 15.0,
                "delta": -10.0,
                "currentCount": 5,
                "previousCount": 15,
                "countDelta": -10,
                "image": None,
                "imageSource": "previous",
                "isNew": False,
                "isDropped": False,
            }
        ],
    }

    xcards.renderMonthlyComparisonCard(
        comparison=comparison,
        snapshotDir=tmp_path,
        previousSnapshotDir=tmp_path,
        outputPath=output,
        sourceTitle="個人ランキング TOP75",
        mode="attack",
        currentGeneratedAt="2026-09-01T05:00:00+09:00",
        previousGeneratedAt="2026-08-02T05:00:00+09:00",
    )

    with Image.open(output) as image:
        assert image.size == (2000, 2600)
        assert image.format == "PNG"


def test_select_new_focus_cards_uses_six_calendar_months_and_five_percent():
    cards = [
        {"avatarId": 1, "name": "inside", "deckUsageRate": 5.0},
        {"avatarId": 2, "name": "too-old", "deckUsageRate": 30.0},
        {"avatarId": 3, "name": "too-low", "deckUsageRate": 4.99},
        {"avatarId": 4, "name": "future", "deckUsageRate": 40.0},
    ]
    scope = {"defense": {"cards": cards}, "attack": {"cards": []}}
    summary = {
        "generatedAt": "2026-07-12T07:05:52+09:00",
        "datasets": {
            "pvp": {"scopes": {"all": scope}},
            "personal": {"scopes": {"all": scope}},
        },
    }
    avatars = [
        {"Id": 1, "StartAt": "2026-01-12T07:05:52+09:00"},
        {"Id": 2, "StartAt": "2026-01-12T07:05:51+09:00"},
        {"Id": 3, "StartAt": "2026-06-01T17:00:00+09:00"},
        {"Id": 4, "StartAt": "2026-07-13T17:00:00+09:00"},
    ]

    rows = xcards.selectNewFocusCards(summary, avatars)

    assert [row["avatarId"] for row in rows] == [1]
    assert rows[0]["rates"]["omitateDefense"] == 5.0
    assert rows[0]["rates"]["personalDefense"] == 5.0


def test_render_new_focus_card_writes_png(tmp_path):
    output = tmp_path / "focus.png"
    xcards.renderNewFocusCard(
        rows=[
            {
                "name": "[Same numbersMV] 梅澤美波",
                "rarity": "LR",
                "releasedAt": "2026-05-21T17:00:00+09:00",
                "rates": {
                    "omitateDefense": 18.88,
                    "omitateAttack": 20.38,
                    "personalDefense": 10.67,
                    "personalAttack": 11.27,
                },
            }
        ],
        snapshotDir=tmp_path,
        outputPath=output,
        generatedAt="2026-07-12T07:05:52+09:00",
    )

    with Image.open(output) as image:
        assert image.size == (2000, 1500)
        assert image.format == "PNG"


def test_main_creates_four_rank_images_and_two_focus_images(tmp_path):
    snapshot = tmp_path / "snapshot"
    snapshot.mkdir()
    card = {
        "name": "card",
        "rarity": "LR",
        "deckCount": 1,
        "deckUsageRate": 50.0,
        "image": None,
    }
    scope = {
        "defense": {"deckCount": 2, "cards": [card]},
        "attack": {"deckCount": 2, "cards": [card]},
    }
    summary = {
        "generatedAt": "2026-07-11T13:38:04+09:00",
        "datasets": {
            "pvp": {"scopes": {"all": scope}},
            "personal": {"scopes": {"all": scope}},
        },
    }
    (snapshot / "summary.json").write_text(json.dumps(summary), encoding="utf-8")
    masterdata = tmp_path / "masterdata"
    masterdata.mkdir()
    (masterdata / "SubUnitAvatar.json").write_text(
        json.dumps([{"Id": 1, "StartAt": "2026-07-01T17:00:00+09:00"}]),
        encoding="utf-8",
    )
    card["avatarId"] = 1
    output = tmp_path / "output"

    result = xcards.main(
        [
            "--snapshot-dir",
            str(snapshot),
            "--output-dir",
            str(output),
            "--masterdata-dir",
            str(masterdata),
            "--release-index",
            str(tmp_path / "card_release_index.json"),
        ]
    )

    assert result == 0
    assert len(list(output.glob("*.png"))) == 6
    assert (output / "x-new-focus-6months-5pct.png").exists()
    assert (output / "x-new-focus-12months-5pct.png").exists()


def test_main_auto_creates_four_monthly_comparison_images(tmp_path):
    current = tmp_path / "20260901"
    previous = tmp_path / "20260802"
    current.mkdir()
    previous.mkdir()

    def summary(generatedAt, rate):
        card = {
            "avatarId": 1,
            "name": "card",
            "rarity": "LR",
            "deckCount": 1,
            "deckUsageRate": rate,
            "image": None,
        }
        scope = {
            "defense": {"deckCount": 2, "cards": [card]},
            "attack": {"deckCount": 2, "cards": [card]},
        }
        return {
            "generatedAt": generatedAt,
            "datasets": {
                "pvp": {"scopes": {"all": scope}},
                "personal": {"scopes": {"all": scope}},
            },
        }

    (current / "summary.json").write_text(
        json.dumps(summary("2026-09-01T05:00:00+09:00", 50.0)), encoding="utf-8"
    )
    (previous / "summary.json").write_text(
        json.dumps(summary("2026-08-02T05:00:00+09:00", 40.0)), encoding="utf-8"
    )
    masterdata = tmp_path / "masterdata"
    masterdata.mkdir()
    (masterdata / "SubUnitAvatar.json").write_text(
        json.dumps([{"Id": 1, "StartAt": "2026-07-01T17:00:00+09:00"}]),
        encoding="utf-8",
    )
    output = tmp_path / "output"

    result = xcards.main(
        [
            "--snapshot-dir",
            str(current),
            "--output-dir",
            str(output),
            "--masterdata-dir",
            str(masterdata),
            "--release-index",
            str(tmp_path / "card_release_index.json"),
        ]
    )

    assert result == 0
    assert len(list(output.glob("*.png"))) == 10
    assert (output / "x-omitate-top20-defense-monthly-change.png").exists()
    assert (output / "x-personal-top75-attack-monthly-change.png").exists()


def test_twelve_month_focus_image_expands_for_more_rows(tmp_path):
    output = tmp_path / "focus-12months.png"
    rows = [
        {
            "name": f"card-{index}",
            "rarity": "LR",
            "releasedAt": "2026-01-01T17:00:00+09:00",
            "rates": {"omitateDefense": 5.0},
        }
        for index in range(15)
    ]

    xcards.renderNewFocusCard(
        rows=rows,
        snapshotDir=tmp_path,
        outputPath=output,
        generatedAt="2026-07-12T07:05:52+09:00",
        months=12,
    )

    with Image.open(output) as image:
        assert image.width == 2000
        assert image.height == 2494
