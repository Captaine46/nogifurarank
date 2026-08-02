"""Collect and report NogiFura PVP deck usage for every channel.

The collector refreshes a DAS access token from the existing encrypted APK
backup, saves resumable raw JSON responses, builds a card-resolved index, and
generates a local HTML report with thumbnails.  No credential or access token is
written to the snapshot.
"""

import argparse
import json
import random
import re
import shutil
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

import requests

import refresh_nogifura_auth as auth


API_BASE_URL = "https://production-app.delta.gu3.jp"
DEFAULT_MASTERDATA_DIR = Path(r"E:\APK\nogifura\masterdata_export")
DEFAULT_IMAGE_ASSETS_DIR = Path(r"E:\APK\nogifura\visual\assets")
DEFAULT_PERSONAL_RANKING_DIR = Path(r"D:\UNI\Fractal\gruop\json\player_rank")
DEFAULT_OUTPUT_DIR = Path("pvp_usage_output")
ATTACK_MODE = 3
DEFENSE_MODE = 4
MODE_NAMES = {"attack": ATTACK_MODE, "defense": DEFENSE_MODE}
DEFAULT_TIMEOUT = 45
DEFAULT_RETRIES = 3
AVATAR_RARITY_LABELS = {1: "N", 2: "R", 3: "SR", 4: "SSR", 5: "UR", 6: "LR"}
UNIT_TYPE_LABELS = {1: "努力", 2: "感謝", 3: "笑顔"}
MEMORIA_SLOT_TYPE_LABELS = {1: "A", 2: "B", 3: "C", 4: "D"}


class PvpUsageError(RuntimeError):
    """Raised when collection or local snapshot processing fails."""


def readJson(path: Path) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PvpUsageError(f"無法讀取 JSON：{path}") from exc


