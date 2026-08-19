# 日経225オプション 建玉残高ダッシュボード

JPXが毎日公開する「デリバティブ建玉残高表」から、日経225オプション・日経225ミニオプションの
権利行使価格別建玉残高（プット/コール、当日・前日比）を取得し、Streamlitで可視化する。

## データソース

- [当日取引高等](https://www.jpx.co.jp/markets/derivatives/trading-volume/index.html) 内の
  「デリバティブ建玉残高表」（`*open_interest.xlsx`、毎営業日20:00頃更新）
- ファイルの別紙1＝日経225オプション（通常）、別紙2＝日経225ミニオプション、権利行使価格別
- ダウンロードURL（コンテンツID部分）は日によって変わるため、`fetch_open_interest.py` は
  毎回トップページを読んでリンクを見つけ直す
- **過去分の履歴はJPX側にアーカイブが無い**（1日分＝前日比のみ）。複数日の推移を見るには、
  このスクリプトを毎日実行してdata/に蓄積していく必要がある（GitHub Actionsで自動化）

## 使い方

### ローカル実行
```bash
pip install -r requirements.txt
python fetch_open_interest.py   # data/oi_YYYYMMDD.csv を作成
streamlit run app.py
```

### 自動更新（GitHub Actions）
`.github/workflows/fetch_daily.yml` が平日21:00 JST（JPX掲載予定20:00の後）に
`fetch_open_interest.py` を実行し、`data/` の新しいCSVを自動コミット・プッシュする。
リポジトリの Settings → Actions → General で "Read and write permissions" を
有効にしておくこと（`GITHUB_TOKEN` によるpushに必要）。

手動実行: Actions タブ → "Fetch daily open interest" → "Run workflow"

### Streamlit Cloud
1. このリポジトリをGitHubにpush
2. [Streamlit Cloud](https://streamlit.io/cloud) で `app.py` を指定してデプロイ
3. GitHub Actionsが`data/`を毎日更新するたびに、Streamlit Cloud側も自動で再デプロイされる
   （リポジトリ更新をトリガーに再起動する設定になっている場合）

## ダッシュボードの機能
- 権利行使価格別の建玉残高（プット/コール色分け棒グラフ）
- 自分のポジション（プット買/売・コール買/売の権利行使価格）を縦線で重ねて表示
- 前日比の建玉増減（上位20銘柄）
- 複数日分蓄積された場合の、選択ストライクの建玉残高推移

## 制約・注意点
- 建玉残高は「概算」（JPXファイル自身に "（概算）" と明記）であり、確定値ではない
- 権利行使価格グリッドは限月・商品ごとに異なる（通常は250円刻み、ミニは125円刻み）
- ミニオプションの限月コード（例: `260820`）はJPXの内部コードをそのまま表示している
  （必ずしも直感的な曜日と一致しないため、正確な満期日は各自SBI証券等の銘柄一覧で確認すること）
