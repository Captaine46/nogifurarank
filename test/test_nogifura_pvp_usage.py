import json
from pathlib import Path

import nogifura_pvp_usage as pvp
import pytest


def writeJson(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def sampleDeckPayload():
    return {
        "player_deck_info": {
            "main_unit": {
                "unit": {
                    "deck_number": 5,
                        "character": {
                            "character_id": 156,
                            "unit_id": 156200,
                            "avatar_id": 156300001,
                            "unit_type": 1,
                            "total_battle_point": 50,
                    },
                }
            },
            "sub_units": [
                {
                    "position": 1,
                    "unit": {
                        "character": {
                            "character_id": 171,
                            "unit_id": 171301,
                            "avatar_id": 171301061,
                            "total_battle_point": 40,
                        }
                    },
                    "sub_unit_memoria": {"sub_unit_memoria_id": 100406},
                }
            ],
            "memorias": [{"id": 10014101}],
        }
    }


def sampleRankingPlayer():
    return {
        "player_id": "player-1",
        "name": "測試玩家",
        "ranking": 1,
        "rank": 236,
        "guild_name": "測試公會",
        "deck_total_battle_point": 123456,
        "profile_icon_id": 156300001,
    }


def writeSampleMasters(path: Path):
    writeJson(
        path / "Character.json",
        [{"Id": 156, "Name": "一ノ瀬 美空"}, {"Id": 171, "Name": "瀬戸口 心月"}],
    )
    writeJson(
        path / "Memoria.json",
        [
            {
                "Id": 10014101,
                "FullName": "通常memo A",
                "ShortName": "memo A",
                "MemoriaSlotType": 1,
            }
        ],
    )
    writeJson(
        path / "SubUnitMemoria.json",
        [{"Id": 100406, "Name": "個人memo A", "ThumbnailId": 100406}],
    )
    writeJson(
        path / "SubUnitAvatar.json",
        [
            {
                "Id": 171301061,
                "Title": "[おひとりさま天国]",
                "Name": "瀬戸口心月",
                "Rarity": 6,
                "WearableSubUnitId": 171301,
            }
        ],
    )
    writeJson(
        path / "MainUnitAvatar.json",
        [
            {
                "Id": 156300001,
                "Title": "[センター]",
                "Name": "一ノ瀬美空",
                "WearableMainUnitId": 156200,
            }
        ],
    )


def test_build_master_indexes_maps_names(tmp_path):
    writeSampleMasters(tmp_path)

    indexes = pvp.buildMasterIndexes(tmp_path)

    assert indexes["characters"][156] == "一ノ瀬 美空"
    assert indexes["memorias"][10014101]["name"] == "通常memo A"
    assert indexes["personalMemorias"][100406]["name"] == "個人memo A"
    assert indexes["avatars"][171301061]["rarity"] == "LR"
    assert indexes["avatars"][171301061]["cardName"] == "[おひとりさま天国] 瀬戸口心月"
    assert indexes["avatars"][156300001]["rarity"] == "メイン"


def test_normalize_deck_and_aggregate_usage_rates():
    masters = {
        "characters": {156: "一ノ瀬 美空", 171: "瀬戸口 心月"},
        "avatars": {
            156300001: {
                "cardName": "[センター] 一ノ瀬美空",
                "title": "[センター]",
                "memberName": "一ノ瀬美空",
                "rarity": "主角色",
                "rarityRank": None,
            },
            171301061: {
                "cardName": "[おひとりさま天国] 瀬戸口心月",
                "title": "[おひとりさま天国]",
                "memberName": "瀬戸口心月",
                "rarity": "LR",
                "rarityRank": 6,
            },
        },
        "memorias": {
            10014101: {"name": "通常memo A", "shortName": "memo A", "slotType": 1},
            10014102: {"name": "通常memo B", "shortName": "memo B", "slotType": 2},
        },
        "personalMemorias": {100406: {"name": "個人memo A", "thumbnailId": 100406}},
    }
    rankingPlayer = {
        "player_id": "player-1",
        "name": "<script>player</script>",
        "ranking": 1,
        "rank": 236,
        "guild_name": "guild",
        "deck_total_battle_point": 123456,
    }
    payload = {
        "player_deck_info": {
            "main_unit": {
                "unit": {
                    "deck_number": 5,
                    "character": {
                        "character_id": 156,
                        "unit_id": 156200,
                        "avatar_id": 156300001,
                        "unit_type": 1,
                        "total_battle_point": 50,
                    },
                }
            },
            "sub_units": [
                {
                    "position": 1,
                    "unit": {
                        "character": {
                            "character_id": 171,
                            "unit_id": 171301,
                            "avatar_id": 171301061,
                            "total_battle_point": 40,
                        }
                    },
                    "sub_unit_memoria": {
                        "sub_unit_memoria_id": 100406,
                        "level": 60,
                        "awakening_count": 4,
                    },
                }
            ],
            "memorias": [
                {"id": 10014101, "level": 40, "awakening_count": 4},
                {"id": 10014102, "level": 40, "awakening_count": 4},
            ],
        }
    }

    deck = pvp.normalizeDeck(8, rankingPlayer, "defense", payload, masters)
    stats = pvp.aggregateDecks([deck])

    assert deck["mainUnit"]["characterName"] == "一ノ瀬 美空"
    assert deck["subUnits"][0]["cardName"] == "[おひとりさま天国] 瀬戸口心月"
    assert deck["subUnits"][0]["rarity"] == "LR"
    assert deck["subUnits"][0]["personalMemoriaName"] == "個人memo A"
    cardRows = {row["avatarId"]: row for row in stats["cards"]}
    assert cardRows[171301061]["rarity"] == "LR"
    assert cardRows[171301061]["deckUsageRate"] == 100.0
    assert cardRows[171301061]["slotUsageRate"] == round(100 / 11, 2)
    memoriaRows = {row["id"]: row for row in stats["memorias"]}
    assert memoriaRows[10014101]["slotUsageRate"] == 25.0
    assert memoriaRows[10014101]["slotTypeLabel"] == "A"
    assert memoriaRows[10014102]["slotTypeLabel"] == "B"
    personalRows = {row["id"]: row for row in stats["personalMemorias"]}
    assert personalRows[100406]["slotUsageRate"] == round(100 / 11, 2)
    assert stats["mainUnitTypes"] == [
        {"unitType": 1, "name": "努力", "count": 1, "usageRate": 100.0},
        {"unitType": 2, "name": "感謝", "count": 0, "usageRate": 0.0},
        {"unitType": 3, "name": "笑顔", "count": 0, "usageRate": 0.0},
    ]


def test_aggregate_counts_each_deck_once_for_card_adoption():
    deck = {
        "subUnits": [
            {"avatarId": 111, "cardName": "LR 卡片", "rarity": "LR", "personalMemoriaId": None},
            {"avatarId": 111, "cardName": "LR 卡片", "rarity": "LR", "personalMemoriaId": None},
        ],
        "memorias": [],
    }

    stats = pvp.aggregateDecks([deck])
    row = stats["cards"][0]

    assert row["slotCount"] == 2
    assert row["deckCount"] == 1
    assert row["deckUsageRate"] == 100.0
    assert row["slotUsageRate"] == round(200 / 11, 2)


def test_cards_sort_by_deck_adoption_before_duplicate_slots():
    repeatedDeck = {
        "subUnits": [
            {"avatarId": 1, "cardName": "重複卡", "rarity": "LR"},
            {"avatarId": 1, "cardName": "重複卡", "rarity": "LR"},
        ],
        "memorias": [],
    }
    adoptedDeckOne = {
        "subUnits": [{"avatarId": 2, "cardName": "廣泛卡", "rarity": "UR"}],
        "memorias": [],
    }
    adoptedDeckTwo = {
        "subUnits": [{"avatarId": 2, "cardName": "廣泛卡", "rarity": "UR"}],
        "memorias": [],
    }

    stats = pvp.aggregateDecks([repeatedDeck, adoptedDeckOne, adoptedDeckTwo])

    assert [row["avatarId"] for row in stats["cards"]] == [2, 1]


def test_player_count_uses_world_and_player_id_as_compound_key():
    decks = [
        {
            "worldId": 1,
            "playerId": "shared-account",
            "subUnits": [],
            "memorias": [],
        },
        {
            "worldId": 2,
            "playerId": "shared-account",
            "subUnits": [],
            "memorias": [],
        },
    ]

    stats = pvp.aggregateDecks(decks)

    assert stats["deckCount"] == 2
    assert stats["playerCount"] == 2


def test_build_summary_keeps_attack_and_defense_separate():
    base = {
        "subUnits": [],
        "memorias": [],
    }
    index = {
        "channels": [
            {
                "worldId": 1,
                "players": [
                    {"decks": {"attack": {**base, "mode": "attack"}, "defense": {**base, "mode": "defense"}}}
                ],
            }
        ]
    }

    summary = pvp.buildSummary(index)

    assert set(summary["scopes"]["all"]) == {"attack", "defense"}
    assert summary["scopes"]["all"]["attack"]["deckCount"] == 1
    assert summary["scopes"]["ch01"]["defense"]["deckCount"] == 1


def test_build_summary_keeps_ranking_sources_separate():
    deck = {"subUnits": [], "memorias": []}
    index = {
        "channels": [
            {"worldId": 1, "players": [{"decks": {"defense": deck}}]}
        ],
        "personalRankingChannels": [
            {
                "worldId": 1,
                "players": [
                    {"decks": {"defense": deck}},
                    {"decks": {"defense": deck}},
                ],
            }
        ],
    }

    summary = pvp.buildSummary(index)

    assert summary["datasets"]["pvp"]["scopes"]["all"]["defense"]["deckCount"] == 1
    assert summary["datasets"]["personal"]["scopes"]["all"]["defense"]["deckCount"] == 2


def test_render_html_escapes_embedded_player_text():
    index = {
        "schemaVersion": 1,
        "generatedAt": "2026-07-11T12:00:00+09:00",
        "channels": [{"worldId": 1, "players": [{"name": "</script><script>alert(1)</script>", "decks": {}}]}],
    }
    summary = {
        "scopes": {
            "all": {
                "defense": pvp.aggregateDecks([]),
                "attack": pvp.aggregateDecks([]),
            }
        }
    }

    html = pvp.renderHtml(index, summary)

    assert "</script><script>alert(1)</script>" not in html
    assert "\\u003c/script\\u003e" in html
    assert "メンバー使用率" in html
    assert "メインメンバータイプ" in html
    assert "努力" in html and "感謝" in html and "笑顔" in html
    assert "装備メンバー" not in html
    assert "防衛 + 挑戦" not in html
    assert "牌組" not in html and "使用格數" not in html and "資料" not in html
    assert 'data-mode="defense"' in html
    assert 'data-mode="attack"' in html
    assert "攻撃編成" in html
    assert "挑戦編成" not in html
    assert "pvp_attack" not in html
    assert "プレイヤーIDや認証情報は表示しません" not in html
    assert "RANK お見立て会" not in html
    assert "<h1>お見立て会</h1>" in html
    assert "データ作成日（日本時間）" in html
    assert "timeZone:'Asia/Tokyo'" in html
    assert "hour:'2-digit'" not in html
    assert "minute:'2-digit'" not in html
    assert "second:'2-digit'" not in html
    assert "--green:#713080" in html
    assert "--orange:#a55393" in html
    assert "ID ${id}" not in html
    assert 'class="stats-table"' in html
    assert 'class="type-table"' in html
    assert 'class="players-table"' in html


def test_attach_images_copies_used_thumbnails_and_sets_relative_paths(tmp_path):
    source = tmp_path / "source"
    for category, itemId in (
        ("avatarthumbnails", 171301061),
        ("memoriathumbnails", 10014101),
    ):
        path = source / category / f"{itemId}_{itemId}.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"png")
    stillPath = source / "stillthumbnails" / "textures_stillthumbnails_s100406_hash_s100406.png"
    stillPath.parent.mkdir(parents=True, exist_ok=True)
    stillPath.write_bytes(b"still")
    index = {
        "channels": [
            {
                "players": [
                    {
                        "decks": {
                            "defense": {
                                "mainUnit": {},
                                "subUnits": [
                                    {"avatarId": 171301061, "personalMemoriaId": 100406}
                                ],
                                "memorias": [{"id": 10014101}],
                            }
                        }
                    }
                ]
            }
        ]
    }

    result = pvp.attachImages(index, source, tmp_path / "snapshot")

    deck = index["channels"][0]["players"][0]["decks"]["defense"]
    assert result == {"avatars": 1, "memorias": 1, "personalMemorias": 1, "missing": 0}
    assert deck["subUnits"][0]["image"] == "assets/avatars/171301061.png"
    assert deck["memorias"][0]["image"] == "assets/memorias/10014101.png"
    assert deck["subUnits"][0]["personalMemoriaImage"] == "assets/personal_memorias/100406.png"


def test_parse_channels_supports_ranges_and_rejects_invalid_values():
    assert pvp.parseChannels("1-3,5,3") == [1, 2, 3, 5]
    with pytest.raises(Exception, match="終點"):
        pvp.parseChannels("3-1")
    with pytest.raises(Exception, match="1 以上"):
        pvp.parseChannels("0")


def test_collect_snapshot_caches_raw_json_and_builds_complete_index(tmp_path):
    class FakeClient:
        def __init__(self):
            self.calls = []

        def postJson(self, endpoint, worldId, payload):
            self.calls.append((endpoint, worldId, payload))
            if endpoint == "/api/pvp/ranking":
                return {"ranking_players": [sampleRankingPlayer()]}
            if endpoint == "/api/player/detail":
                return {
                    "target_player": {
                        "profile": {"description": "profile text", "player_id": "player-1"}
                    }
                }
            return sampleDeckPayload()

    snapshotDir = tmp_path / "snapshot"
    client = FakeClient()
    errors = pvp.collectSnapshot(snapshotDir, client, [1], 20, 1)
    firstCallCount = len(client.calls)
    secondErrors = pvp.collectSnapshot(snapshotDir, client, [1], 20, 1)
    masterDir = tmp_path / "masters"
    writeSampleMasters(masterDir)
    masters = pvp.buildMasterIndexes(masterDir)
    index = pvp.buildIndex(snapshotDir, [1], 20, masters, masterDir)

    assert errors == []
    assert secondErrors == []
    assert firstCallCount == 4
    assert len(client.calls) == firstCallCount
    assert index["coverage"]["attackDecks"] == 1
    assert index["coverage"]["defenseDecks"] == 1
    assert index["channels"][0]["players"][0]["description"] == "profile text"
    assert index["channels"][0]["players"][0]["decks"]["attack"]["mainUnit"]["characterName"] == "一ノ瀬 美空"


def test_personal_ranking_reuses_pvp_decks_and_builds_separate_index(tmp_path):
    class NoCallClient:
        def postJson(self, endpoint, worldId, payload):
            raise AssertionError("cached PVP decks should be reused")

    snapshotDir = tmp_path / "snapshot"
    pvpPlayerDir = snapshotDir / "raw" / "ch01" / "players" / "player-1"
    writeJson(pvpPlayerDir / "attack.json", sampleDeckPayload())
    writeJson(pvpPlayerDir / "defense.json", sampleDeckPayload())
    rankingDir = tmp_path / "player_rank"
    rankingRow = {
        "player_id": "player-1",
        "player_name": "player",
        "player_rank": 100,
        "guild_name": "guild",
        "ranking": 1,
        "total_battle_point": 999,
    }
    writeJson(
        rankingDir / "ch01-player_rank.json",
        {"exists_ranking": True, "personal_rankings": [], "ranking_list": [rankingRow]},
    )

    errors = pvp.collectPersonalRankingSnapshot(
        snapshotDir, NoCallClient(), [1], 100, 1, rankingDir
    )
    masterDir = tmp_path / "masters"
    writeSampleMasters(masterDir)
    channels, coverage, missing = pvp.buildPersonalRankingIndex(
        snapshotDir, [1], 100, pvp.buildMasterIndexes(masterDir)
    )

    assert errors == []
    assert missing == []
    assert coverage["availableTop"] == 1
    assert coverage["attackDecks"] == coverage["defenseDecks"] == 1
    assert channels[0]["players"][0]["name"] == "player"


def test_personal_ranking_can_fetch_and_cache_ranking_api(tmp_path):
    rankingRow = {
        "player_id": "player-1",
        "player_name": "player",
        "player_rank": 100,
        "guild_name": "guild",
        "ranking": 1,
        "total_battle_point": 999,
    }

    class RankingClient:
        def __init__(self):
            self.calls = []

        def postJson(self, endpoint, worldId, payload):
            self.calls.append((endpoint, worldId, payload))
            return {"ranking_list": [rankingRow]}

    snapshotDir = tmp_path / "snapshot"
    pvpPlayerDir = snapshotDir / "raw" / "ch01" / "players" / "player-1"
    writeJson(pvpPlayerDir / "attack.json", sampleDeckPayload())
    writeJson(pvpPlayerDir / "defense.json", sampleDeckPayload())
    client = RankingClient()

    errors = pvp.collectPersonalRankingSnapshot(
        snapshotDir,
        client,
        [1],
        100,
        1,
        tmp_path / "unused",
        fetchRanking=True,
    )

    assert errors == []
    assert client.calls == [
        (
            "/api/worldgroup_ranking/player_ranking",
            1,
            {"character_id": 0, "ranking_type": 1},
        )
    ]
    cached = pvp.readJson(snapshotDir / "personal_raw" / "ch01" / "ranking.json")
    assert cached["ranking_list"][0]["player_id"] == "player-1"

    errors = pvp.collectPersonalRankingSnapshot(
        snapshotDir,
        client,
        [1],
        100,
        1,
        tmp_path / "unused",
        fetchRanking=True,
    )
    assert errors == []
    assert len(client.calls) == 1


def test_api_client_retries_then_returns_json(monkeypatch):
    class FakeResponse:
        def __init__(self, statusCode, payload):
            self.status_code = statusCode
            self.payload = payload

        def json(self):
            return self.payload

    class FakeSession:
        def __init__(self):
            self.responses = [FakeResponse(500, {"error_code": "TEMP"}), FakeResponse(200, {"ok": True})]
            self.calls = []

        def post(self, url, **kwargs):
            self.calls.append((url, kwargs))
            return self.responses.pop(0)

    monkeypatch.setattr(pvp.time, "sleep", lambda seconds: None)
    client = pvp.ApiClient("token", "4.9.8", "4.9.8_hash", retries=2, requestDelay=0)
    session = FakeSession()
    client.local.session = session

    result = client.postJson("/api/pvp/ranking", 8, {})

    assert result == {"ok": True}
    assert len(session.calls) == 2
    headers = session.calls[-1][1]["headers"]
    assert headers["Authorization"] == "das token"
    assert headers["X-GUMI-WORLDID"] == "8"


def test_refresh_access_token_coordinates_existing_auth_helpers(monkeypatch, tmp_path):
    monkeypatch.setattr(pvp.auth, "load_saved_credentials", lambda *args, **kwargs: ("secret", "device"))
    monkeypatch.setattr(pvp.auth, "select_current_file", lambda *args, **kwargs: tmp_path / "current")
    monkeypatch.setattr(pvp.auth, "load_dlc_version", lambda path: ("4.9.8_hash", "4.9.8"))
    monkeypatch.setattr(
        pvp.auth,
        "request_access_token",
        lambda *args, **kwargs: ("access", 86400),
    )

    result = pvp.refreshAccessToken(tmp_path, None, None, 30)

    assert result == ("access", "4.9.8", "4.9.8_hash", 86400)


def test_main_rebuild_only_writes_machine_and_html_outputs(tmp_path):
    masterDir = tmp_path / "masters"
    writeSampleMasters(masterDir)
    outputDir = tmp_path / "output"
    snapshotDir = outputDir / "sample"
    playerDir = snapshotDir / "raw" / "ch01" / "players" / "player-1"
    writeJson(snapshotDir / "raw" / "ch01" / "ranking.json", {"ranking_players": [sampleRankingPlayer()]})
    writeJson(playerDir / "detail.json", {"target_player": {"profile": {"description": "ok"}}})
    writeJson(playerDir / "attack.json", sampleDeckPayload())
    writeJson(playerDir / "defense.json", sampleDeckPayload())

    result = pvp.main(
        [
            "--channels",
            "1",
            "--top",
            "20",
            "--output-dir",
            str(outputDir),
            "--snapshot-name",
            "sample",
            "--masterdata-dir",
            str(masterDir),
            "--image-assets-dir",
            str(tmp_path / "missing-assets"),
            "--rebuild-only",
        ]
    )

    assert result == 0
    assert (snapshotDir / "index.json").is_file()
    assert (snapshotDir / "summary.json").is_file()
    reportHtml = (snapshotDir / "report.html").read_text(encoding="utf-8")
    assert "<h1>お見立て会</h1>" in reportHtml
    assert "RANK" not in reportHtml
    assert json.loads((outputDir / "latest.json").read_text(encoding="utf-8"))["snapshotName"] == "sample"
