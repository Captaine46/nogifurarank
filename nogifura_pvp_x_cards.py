"""Render X-ready NogiFura deck-adoption charts from a usage snapshot."""

import argparse
import calendar
import json
import math
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence
from zoneinfo import ZoneInfo

from PIL import Image, ImageDraw, ImageFont

from nogifura_card_release_index import ensureCardReleaseIndex


WIDTH = 2000
HEIGHT = 2600
FOCUS_MIN_HEIGHT = 1500
FOCUS_ROW_HEIGHT = 136
DEFAULT_SNAPSHOT_DIR = Path("pvp_usage_output") / datetime.now().strftime("%Y%m%d")
DEFAULT_MASTERDATA_DIR = Path(r"E:\APK\nogifura\masterdata_export")
FONT_REGULAR = Path(r"C:\Windows\Fonts\YuGothM.ttc")
FONT_BOLD = Path(r"C:\Windows\Fonts\YuGothB.ttc")
MODE_LABELS = {"defense": "防衛編成", "attack": "攻撃編成"}
MODE_COLORS = {"defense": "#713080", "attack": "#A55393"}
RARITY_COLORS = {
    "LR": ("#F2D75C", "#5F4900"),
    "UR": ("#EAD8FF", "#5B2A8F"),
    "SSR": ("#FFE0CC", "#9E3C11"),
}
DATASETS = {
    "pvp": ("お見立て会 TOP20", "x-omitate-top20"),
    "personal": ("個人ランキング TOP75", "x-personal-top75"),
}
FOCUS_RATE_KEYS = (
    ("pvp", "defense", "omitateDefense"),
    ("pvp", "attack", "omitateAttack"),
    ("personal", "defense", "personalDefense"),
    ("personal", "attack", "personalAttack"),
)


def readJson(path: Path) -> Dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"JSONを読み込めません：{path}") from exc
    if not isinstance(value, dict):
        raise RuntimeError(f"JSONのルートがオブジェクトではありません：{path}")
    return value


def selectCardRows(stats: Dict[str, Any], top: int = 50) -> List[Dict[str, Any]]:
    rows = stats.get("cards") or []
    return [row for row in rows[:top] if isinstance(row, dict)]


