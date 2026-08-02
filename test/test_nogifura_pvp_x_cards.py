import json
from pathlib import Path

from PIL import Image

import nogifura_pvp_x_cards as xcards


def test_rarity_colors_keep_game_palette():
    assert xcards.RARITY_COLORS["LR"][0] == "#F2D75C"
    assert xcards.RARITY_COLORS["UR"][0] == "#EAD8FF"
    assert xcards.RARITY_COLORS["SSR"][0] == "#FFE0CC"


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