def writeJsonAtomic(path: Path, value: Any) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tempPath = path.with_suffix(path.suffix + ".tmp")
    try:
        tempPath.write_text(
            json.dumps(value, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        tempPath.replace(path)
    except OSError as exc:
        raise PvpUsageError(f"無法寫入 JSON：{path}") from exc


def writeTextAtomic(path: Path, text: str) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tempPath = path.with_suffix(path.suffix + ".tmp")
    try:
        tempPath.write_text(text, encoding="utf-8")
        tempPath.replace(path)
    except OSError as exc:
        raise PvpUsageError(f"無法寫入檔案：{path}") from exc


def buildMasterIndexes(masterdataDir: Path) -> Dict[str, Dict[int, Any]]:
    """Load card, character, and memoria labels used by the report."""

    masterdataDir = Path(masterdataDir)

    def loadRows(name: str) -> List[Dict[str, Any]]:
        value = readJson(masterdataDir / f"{name}.json")
        if not isinstance(value, list):
            raise PvpUsageError(f"masterdata 格式錯誤：{name}.json 根節點不是陣列")
        return value

    characters = {
        int(row["Id"]): str(row.get("Name") or f"メンバー {row['Id']}")
        for row in loadRows("Character")
        if isinstance(row, dict) and isinstance(row.get("Id"), int)
    }
    memorias = {
        int(row["Id"]): {
            "name": str(row.get("FullName") or row.get("ShortName") or f"memo {row['Id']}"),
            "shortName": str(row.get("ShortName") or row.get("FullName") or f"memo {row['Id']}"),
            "slotType": row.get("MemoriaSlotType"),
            "thumbnailId": row.get("ThumbnailId") or row.get("Id"),
        }
        for row in loadRows("Memoria")
        if isinstance(row, dict) and isinstance(row.get("Id"), int)
    }
    personalMemorias = {
        int(row["Id"]): {
            "name": str(row.get("Name") or f"個人メモリア {row['Id']}"),
            "thumbnailId": row.get("ThumbnailId") or row.get("Id"),
        }
        for row in loadRows("SubUnitMemoria")
        if isinstance(row, dict) and isinstance(row.get("Id"), int)
    }
    avatars = {}
    for row in loadRows("SubUnitAvatar"):
        if not isinstance(row, dict) or not isinstance(row.get("Id"), int):
            continue
        rarityRank = _intOrNone(row.get("Rarity"))
        title = str(row.get("Title") or "").strip()
        memberName = str(row.get("Name") or "").strip()
        avatars[int(row["Id"])] = {
            "cardName": " ".join(part for part in (title, memberName) if part),
            "title": title,
            "memberName": memberName,
            "rarity": AVATAR_RARITY_LABELS.get(rarityRank, "不明"),
            "rarityRank": rarityRank,
            "unitId": row.get("WearableSubUnitId"),
            "isMainUnit": False,
        }
    for row in loadRows("MainUnitAvatar"):
        if not isinstance(row, dict) or not isinstance(row.get("Id"), int):
            continue
        title = str(row.get("Title") or "").strip()
        memberName = str(row.get("Name") or "").strip()
        avatars[int(row["Id"])] = {
            "cardName": " ".join(part for part in (title, memberName) if part),
            "title": title,
            "memberName": memberName,
            "rarity": "メイン",
            "rarityRank": None,
            "unitId": row.get("WearableMainUnitId"),
            "isMainUnit": True,
        }
    return {
        "characters": characters,
        "avatars": avatars,
        "memorias": memorias,
        "personalMemorias": personalMemorias,
    }


def _intOrNone(value: Any) -> Optional[int]:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _characterRecord(character: Any, masters: Dict[str, Dict[int, Any]]) -> Dict[str, Any]:
    character = character if isinstance(character, dict) else {}
    characterId = _intOrNone(character.get("character_id"))
    unitId = _intOrNone(character.get("unit_id"))
    avatarId = _intOrNone(character.get("avatar_id"))
    name = masters["characters"].get(characterId, f"不明メンバー {characterId}")
    avatar = masters.get("avatars", {}).get(avatarId, {})
    return {
        "characterId": characterId,
        "characterName": name,
        "unitId": unitId,
        "avatarId": avatarId,
        "cardName": avatar.get("cardName") or name,
        "cardTitle": avatar.get("title"),
        "memberName": avatar.get("memberName") or name,
        "rarity": avatar.get("rarity") or "不明",
        "rarityRank": avatar.get("rarityRank"),
        "unitType": _intOrNone(character.get("unit_type")),
        "totalBattlePoint": _intOrNone(character.get("total_battle_point")),
        "unitLevel": _intOrNone(character.get("unit_level")),
        "starLevel": _intOrNone(character.get("star_level")),
        "breakthrough": _intOrNone(character.get("breakthrough")),
    }


def normalizeDeck(
    worldId: int,
    rankingPlayer: Dict[str, Any],
    mode: str,
    payload: Dict[str, Any],
    masters: Dict[str, Dict[int, Any]],
) -> Dict[str, Any]:
    """Reduce a large player/detail/deck response to reusable report fields."""

    if mode not in MODE_NAMES:
        raise PvpUsageError(f"未知牌組類型：{mode}")
    deckInfo = payload.get("player_deck_info")
    if not isinstance(deckInfo, dict):
        raise PvpUsageError("player/detail/deck 缺少 player_deck_info")

    mainContainer = deckInfo.get("main_unit")
    mainContainer = mainContainer if isinstance(mainContainer, dict) else {}
    mainUnitData = mainContainer.get("unit")
    mainUnitData = mainUnitData if isinstance(mainUnitData, dict) else {}
    mainUnit = _characterRecord(mainUnitData.get("character"), masters)
    mainUnit["deckNumber"] = _intOrNone(mainUnitData.get("deck_number"))

    subUnits = []
    for rawSubUnit in deckInfo.get("sub_units") or []:
        if not isinstance(rawSubUnit, dict):
            continue
        unitData = rawSubUnit.get("unit")
        unitData = unitData if isinstance(unitData, dict) else {}
        record = _characterRecord(unitData.get("character"), masters)
        record["position"] = _intOrNone(rawSubUnit.get("position"))
        rawPersonal = rawSubUnit.get("sub_unit_memoria")
        rawPersonal = rawPersonal if isinstance(rawPersonal, dict) else {}
        personalId = _intOrNone(rawPersonal.get("sub_unit_memoria_id"))
        personalMaster = masters["personalMemorias"].get(personalId, {})
        record.update(
            {
                "personalMemoriaId": personalId,
                "personalMemoriaName": personalMaster.get(
                    "name", f"不明個人メモリア {personalId}"
                )
                if personalId is not None
                else None,
                "personalMemoriaLevel": _intOrNone(rawPersonal.get("level")),
                "personalMemoriaAwakening": _intOrNone(
                    rawPersonal.get("awakening_count")
                ),
            }
        )
        subUnits.append(record)
    subUnits.sort(key=lambda row: row.get("position") or 999)

    memorias = []
    for rawMemoria in deckInfo.get("memorias") or []:
        if not isinstance(rawMemoria, dict):
            continue
        memoriaId = _intOrNone(rawMemoria.get("id"))
        master = masters["memorias"].get(memoriaId, {})
        memorias.append(
            {
                "id": memoriaId,
                "name": master.get("name", f"不明メモリア {memoriaId}"),
                "shortName": master.get("shortName", f"不明メモリア {memoriaId}"),
                "slotType": master.get("slotType"),
                "thumbnailId": master.get("thumbnailId") or memoriaId,
                "level": _intOrNone(rawMemoria.get("level")),
                "awakening": _intOrNone(rawMemoria.get("awakening_count")),
            }
        )

    return {
        "worldId": worldId,
        "mode": mode,
        "gameMode": MODE_NAMES[mode],
        "playerId": rankingPlayer.get("player_id"),
        "playerName": rankingPlayer.get("name"),
        "ranking": rankingPlayer.get("ranking"),
        "deckTotalBattlePoint": rankingPlayer.get("deck_total_battle_point"),
        "mainUnit": mainUnit,
        "subUnits": subUnits,
        "memorias": memorias,
    }


def _rate(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator * 100 / denominator, 2)


def aggregateDecks(decks: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    """Aggregate sub-unit cards, normal memoria, and personal memoria adoption."""

    deckList = list(decks)
    cardCounts: Dict[Any, Dict[str, Any]] = {}
    memoriaCounts: Dict[Any, Dict[str, Any]] = {}
    personalCounts: Dict[Any, Dict[str, Any]] = {}
    mainUnitTypeCounts = {unitType: 0 for unitType in UNIT_TYPE_LABELS}
    playerIds = set()

    for deckIndex, deck in enumerate(deckList):
        playerId = deck.get("playerId")
        if playerId is not None:
            playerIds.add(playerId)
        mainUnitType = (deck.get("mainUnit") or {}).get("unitType")
        if mainUnitType in mainUnitTypeCounts:
            mainUnitTypeCounts[mainUnitType] += 1

        for subUnit in deck.get("subUnits") or []:
            avatarId = subUnit.get("avatarId")
            if avatarId is not None:
                row = cardCounts.setdefault(
                    avatarId,
                    {
                        "avatarId": avatarId,
                        "name": subUnit.get("cardName") or subUnit.get("characterName"),
                        "title": subUnit.get("cardTitle"),
                        "memberName": subUnit.get("memberName") or subUnit.get("characterName"),
                        "rarity": subUnit.get("rarity") or "不明",
                        "rarityRank": subUnit.get("rarityRank"),
                        "image": subUnit.get("image"),
                        "slotCount": 0,
                        "deckIndexes": set(),
                    },
                )
                row["slotCount"] += 1
                row["deckIndexes"].add(deckIndex)
                if not row.get("image") and subUnit.get("image"):
                    row["image"] = subUnit["image"]

            personalId = subUnit.get("personalMemoriaId")
            if personalId is not None:
                personal = personalCounts.setdefault(
                    personalId,
                    {
                        "id": personalId,
                        "name": subUnit.get("personalMemoriaName"),
                        "slotCount": 0,
                        "deckIndexes": set(),
                        "characterNames": set(),
                        "image": subUnit.get("personalMemoriaImage"),
                    },
                )
                personal["slotCount"] += 1
                personal["deckIndexes"].add(deckIndex)
                if subUnit.get("characterName"):
                    personal["characterNames"].add(subUnit["characterName"])
                if not personal.get("image") and subUnit.get("personalMemoriaImage"):
                    personal["image"] = subUnit["personalMemoriaImage"]

        for memoria in deck.get("memorias") or []:
            memoriaId = memoria.get("id")
            if memoriaId is None:
                continue
            row = memoriaCounts.setdefault(
                memoriaId,
                {
                    "id": memoriaId,
                    "name": memoria.get("name"),
                    "shortName": memoria.get("shortName"),
                    "slotType": memoria.get("slotType"),
                    "slotTypeLabel": MEMORIA_SLOT_TYPE_LABELS.get(
                        memoria.get("slotType"), "不明"
                    ),
                    "image": memoria.get("image"),
                    "slotCount": 0,
                    "deckIndexes": set(),
                },
            )
            row["slotCount"] += 1
            row["deckIndexes"].add(deckIndex)
            if not row.get("image") and memoria.get("image"):
                row["image"] = memoria["image"]

    deckCount = len(deckList)
    cardRows = []
    for row in cardCounts.values():
        usedDeckCount = len(row.pop("deckIndexes"))
        row["deckCount"] = usedDeckCount
        row["deckUsageRate"] = _rate(usedDeckCount, deckCount)
        row["slotUsageRate"] = _rate(row["slotCount"], deckCount * 11)
        cardRows.append(row)

    memoriaRows = []
    for row in memoriaCounts.values():
        usedDeckCount = len(row.pop("deckIndexes"))
        row["deckCount"] = usedDeckCount
        row["deckUsageRate"] = _rate(usedDeckCount, deckCount)
        row["slotUsageRate"] = _rate(row["slotCount"], deckCount * 4)
        memoriaRows.append(row)

    personalRows = []
    for row in personalCounts.values():
        usedDeckCount = len(row.pop("deckIndexes"))
        row["characterNames"] = "、".join(sorted(row["characterNames"]))
        row["deckCount"] = usedDeckCount
        row["deckUsageRate"] = _rate(usedDeckCount, deckCount)
        row["slotUsageRate"] = _rate(row["slotCount"], deckCount * 11)
        personalRows.append(row)

    cardRows.sort(
        key=lambda row: (
            -row["deckCount"],
            -row["slotCount"],
            str(row.get("name") or ""),
            row["avatarId"],
        )
    )
    slotSortKey = lambda row: (
        -row["slotCount"],
        -row["deckCount"],
        str(row.get("name") or ""),
        row["id"],
    )
    memoriaRows.sort(key=slotSortKey)
    personalRows.sort(key=slotSortKey)
    mainUnitTypeRows = [
        {
            "unitType": unitType,
            "name": name,
            "count": mainUnitTypeCounts[unitType],
            "usageRate": _rate(mainUnitTypeCounts[unitType], deckCount),
        }
        for unitType, name in UNIT_TYPE_LABELS.items()
    ]
    return {
        "deckCount": deckCount,
        "playerCount": len(playerIds) if playerIds else deckCount,
        "cardSlotCapacity": deckCount * 11,
        "memoriaSlotCapacity": deckCount * 4,
        "personalMemoriaSlotCapacity": deckCount * 11,
        "cards": cardRows,
        "mainUnitTypes": mainUnitTypeRows,
        "memorias": memoriaRows,
        "personalMemorias": personalRows,
    }


def _buildDatasetScopes(channels: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """Precompute all-channel and per-channel scopes for one ranking source."""

    scopes: Dict[str, Dict[str, Any]] = {}

    def collectDecks(channels: Iterable[Dict[str, Any]], mode: str) -> List[Dict[str, Any]]:
        decks = []
        for channel in channels:
            for player in channel.get("players") or []:
                playerDecks = player.get("decks") or {}
                deck = playerDecks.get(mode)
                if isinstance(deck, dict):
                    decks.append(deck)
        return decks

    scopeChannels = [("all", channels)]
    scopeChannels.extend(
        (f"ch{int(channel['worldId']):02d}", [channel])
        for channel in channels
        if isinstance(channel, dict) and isinstance(channel.get("worldId"), int)
    )
    for scopeName, selectedChannels in scopeChannels:
        scopes[scopeName] = {
            mode: aggregateDecks(collectDecks(selectedChannels, mode))
            for mode in ("defense", "attack")
        }
    return scopes


def buildSummary(index: Dict[str, Any]) -> Dict[str, Any]:
    """Keep PVP TOP20 and personal-ranking statistics in separate datasets."""

    pvpScopes = _buildDatasetScopes(index.get("channels") or [])
    personalScopes = _buildDatasetScopes(index.get("personalRankingChannels") or [])
    return {
        "schemaVersion": 3,
        "generatedAt": index.get("generatedAt"),
        "scopes": pvpScopes,
        "datasets": {
            "pvp": {"scopes": pvpScopes},
            "personal": {"scopes": personalScopes},
        },
    }


class ApiClient:
    """Thread-local HTTP client that never serializes its DAS token."""

    def __init__(
        self,
        accessToken: str,
        appVersion: str,
        dlcVersion: str,
        timeout: int = DEFAULT_TIMEOUT,
        retries: int = DEFAULT_RETRIES,
        requestDelay: float = 0.05,
    ) -> None:
        self.accessToken = accessToken
        self.appVersion = appVersion
        self.dlcVersion = dlcVersion
        self.timeout = timeout
        self.retries = retries
        self.requestDelay = max(0.0, requestDelay)
        self.local = threading.local()

    def _session(self) -> requests.Session:
        session = getattr(self.local, "session", None)
        if session is None:
            session = requests.Session()
            self.local.session = session
        return session

    def _headers(self, worldId: int) -> Dict[str, str]:
        userAgentInfo = {
            "os_info": "Android",
            "device_model": "APK credential backup",
            "cpu_info": "arm64-v8a",
            "graphics_device_vendor": "unknown",
            "graphics_device_model": "unknown",
            "memory_size": "unknown",
        }
        return {
            "Accept": "*/*",
            "Authorization": f"das {self.accessToken}",
            "Content-Type": "application/json; charset=utf-8",
            "X-GUMI-APP-VER": self.appVersion,
            "X-GUMI-DLC-VER": self.dlcVersion,
            "X-GUMI-REQUEST-ID": uuid.uuid4().hex,
            "X-GUMI-WORLDID": str(worldId),
            "X-GUMI-DEVICE-OS": "android",
            "X-GUMI-STORE-PLATFORM": "googleplay",
            "X-GUMI-USER-AGENT": json.dumps(userAgentInfo, separators=(",", ":")),
            "User-Agent": f"DeltaUnityProject/{self.appVersion}",
        }

    def postJson(self, endpoint: str, worldId: int, payload: Dict[str, Any]) -> Dict[str, Any]:
        lastError: Optional[BaseException] = None
        for attempt in range(1, self.retries + 1):
            try:
                response = self._session().post(
                    API_BASE_URL + endpoint,
                    headers=self._headers(worldId),
                    json=payload,
                    timeout=self.timeout,
                )
                try:
                    responseData = response.json()
                except ValueError as exc:
                    raise PvpUsageError(
                        f"{endpoint} 回應不是 JSON（HTTP {response.status_code}）"
                    ) from exc
                if response.status_code != 200 or not isinstance(responseData, dict):
                    errorCode = (
                        responseData.get("error_code")
                        if isinstance(responseData, dict)
                        else None
                    )
                    detail = f"，錯誤={errorCode}" if errorCode else ""
                    error = PvpUsageError(
                        f"{endpoint} 請求失敗（HTTP {response.status_code}{detail}）"
                    )
                    if 400 <= response.status_code < 500 and response.status_code != 429:
                        raise error from None
                    raise error
                if self.requestDelay:
                    time.sleep(random.uniform(self.requestDelay, self.requestDelay * 1.35))
                return responseData
            except (requests.RequestException, PvpUsageError) as exc:
                lastError = exc
                if "HTTP 4" in str(exc) and "HTTP 429" not in str(exc):
                    break
                if attempt < self.retries:
                    time.sleep(2 ** (attempt - 1))
        raise PvpUsageError(f"{endpoint} 重試 {self.retries} 次仍失敗") from lastError


def parseChannels(value: str) -> List[int]:
    channels = set()
    for part in value.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            startText, endText = part.split("-", 1)
            start, end = int(startText), int(endText)
            if end < start:
                raise argparse.ArgumentTypeError("CH 範圍終點不可小於起點")
            channels.update(range(start, end + 1))
        else:
            channels.add(int(part))
    if not channels or min(channels) < 1:
        raise argparse.ArgumentTypeError("CH 必須是 1 以上的整數")
    return sorted(channels)


def _cachedJson(path: Path, fetcher: Callable[[], Dict[str, Any]], refresh: bool) -> Dict[str, Any]:
    if path.is_file() and not refresh:
        value = readJson(path)
        if isinstance(value, dict):
            return value
    value = fetcher()
    writeJsonAtomic(path, value)
    return value


def collectSnapshot(
    snapshotDir: Path,
    client: ApiClient,
    channels: Sequence[int],
    top: int,
    workers: int,
    refresh: bool = False,
    skipDetail: bool = False,
) -> List[str]:
    """Fetch ranking, profile, attack deck, and defense deck raw JSON."""

    rawDir = Path(snapshotDir) / "raw"
    rankingByChannel: Dict[int, List[Dict[str, Any]]] = {}
    errors = []

    for worldId in channels:
        rankingPath = rawDir / f"ch{worldId:02d}" / "ranking.json"
        try:
            ranking = _cachedJson(
                rankingPath,
                lambda worldId=worldId: client.postJson("/api/pvp/ranking", worldId, {}),
                refresh,
            )
            rankingPlayers = ranking.get("ranking_players")
            if not isinstance(rankingPlayers, list):
                raise PvpUsageError("pvp/ranking 缺少 ranking_players")
            rankingByChannel[worldId] = [
                row for row in rankingPlayers[:top] if isinstance(row, dict)
            ]
            print(f"[排名] CH{worldId:02d}：{len(rankingByChannel[worldId])} 名")
        except PvpUsageError as exc:
            errors.append(f"CH{worldId:02d} ranking：{exc}")

    tasks: List[Tuple[int, Dict[str, Any]]] = []
    for worldId, players in rankingByChannel.items():
        tasks.extend((worldId, player) for player in players)

    progressLock = threading.Lock()
    completed = 0

    def collectPlayer(worldId: int, rankingPlayer: Dict[str, Any]) -> List[str]:
        playerErrors = []
        playerId = rankingPlayer.get("player_id")
        if not isinstance(playerId, str) or not playerId:
            return [f"CH{worldId:02d} 缺少 player_id"]
        playerDir = rawDir / f"ch{worldId:02d}" / "players" / playerId
        basePayload = {"player_id": playerId, "world_id": worldId}
        requestsToMake = []
        if not skipDetail:
            requestsToMake.append(
                (
                    "detail",
                    playerDir / "detail.json",
                    "/api/player/detail",
                    basePayload,
                )
            )
        for modeName, gameMode in MODE_NAMES.items():
            requestsToMake.append(
                (
                    modeName,
                    playerDir / f"{modeName}.json",
                    "/api/player/detail/deck",
                    {**basePayload, "game_mode": gameMode},
                )
            )
        for label, path, endpoint, payload in requestsToMake:
            try:
                _cachedJson(
                    path,
                    lambda endpoint=endpoint, worldId=worldId, payload=payload: client.postJson(
                        endpoint, worldId, payload
                    ),
                    refresh,
                )
            except PvpUsageError as exc:
                playerErrors.append(
                    f"CH{worldId:02d} rank={rankingPlayer.get('ranking')} {label}：{exc}"
                )
        return playerErrors

    with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
        futureMap = {
            executor.submit(collectPlayer, worldId, player): (worldId, player)
            for worldId, player in tasks
        }
        for future in as_completed(futureMap):
            worldId, player = futureMap[future]
            try:
                errors.extend(future.result())
            except BaseException as exc:
                errors.append(
                    f"CH{worldId:02d} rank={player.get('ranking')} 未預期錯誤：{type(exc).__name__}"
                )
            with progressLock:
                completed += 1
                if completed == len(tasks) or completed % 20 == 0:
                    print(f"[牌組] 已處理 {completed}/{len(tasks)} 名玩家")
    return errors


def _personalRankingPlayer(row: Dict[str, Any]) -> Dict[str, Any]:
    """Map world-group ranking fields to the deck normalizer's PVP-shaped input."""

    return {
        "player_id": row.get("player_id"),
        "name": row.get("player_name"),
        "ranking": row.get("ranking"),
        "rank": row.get("player_rank"),
        "guild_name": row.get("guild_name"),
        "deck_total_battle_point": row.get("total_battle_point"),
        "profile_icon_id": row.get("profile_icon_id"),
    }


def collectPersonalRankingSnapshot(
    snapshotDir: Path,
    client: ApiClient,
    channels: Sequence[int],
    top: int,
    workers: int,
    rankingSourceDir: Path,
    refresh: bool = False,
    fetchRanking: bool = False,
) -> List[str]:
    """Fetch deck JSON for the locally captured personal-ranking rows.

    The endpoint has no pagination/count field and currently returns 75 rows.
    Existing PVP deck responses are reused, and every new response is cached so
    an interrupted conservative crawl can resume without duplicate requests.
    """

    snapshotDir = Path(snapshotDir)
    rawDir = snapshotDir / "personal_raw"
    pvpRawDir = snapshotDir / "raw"
    rankingByChannel: Dict[int, List[Dict[str, Any]]] = {}
    errors: List[str] = []
    for worldId in channels:
        sourcePath = Path(rankingSourceDir) / f"ch{worldId:02d}-player_rank.json"
        targetPath = rawDir / f"ch{worldId:02d}" / "ranking.json"
        try:
            if fetchRanking:
                ranking = _cachedJson(
                    targetPath,
                    lambda worldId=worldId: client.postJson(
                        "/api/worldgroup_ranking/player_ranking",
                        worldId,
                        {"character_id": 0, "ranking_type": 1},
                    ),
                    refresh,
                )
            else:
                if targetPath.is_file() and not refresh:
                    ranking = readJson(targetPath)
                else:
                    if not sourcePath.is_file():
                        raise PvpUsageError(f"{sourcePath} がありません")
                    ranking = readJson(sourcePath)
            rows = ranking.get("ranking_list") if isinstance(ranking, dict) else None
            if not isinstance(rows, list):
                raise PvpUsageError("ranking_list がありません")
            selected = [row for row in rows[:top] if isinstance(row, dict)]
            rankingByChannel[worldId] = selected
            if not targetPath.is_file():
                writeJsonAtomic(targetPath, ranking)
            print(f"[個人ランキング] CH{worldId:02d}：{len(selected)}名")
        except PvpUsageError as exc:
            errors.append(f"CH{worldId:02d} 個人ランキング：{exc}")

    tasks = [
        (worldId, row)
        for worldId, rows in rankingByChannel.items()
        for row in rows
    ]
    completed = 0
    progressLock = threading.Lock()

    def collectPlayer(worldId: int, row: Dict[str, Any]) -> List[str]:
        playerId = row.get("player_id")
        if not isinstance(playerId, str) or not playerId:
            return [f"CH{worldId:02d} rank={row.get('ranking')} player_id がありません"]
        playerDir = rawDir / f"ch{worldId:02d}" / "players" / playerId
        pvpPlayerDir = pvpRawDir / f"ch{worldId:02d}" / "players" / playerId
        playerErrors = []
        for modeName, gameMode in MODE_NAMES.items():
            targetPath = playerDir / f"{modeName}.json"
            reusablePath = pvpPlayerDir / f"{modeName}.json"
            if targetPath.is_file() and not refresh:
                continue
            if reusablePath.is_file() and not refresh:
                writeJsonAtomic(targetPath, readJson(reusablePath))
                continue
            try:
                payload = {
                    "player_id": playerId,
                    "world_id": worldId,
                    "game_mode": gameMode,
                }
                _cachedJson(
                    targetPath,
                    lambda payload=payload, worldId=worldId: client.postJson(
                        "/api/player/detail/deck", worldId, payload
                    ),
                    refresh,
                )
            except PvpUsageError as exc:
                playerErrors.append(
                    f"CH{worldId:02d} rank={row.get('ranking')} {modeName}：{exc}"
                )
        return playerErrors

    with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
        futureMap = {
            executor.submit(collectPlayer, worldId, row): (worldId, row)
            for worldId, row in tasks
        }
        for future in as_completed(futureMap):
            worldId, row = futureMap[future]
            try:
                errors.extend(future.result())
            except BaseException as exc:
                errors.append(
                    f"CH{worldId:02d} rank={row.get('ranking')}：{type(exc).__name__}"
                )
            with progressLock:
                completed += 1
                if completed == len(tasks) or completed % 20 == 0:
                    print(f"[個人ランキング編成] {completed}/{len(tasks)}名")
    return errors


def _profileFromDetail(detail: Any) -> Dict[str, Any]:
    if not isinstance(detail, dict):
        return {}
    target = detail.get("target_player")
    target = target if isinstance(target, dict) else {}
    profile = target.get("profile")
    return profile if isinstance(profile, dict) else {}


def buildIndex(
    snapshotDir: Path,
    channels: Sequence[int],
    top: int,
    masters: Dict[str, Dict[int, Any]],
    masterdataDir: Path,
) -> Dict[str, Any]:
    """Build a compact, name-resolved index from raw snapshot JSON."""

    rawDir = Path(snapshotDir) / "raw"
    channelRows = []
    missing = []
    coverage = {
        "requestedChannels": len(channels),
        "rankingChannels": 0,
        "expectedPlayers": 0,
        "players": 0,
        "details": 0,
        "attackDecks": 0,
        "defenseDecks": 0,
    }

    for worldId in channels:
        channelDir = rawDir / f"ch{worldId:02d}"
        rankingPath = channelDir / "ranking.json"
        if not rankingPath.is_file():
            missing.append(f"CH{worldId:02d}/ranking.json")
            continue
        ranking = readJson(rankingPath)
        rankingPlayers = ranking.get("ranking_players") if isinstance(ranking, dict) else None
        if not isinstance(rankingPlayers, list):
            missing.append(f"CH{worldId:02d}/ranking.json:ranking_players")
            continue
        coverage["rankingChannels"] += 1
        selectedPlayers = [row for row in rankingPlayers[:top] if isinstance(row, dict)]
        coverage["expectedPlayers"] += len(selectedPlayers)
        players = []
        for rankingPlayer in selectedPlayers:
            playerId = rankingPlayer.get("player_id")
            if not isinstance(playerId, str):
                continue
            playerDir = channelDir / "players" / playerId
            profile = {}
            detailPath = playerDir / "detail.json"
            if detailPath.is_file():
                profile = _profileFromDetail(readJson(detailPath))
                coverage["details"] += 1
            decks = {}
            for modeName in ("attack", "defense"):
                deckPath = playerDir / f"{modeName}.json"
                if not deckPath.is_file():
                    missing.append(
                        f"CH{worldId:02d}/rank{rankingPlayer.get('ranking')}/{modeName}.json"
                    )
                    continue
                try:
                    decks[modeName] = normalizeDeck(
                        worldId,
                        rankingPlayer,
                        modeName,
                        readJson(deckPath),
                        masters,
                    )
                    coverage[f"{modeName}Decks"] += 1
                except PvpUsageError as exc:
                    missing.append(
                        f"CH{worldId:02d}/rank{rankingPlayer.get('ranking')}/{modeName}: {exc}"
                    )
            players.append(
                {
                    "worldId": worldId,
                    "ranking": rankingPlayer.get("ranking"),
                    "playerId": playerId,
                    "name": rankingPlayer.get("name"),
                    "guildName": rankingPlayer.get("guild_name"),
                    "rank": rankingPlayer.get("rank"),
                    "deckTotalBattlePoint": rankingPlayer.get("deck_total_battle_point"),
                    "description": profile.get("description"),
                    "profileIconId": rankingPlayer.get("profile_icon_id"),
                    "decks": decks,
                }
            )
        coverage["players"] += len(players)
        channelRows.append({"worldId": worldId, "players": players})

    now = datetime.now().astimezone().isoformat(timespec="seconds")
    return {
        "schemaVersion": 2,
        "generatedAt": now,
        "source": {
            "apiBaseUrl": API_BASE_URL,
            "rankingEndpoint": "/api/pvp/ranking",
            "playerDetailEndpoint": "/api/player/detail",
            "playerDeckEndpoint": "/api/player/detail/deck",
            "gameModes": {"attack": ATTACK_MODE, "defense": DEFENSE_MODE},
            "masterdataDir": str(Path(masterdataDir).resolve()),
            "topPerChannel": top,
        },
        "coverage": coverage,
        "missing": missing,
        "channels": channelRows,
    }


def buildPersonalRankingIndex(
    snapshotDir: Path,
    channels: Sequence[int],
    top: int,
    masters: Dict[str, Dict[int, Any]],
) -> Tuple[List[Dict[str, Any]], Dict[str, int], List[str]]:
    """Build the wholly separate personal-ranking channel index."""

    rawDir = Path(snapshotDir) / "personal_raw"
    channelRows: List[Dict[str, Any]] = []
    missing: List[str] = []
    coverage = {
        "requestedChannels": len(channels),
        "rankingChannels": 0,
        "availableTop": 0,
        "expectedPlayers": 0,
        "players": 0,
        "attackDecks": 0,
        "defenseDecks": 0,
    }
    availableCounts = []
    for worldId in channels:
        channelDir = rawDir / f"ch{worldId:02d}"
        rankingPath = channelDir / "ranking.json"
        if not rankingPath.is_file():
            missing.append(f"個人ランキング CH{worldId:02d}/ranking.json")
            continue
        ranking = readJson(rankingPath)
        rows = ranking.get("ranking_list") if isinstance(ranking, dict) else None
        if not isinstance(rows, list):
            missing.append(f"個人ランキング CH{worldId:02d}/ranking_list")
            continue
        coverage["rankingChannels"] += 1
        selected = [row for row in rows[:top] if isinstance(row, dict)]
        availableCounts.append(len(selected))
        coverage["expectedPlayers"] += len(selected)
        players = []
        for row in selected:
            rankingPlayer = _personalRankingPlayer(row)
            playerId = rankingPlayer.get("player_id")
            if not isinstance(playerId, str) or not playerId:
                continue
            playerDir = channelDir / "players" / playerId
            decks = {}
            for modeName in ("attack", "defense"):
                path = playerDir / f"{modeName}.json"
                if not path.is_file():
                    missing.append(
                        f"個人ランキング CH{worldId:02d}/rank{row.get('ranking')}/{modeName}.json"
                    )
                    continue
                try:
                    decks[modeName] = normalizeDeck(
                        worldId, rankingPlayer, modeName, readJson(path), masters
                    )
                    coverage[f"{modeName}Decks"] += 1
                except PvpUsageError as exc:
                    missing.append(
                        f"個人ランキング CH{worldId:02d}/rank{row.get('ranking')}/{modeName}: {exc}"
                    )
            players.append(
                {
                    "worldId": worldId,
                    "ranking": row.get("ranking"),
                    "playerId": playerId,
                    "name": row.get("player_name"),
                    "guildName": row.get("guild_name"),
                    "rank": row.get("player_rank"),
                    "deckTotalBattlePoint": row.get("total_battle_point"),
                    "profileIconId": row.get("profile_icon_id"),
                    "decks": decks,
                }
            )
        coverage["players"] += len(players)
        channelRows.append({"worldId": worldId, "players": players})
    coverage["availableTop"] = min(availableCounts) if availableCounts else 0
    return channelRows, coverage, missing


def attachImages(
    index: Dict[str, Any], sourceAssetsDir: Path, snapshotDir: Path
) -> Dict[str, int]:
    """Copy used local thumbnails into the snapshot and attach relative paths."""

    sourceAssetsDir = Path(sourceAssetsDir)
    snapshotDir = Path(snapshotDir)
    specifications = {
        "avatars": (("avatarthumbnails",), "avatars"),
        "memorias": (("memoriathumbnails",), "memorias"),
        "personalMemorias": (
            ("subunitmemoriathumbnails", "stillthumbnails"),
            "personal_memorias",
        ),
    }
    sourceMaps: Dict[str, Dict[int, Path]] = {}
    imageIdPattern = re.compile(r"(?:^|_)(?:s)?(\d{6,12})(?:_|\.png$)", re.I)
    for key, (sourceCategories, _) in specifications.items():
        rows = {}
        for sourceCategory in sourceCategories:
            folder = sourceAssetsDir / sourceCategory
            if not folder.is_dir():
                continue
            for path in folder.glob("*.png"):
                match = imageIdPattern.search(path.name)
                if match:
                    rows.setdefault(int(match.group(1)), path)
        sourceMaps[key] = rows

    foundIds = {key: set() for key in specifications}
    missingIds = set()

    def attach(record: Dict[str, Any], key: str, itemId: Any, field: str) -> None:
        if not isinstance(itemId, int):
            return
        source = sourceMaps[key].get(itemId)
        if source is None:
            missingIds.add((key, itemId))
            record[field] = None
            return
        _, targetCategory = specifications[key]
        target = snapshotDir / "assets" / targetCategory / f"{itemId}.png"
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.is_file() or target.stat().st_size != source.stat().st_size:
            try:
                shutil.copy2(source, target)
            except OSError as exc:
                raise PvpUsageError(f"無法複製圖示：{source} -> {target}") from exc
        record[field] = f"assets/{targetCategory}/{itemId}.png"
        foundIds[key].add(itemId)

    for channelKey in ("channels", "personalRankingChannels"):
        for channel in index.get(channelKey) or []:
            for player in channel.get("players") or []:
                for deck in (player.get("decks") or {}).values():
                    mainUnit = deck.get("mainUnit") or {}
                    attach(mainUnit, "avatars", mainUnit.get("avatarId"), "image")
                    for subUnit in deck.get("subUnits") or []:
                        attach(subUnit, "avatars", subUnit.get("avatarId"), "image")
                        attach(
                            subUnit,
                            "personalMemorias",
                            subUnit.get("personalMemoriaId"),
                            "personalMemoriaImage",
                        )
                    for memoria in deck.get("memorias") or []:
                        attach(
                            memoria,
                            "memorias",
                            memoria.get("thumbnailId") or memoria.get("id"),
                            "image",
                        )

    return {
        "avatars": len(foundIds["avatars"]),
        "memorias": len(foundIds["memorias"]),
        "personalMemorias": len(foundIds["personalMemorias"]),
        "missing": len(missingIds),
    }


def _safeScriptJson(value: Any) -> str:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )


def renderHtml(index: Dict[str, Any], summary: Dict[str, Any]) -> str:
    """Render a dependency-free interactive report with local thumbnails."""

    template = r'''<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>お見立て会 編成採用率</title>
<style>
:root{--ink:#241a26;--muted:#756879;--paper:#f7f2f8;--card:#fffafe;--line:#e2d4e5;--green:#713080;--lime:#d8addf;--orange:#a55393;--shadow:0 16px 44px rgba(80,39,88,.12)}
*{box-sizing:border-box}body{margin:0;color:var(--ink);background:radial-gradient(circle at 85% 4%,#e8d4ec 0,transparent 30%),linear-gradient(140deg,#fbf7fc,#f1e7f3);font-family:"Yu Gothic UI","Meiryo","Segoe UI",sans-serif;min-height:100vh}
.shell{width:min(1540px,calc(100% - 32px));margin:28px auto 60px}.hero{display:grid;grid-template-columns:1.45fr .55fr;gap:22px;align-items:end;padding:30px;border:1px solid rgba(255,255,255,.85);border-radius:28px;background:rgba(255,250,254,.86);box-shadow:var(--shadow);backdrop-filter:blur(18px)}
.eyebrow{font-size:12px;letter-spacing:.22em;text-transform:uppercase;color:var(--green);font-weight:800}.hero h1{font-size:clamp(30px,5vw,66px);line-height:.97;margin:10px 0 12px;letter-spacing:-.045em}.hero p{color:var(--muted);font-size:15px;line-height:1.7;margin:0;max-width:760px}.stamp{text-align:right;font-variant-numeric:tabular-nums;color:var(--muted)}
.dataset-switch,.mode-switch{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin:18px 0}.dataset-button,.mode-button{display:flex;align-items:center;gap:14px;border:1px solid var(--line);border-radius:20px;padding:17px 20px;background:var(--card);color:var(--ink);cursor:pointer;text-align:left;box-shadow:0 8px 24px rgba(80,39,88,.07)}.dataset-button .mode-icon,.mode-button .mode-icon{display:grid;place-items:center;width:46px;height:46px;border-radius:14px;background:#eee0f1;font-size:24px}.dataset-button strong,.mode-button strong{display:block;font-size:18px}.dataset-button small,.mode-button small{display:block;color:var(--muted);margin-top:3px}.dataset-button.active,.mode-button.active{border:2px solid var(--green);background:#f0e2f3}.mode-button.attack.active{border-color:var(--orange);background:#f7e5f2}.mode-button.attack .mode-icon{background:#efd7e9}
.toolbar{position:sticky;top:12px;z-index:5;display:grid;grid-template-columns:180px 180px minmax(240px,1fr);gap:12px;margin:18px 0;padding:14px;border-radius:18px;background:rgba(60,28,66,.95);box-shadow:0 12px 34px rgba(80,39,88,.25)}select,input{width:100%;border:1px solid #8e6a95;background:#512758;color:#fff;border-radius:11px;padding:11px 13px;font:inherit;outline:none}input::placeholder{color:#d8c4dc}
.kpis{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:16px 0}.kpi{background:var(--card);border:1px solid var(--line);border-radius:18px;padding:18px;box-shadow:0 8px 24px rgba(80,39,88,.07)}.kpi span{display:block;color:var(--muted);font-size:12px}.kpi strong{display:block;font-size:29px;margin-top:6px;font-variant-numeric:tabular-nums}.kpi.accent{background:var(--green);color:white;border-color:var(--green)}.kpi.accent span{color:#ead9ee}
.tabs{display:flex;gap:8px;flex-wrap:wrap;margin:20px 0 12px}.tab{border:1px solid var(--line);border-radius:999px;padding:10px 18px;background:var(--card);color:var(--ink);cursor:pointer;font-weight:700}.tab.active{background:var(--lime);border-color:#b67cc1}.panel{display:none}.panel.active{display:block}.card{background:var(--card);border:1px solid var(--line);border-radius:22px;overflow:hidden;box-shadow:var(--shadow)}
.card-head{display:flex;justify-content:space-between;gap:16px;align-items:center;padding:20px 22px;border-bottom:1px solid var(--line)}.card-head h2{margin:0;font-size:19px}.card-head p{margin:4px 0 0;color:var(--muted);font-size:12px}.table-wrap{overflow:auto;max-height:72vh}table{width:100%;border-collapse:collapse;font-size:13px}.stats-table{width:min(1180px,calc(100% - 24px));margin:0 auto}.type-table{width:min(720px,calc(100% - 24px));margin:0 auto}.players-table{min-width:1500px}th{position:sticky;top:0;background:#f2eaf4;z-index:1;text-align:left;color:#67556b;font-size:11px;letter-spacing:.04em;padding:9px 10px;border-bottom:1px solid var(--line);white-space:nowrap}td{padding:8px 10px;border-bottom:1px solid #eee3ef;vertical-align:middle}tr:hover td{background:#faf3fb}.num{text-align:right;font-variant-numeric:tabular-nums}.name{font-weight:750;min-width:220px}.meta{color:var(--muted);font-size:11px;margin-top:3px}.rate{min-width:135px}.bar{height:7px;background:#e8dfe9;border-radius:9px;overflow:hidden;margin-top:5px}.bar i{display:block;height:100%;background:linear-gradient(90deg,var(--green),var(--lime));border-radius:9px}.rarity{display:inline-grid;place-items:center;min-width:40px;border-radius:8px;padding:4px 8px;font-size:11px;font-weight:900;background:#ece7da}.rarity.lr{color:#735400;background:linear-gradient(135deg,#fff3a3,#e6b928)}.rarity.ur{color:#5b2a8f;background:#ead8ff}.rarity.ssr{color:#9e3c11;background:#ffe0cc}.entity{display:flex;align-items:center;gap:9px;min-width:230px}.thumb{width:54px;height:54px;border-radius:12px;object-fit:cover;background:#eee5f0;border:1px solid #dacbdd;flex:0 0 auto}.thumb.small{width:38px;height:38px;border-radius:9px}.thumb-fallback{display:grid;place-items:center;color:#796b7d;font-weight:900}.entity-copy{min-width:0}.entity-name{font-weight:750;line-height:1.35}.lineup{min-width:300px}.chip-list{display:flex;flex-wrap:wrap;gap:6px}.chip{display:flex;align-items:center;gap:5px;padding:4px 7px 4px 4px;border-radius:10px;background:#f1e7f3;max-width:220px}.chip span{font-size:11px;line-height:1.25}.warning{display:none;margin:14px 0;padding:13px 16px;border:1px solid #cfa7d5;background:#f7eaf8;color:#6f3478;border-radius:14px}.empty{text-align:center;color:var(--muted);padding:38px}.footer{color:var(--muted);font-size:12px;line-height:1.7;margin-top:18px}.nowrap{white-space:nowrap}
@media(max-width:800px){.shell{width:min(100% - 18px,1540px);margin-top:10px}.hero{grid-template-columns:1fr;padding:22px}.stamp{text-align:left}.dataset-switch,.mode-switch{grid-template-columns:1fr}.toolbar{grid-template-columns:1fr;position:static}.kpis{grid-template-columns:repeat(2,1fr)}.hero h1{font-size:38px}.stats-table,.type-table{width:100%}}
</style>
</head>
<body>
<main class="shell">
  <section class="hero">
    <div><div class="eyebrow">乃木坂的フラクタル · 編成採用率</div><h1>お見立て会</h1><p>お見立て会 TOP20 と個人ランキングは別集計です。防衛編成と攻撃編成も混在させず、LR／UR／SSR など同じメンバーのカード別に採用率を集計します。</p></div>
    <div class="stamp"><div>データ作成日（日本時間）</div><strong id="generated-at">—</strong><div id="coverage-text"></div></div>
  </section>
  <div id="warning" class="warning"></div>
  <section class="dataset-switch" aria-label="ランキング種別">
    <button class="dataset-button active" data-dataset="pvp"><span class="mode-icon">🏆</span><span><strong>お見立て会 TOP20</strong><small id="pvp-caption">各CH 20名を集計</small></span></button>
    <button class="dataset-button" data-dataset="personal"><span class="mode-icon">👤</span><span><strong id="personal-title">個人ランキング TOP75</strong><small id="personal-caption">各CHの個人ランキングを別集計</small></span></button>
  </section>
  <section class="mode-switch" aria-label="編成種別">
    <button class="mode-button active" data-mode="defense"><span class="mode-icon">🛡️</span><span><strong>防衛編成</strong><small>防衛編成のみを集計</small></span></button>
    <button class="mode-button attack" data-mode="attack"><span class="mode-icon">⚔️</span><span><strong>攻撃編成</strong><small>お見立て会で挑戦する側</small></span></button>
  </section>
  <section class="toolbar">
    <select id="channel-select" aria-label="CH選択"><option value="all">全CH</option></select>
    <select id="rarity-select" aria-label="メンバーレアリティ"><option value="all">全レアリティ</option><option value="LR">LR</option><option value="UR">UR</option><option value="SSR">SSR</option><option value="SR">SR</option><option value="R">R</option><option value="N">N</option></select>
    <input id="search" type="search" placeholder="メンバー、メモリア、プレイヤー、ギルドを検索…">
  </section>
  <section class="kpis">
    <div class="kpi accent"><span>集計編成数</span><strong id="kpi-decks">0</strong></div>
    <div class="kpi"><span>プレイヤー数</span><strong id="kpi-players">0</strong></div>
    <div class="kpi"><span>メンバーカード種類</span><strong id="kpi-cards">0</strong></div>
    <div class="kpi"><span>メモリア / 個人メモリア</span><strong id="kpi-memorias">0</strong></div>
  </section>
  <nav class="tabs"><button class="tab active" data-panel="cards">メンバー使用率</button><button class="tab" data-panel="main-types">メインメンバータイプ</button><button class="tab" data-panel="memorias">メモリア</button><button class="tab" data-panel="personal">個人メモリア</button><button class="tab" data-panel="players">編成一覧</button></nav>
  <section id="panel-cards" class="panel active"><div class="card"><div class="card-head"><div><h2>メンバー使用率</h2><p>カードとレアリティ別に集計。編成採用率＝採用編成数 ÷ 選択中の編成数、枠使用率の分母は1編成11枠です。</p></div></div><div class="table-wrap"><table class="stats-table"><thead><tr><th>#</th><th>メンバーカード</th><th>レアリティ</th><th class="num">採用編成数</th><th>編成採用率</th><th class="num">使用枠数</th><th>枠使用率</th></tr></thead><tbody id="cards-body"></tbody></table></div></div></section>
  <section id="panel-main-types" class="panel"><div class="card"><div class="card-head"><div><h2>メインメンバータイプ</h2><p>各プレイヤーのメインメンバーを「努力・感謝・笑顔」のタイプ別に集計します。メインメンバータイプは攻撃・防衛で共通です。</p></div></div><div class="table-wrap"><table class="type-table"><thead><tr><th>#</th><th>タイプ</th><th class="num">編成数</th><th>使用率</th></tr></thead><tbody id="main-types-body"></tbody></table></div></div></section>
  <section id="panel-memorias" class="panel"><div class="card"><div class="card-head"><div><h2>メモリア使用率</h2><p>枠使用率＝使用枠数 ÷（選択中の編成数 × 4）。</p></div></div><div class="table-wrap"><table class="stats-table"><thead><tr><th>#</th><th>メモリア</th><th>タイプ</th><th class="num">採用編成数</th><th>編成採用率</th><th class="num">使用枠数</th><th>枠使用率</th></tr></thead><tbody id="memorias-body"></tbody></table></div></div></section>
  <section id="panel-personal" class="panel"><div class="card"><div class="card-head"><div><h2>個人メモリア使用率</h2><p>枠使用率＝使用枠数 ÷（選択中の編成数 × 11）。</p></div></div><div class="table-wrap"><table class="stats-table"><thead><tr><th>#</th><th>個人メモリア</th><th class="num">採用編成数</th><th>編成採用率</th><th class="num">使用枠数</th><th>枠使用率</th></tr></thead><tbody id="personal-body"></tbody></table></div></div></section>
  <section id="panel-players" class="panel"><div class="card"><div class="card-head"><div><h2 id="players-title">各CH お見立て会 TOP20 編成一覧</h2><p>選択中の防衛編成または攻撃編成のみ表示します。</p></div></div><div class="table-wrap"><table class="players-table"><thead><tr><th>CH</th><th>順位</th><th>プレイヤー / ギルド</th><th class="num">総戦力</th><th>メインメンバー</th><th>メンバーカード</th><th>メモリア</th><th>個人メモリア</th></tr></thead><tbody id="players-body"></tbody></table></div></div></section>
  <p class="footer">お見立て会 TOP20 と個人ランキング、防衛編成と攻撃編成はすべて別集計です。</p>
</main>
<script>
const INDEX=__INDEX_JSON__;
const SUMMARY=__SUMMARY_JSON__;
const $=id=>document.getElementById(id);
const nf=new Intl.NumberFormat('ja-JP');
const jstDate=new Intl.DateTimeFormat('ja-JP',{timeZone:'Asia/Tokyo',year:'numeric',month:'2-digit',day:'2-digit'});
const state={dataset:'pvp',channel:'all',mode:'defense',rarity:'all',search:''};
function cell(text,cls=''){const td=document.createElement('td');td.textContent=text??'—';if(cls)td.className=cls;return td}
function imageNode(src,alt,small=false){if(src){const img=document.createElement('img');img.className='thumb'+(small?' small':'');img.src=src;img.alt=alt||'';img.loading='lazy';return img}const fallback=document.createElement('div');fallback.className='thumb thumb-fallback'+(small?' small':'');fallback.textContent=(alt||'無').replace(/^\[[^\]]+\]\s*/,'').slice(0,1)||'無';fallback.title='画像なし';return fallback}
function entityCell(name,image,meta=''){const td=document.createElement('td');const wrap=document.createElement('div');wrap.className='entity';wrap.appendChild(imageNode(image,name));const copy=document.createElement('div');copy.className='entity-copy';const title=document.createElement('div');title.className='entity-name';title.textContent=name||'—';copy.appendChild(title);if(meta){const detail=document.createElement('div');detail.className='meta';detail.textContent=meta;copy.appendChild(detail)}wrap.appendChild(copy);td.appendChild(wrap);return td}
function rarityCell(value){const td=document.createElement('td');const badge=document.createElement('span');badge.className='rarity '+String(value||'').toLowerCase();badge.textContent=value||'不明';td.appendChild(badge);return td}
function rateCell(value){const td=cell(`${Number(value||0).toFixed(2)}%`,'rate');const bar=document.createElement('div');bar.className='bar';const i=document.createElement('i');i.style.width=`${Math.min(100,Number(value||0))}%`;bar.appendChild(i);td.appendChild(bar);return td}
function queryMatch(...values){if(!state.search)return true;return values.some(v=>String(v??'').toLocaleLowerCase().includes(state.search))}
function datasetChannels(){return state.dataset==='personal'?(INDEX.personalRankingChannels||[]):(INDEX.channels||[])}
function currentStats(){return SUMMARY.datasets?.[state.dataset]?.scopes?.[state.channel]?.[state.mode]||{deckCount:0,playerCount:0,cards:[],mainUnitTypes:[],memorias:[],personalMemorias:[]}}
function emptyRow(body,colspan){const tr=document.createElement('tr');const td=cell('該当データがありません','empty');td.colSpan=colspan;tr.appendChild(td);body.appendChild(tr)}
function renderCards(stats){const body=$('cards-body');body.replaceChildren();let rank=0;stats.cards.filter(r=>(state.rarity==='all'||r.rarity===state.rarity)&&queryMatch(r.name,r.memberName,r.title,r.rarity)).forEach(row=>{rank++;const tr=document.createElement('tr');[cell(rank,'num'),entityCell(row.name,row.image,row.memberName),rarityCell(row.rarity),cell(nf.format(row.deckCount),'num'),rateCell(row.deckUsageRate),cell(nf.format(row.slotCount),'num'),rateCell(row.slotUsageRate)].forEach(x=>tr.appendChild(x));body.appendChild(tr)});if(!rank)emptyRow(body,7)}
function renderMemorias(stats){const body=$('memorias-body');body.replaceChildren();let rank=0;stats.memorias.filter(r=>queryMatch(r.name,r.shortName,r.slotTypeLabel)).forEach(row=>{rank++;const tr=document.createElement('tr');[cell(rank,'num'),entityCell(row.name,row.image,row.shortName),cell(row.slotTypeLabel||'不明'),cell(nf.format(row.deckCount),'num'),rateCell(row.deckUsageRate),cell(nf.format(row.slotCount),'num'),rateCell(row.slotUsageRate)].forEach(x=>tr.appendChild(x));body.appendChild(tr)});if(!rank)emptyRow(body,7)}
function renderMainTypes(stats){const body=$('main-types-body');body.replaceChildren();let rank=0;(stats.mainUnitTypes||[]).forEach(row=>{rank++;const tr=document.createElement('tr');[cell(rank,'num'),cell(row.name,'name'),cell(nf.format(row.count),'num'),rateCell(row.usageRate)].forEach(x=>tr.appendChild(x));body.appendChild(tr)});if(!rank)emptyRow(body,4)}
function renderPersonal(stats){const body=$('personal-body');body.replaceChildren();let rank=0;stats.personalMemorias.filter(r=>queryMatch(r.name)).forEach(row=>{rank++;const tr=document.createElement('tr');[cell(rank,'num'),entityCell(row.name,row.image),cell(nf.format(row.deckCount),'num'),rateCell(row.deckUsageRate),cell(nf.format(row.slotCount),'num'),rateCell(row.slotUsageRate)].forEach(x=>tr.appendChild(x));body.appendChild(tr)});if(!rank)emptyRow(body,6)}
function chipList(items,nameKey,imageKey){const td=document.createElement('td');td.className='lineup';const list=document.createElement('div');list.className='chip-list';items.forEach(item=>{const chip=document.createElement('div');chip.className='chip';chip.appendChild(imageNode(item[imageKey],item[nameKey],true));const text=document.createElement('span');text.textContent=item[nameKey]||'—';chip.appendChild(text);list.appendChild(chip)});td.appendChild(list);return td}
function renderPlayers(){const body=$('players-body');body.replaceChildren();let count=0;const all=datasetChannels();const channels=state.channel==='all'?all:all.filter(c=>`ch${String(c.worldId).padStart(2,'0')}`===state.channel);channels.forEach(channel=>(channel.players||[]).forEach(player=>{const deck=player.decks?.[state.mode];if(!deck)return;const subs=deck.subUnits||[];const memos=deck.memorias||[];const personals=subs.filter(x=>x.personalMemoriaName).map(x=>({name:x.personalMemoriaName,image:x.personalMemoriaImage}));if(!queryMatch(player.name,player.guildName,deck.mainUnit?.cardName,...subs.map(x=>x.cardName),...memos.map(x=>x.name),...personals.map(x=>x.name)))return;count++;const tr=document.createElement('tr');const who=cell(player.name,'name');const guild=document.createElement('div');guild.className='meta';guild.textContent=player.guildName||'ギルド未加入';who.appendChild(guild);[cell(`CH${String(channel.worldId).padStart(2,'0')}`,'nowrap'),cell(player.ranking,'num'),who,cell(nf.format(player.deckTotalBattlePoint||0),'num'),entityCell(deck.mainUnit?.cardName||deck.mainUnit?.characterName,deck.mainUnit?.image),chipList(subs,'cardName','image'),chipList(memos,'shortName','image'),chipList(personals,'name','image')].forEach(x=>tr.appendChild(x));body.appendChild(tr)}));if(!count)emptyRow(body,8)}
function rebuildChannels(){const select=$('channel-select');select.replaceChildren();const all=document.createElement('option');all.value='all';all.textContent='全CH';select.appendChild(all);datasetChannels().forEach(channel=>{const option=document.createElement('option');option.value=`ch${String(channel.worldId).padStart(2,'0')}`;option.textContent=`CH${String(channel.worldId).padStart(2,'0')}（${channel.players.length}名）`;select.appendChild(option)});state.channel='all';select.value='all'}
function render(){const stats=currentStats();const personalTop=INDEX.personalRankingCoverage?.availableTop||0;$('players-title').textContent=state.dataset==='personal'?`各CH 個人ランキング TOP${personalTop} 編成一覧`:'各CH お見立て会 TOP20 編成一覧';$('kpi-decks').textContent=nf.format(stats.deckCount||0);$('kpi-players').textContent=nf.format(stats.playerCount||0);$('kpi-cards').textContent=nf.format(stats.cards?.length||0);$('kpi-memorias').textContent=`${nf.format(stats.memorias?.length||0)} / ${nf.format(stats.personalMemorias?.length||0)}`;renderCards(stats);renderMainTypes(stats);renderMemorias(stats);renderPersonal(stats);renderPlayers()}
function init(){const generatedAt=INDEX.generatedAt?new Date(INDEX.generatedAt):null;$('generated-at').textContent=generatedAt&&!Number.isNaN(generatedAt.getTime())?jstDate.format(generatedAt):'—';const c=INDEX.coverage||{};const pc=INDEX.personalRankingCoverage||{};const top=pc.availableTop||0;$('personal-title').textContent=`個人ランキング TOP${top}`;$('coverage-text').textContent=`お見立て会 ${c.rankingChannels||0}/${c.requestedChannels||0} CH · 個人ランキング ${pc.rankingChannels||0}/${pc.requestedChannels||0} CH`;const missing=(INDEX.missing||[]).length;if(missing){const warning=$('warning');warning.style.display='block';warning.textContent=`未取得データが ${missing} 件あります。同じスナップショット名で再実行すると続きから取得できます。`}rebuildChannels();$('channel-select').addEventListener('change',e=>{state.channel=e.target.value;render()});$('rarity-select').addEventListener('change',e=>{state.rarity=e.target.value;renderCards(currentStats())});$('search').addEventListener('input',e=>{state.search=e.target.value.trim().toLocaleLowerCase();render()});document.querySelectorAll('.dataset-button').forEach(button=>button.addEventListener('click',()=>{state.dataset=button.dataset.dataset;document.querySelectorAll('.dataset-button').forEach(x=>x.classList.toggle('active',x===button));rebuildChannels();render()}));document.querySelectorAll('.mode-button').forEach(button=>button.addEventListener('click',()=>{state.mode=button.dataset.mode;document.querySelectorAll('.mode-button').forEach(x=>x.classList.toggle('active',x===button));render()}));document.querySelectorAll('.tab').forEach(button=>button.addEventListener('click',()=>{document.querySelectorAll('.tab').forEach(x=>x.classList.remove('active'));document.querySelectorAll('.panel').forEach(x=>x.classList.remove('active'));button.classList.add('active');$(`panel-${button.dataset.panel}`).classList.add('active')}));render()}
init();
</script>
</body>
</html>
'''
    return template.replace("__INDEX_JSON__", _safeScriptJson(index)).replace(
        "__SUMMARY_JSON__", _safeScriptJson(summary)
    )


def refreshAccessToken(
    nogifuraRoot: Path,
    authDir: Optional[Path],
    currentFile: Optional[Path],
    timeout: int,
) -> Tuple[str, str, str, int]:
    """Use the existing APK backup without writing decrypted credentials."""

    secretKey, deviceId = auth.load_saved_credentials(nogifuraRoot, auth_dir=authDir)
    selectedCurrent = auth.select_current_file(nogifuraRoot, currentFile)
    dlcVersion, appVersion = auth.load_dlc_version(selectedCurrent)
    accessToken, expiresIn = auth.request_access_token(
        secretKey,
        deviceId,
        dlcVersion,
        appVersion,
        timeout=timeout,
    )
    return accessToken, appVersion, dlcVersion, expiresIn


def parseArgs(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="擷取 NogiFura 各 CH お見立て会 Top 20 防衛/挑戰牌組並產生使用率 HTML"
    )
    parser.add_argument("--channels", type=parseChannels, default=parseChannels("1-40"))
    parser.add_argument("--top", type=int, default=20)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument(
        "--request-delay",
        type=float,
        default=0.6,
        help="APIリクエスト間隔（実際は指定値～1.35倍のランダム間隔）",
    )
    parser.add_argument("--personal-top", type=int, default=100)
    parser.add_argument("--personal-workers", type=int, default=1)
    parser.add_argument(
        "--personal-ranking-dir",
        type=Path,
        default=DEFAULT_PERSONAL_RANKING_DIR,
    )
    parser.add_argument(
        "--skip-personal-ranking",
        action="store_true",
        help="個人ランキング編成の取得と集計を行わない",
    )
    parser.add_argument(
        "--fetch-personal-ranking",
        action="store_true",
        help="個人ランキングをAPIから取得してsnapshot内に保存（同じsnapshotは再利用）",
    )
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)
    parser.add_argument("--retries", type=int, default=DEFAULT_RETRIES)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument(
        "--snapshot-name",
        default=datetime.now().astimezone().strftime("%Y%m%d"),
        help="快照資料夾名稱；預設為今天 YYYYMMDD，重跑會續抓",
    )
    parser.add_argument("--masterdata-dir", type=Path, default=DEFAULT_MASTERDATA_DIR)
    parser.add_argument(
        "--image-assets-dir",
        type=Path,
        default=DEFAULT_IMAGE_ASSETS_DIR,
        help=f"已解包的本機縮圖根目錄（預設：{DEFAULT_IMAGE_ASSETS_DIR}）",
    )
    parser.add_argument("--nogifura-root", type=Path, default=auth.DEFAULT_NOGIFURA_ROOT)
    parser.add_argument("--auth-dir", type=Path)
    parser.add_argument("--current-file", type=Path)
    parser.add_argument("--refresh", action="store_true", help="忽略快取並重新抓取全部 API")
    parser.add_argument("--rebuild-only", action="store_true", help="只從既有 raw JSON 重建索引與 HTML")
    parser.add_argument("--skip-detail", action="store_true", help="不抓 player/detail；牌組統計仍可完成")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parseArgs(argv)
    if (
        args.top < 1
        or args.personal_top < 1
        or args.workers < 1
        or args.personal_workers < 1
        or args.retries < 1
        or args.request_delay < 0
    ):
        print("[錯誤] top、workers、retries 必須大於 0", file=sys.stderr)
        return 2
    if not args.snapshot_name or any(char in args.snapshot_name for char in '<>:"/\\|?*'):
        print("[錯誤] snapshot-name 含有 Windows 不允許的字元", file=sys.stderr)
        return 2

    snapshotDir = args.output_dir / args.snapshot_name
    try:
        masters = buildMasterIndexes(args.masterdata_dir)
        collectionErrors = []
        if not args.rebuild_only:
            print("[認證] 從 APK 加密備份換發 DAS access token（不寫入磁碟）")
            accessToken, appVersion, dlcVersion, expiresIn = refreshAccessToken(
                args.nogifura_root,
                args.auth_dir,
                args.current_file,
                args.timeout,
            )
            print(
                f"[認證] 成功：APP={appVersion} DLC={dlcVersion} "
                f"有效期={expiresIn}s"
            )
            client = ApiClient(
                accessToken,
                appVersion,
                dlcVersion,
                timeout=args.timeout,
                retries=args.retries,
                requestDelay=args.request_delay,
            )
            collectionErrors = collectSnapshot(
                snapshotDir,
                client,
                args.channels,
                args.top,
                args.workers,
                refresh=args.refresh,
                skipDetail=args.skip_detail,
            )
            if not args.skip_personal_ranking:
                collectionErrors.extend(
                    collectPersonalRankingSnapshot(
                        snapshotDir,
                        client,
                        args.channels,
                        args.personal_top,
                        args.personal_workers,
                        args.personal_ranking_dir,
                        refresh=args.refresh,
                        fetchRanking=args.fetch_personal_ranking,
                    )
                )

        index = buildIndex(
            snapshotDir,
            args.channels,
            args.top,
            masters,
            args.masterdata_dir,
        )
        if collectionErrors:
            index["collectionErrors"] = collectionErrors
        includePersonalRanking = not args.skip_personal_ranking and (
            not args.rebuild_only or (snapshotDir / "personal_raw").is_dir()
        )
        if includePersonalRanking:
            personalChannels, personalCoverage, personalMissing = buildPersonalRankingIndex(
                snapshotDir,
                args.channels,
                args.personal_top,
                masters,
            )
            index["personalRankingChannels"] = personalChannels
            index["personalRankingCoverage"] = personalCoverage
            index["missing"].extend(personalMissing)
            index["source"]["personalRankingEndpoint"] = (
                "/api/worldgroup_ranking/player_ranking"
            )
            index["source"]["personalRankingDir"] = str(
                args.personal_ranking_dir.resolve()
            )
            index["source"]["personalRequestedTopPerChannel"] = args.personal_top
        imageCoverage = attachImages(index, args.image_assets_dir, snapshotDir)
        index["imageCoverage"] = imageCoverage
        index["source"]["imageAssetsDir"] = str(args.image_assets_dir.resolve())
        summary = buildSummary(index)
        writeJsonAtomic(snapshotDir / "index.json", index)
        writeJsonAtomic(snapshotDir / "summary.json", summary)
        writeTextAtomic(snapshotDir / "report.html", renderHtml(index, summary))
        writeJsonAtomic(
            args.output_dir / "latest.json",
            {
                "snapshotName": args.snapshot_name,
                "generatedAt": index["generatedAt"],
                "index": f"{args.snapshot_name}/index.json",
                "summary": f"{args.snapshot_name}/summary.json",
                "report": f"{args.snapshot_name}/report.html",
            },
        )
    except (PvpUsageError, auth.AuthRefreshError) as exc:
        print(f"[失敗] {exc}", file=sys.stderr)
        return 1

    coverage = index["coverage"]
    print(f"[輸出] index={snapshotDir / 'index.json'}")
    print(f"[輸出] summary={snapshotDir / 'summary.json'}")
    print(f"[輸出] HTML={snapshotDir / 'report.html'}")
    print(
        f"[圖示] 角色卡={imageCoverage['avatars']} 通常memo={imageCoverage['memorias']} "
        f"個人memo={imageCoverage['personalMemorias']} 缺圖={imageCoverage['missing']}"
    )
    print(
        f"[覆蓋] CH={coverage['rankingChannels']}/{coverage['requestedChannels']} "
        f"玩家={coverage['players']}/{coverage['expectedPlayers']} "
        f"防衛={coverage['defenseDecks']} 攻撃={coverage['attackDecks']}"
    )
    missingCount = len(index.get("missing") or []) + len(collectionErrors)
    if missingCount:
        print(f"[未完成] 尚有 {missingCount} 項缺漏；用相同 snapshot-name 重跑即可續抓")
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
