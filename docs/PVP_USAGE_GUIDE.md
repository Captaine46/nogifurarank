# PVP TOP75 使用率資料與圖片建立手冊

本手冊說明如何建立以下兩套互不混合的統計資料：

| 資料集 | 每 CH 名次 | 40 CH 編成數 | 統計方式 |
|---|---:|---:|---|
| お見立て会 TOP20 | 20 名 | 攻撃 800／防衛 800 | 各自獨立統計 |
| 個人ランキング TOP75 | 75 名 | 攻撃 3,000／防衛 3,000 | 各自獨立統計 |

個人ランキング使用 `/api/worldgroup_ranking/player_ranking`。這個 API 沒有分頁與取得筆數參數，目前每個 CH 固定回傳 75 名，因此不能由同一個 API 取得 TOP100。

## 1. 執行前確認

請確認下列資料存在：

- Python：`c:\Users\aelin\AppData\Local\Programs\Python\Python39\python.exe`
- 認證備份：`E:\APK\nogifura\device_pull\external\auth`
- Master data：`E:\APK\nogifura\masterdata_export`
- 卡片與メモリア縮圖：`E:\APK\nogifura\visual\assets`

程式會由加密認證備份換發短期 access token。token、`secret_key`、`device_id` 不會寫進報表或快照。

## 2. 建議方式：雙擊 BAT 一鍵完整建立

在檔案總管雙擊：

```text
D:\UNI\Fractal\gruop\autoexcel\update_pvp_usage.bat
```

不帶日期時，資料夾名稱會使用執行當天的日本日期。例如 2026 年 9 月 1 日執行，會建立：

```text
D:\UNI\Fractal\gruop\autoexcel\pvp_usage_output\20260901\
```

若要指定快照日期，請在 PowerShell 或命令提示字元執行：

```bat
cd /d D:\UNI\Fractal\gruop\autoexcel
update_pvp_usage.bat 20260901
```

BAT 會依序完成三件事：

1. 更新 `pvp_usage_output\card_release_index.json` 的メンバーカード初回登場日期。
2. 低速取得全 40 CH 的お見立て会 TOP20、個人ランキング TOP75、攻撃編成與防衛編成，並建立 `index.json`、`summary.json`、`report.html`。
3. 從 `summary.json` 產生四張 TOP50 圖、四張前月比圖及半年／一年新登場注目卡圖片。

預設使用：

- 一般取得執行緒：2
- 個人ランキング執行緒：1
- API 間隔：最少 0.8 秒，程式會加入隨機間隔
- 個人ランキング參數上限：100，但 API 實際只有 75 筆，所以報表自動顯示 TOP75

個人ランキング最多需要處理 `40 CH × 75 名 × 2 種編成`。第一次執行時間會較長；請讓視窗保持開啟。中斷時不必刪除資料，使用同一日期重跑即可續抓。

## 3. 如何確認 TOP75 已經完整

完成後應有下列數量：

- 個人ランキング ranking JSON：40 份
- 個人ランキング攻撃編成 JSON：3,000 份
- 個人ランキング防衛編成 JSON：3,000 份
- 報表的「個人ランキング TOP75」中，攻撃編成與防衛編成的「集計編成数」各為 3,000

可在 PowerShell 檢查檔案數：

```powershell
$snapshot = 'D:\UNI\Fractal\gruop\autoexcel\pvp_usage_output\20260901'
(Get-ChildItem "$snapshot\personal_raw" -Filter ranking.json -Recurse).Count
(Get-ChildItem "$snapshot\personal_raw" -Filter attack.json -Recurse).Count
(Get-ChildItem "$snapshot\personal_raw" -Filter defense.json -Recurse).Count
```

正常結果依序是：

```text
40
3000
3000
```

接著開啟：

```text
D:\UNI\Fractal\gruop\autoexcel\pvp_usage_output\20260901\report.html
```

若少於上述數量，請直接用同一個日期再次執行：

```bat
update_pvp_usage.bat 20260901
```

程式會沿用已完成的 JSON，只補缺少的 ranking／attack／defense，不會從第一名全部重抓。

## 4. 手動建立 TOP75 資料與 HTML

如果不要使用 BAT，可在 PowerShell 執行：

```powershell
cd D:\UNI\Fractal\gruop\autoexcel
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
& 'c:\Users\aelin\AppData\Local\Programs\Python\Python39\python.exe' -u .\nogifura_pvp_usage.py `
  --snapshot-name 20260901 `
  --channels 1-40 `
  --top 20 `
  --personal-top 100 `
  --workers 2 `
  --personal-workers 1 `
  --request-delay 0.8 `
  --skip-detail `
  --fetch-personal-ranking
