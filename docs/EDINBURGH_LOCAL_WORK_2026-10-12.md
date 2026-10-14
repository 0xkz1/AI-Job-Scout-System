---
type: implementation-report
status: integrated-validated
updated: 2026-10-12
language: ja
---
# Edinburghの事務・倉庫・キッチン求人をJISに追加

ユーザーのL2許可に基づき実装・検証し、その後の明示承認を受けて稼働中のJISへ差分を反映済み。反映後の関連テスト337件がすべて成功（スキップなし、126.80秒）。
独立worktree: `/home/kz003/.codex/worktrees/52cd/Job-Intelligence-System`
ブランチ: `loop/edinburgh-local-20261012`。push・merge・応募送信は行っていない。

## 検索対象

Edinburgh限定でAdministrator、Business Support、Operations Assistant、Warehouse Operative、Parcel Sorter、Removals Porter、Kitchen Porter、Stock Assistantの8語を追加。既存36組から44組へ、LinkedInの既存Japan検索を含める場合は54組へ増加する。ローカル職をJapan検索には追加しない。

Reedは取得深度を3から2ページに調整。測定済みの処理速度で44検索×3ページは約2578秒となり2200秒の制限を超えるため。2ページでは約1719秒で、全検索語を維持する。3ページ目以降の求人は取得範囲から外れる。他サイトの取得深度は変更しない。実行時間は予測であり次回実行の完了を保証するものではない。

## 判定とCV

タイトルに一致するローカル職のみ年収£26,000の下限を適用しない。時給や短時間勤務を従来の年収下限で落とさないための変更。Senior、Driver、臨床職等の既存除外は維持。本文の倉庫等への言及だけでは例外にならない。Systems / Network / Database等の技術系Administratorにも例外を適用しない。

|区分|共有CV|
|---|---|
|事務・業務支援|[Business Administration](../../cv/CV_Business-Administration.md)|
|倉庫・荷物仕分け・引っ越し補助・品出し|[Warehouse / Manual Work](../../cv/CV_Stock-Replenishment.md)|
|キッチンポーター|[Kitchen Porter](../../cv/CV_Kitchen-Porter.md)|

2026-10-12、ユーザーの指示に従いテンプレート保管先を既存の `career/cv/` と `career/cover-letter/` に統一。JISの参照先も `career/cv/CV_*.md` に変更済み。旧 `_Casual_Kit` は記録・PDF作成ヘルパーと案内のみを保持する。

マッチレポートに職種区分と共有CVリンクを保存。関連性の評価時にも確認済みの実務経験を参照する。求人一覧・順位には残し、技術職向けCV／レターの生成枠とHermes自動レビュー枠から除外する。人が共有CVを選んで応募する流れ。自動応募は追加していない。

## 検証

関連テスト328件成功、既存データ依存の9件スキップ。確認した内容は、タイトル判定、給与下限の限定的な例外、技術系Administratorと運転・上位職の除外、Edinburgh限定検索、時間予算、共有CVへのリンク、確認済み職歴の参照、応募済み／失効フラグの保持、生成・レビュー枠を使わない動作。Hermes bridgeのdry-run／generate-only／review-onlyの各経路で、ローカル求人の文書生成・レビュー登録を防ぐテストも成功。

実装時は独立worktreeで328件成功・9件スキップ。統合後は実データがある稼働ディレクトリでも337件すべて成功し、スキップはなかった。全件のライブ収集・次回nightlyの実行結果は未確認。
既存の稼働環境の未コミット変更を保持し、今回の差分だけを統合した。反映対象9ファイルは検証済みworktreeとバイト単位で一致。
既存のnightlyスクリプトが稼働ディレクトリの `run.py` と設定を読むことを確認。次回の通常実行から対象に含まれる。
反映前のバックアップ：`/tmp/jis-local-integration-backup-20261012/`。
レビュー用差分: `docs/EDINBURGH_LOCAL_WORK_2026-10-12.patch`。

[求人10件・CV一式の調査レポート](../../2025-2026_Edin/Casual_Jobs_Research_2026-10-12.md)

保管先修正後の確認：ローカル求人関連39テスト成功、調査レポートのローカルリンク11件は全件解決。既存ヘルパーの3カテゴリとPDF出力経路を一時ディレクトリで検証済み。テンプレートと書き出し15ファイルは内容を変更せず移動した。


## 追加監査：最初のテストが見逃していた問題

ユーザーの「本当に、不具合ない？」を受けて経路を追い直し、次の問題を再現・修正した。

|問題|修正|
|---|---|
|共有CVが本文だけにリンクされ、既存のCV欄／PDF画面ではCVなし扱い|標準の `cv` プロパティにも保存し、PDF画面から作成済み共有CVを直接ダウンロードできるようにした。共有CVは自動レビュー・求人別再生成の対象にしない。|
|Festive Colleague、Warehouse Operatives、Kitchen Porters等の名称を取りこぼす|単複の表記とFestive Colleagueを対象に追加。スクレイパー共通のキーワード選別でも、ローカル職の検索がある場合に限りこれらの名称を保持する。検索語・地域の44組は増やしていない。|
|地域指定を無視するサイト／Adzuna APIから遠方のローカル求人が混ざる|既知の遠方勤務地をローカル職のフィルタで除外。Edinburgh・確認済み周辺地名とEH1–17／28–30の郵便地区を対象とする。Adzuna APIの追加職種は英国だけにし `where=Edinburgh` を渡す。勤務地不明は人の確認が必要。|

共有PDFがMarkdownより古い場合はダウンロードを提示せず更新を案内する。共有CVファイルがない場合は壊れたCVリンクを出さない。画面で多数のタイトルを再評価するときは設定を1回だけ読み込む。

追加の独立worktree検証：384件成功、9件データ依存スキップ。統合後は稼働ディレクトリで393件すべて成功、スキップなし（128.78秒）。
Streamlitの実行環境でも共有PDFダウンロードボタンを1つ描画でき、例外は0件だった。
API地域指定は[Adzuna公式検索仕様](https://developer.adzuna.com/docs/search)を確認し、HTTPリクエストに `where` が入るテストを実施した。APIの実データ取得は行っていない。

初回統合の差分は `EDINBURGH_LOCAL_WORK_2026-10-12.patch`。
今回の修正差分は `EDINBURGH_LOCAL_WORK_AUDIT_2026-10-12.patch`。
追加修正前のバックアップは `/tmp/jis-local-audit-preimages-20261012/`。

テスト成功はサイト側の将来のDOM変更やアクセス制限、全夜間処理の完了を保証しない。
次回nightlyの実際の件数・実行時間は未確認。採用枠、勤務時間、通勤ルートも人の確認が必要。

10月13日の実行後の問題・補修・未解決項目は[追加監査](EDINBURGH_LOCAL_WORK_FOLLOWUP_2026-10-13.md)を参照。
