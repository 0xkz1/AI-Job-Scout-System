# Jevで選ぶ応募文 — 実績選択と多言語条件の修正

追記（2026-10-12）：[JIS本体への試験導入と実行経路での比較](JEV_PIPELINE_TRIAL_2026-10-12.md)を実施。
以下は10月11日の隔離試作時点の記録。

[前回のMD](JEV_PREPARED_LETTERS_2026-10-11.md)に残した、求人に合わない実績が入る問題と、日本語・ドイツ語の求人で候補が消える問題を修正した。
隔離worktreeでの試作で、既存の本番生成処理への接続はまだ行っていない。

固定の自己紹介・実績の原文と、v2の9種類の接続文は変更していない。
今回変えたのは、どの素材と接続文を候補にするかという条件。Jevは文章を生成せず、候補IDまたは `none` を返す。

## 解決した点

| 前回の課題 | 今回の変更 |
| --- | --- |
| LEGO向けに画像タグ付けの実績が入る | 旧処理では `visionary` が `vision` に部分一致していた。試作の実績選択を職名・主業務に沿う処理へ変更し、TAIFU modeのCanvas・Web AudioとWeb制作の実績を使う |
| Staysure向けにe-commerceの実績が入る | 会話設計をUXに関連する選択枠へ振り分け、Asset Weaverのオンボーディング・エラー復旧と、ポートフォリオのアクセシブルなUIを使う |
| ブランド等の付随語だけで接続文が候補になる | 会話設計、Web、AIワークフロー等の主業務の枠を追加。会話設計ではブランド用・汎用連携用の接続文を除外する |
| 日本語・ドイツ語の求人で候補が消える | 職名と候補の条件を拡張。日本語のProduct Designer・Webフロントエンドと、ドイツ語のGrafikdesignerで候補が得られることを確認した |
| 用意した素材の範囲外でも汎用応募文ができる | ASIC等のハードウェア設計、ライフガード等では完成応募文を作らず、素材・選択枠の不足を記録する。JevのAPIも呼ばない |
| PDFの見た目が未確認 | LEGO・Staysureの草案を既存の共通レンダラーでPDF化。各1ページ、本文文字の保持、改ページ・文字切れ・重なりがないことを確認した |

実績選択はPythonの条件で行う。これも人間が確認する必要のある選択方針で、職種への適合を自動的に証明するものではない。
固定素材の職種条件と出典IDを維持し、その条件を満たす原文だけを組み立てる。

## 同じ40求人での測定

初回の求人名・会社名・求人本文が40件すべて一致するスナップショットを使用した。
実績と候補の選択条件が変わったため、完成本文は初回と異なる。

| 結果 | 初回v1 | 修正後v3 |
| --- | ---: | ---: |
| 暫定条件を満たして候補を選択 | 10 | 14 |
| 判断が曖昧で保留 | 16 | 12 |
| Jevが該当なしを選択 | 6 | 2 |
| Pythonの条件で候補なし | 8 | 12 |
| 合計 | 40 | 40 |

修正後の候補なし12件は、用意した実績・選択枠の範囲外として応募文を作らなかった求人。
これは求人自体への応募可否の判定ではなく、この試作の素材が足りないという記録である。
候補を選択した件数が増えたことも、文章品質が向上した正解率としては扱わない。

API呼び出しは28回、すべて `jev-1.13.0` の有効な回答。失敗0、SDK再試行0。
中央値 **0.1723秒**、p95 **0.2253秒**、累計 **5.0306秒**。
入力55,810トークン、出力1,333トークン。生成LLMへの呼び出しは **0回**。
時間はJev呼び出しの測定で、同品質でMistralを置き換えた速度比ではない。

confidence 0.60、確率差0.10の暫定条件は変更していない。
保留・該当なしでは中立の固定文を使う。すべての草案は `review_required: true`。

