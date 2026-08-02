# Changelog

所有重要變更都會記錄在此文件。

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## [Unreleased]

### Added

- **Pixiu 標準化**: 導入標準文件結構與管理流程。
- **文件補齊**: 新增 RoadMap, Architecture, API, Env, Deployment 等文件。
- **お見立て会使用率**: 新增 CH01～CH40 Top 20 防衛／挑戰牌組擷取、可續跑 raw JSON、名稱索引、統計 JSON 與互動 HTML。
- **角色卡 Meta**: 使用 `SubUnitAvatar` 按實際 LR／UR／SSR 卡片分開統計，防衛與挑戰不再混合，HTML 隱藏資料 ID 並加入本機角色卡／memo 縮圖。
- **X 投稿画像**: 新增お見立て会 TOP20／個人ランキング TOP75 × 防衛／攻撃四張メンバーカード採用率 TOP50 圖片產生器。
- **新登場注目カード画像**: 以排名快照為基準，新增初回登場六個月／一年內且任一區分編成採用率達 5% 的 X 用比較圖，一年版依符合卡片數自動調整高度。
- **カード登場日時索引**: 新增 `SubUnitAvatar.StartAt` 本地快取索引，保存初回索引與變更檢出日期，masterdata 更新時自動合併新卡。
- **個人排名編成 Meta**: 新增每 CH 個人ランキング API 實際上限 TOP75 的可續跑防衛／挑戰編成擷取，與お見立て会 TOP20 完全分開統計。
- **日文統計介面**: HTML 全面改用遊戲日文術語，補齊個人メモリア縮圖，移除裝備メンバー欄，並新增努力／感謝／笑顔主メンバータイプ使用率。

### Changed

- **統計表レイアウト**: 使用率表格改為置中的緊湊欄寬，縮小欄位留白；編成一覧保留橫向捲動。
- **メモリアタイプ**: 將內部數值 1／2／3／4 改以遊戲使用的 A／B／C／D 顯示。
- **お見立て会攻撃表記**: 將容易與活動チャレンジ混淆的「挑戦編成」改為「攻撃編成」，畫面不顯示內部 API 名稱。
- **見出し表記**: 移除非遊戲術語的 `RANK` 主標題與不必要的認證資訊說明。
- **作成日時**: 報表固定以日本時間格式顯示，不再直接露出 ISO `T` 與時區偏移字串。
- **乃木坂46配色**: 網頁與 X 圖片統一改為紫色、紅紫與淡紫配色。
- **X 圖表欄寬**: 收窄メンバーカード欄位留白，LR／UR／SSR 徽章恢復遊戲內辨識色。

## [1.0.0] - 2026-02-16

### Added

- **Site Manager**: `site_manager.py` 支援 `init`, `archive`, `build`, `deploy` 指令。
- **Auto Pipeline**: `run_pipeline.py` 自動執行多個排名生成腳本。
- **Excel Processing**: 支援 `player_ranking`, `guild_ranking`, `league_ranking` 生成 HTML。

### Changed

- Refactored `run_pipeline.py` to use `subprocess` for better error handling.

### Fixed

- Fixed memory leaks in large Excel file processing (optimized pandas usage).