def attachReleaseDates(
    rows: Sequence[Dict[str, Any]], releaseRows: Sequence[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    releasedAtByAvatar = {
        row.get("avatarId"): row.get("releasedAt")
        for row in releaseRows
        if isinstance(row, dict) and isinstance(row.get("avatarId"), int)
    }
    return [
        {**row, "releasedAt": releasedAtByAvatar.get(row.get("avatarId"))}
        for row in rows
    ]


def _subtractCalendarMonths(value: datetime, months: int) -> datetime:
    totalMonths = value.year * 12 + value.month - 1 - months
    year, zeroBasedMonth = divmod(totalMonths, 12)
    month = zeroBasedMonth + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return value.replace(year=year, month=month, day=day)


def selectNewFocusCards(
    summary: Dict[str, Any],
    avatarRows: Sequence[Dict[str, Any]],
    months: int = 6,
    minRate: float = 5.0,
) -> List[Dict[str, Any]]:
    """Select recently released cards exceeding the adoption threshold anywhere."""

    generatedAt = summary.get("generatedAt")
    if not isinstance(generatedAt, str):
        raise RuntimeError("summary.json に generatedAt がありません")
    try:
        reference = datetime.fromisoformat(generatedAt.replace("Z", "+00:00"))
    except ValueError as exc:
        raise RuntimeError("summary.json の generatedAt が不正です") from exc
    cutoff = _subtractCalendarMonths(reference, months)

    releases: Dict[int, datetime] = {}
    for row in avatarRows:
        avatarId = row.get("avatarId", row.get("Id"))
        startAt = row.get("releasedAt", row.get("StartAt"))
        if not isinstance(avatarId, int) or not isinstance(startAt, str):
            continue
        try:
            parsed = datetime.fromisoformat(startAt.replace("Z", "+00:00"))
        except ValueError:
            continue
        if parsed.year > 1:
            releases[avatarId] = parsed

    selected: Dict[int, Dict[str, Any]] = {}
    datasets = summary.get("datasets") or {}
    for dataset, mode, rateKey in FOCUS_RATE_KEYS:
        stats = (
            datasets.get(dataset, {})
            .get("scopes", {})
            .get("all", {})
            .get(mode, {})
        )
        for card in stats.get("cards") or []:
            if not isinstance(card, dict) or not isinstance(card.get("avatarId"), int):
                continue
            avatarId = card["avatarId"]
            releasedAt = releases.get(avatarId)
            if releasedAt is None or releasedAt < cutoff or releasedAt > reference:
                continue
            item = selected.setdefault(
                avatarId,
                {
                    "avatarId": avatarId,
                    "name": card.get("name") or "—",
                    "rarity": card.get("rarity") or "—",
                    "image": card.get("image"),
                    "releasedAt": releasedAt.isoformat(),
                    "rates": {},
                },
            )
            item["rates"][rateKey] = float(card.get("deckUsageRate") or 0)
            if not item.get("image") and card.get("image"):
                item["image"] = card["image"]

    result = []
    for item in selected.values():
        item["maxRate"] = max(item["rates"].values(), default=0.0)
        if item["maxRate"] >= minRate:
            result.append(item)
    result.sort(key=lambda row: (-row["maxRate"], row["releasedAt"], row["name"]))
    return result


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    path = FONT_BOLD if bold else FONT_REGULAR
    return ImageFont.truetype(str(path), size=size)


def _fitText(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, width: int) -> str:
    text = str(text or "—")
    if draw.textlength(text, font=font) <= width:
        return text
    suffix = "…"
    while text and draw.textlength(text + suffix, font=font) > width:
        text = text[:-1]
    return text + suffix


def _japanDate(value: Any) -> str:
    if not isinstance(value, str) or not value:
        return "—"
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.astimezone(ZoneInfo("Asia/Tokyo")).strftime("%Y/%m/%d")
    except ValueError:
        return "—"


def _thumbnail(
    snapshotDir: Path, relative: Any, maxSize: int = 46
) -> Optional[Image.Image]:
    if not isinstance(relative, str) or not relative:
        return None
    path = snapshotDir / relative
    try:
        with Image.open(path) as source:
            image = source.convert("RGB")
            image.thumbnail((maxSize, maxSize), Image.Resampling.LANCZOS)
            return image.copy()
    except OSError:
        return None


def renderXCard(
    rows: Sequence[Dict[str, Any]],
    snapshotDir: Path,
    outputPath: Path,
    sourceTitle: str,
    mode: str,
    deckCount: int,
    generatedAt: Any,
    axisMax: int,
    top: int = 50,
) -> None:
    if mode not in MODE_LABELS:
        raise ValueError(f"unknown mode: {mode}")
    image = Image.new("RGB", (WIDTH, HEIGHT), "#F7F2F8")
    draw = ImageDraw.Draw(image)
    accent = MODE_COLORS[mode]
    ink = "#241A26"
    muted = "#756879"
    line = "#E2D4E5"
    paper = "#FFFAFE"
    highlight = "#D8ADDF"
    titleFont = _font(62, bold=True)
    subtitleFont = _font(34, bold=True)
    bodyFont = _font(23)
    rowFont = _font(18, bold=True)
    smallFont = _font(17)

    draw.rectangle((0, 0, WIDTH, 18), fill=accent)
    draw.text((54, 50), "乃木坂的フラクタル", font=bodyFont, fill=accent)
    draw.text((54, 88), sourceTitle, font=titleFont, fill=ink)
    draw.text(
        (54, 162),
        f"{MODE_LABELS[mode]}｜メンバーカード採用率 TOP{top}",
        font=subtitleFont,
        fill=ink,
    )
    draw.text(
        (54, 214),
        f"40 CH・{deckCount:,}編成　作成日 {_japanDate(generatedAt)}（日本時間）",
        font=smallFont,
        fill=muted,
    )

    headerY = 285
    draw.rounded_rectangle((38, headerY, WIDTH - 38, HEIGHT - 54), 22, fill=paper)
    labels = [
        (72, "順位"),
        (210, "メンバーカード"),
        (800, "レア"),
        (900, "初回登場"),
        (1090, "採用数"),
        (1240, "採用率"),
    ]
    for x, label in labels:
        draw.text((x, headerY + 20), label, font=smallFont, fill=muted)
    barLeft, barRight = 1450, 1920
    draw.text((barLeft, headerY + 20), "0%", font=smallFont, fill=muted)
    axisText = f"{axisMax}%"
    draw.text((barRight - draw.textlength(axisText, font=smallFont), headerY + 20), axisText, font=smallFont, fill=muted)
    draw.line((38, headerY + 58, WIDTH - 38, headerY + 58), fill=line, width=2)

    rowTop = headerY + 60
    rowHeight = 44
    for rank, row in enumerate(rows[:top], start=1):
        y = rowTop + (rank - 1) * rowHeight
        if rank % 2 == 0:
            draw.rectangle((39, y, WIDTH - 39, y + rowHeight), fill="#F6EDF8")
        draw.text((82, y + 11), str(rank), font=rowFont, fill=ink)
        thumb = _thumbnail(Path(snapshotDir), row.get("image"))
        if thumb is not None:
            thumb.thumbnail((36, 36), Image.Resampling.LANCZOS)
            image.paste(thumb, (142, y + 4))
        else:
            draw.rounded_rectangle((142, y + 4, 178, y + 40), 7, fill="#EADFED")
        name = _fitText(draw, str(row.get("name") or "—"), rowFont, 545)
        draw.text((210, y + 11), name, font=rowFont, fill=ink)
        rarity = str(row.get("rarity") or "—")
        rarityFill, rarityInk = RARITY_COLORS.get(rarity, ("#E8E1E9", ink))
        draw.rounded_rectangle((790, y + 7, 870, y + 37), 12, fill=rarityFill)
        rarityWidth = draw.textlength(rarity, font=smallFont)
        draw.text((830 - rarityWidth / 2, y + 11), rarity, font=smallFont, fill=rarityInk)
        draw.text((895, y + 11), _japanDate(row.get("releasedAt")), font=smallFont, fill=ink)
        countText = f"{int(row.get('deckCount') or 0):,}"
        draw.text((1190 - draw.textlength(countText, font=rowFont), y + 11), countText, font=rowFont, fill=ink)
        rate = float(row.get("deckUsageRate") or 0)
        rateText = f"{rate:.2f}%"
        draw.text((1400 - draw.textlength(rateText, font=rowFont), y + 11), rateText, font=rowFont, fill=ink)
        barY = y + 15
        draw.rounded_rectangle((barLeft, barY, barRight, barY + 14), 7, fill="#E5E1D5")
        fillRight = barLeft + int((barRight - barLeft) * min(rate, axisMax) / axisMax)
        if fillRight > barLeft:
            draw.rounded_rectangle((barLeft, barY, fillRight, barY + 14), 7, fill=accent)
            if fillRight - barLeft > 24:
                draw.ellipse((fillRight - 14, barY, fillRight, barY + 14), fill=highlight)
        draw.line((39, y + rowHeight, WIDTH - 39, y + rowHeight), fill=line, width=1)

    draw.text(
        (54, HEIGHT - 38),
        "編成採用率 ＝ 採用編成数 ÷ 集計編成数",
        font=smallFont,
        fill=muted,
    )
    outputPath = Path(outputPath)
    outputPath.parent.mkdir(parents=True, exist_ok=True)
    image.save(outputPath, format="PNG", optimize=True)


def renderNewFocusCard(
    rows: Sequence[Dict[str, Any]],
    snapshotDir: Path,
    outputPath: Path,
    generatedAt: Any,
    months: int = 6,
    minRate: float = 5.0,
) -> None:
    focusHeight = max(FOCUS_MIN_HEIGHT, 454 + len(rows) * FOCUS_ROW_HEIGHT)
    image = Image.new("RGB", (WIDTH, focusHeight), "#F7F2F8")
    draw = ImageDraw.Draw(image)
    ink = "#241A26"
    muted = "#756879"
    line = "#E2D4E5"
    paper = "#FFFAFE"
    defense = MODE_COLORS["defense"]
    attack = MODE_COLORS["attack"]
    titleFont = _font(58, bold=True)
    subtitleFont = _font(30, bold=True)
    headerFont = _font(21, bold=True)
    bodyFont = _font(23)
    rowFont = _font(20, bold=True)
    smallFont = _font(17)
    rateFont = _font(23, bold=True)

    draw.rectangle((0, 0, WIDTH, 18), fill="#713080")
    draw.text((54, 48), "乃木坂的フラクタル", font=bodyFont, fill="#713080")
    draw.text((54, 86), "新登場・注目メンバーカード", font=titleFont, fill=ink)
    draw.text(
        (54, 166),
        f"直近{months}か月に初登場｜編成採用率 {minRate:g}%以上",
        font=subtitleFont,
        fill=ink,
    )
    draw.text(
        (54, 216),
        f"40 CH集計　基準日 {_japanDate(generatedAt)}（日本時間）",
        font=smallFont,
        fill=muted,
    )

    top = 278
    bottom = focusHeight - 72
    draw.rounded_rectangle((38, top, WIDTH - 38, bottom), 22, fill=paper)
    cardX, releaseX = 88, 940
    rateXs = (1180, 1370, 1580, 1770)
    draw.text((cardX, top + 24), "メンバーカード", font=headerFont, fill=muted)
    draw.text((releaseX, top + 24), "初回登場", font=headerFont, fill=muted)
    draw.text((1178, top + 18), "お見立て会 TOP20", font=headerFont, fill=ink)
    draw.text((1578, top + 18), "個人ランキング TOP75", font=headerFont, fill=ink)
    draw.text((rateXs[0], top + 52), "防衛", font=smallFont, fill=defense)
    draw.text((rateXs[1], top + 52), "攻撃", font=smallFont, fill=attack)
    draw.text((rateXs[2], top + 52), "防衛", font=smallFont, fill=defense)
    draw.text((rateXs[3], top + 52), "攻撃", font=smallFont, fill=attack)
    draw.line((38, top + 86, WIDTH - 38, top + 86), fill=line, width=2)

    rowTop = top + 88
    available = bottom - rowTop
    rowHeight = min(166, max(112, available // max(1, len(rows))))
    rateKeys = ("omitateDefense", "omitateAttack", "personalDefense", "personalAttack")
    for rank, row in enumerate(rows, start=1):
        y = rowTop + (rank - 1) * rowHeight
        if y + rowHeight > bottom:
            break
        if rank % 2 == 0:
            draw.rectangle((39, y, WIDTH - 39, y + rowHeight), fill="#F6EDF8")
        draw.text((58, y + rowHeight // 2 - 14), str(rank), font=rowFont, fill=ink)
        thumb = _thumbnail(Path(snapshotDir), row.get("image"), maxSize=96)
        thumbSize = min(96, rowHeight - 24)
        if thumb is not None:
            thumb.thumbnail((thumbSize, thumbSize), Image.Resampling.LANCZOS)
            image.paste(thumb, (100, y + (rowHeight - thumb.height) // 2))
        else:
            draw.rounded_rectangle(
                (100, y + 16, 100 + thumbSize, y + 16 + thumbSize), 12, fill="#EADFED"
            )
        name = _fitText(draw, str(row.get("name") or "—"), rowFont, 690)
        nameY = y + rowHeight // 2 - 29
        draw.text((220, nameY), name, font=rowFont, fill=ink)
        rarity = str(row.get("rarity") or "—")
        rarityFill, rarityInk = RARITY_COLORS.get(rarity, ("#E8E1E9", ink))
        draw.rounded_rectangle((220, nameY + 40, 302, nameY + 72), 12, fill=rarityFill)
        rarityWidth = draw.textlength(rarity, font=smallFont)
        draw.text((261 - rarityWidth / 2, nameY + 44), rarity, font=smallFont, fill=rarityInk)

        try:
            releaseText = datetime.fromisoformat(str(row.get("releasedAt"))).strftime("%Y/%m/%d")
        except ValueError:
            releaseText = "—"
        draw.text((releaseX, y + rowHeight // 2 - 14), releaseText, font=rowFont, fill=ink)

        rates = row.get("rates") or {}
        for column, (x, key) in enumerate(zip(rateXs, rateKeys)):
            rate = rates.get(key)
            modeColor = defense if column % 2 == 0 else attack
            box = (x - 12, y + rowHeight // 2 - 34, x + 154, y + rowHeight // 2 + 34)
            isFocus = isinstance(rate, (int, float)) and rate >= minRate
            draw.rounded_rectangle(box, 18, fill=modeColor if isFocus else "#ECE6EE")
            textValue = f"{rate:.2f}%" if isinstance(rate, (int, float)) else "—"
            textWidth = draw.textlength(textValue, font=rateFont)
            draw.text(
                (x + 71 - textWidth / 2, y + rowHeight // 2 - 16),
                textValue,
                font=rateFont,
                fill="#FFFFFF" if isFocus else muted,
            )
        draw.line((39, y + rowHeight, WIDTH - 39, y + rowHeight), fill=line, width=1)

    draw.text(
        (54, focusHeight - 45),
        f"判定：初回登場から{months}か月以内、かつ4区分のいずれかで編成採用率 {minRate:g}%以上　※所持率ではありません",
        font=smallFont,
        fill=muted,
    )
    outputPath = Path(outputPath)
    outputPath.parent.mkdir(parents=True, exist_ok=True)
    image.save(outputPath, format="PNG", optimize=True)


def parseArgs(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="X投稿用の採用率TOP50画像を作成")
    parser.add_argument("--snapshot-dir", type=Path, default=DEFAULT_SNAPSHOT_DIR)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--masterdata-dir", type=Path, default=DEFAULT_MASTERDATA_DIR)
    parser.add_argument("--release-index", type=Path)
    parser.add_argument("--top", type=int, default=50)
    parser.add_argument("--focus-months", type=int, nargs="+", default=[6, 12])
    parser.add_argument("--focus-min-rate", type=float, default=5.0)
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parseArgs(argv)
    if args.top < 1 or args.top > 50:
        print("[エラー] top は1～50で指定してください", file=sys.stderr)
        return 2
    if any(months < 1 for months in args.focus_months) or args.focus_min_rate <= 0:
        print("[エラー] focus-months と focus-min-rate は正数で指定してください", file=sys.stderr)
        return 2
    try:
        summary = readJson(args.snapshot_dir / "summary.json")
        outputDir = args.output_dir or (args.snapshot_dir / "x_cards")
        releaseIndexPath = args.release_index or (
            args.snapshot_dir.parent / "card_release_index.json"
        )
        releaseIndex, refreshed = ensureCardReleaseIndex(
            args.masterdata_dir, releaseIndexPath
        )
        releaseRows = releaseIndex.get("cards") or []
        print(
            f"[登場日時索引] {releaseIndexPath}"
            f"（{'更新' if refreshed else 'キャッシュ使用'}）"
        )
        allRates = []
        for dataset in DATASETS:
            scopes = summary.get("datasets", {}).get(dataset, {}).get("scopes", {})
            for mode in MODE_LABELS:
                allRates.extend(
                    float(row.get("deckUsageRate") or 0)
                    for row in selectCardRows(scopes.get("all", {}).get(mode, {}), args.top)
                )
        axisMax = max(10, int(math.ceil(max(allRates or [10]) / 10.0) * 10))
        for dataset, (sourceTitle, prefix) in DATASETS.items():
            scopes = summary.get("datasets", {}).get(dataset, {}).get("scopes", {})
            for mode in MODE_LABELS:
                stats = scopes.get("all", {}).get(mode, {})
                output = outputDir / f"{prefix}-{mode}-top{args.top}.png"
                renderXCard(
                    rows=attachReleaseDates(
                        selectCardRows(stats, args.top), releaseRows
                    ),
                    snapshotDir=args.snapshot_dir,
                    outputPath=output,
                    sourceTitle=sourceTitle,
                    mode=mode,
                    deckCount=int(stats.get("deckCount") or 0),
                    generatedAt=summary.get("generatedAt"),
                    axisMax=axisMax,
                    top=args.top,
                )
                print(f"[出力] {output}")
        rateSlug = f"{args.focus_min_rate:g}".replace(".", "p")
        for focusMonths in dict.fromkeys(args.focus_months):
            focusRows = selectNewFocusCards(
                summary,
                releaseIndex.get("cards") or [],
                months=focusMonths,
                minRate=args.focus_min_rate,
            )
            focusOutput = (
                outputDir
                / f"x-new-focus-{focusMonths}months-{rateSlug}pct.png"
            )
            renderNewFocusCard(
                rows=focusRows,
                snapshotDir=args.snapshot_dir,
                outputPath=focusOutput,
                generatedAt=summary.get("generatedAt"),
                months=focusMonths,
                minRate=args.focus_min_rate,
            )
            print(f"[出力] {focusOutput}（{len(focusRows)}枚）")
    except (RuntimeError, OSError, ValueError) as exc:
        print(f"[エラー] {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