[測定結果](../10_output/_worktrees/jev-project-selector-20261008/10_output/jev_letter_bridges_v3_live_20261011/summary.json) ·
[求人・素材・候補・実行コードのハッシュ](../10_output/_worktrees/jev-project-selector-20261008/10_output/jev_letter_bridges_v3_live_20261011/manifest.json) ·
[照合結果](../10_output/_worktrees/jev-project-selector-20261008/10_output/jev_letter_bridges_v3_live_20261011/audit.json)

## LEGOとStaysureの現在の状態

両件とも実績を修正したが、接続文の選択は引き続き保留。

| 求人 | Jevの首位候補 | 候補の確率 | confidence | 完成草案に入れた文 |
| --- | --- | ---: | ---: | --- |
| LEGO Creative Technologist | interactive_prototypes | 0.79 | 0.58 | 中立文 |
| Staysure AI Conversational Designer | conversation_testing | 0.66 | 0.55 | 中立文 |

LEGOの物理的・遊びの試作や子どもとのテスト、Staysureの会話フロー・対話管理・音声サービスの納品経験は未確認。
Webの実績をその経験として書き換えていない。この不足は評価入力と草案のメタデータにも記録した。
「I would」で述べる候補文は将来の提案であり、過去の実績を証明しない。

- [LEGOの完成草案](../10_output/_worktrees/jev-project-selector-20261008/10_output/jev_letter_bridges_v3_live_20261011/case_17_CL_en_DRAFT.md) · [PDF草案](../10_output/_worktrees/jev-project-selector-20261008/10_output/jev_letter_bridges_v3_live_20261011/case_17_DRAFT_CL.pdf)
- [Staysureの完成草案](../10_output/_worktrees/jev-project-selector-20261008/10_output/jev_letter_bridges_v3_live_20261011/case_32_CL_en_DRAFT.md) · [PDF草案](../10_output/_worktrees/jev-project-selector-20261008/10_output/jev_letter_bridges_v3_live_20261011/case_32_DRAFT_CL.pdf)
- [修正前後の実績、求人全文、候補文の比較](../10_output/_worktrees/jev-project-selector-20261008/10_output/jev_letter_bridges_v3_live_20261011/LEGO_STAYSURE_REVIEW.md)

## 検証と残る確認

関連テスト **113 passed**。`visionary` の誤一致、会話設計の実績、日本語・ドイツ語、対象外職種、候補外回答・自由文の混入を確認した。
28通すべてで本文が固定本文＋候補原文と一致し、自己紹介・実績・出典も照合できた。本文316〜381語で、250〜400語の予算内。
本番CL/CVソースの作業前後のハッシュは一致。固定素材も初回スナップショットと一致した。

残るのは、候補文と実績の組み合わせの人間による承認、選択条件の校正、本物のMistral Mediumとの同品質比較。
人間の正解ラベルはまだ0件。[40件の確認用CSV](../10_output/_worktrees/jev-project-selector-20261008/10_output/jev_letter_bridges_v3_live_20261011/human_review.csv)を用意し、承認欄は空欄にした。
推奨候補または `none`、実績の関連性、主張の根拠、完成文の使用可否を記入してから、Jevの判断と比較する。
前回のモデル比較では要求名と実際の応答モデルが一致していなかったため、Mistralとの実測比較として扱わない。

この範囲では、Mistralが担っていた接続文の自由生成を呼ばずに草案を組み立てられる。
人間の承認・素材不足の解消・L3の事実確認は引き続き必要。本番接続、応募、コミット、pushは未実施。

実装: [実績選択](../10_output/_worktrees/jev-project-selector-20261008/letter_evidence_selector.py) ·
[候補バンクv3](../10_output/_worktrees/jev-project-selector-20261008/letter_bridge_candidates.json) ·
[Jev選択部品](../10_output/_worktrees/jev-project-selector-20261008/jev_letter_bridge_selector.py) ·
[評価・草案組み立て](../10_output/_worktrees/jev-project-selector-20261008/evaluate_jev_letter_bridges.py)
