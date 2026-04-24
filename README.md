# stock-morning-line

毎朝8時(JST)にLINEで日本株モーニングブリーフィングを配信する個人用ツール。

## 構成
- `scripts/send_morning.py` … メインエントリ。ニュース収集→指数スナップショット→Gemini要約→LINE broadcast
- `scripts/news_fetch.py` … Yahoo/ロイター/NHK/株探からRSS収集
- `scripts/stock_data.py` … yfinanceで日経平均/TOPIXの前日終値＋ATRベース予想レンジ
- `scripts/gemini_client.py` … Gemini 2.0 Flash (無料枠) で要約生成
- `scripts/line_client.py` … LINE Messaging API broadcast
- `.github/workflows/morning.yml` … GitHub Actions cron (23:00 UTC = 08:00 JST)
- `docs/index.html` … GitHub Pagesで公開される設定画面

## 必要なSecrets (Settings → Secrets and variables → Actions)
- `LINE_CHANNEL_ACCESS_TOKEN`
- `GEMINI_API_KEY`

## 設定画面
GitHub Pagesを有効にすると `https://{user}.github.io/stock-morning-line/` で開けます。
予算ボタン(5/10/20/30/50/100万)・単元未満株オンオフ・今週末配信可否を選択可能。
GitHub PATで直接 `config/settings.json` を更新します。

## 手動実行
Actions → morning-brief → Run workflow でいつでもテスト送信できます。
