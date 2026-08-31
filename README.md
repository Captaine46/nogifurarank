# NogiFra Ranking Project (AutoExcel)

這是一個針對「乃木坂的フラクタル」遊戲數據排名的自動化生成與封存系統。

## 🌟 功能特色

- **Excel 自動處理**: 解析玩家、公會、聯賽 Excel 檔並生成排名 JSON/HTML。
- **網站生成**: 自動建立基於 Bootstrap 的靜態排名頁面。
- **Git 封存與部署**: 透過 `site_manager.py` 一鍵封存每週排名並發布至 GitHub Pages。
- **靈活配置**: 支援 `config.ini` 修改目標日期與計算規則。

## 🛠️ 安裝

1. **環境需求**
   - Python 3.9+
   - Git
   - pandas, openpyxl, requests, pycryptodome, lz4, flask (視具体依賴而定)

   ```bash
   pip install pandas openpyxl requests pycryptodome lz4
   ```

2. **設定**
   - 修改 `config.ini` 中的目標日期 (`YYYYMMDD`)。
   - 修改 `site_config.json` 設定 Repo URL 與網站標題。

## 🚀 使用方式

### 生成排名 (Pipeline)

執行 `run_pipeline.py` 依序處理所有 Excel 腳本：

```bash
python run_pipeline.py
```

Pipeline 會先執行 `refresh_nogifura_auth.py`，從
`E:\APK\nogifura\device_pull\external\auth` 的既有加密備份讀取
`secret_key` 與 `device_id`，直接向 DAS 換發 24 小時 access token，並更新
`guild_ranking.json`、`player_ranking.json`、`league_ranking.json`、`site.json`。
長期認證只在記憶體中解密，不會另存成明文，因此不需要每次開手機攔包。

只驗證認證流程、不改 JSON：

```bash
python refresh_nogifura_auth.py --dry-run
```

### お見立て会 TOP20／個人ランキング使用率

完整操作、TOP75 完整性檢查、續抓方式、離線重建 HTML 與六張 PNG 的命令請參閱：

- [PVP TOP75 使用率資料與圖片建立手冊](docs/PVP_USAGE_GUIDE.md)

通常は `update_pvp_usage.bat` をダブルクリックすると、内部で
`update_pvp_usage.py` を起動し、カード登場日時索引、
全40 CHの低速取得、HTML、TOP50画像、直近6か月／12か月画像まで一括で更新する。
同じ日付で再実行すると保存済みJSONを再利用し、不足分だけ続行する。実行中の
重複起動も防止する。コマンドラインから日付を固定する場合：

```bat
update_pvp_usage.bat 20260802
```

`nogifura_pvp_usage.py` 會從同一份 APK 加密認證備份換發 token，抓取
CH01～CH40 的 `/api/pvp/ranking` 前 20 名，再以
`/api/player/detail` 與 `/api/player/detail/deck` 取得玩家資料：

- `game_mode=3`：お見立て会攻擊側（`pvp_attack`，不是活動チャレンジ）
- `game_mode=4`：防衛（`pvp_defense`）

完整執行：

```bash
python nogifura_pvp_usage.py --channels 1-40 --top 20
```

同一次執行也會讀取
`D:\UNI\Fractal\gruop\json\player_rank\chXX-player_rank.json` 的個人排名，
再查詢每位玩家的防衛／挑戰編成。遊戲 API 的
`WorldgroupRankingPlayerRankingRequest` 沒有分頁或筆數參數，目前每個 CH
固定回傳 75 名，所以報表標示為「個人ランキング TOP75」，不會誤稱為
TOP100。個人排名與お見立て会 TOP20 使用不同資料集與分母，完全分開統計。

個人排名牌組預設以單執行緒及 0.6～0.81 秒的隨機請求間隔抓取，已存在的
JSON 會直接沿用；可使用 `--personal-workers` 與 `--request-delay` 調整，遇到
暫時性錯誤會退避重試。為避免大量重複請求，不建議搭配 `--refresh` 使用。

預設輸出到 `pvp_usage_output/YYYYMMDD/`：

- `raw/chXX/ranking.json`：該 CH 的原始排名回應。
- `raw/chXX/players/<player_id>/detail.json`：玩家基本資料。
- `raw/chXX/players/<player_id>/attack.json`：挑戰牌組原始資料。
- `raw/chXX/players/<player_id>/defense.json`：防衛牌組原始資料。
- `personal_raw/chXX/ranking.json`：個人排名原始回應（目前每 CH 75 名）。
- `personal_raw/chXX/players/<player_id>/attack.json`：個人排名挑戰編成。
- `personal_raw/chXX/players/<player_id>/defense.json`：個人排名防衛編成。
- `index.json`：已用本機 masterdata 解析實際角色卡標題、稀有度、通常 memo、個人 memo 名稱的索引。
- `summary.json`：全部 CH 與各 CH 的防衛／挑戰獨立使用率統計，不產生混合統計。
- `report.html`：可直接開啟的互動統計頁。
- `assets/`：報表使用的角色卡、通常 memo 與可取得的個人 memo 本機縮圖。

