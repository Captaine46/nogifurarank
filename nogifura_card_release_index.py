"""Build a reusable local index of NogiFura member-card release dates."""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo


DEFAULT_MASTERDATA_DIR = Path(r"E:\APK\nogifura\masterdata_export")
DEFAULT_OUTPUT = Path("pvp_usage_output") / "card_release_index.json"
RARITY_LABELS = {1: "N", 2: "R", 3: "SR", 4: "SSR", 5: "UR", 6: "LR"}
SCHEMA_VERSION = 2


def _readJson(path: Path) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"JSONを読み込めません：{path}") from exc


def _writeJsonAtomic(path: Path, value: Any) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def _japanNow() -> datetime:
    return datetime.now(ZoneInfo("Asia/Tokyo"))


def _sourceFingerprint(path: Path) -> Dict[str, Any]:
    stat = Path(path).stat()
    return {
        "path": str(Path(path).resolve()),
        "size": stat.st_size,
        "mtimeNs": stat.st_mtime_ns,
        "updatedAt": datetime.fromtimestamp(
            stat.st_mtime, ZoneInfo("Asia/Tokyo")
        ).isoformat(timespec="seconds"),
    }


def _cardCore(row: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    avatarId = row.get("Id")
    releasedAt = row.get("StartAt")
    if not isinstance(avatarId, int):
        return None
    parsed: Optional[datetime] = None
    if isinstance(releasedAt, str):
        try:
            candidate = datetime.fromisoformat(releasedAt.replace("Z", "+00:00"))
            if candidate.year > 1:
                parsed = candidate
        except ValueError:
            pass
    title = str(row.get("Title") or "").strip()
    memberName = str(row.get("Name") or "").strip()
    rarityRank = row.get("Rarity") if isinstance(row.get("Rarity"), int) else None
    return {
        "avatarId": avatarId,
        "cardName": " ".join(part for part in (title, memberName) if part),
        "title": title,
        "memberName": memberName,
        "rarity": RARITY_LABELS.get(rarityRank, "不明"),
        "rarityRank": rarityRank,
        "releasedAt": parsed.isoformat() if parsed else None,
    }


def _sameCore(left: Dict[str, Any], right: Dict[str, Any]) -> bool:
    return all(left.get(key) == right.get(key) for key in (
        "avatarId",
        "cardName",
        "title",
        "memberName",
        "rarity",
        "rarityRank",
        "releasedAt",
    ))


def ensureCardReleaseIndex(
    masterdataDir: Path,
    outputPath: Path,
    now: Optional[datetime] = None,
) -> Tuple[Dict[str, Any], bool]:
    """Return the cached index, refreshing only when SubUnitAvatar changes."""

    sourcePath = Path(masterdataDir) / "SubUnitAvatar.json"
    source = _sourceFingerprint(sourcePath)
    outputPath = Path(outputPath)
    existing: Dict[str, Any] = {}
    if outputPath.exists():
        value = _readJson(outputPath)
        if isinstance(value, dict):
            existing = value
            if (
                existing.get("schemaVersion") == SCHEMA_VERSION
                and existing.get("source", {}).get("path") == source["path"]
                and existing.get("source", {}).get("size") == source["size"]
                and existing.get("source", {}).get("mtimeNs") == source["mtimeNs"]
                and isinstance(existing.get("cards"), list)
            ):
                return existing, False

    rawRows = _readJson(sourcePath)
    if not isinstance(rawRows, list):
        raise RuntimeError(f"SubUnitAvatar.json のルートが配列ではありません：{sourcePath}")
    indexedAt = (now or _japanNow()).astimezone(ZoneInfo("Asia/Tokyo")).isoformat(
        timespec="seconds"
    )
    oldCards = {
        row.get("avatarId"): row
        for row in existing.get("cards", [])
        if isinstance(row, dict) and isinstance(row.get("avatarId"), int)
    }
    cards: List[Dict[str, Any]] = []
    newCount = 0
    updatedCount = 0
    for rawRow in rawRows:
        if not isinstance(rawRow, dict):
            continue
        core = _cardCore(rawRow)
        if core is None:
            continue
        old = oldCards.get(core["avatarId"])
        if old is None:
            newCount += 1
            firstIndexedAt = indexedAt
            lastChangedAt = indexedAt
        elif _sameCore(old, core):
            firstIndexedAt = old.get("firstIndexedAt") or indexedAt
            lastChangedAt = old.get("lastChangedAt") or firstIndexedAt
        else:
            updatedCount += 1
            firstIndexedAt = old.get("firstIndexedAt") or indexedAt
            lastChangedAt = indexedAt
        cards.append(
            {
                **core,
                "firstIndexedAt": firstIndexedAt,
                "lastChangedAt": lastChangedAt,
            }
        )
    cards.sort(
        key=lambda row: (
            row["releasedAt"] is None,
            row["releasedAt"] or "",
            row["avatarId"],
        )
    )
    knownReleaseCount = sum(row["releasedAt"] is not None for row in cards)
    result = {
        "schemaVersion": SCHEMA_VERSION,
        "sourceField": "SubUnitAvatar.StartAt",
        "indexedAt": indexedAt,
        "source": source,
        "cardCount": len(cards),
        "releaseDateKnownCount": knownReleaseCount,
        "releaseDateUnknownCount": len(cards) - knownReleaseCount,
        "newCardCount": newCount,
        "updatedCardCount": updatedCount,
        "cards": cards,
    }
    _writeJsonAtomic(outputPath, result)
    return result, True


def parseArgs(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="メンバーカード初回登場日時索引を更新")
    parser.add_argument("--masterdata-dir", type=Path, default=DEFAULT_MASTERDATA_DIR)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parseArgs(argv)
    try:
        index, refreshed = ensureCardReleaseIndex(args.masterdata_dir, args.output)
    except (OSError, RuntimeError) as exc:
        print(f"[エラー] {exc}", file=sys.stderr)
        return 1
    state = "更新" if refreshed else "キャッシュ使用"
    print(
        f"[{state}] {args.output}｜{index.get('cardCount', 0)}枚"
        f"｜登場日時あり {index.get('releaseDateKnownCount', 0)}"
        f"｜新規 {index.get('newCardCount', 0)}｜変更 {index.get('updatedCardCount', 0)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