```

各參數用途：

| 參數 | 用途 |
|---|---|
| `--snapshot-name 20260901` | 指定輸出快照；續抓時必須使用同一名稱 |
| `--channels 1-40` | 取得 CH01～CH40 |
| `--top 20` | お見立て会每 CH 取前 20 名 |
| `--personal-top 100` | 個人排名最多接受 100 筆；API 實際回傳 75 筆 |
| `--workers 2` | お見立て会取得執行緒數 |
| `--personal-workers 1` | 個人ランキング保持單執行緒，避免過快 |
| `--request-delay 0.8` | API 最短間隔；實際會在 0.8～1.08 秒間隨機 |
| `--skip-detail` | 不另外取得不影響牌組統計的玩家詳細資料 |
| `--fetch-personal-ranking` | 直接從 API 建立每 CH 的個人ランキング JSON |

這個步驟完成後會同時建立 HTML，不必再執行另一個 HTML 產生器。

## 5. 只用既有 JSON 重建 HTML

修改版面或統計程式後，如果 raw JSON 已完整，不需要再訪問 API：

```powershell
cd D:\UNI\Fractal\gruop\autoexcel
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
& 'c:\Users\aelin\AppData\Local\Programs\Python\Python39\python.exe' -u .\nogifura_pvp_usage.py `
  --snapshot-name 20260901 `
  --channels 1-40 `
  --top 20 `
  --personal-top 100 `
  --rebuild-only
```

`--rebuild-only` 只讀取下列既有目錄：

- `raw\`：お見立て会 TOP20
- `personal_raw\`：個人ランキング TOP75

然後重建：

- `index.json`
- `summary.json`
- `report.html`
- `assets\` 內實際使用到的本機縮圖

## 6. 由既有統計建立 X 用圖片

圖片只讀取既有 `summary.json`、`index.json` 與本機卡片登場日期索引，不會訪問玩家 API：

```powershell
cd D:\UNI\Fractal\gruop\autoexcel
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
& 'c:\Users\aelin\AppData\Local\Programs\Python\Python39\python.exe' -u .\nogifura_pvp_x_cards.py `
  --snapshot-dir .\pvp_usage_output\20260901 `
  --top 50
```

輸出位置：

```text
pvp_usage_output\20260901\x_cards\
```

前一月份有完整快照時，會建立十張 PNG：

1. `x-omitate-top20-defense-top50.png`
2. `x-omitate-top20-attack-top50.png`
3. `x-personal-top75-defense-top50.png`
4. `x-personal-top75-attack-top50.png`
5. `x-omitate-top20-defense-monthly-change.png`
6. `x-omitate-top20-attack-monthly-change.png`
7. `x-personal-top75-defense-monthly-change.png`
8. `x-personal-top75-attack-monthly-change.png`
9. `x-new-focus-6months-5pct.png`
10. `x-new-focus-12months-5pct.png`

前四張是メンバーカード編成採用率 TOP50。第 5～8 張是前月比圖片：左側顯示採用率上昇 TOP25，右側顯示低下 TOP25。每月欄位同時列出採用率與採用編成数；増減欄上段是實際増減編成数，下段是採用率差。後兩張分別整理半年／一年內初回登場，且四種區分中任一編成採用率達 5% 的卡片。

程式會依 `generatedAt` 自動尋找「緊鄰前一個月份」日期最新的快照。例如 `20260901` 會尋找 2026 年 8 月的快照。若要明確指定比較來源：

```powershell
& 'c:\Users\aelin\AppData\Local\Programs\Python\Python39\python.exe' -u .\nogifura_pvp_x_cards.py `
  --snapshot-dir .\pvp_usage_output\20260901 `
  --previous-snapshot-dir .\pvp_usage_output\20260802 `
  --top 50 `
  --comparison-top 25
```

月比的増減欄會同時顯示實際編成数與採用率差：

```text
前月 256編成／32.00%
今月 309編成／38.62%
増減 +53／+6.62%
```

`新規` 只表示前月採用實績為零／沒有出現在前月統計，不表示該卡一定是新登場卡。若前一月份沒有可用快照，月比圖片會自動略過，其餘六張圖片仍正常建立。

## 7. 只重建圖片的最短流程

如果 `report.html` 與 `summary.json` 已經存在，只想重新輸出 PNG，只需執行：

```bat
cd /d D:\UNI\Fractal\gruop\autoexcel
c:\Users\aelin\AppData\Local\Programs\Python\Python39\python.exe nogifura_pvp_x_cards.py --snapshot-dir pvp_usage_output\20260901 --top 50
```

## 8. 快取與安全注意事項

- 續抓一定要使用相同的 `--snapshot-name`；換日期會建立新的完整快照。
- 一般續抓不要加 `--refresh`。`--refresh` 會忽略快取並重新訪問全部 API。
- 不要同時開兩個更新視窗；一鍵程式會偵測重複執行並停止第二個程序。
- `--personal-top 100` 不代表 API 能回傳 100 名；目前 API 固定只有 75 名。
- 攻撃與防衛分開計算，所以完整 TOP75 應是攻撃 3,000、 防衛 3,000，不是兩者合計 3,000。
- 編成採用率是「採用該卡的編成數 ÷ 選定資料集的編成數」。一個編成可同時採用多張卡，因此所有卡片的採用率相加不會等於 100%。

## 9. 既有 player_rank JSON 的替代用法

若不想由 API 取得個人ランキング本身，且已有：

```text
D:\UNI\Fractal\gruop\json\player_rank\ch01-player_rank.json
...
D:\UNI\Fractal\gruop\json\player_rank\ch40-player_rank.json
```

可以使用第 4 節的命令，但拿掉 `--fetch-personal-ranking`。程式會讀取這 40 份 ranking JSON，再低速查詢其中玩家的攻撃／防衛編成。

日常更新建議保留 `--fetch-personal-ranking`，讓 ranking JSON 與編成 JSON 都封存在同一個日期快照內，之後才能完整離線重建 HTML 與圖片。