同一天重跑會沿用已存在的有效 JSON，只補抓缺漏。若只要從既有 raw JSON
重建索引與 HTML：

```bash
python nogifura_pvp_usage.py --channels 1-40 --top 20 --rebuild-only
```

HTML 的所有操作介面與統計術語均使用日文，並可在「お見立て会 TOP20」與
「個人ランキング TOP75」之間切換。角色卡以 API 回傳的 `avatar_id` 對應 `SubUnitAvatar`，因此同一成員的不同
LR／UR／SSR 卡片不會合併。「牌組採用率」以採用該卡的牌組數除以目前所選
防衛或お見立て会攻擊牌組數；「角色卡格率」以出現次數除以每副牌 11 格。通常 memo
與個人 memo 的格率分母分別是每副牌 4 格與 11 格，未裝備空格仍計入分母。
個人 memo 表不列出裝備成員，並會從 `stillthumbnails` 補齊縮圖；另有主角色
「努力／感謝／笑顔」類型使用率。HTML 不顯示任何資料表 ID，並可按稀有度
篩選角色卡。

原始資料、縮圖與報表只保留在本機輸出目錄且已由 Git 忽略。程式不會把
`Authorization`、`secret_key` 或 `device_id` 寫入快照。

### X 投稿用 TOP50 圖片

既有 `summary.json` 可直接產生四張 TOP50 圖與兩張新登場注目卡比較圖，
不會重新訪問 API：

```bash
python nogifura_pvp_x_cards.py --snapshot-dir pvp_usage_output/20260711
```

輸出到 snapshot 的 `x_cards/`，內容為「お見立て会 TOP20／個人ランキング
TOP75」各自的防衛編成與攻撃編成メンバーカード採用率 TOP50。四張圖使用
相同百分比刻度與乃木坂46紫色系，並從本地日期索引顯示每張卡的「初回登場」。
採用率橫條採用較短的比較區，適合放在同一則 X 貼文比較。

`x-new-focus-6months-5pct.png` 與 `x-new-focus-12months-5pct.png` 以排名快照的
日本時間為基準，分別列出初回登場六個月／一年內、且「お見立て会 TOP20／
個人ランキング TOP75 × 防衛／攻撃」四區分任一編成採用率達 5% 的
メンバーカード。一年版會依符合卡片數自動增加圖片高度。這裡是編成採用率，
不是玩家所持率；目前的排名 API 沒有提供每位玩家的完整所持カード一覧。

### メンバーカード初回登場日時索引

`SubUnitAvatar.StartAt` 會整理到共用的
`pvp_usage_output/card_release_index.json`。這是本機 masterdata 索引，不需要
重新抓取排名或玩家 API：

```bash
python nogifura_card_release_index.py
```

索引以 `avatarId` 合併並保存 `releasedAt`、`firstIndexedAt`、
`lastChangedAt`。masterdata 沒有變更時直接使用快取；更新 DLC／masterdata 後
再次執行會加入新卡，或記錄占位日期改成正式登場日期的變更。尚無有效
`StartAt` 的卡仍會保留在索引中，`releasedAt` 為 `null`。產生 X 圖時也會自動
檢查並使用這份索引。

`StartAt` 是可離線確認的卡片初回開放時間，適合用作新卡登場基準；它不包含
ガチャ名稱、卡池內容或結束時間。若需要精確到特定ガチャ活動，仍需另外保存
該ガチャ畫面的 API 回應。

### 管理網站 (Site Manager)

使用 `site_manager.py` 管理網站封存與發布：

```bash
# 初始化
python site_manager.py init

# 封存當前排名 (例如第24賽季第1週)
python site_manager.py archive "Week 1" --season "Season 24"

# 重新生成首頁索引
python site_manager.py build

# 部署至 GitHub
python site_manager.py deploy
```

## 📂 目錄結構

- `docs/`: 專案文件 (API, 架構, Roadmap)
- `archives/`: 歷次封存的排名數據
- `site_manager.py`: 網站管理工具
- `run_pipeline.py`: 自動化腳本入口
- `generate_*.py`: 各類排名生成邏輯

## 📄 授權

MIT License
