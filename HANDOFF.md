# 株通知システム 引継ぎノート

> **次回再開時にまずこれを読む。** Claudeに「このリポの HANDOFF.md を読んで続きをやって」と渡せばOK。

最終更新: 2026-04-25 / 構築者: Claude (Sonnet) + KATO-BOON

---

## 1. システム全体像

```
[GitHub Pages 設定画面]               [LINE 公式アカウント (株通知)]
  morning.html  ─┐                       ▲
  holdings.html ─┤                       │
                 ▼                       │
  [GitHub Repo: KATO-BOON/stock-morning-line]
       ▲                ▲                │
       │ PATCH/         │ cron           │ broadcast
       │ dispatch       ▼                │
   PAT(端末保存)    [GitHub Actions]──────┘
                    morning.yml(毎朝8時JST)
                    price-alert.yml(平日10分毎)
```

## 2. 認証情報の所在

| 項目 | 場所 | 備考 |
|---|---|---|
| LINE Channel ID | `2009890599` | 公開可 |
| LINE Channel Access Token | GitHub Secrets `LINE_CHANNEL_ACCESS_TOKEN` | OA Manager から再発行可 |
| Gemini API Key | GitHub Secrets `GEMINI_API_KEY` | aistudio.google.com/apikey |
| GitHub PAT | 各端末ブラウザのlocalStorage | 漏洩時は revoke→再発行 |

**ユーザーアカウント**: katounewhome@gmail.com / GitHub: KATO-BOON

## 3. ファイル構成

```
stock-morning-line/
├── HANDOFF.md           ← このファイル
├── README.md
├── requirements.txt     # Python deps (anthropic不要、Geminiのみ)
├── .github/workflows/
│   ├── morning.yml      # 毎朝8時 cron(23:00 UTC)
│   └── price-alert.yml  # 平日10分毎 cron(*/10 0-6 * * 1-5)
├── config/
│   └── settings.json    # 予算・保有銘柄等(設定画面が更新)
├── state/
│   └── alerts.json      # 重複通知防止state(workflow自動コミット)
├── scripts/
│   ├── send_morning.py     # 朝のブリーフのメインエントリ
│   ├── check_alerts.py     # 損切利確チェック
│   ├── news_fetch.py       # RSS収集(Yahoo/ロイター/NHK/株探)
│   ├── stock_data.py       # yfinance(日米指数+為替+商品)
│   ├── gemini_client.py    # Gemini 2.5 Flash + フォールバック
│   ├── line_client.py      # LINE broadcast(改行境界で分割)
│   ├── trading_day.py      # 東証営業日判定(jpholiday使用)
│   └── make_richmenu.py    # リッチメニュー登録
└── docs/                # GitHub Pages
    ├── index.html       # ランディング
    ├── morning.html     # 朝ニュース設定
    ├── holdings.html    # 保有銘柄管理
    ├── common.js        # 共通JS(state/save/dispatch)
    └── styles.css
```

## 4. URL集

- **設定ホーム**: https://kato-boon.github.io/stock-morning-line/
- **朝設定**: https://kato-boon.github.io/stock-morning-line/morning.html
- **保有銘柄**: https://kato-boon.github.io/stock-morning-line/holdings.html
- **GitHub repo**: https://github.com/KATO-BOON/stock-morning-line
- **Actions**: https://github.com/KATO-BOON/stock-morning-line/actions
- **LINE Developers**: https://developers.line.biz/console/channel/2009890599
- **Gemini Console**: https://aistudio.google.com/apikey

## 5. 動作中の機能

- ✅ 毎朝8時(JST)にLINE通知（土日祝は自動スキップ＝jpholiday判定）
- ✅ 朝のブリーフ：海外市場・為替・商品・日経予想レンジ・重要ニュース・注目銘柄(金額計算付)・リスク要因
- ✅ 保有銘柄の現在値監視(平日9:00-15:30の10分毎)
- ✅ 損切/利確ライン突破でLINE即通知(同条件は1日1回まで)
- ✅ LINEリッチメニュー：朝ニュース・保有銘柄・今すぐ配信
- ✅ 設定画面：PCでもスマホでも編集可（PATは端末保存）
- ✅ 例外日付：`config/settings.json` の `allowed_weekends` / `allowed_dates` で強制配信可

## 6. 既知の制約・TODO

### やりたいこと（次回以降）
- [ ] **auカブコム証券 開設後 kabuステーション API 連携**
  - REST + WebSocketでリアルタイム株価＆保有銘柄自動同期
  - 楽天証券は公開APIなし（諦め）
- [ ] price-alertの間隔を5分にしてもよい（GitHub Actions最短5分）
  - ただしyfinanceは20分遅延データなので体感差は小さい
- [ ] 設定画面の週末設定を「次の土日」自動計算に
  - 現在は固定日付なので来週には古くなる

### 設計上の制約
- **yfinance(無料)は20分遅延** → 真のリアルタイム監視は kabu API 等が必要
- **GitHub Actions cronは最短5分**（1分は不可、高負荷時遅延あり）
- **LINEメッセージ最大5,000字/通**、broadcastは1API呼出で5通まで

## 7. よく使うコマンド

```bash
# ローカルで動作確認
cd C:\Users\ha120\cloadcodeKABU\stock-morning-line
PYTHONIOENCODING=utf-8 py scripts/news_fetch.py
PYTHONIOENCODING=utf-8 py scripts/stock_data.py
PYTHONIOENCODING=utf-8 py scripts/trading_day.py

# GitHub Actions 手動起動(PAT必要)
curl -X POST -H "Authorization: token YOUR_PAT" \
  -H "Accept: application/vnd.github+json" \
  -d '{"ref":"main"}' \
  https://api.github.com/repos/KATO-BOON/stock-morning-line/actions/workflows/morning.yml/dispatches

# リッチメニュー再登録
LINE_CHANNEL_ACCESS_TOKEN=xxx PAGES_URL=https://kato-boon.github.io/stock-morning-line/ \
  py scripts/make_richmenu.py
```

## 8. トラブルシューティング

| 症状 | 原因 | 対処 |
|---|---|---|
| LINEに届かない | Token失効/Secretsミス | OA Managerでtoken再発行→GitHub Secrets更新 |
| Gemini 429 | 無料枠到達 or モデル名 | gemini_client.py のMODEL_FALLBACKS 順序確認 |
| TOPIX取れない | yfinance仕様変更 | `^TPX`/`1306.T`/`^TOPX` 試す |
| 保存失敗(設定画面) | PAT期限切れ/scope不足 | 新PAT作成(repo scope必須) |
| Actions失敗 | run logs参照 | https://github.com/KATO-BOON/stock-morning-line/actions |

## 9. 再開時の手順（次回Claudeに伝える）

```
このリポジトリ ( https://github.com/KATO-BOON/stock-morning-line ) で
株通知システムを使っている。
HANDOFF.md を読んで続きをやってほしい。
今日やりたいこと: <ここに書く>
```

例: 「auカブコム証券で口座開設したので、kabuステーション API連携を追加して」

## 10. PAT管理の注意

- 漏洩したPATは必ず https://github.com/settings/tokens でrevoke
- 新規発行はrepo scopeのみで十分
- 設定画面の「PAT入力」は端末ごとに1回でOK（外部送信なし）
