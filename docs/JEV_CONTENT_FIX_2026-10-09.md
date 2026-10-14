# Jev試作の内容修正と完成文書の確認 — 2026-10-09

TAIFUNOMEの優先規則と、求人の中核業務を軽く扱う選択基準を修正した。
同じ40求人で再評価し、日英80本の完成CVを作成・照合した。
LEGOとStaysureには、実績の重複やレターとのつながりを見直した日英CV計4本と、英語レター2本を別途用意した。

今回確認できたのは、選択と原文の組み立てを分けることで、新しい実績を捏造せずに草案を作れること。
Jevによる自動選択だけで、応募文書の内容が適切になるとは言えない。
選択・採点の部分でMistral等への依存は減らせるが、説明文の執筆と完成文書の編集・事実監査は残る。

## 実装した修正

変更先は隔離ブランチ `experiment/jev-project-selector-20261008`。
本番の `cv_generator.py`、`matcher.py`、既存の応募文書には変更を加えていない。

| 対象 | 修正 | 目的 |
| --- | --- | --- |
| Jev選択器 | TAIFUNOMEを原則先頭にする。守備範囲外の例外は、点数ではなく明示的な `taifunome_out_of_scope=True` で指定する | 0.92という未校正の数値だけで主たる活動が消える問題を解消 |
| Jevへの質問 | イラスト・3D概念制作と実際に試せるプロトタイプ、LLM自動化と会話フロー・対話管理の実績を区別する | 共通のキーワードだけで中核業務の実績とみなさない |
| 隔離版CV生成 | 明示した既知のプロジェクトIDを原文から組み立てる経路を追加。余白埋めの追加選択を行わない | 選択から外した実績が、完成CVで再び詳述されるのを防ぐ |
| 確認情報 | 草案に確認必須の印と、直接の根拠が弱い場合や順位の境界が近い場合の注意を記録 | 点数を文章品質の合格判定にしない |

[選択器](../10_output/_worktrees/jev-project-selector-20261008/jev_project_selector.py)、
[隔離版CV生成](../10_output/_worktrees/jev-project-selector-20261008/cv_generator.py)、
[完成CVの組み立てコマンド](../10_output/_worktrees/jev-project-selector-20261008/assemble_jev_cv_previews.py)。

## 同じ40求人での再評価

元の入力スナップショットを再使用し、`jev-1.13.0` の新しい質問・編集規則で測定した。

- 40件中40件成功。失敗0件、SDK再試行0回。
- API応答の中央値 **0.2126秒**、p95 **0.3002秒**、累計8.8809秒。完成文書の編集時間を含む数字ではない。
- 入力284,492トークン、出力9,360トークン。既に確認した入力単価 $0.042/百万トークンでは、今回の再評価は約 **$0.01195**。
- 過去のCVがある18件との平均重なりは編集規則後85.6%、規則前78.7%。過去の選択との一致であり、品質向上や正解率を示すものではない。
- 40件すべてでTAIFUNOMEが先頭。15件で上位4件の構成が変わった。
- 35件は、選ばれた実績の最高点が「中核業務の一部を直接示す」段階の2を下回った。この注意は未校正の点数に基づくもので、候補者の能力不足や応募不可という判定ではない。

[測定結果](../10_output/_worktrees/jev-project-selector-20261008/10_output/jev_projects_v2_live_20261009/summary.json)、
[入力・出力の記録](../10_output/_worktrees/jev-project-selector-20261008/10_output/jev_projects_v2_live_20261009/results.jsonl)。
修正前の入力・出力・測定結果はそのまま保存してある。

## 文章を読んで調整した2件

以下のCVは私が実績の構成を編集した草案で、Jevの生の順位や人間の正解ラベルとしては扱っていない。
記録にある本文をそのまま使い、過去の経験を新しく書き足してはいない。

**LEGO Digital Play / Creative Technologist**

再評価ではFeral BestiaryとHive Floral Podが4件の詳述から外れた。
ただしAsset WeaverとAI Asset Taggerが並び、画像整理の実績が重複したため、
編集草案ではTAIFUNOME、Portfolio Website、Asset Weaver、Priority Orchestratorを選んだ。
インタラクティブなWeb体験と、実際に使えるツールの制作を示す構成にした。
レターは固定の自己紹介とTAIFUNOMEの事実ブロックを使い、求人への接続だけを書いた。
子どもと遊びを試した実績、電子工作・ロボティクス等の物理的試作経験は、この記録では確認できていない。

- [英語CV草案](../10_output/_worktrees/jev-project-selector-20261008/10_output/jev_projects_v2_review_20261009/case_17_CV_en_EDITORIAL_DRAFT.md)
- [日本語CV草案](../10_output/_worktrees/jev-project-selector-20261008/10_output/jev_projects_v2_review_20261009/case_17_CV_ja_EDITORIAL_DRAFT.md)
- [英語レター草案](../10_output/_worktrees/jev-project-selector-20261008/10_output/jev_projects_v2_review_20261009/case_17_CL_en_DRAFT.md)

**Staysure Group / AI Conversational Designer**

TAIFUNOMEが復帰した。編集草案ではTAIFUNOME、JIS、Portfolio Website、Asset Weaverを選び、
一般的なタスク優先順位付けの実績を、求人が求めるアクセシビリティの実績へ入れ替えた。
レターのアクセシビリティの事実ブロックと、CVの詳述も対応させた。
LLMワークフローとインターフェースの経験を今後の貢献として述べ、
顧客向けの会話・音声アシスタントを既に設計・運用したという主張はしていない。
会話フロー、対話管理、顧客向け本番運用の直接の実績は引き続き未確認。

- [英語CV草案](../10_output/_worktrees/jev-project-selector-20261008/10_output/jev_projects_v2_review_20261009/case_32_CV_en_EDITORIAL_DRAFT.md)
- [日本語CV草案](../10_output/_worktrees/jev-project-selector-20261008/10_output/jev_projects_v2_review_20261009/case_32_CV_ja_EDITORIAL_DRAFT.md)
- [英語レター草案](../10_output/_worktrees/jev-project-selector-20261008/10_output/jev_projects_v2_review_20261009/case_32_CL_en_DRAFT.md)

比較用GLMの説明4件にも編集案を用意した。不要な引用符、壊れたP2P表現、Figma能力を根拠なく低く扱う比較を見直した。
Henry Schein Oneのrole_fit 0.65は元の実測値として残し、説明との矛盾は要再確認とした。新しい数値は作っていない。
[説明文の編集案](../10_output/_worktrees/jev-project-selector-20261008/10_output/jev_projects_v2_review_20261009/reviewed_gateway_explanations.json)。

## 確認結果と限界

- 関連テスト **76 passed、3 skipped**。明示IDの検証、モデル選択と余白埋めの回避、日英の原文保持、既存の生成経路を確認。
- 自動選択から組み立てた80本のCVの314件の詳述を原文へ再照合。全件一致し、箇条書きの削除も0件。74本は4件、6本は3件の詳述で、3件への削減は既存の長さ調整による。
- 80本すべてで、プロフィール・職歴・技術欄・Other projectsを既存の生成結果へ照合。プロジェクトの重複、選択外の詳述、順序変更、連絡先プレースホルダー、空のリンクは検出されなかった。
- 英語本文の最大は1,103語、日本語本文の最大は5,440文字。現在の本文予算1,107語・5,450文字以内。PDFの実ページ数と見た目は今回未検証。
- 編集した日英CV4本の詳述も原文と全件一致し、本文予算内。レター2本は固定の自己紹介と選んだ事実ブロックを保持し、本文282語・322語で既存の250〜400語の範囲内。
- 草案の組み立て・編集では追加のJev/LLM API呼び出し0回。Jev自身は今回も文章を生成していない。
- 本番の2件のレターは修正前のハッシュと一致。固定の自己紹介、事実バンク、本番ソースは書き換えていない。

[80本のCV記録](../10_output/_worktrees/jev-project-selector-20261008/10_output/jev_projects_v2_review_20261009/audit.json)、
[編集CVの記録](../10_output/_worktrees/jev-project-selector-20261008/10_output/jev_projects_v2_review_20261009/editorial_cv_audit.json)、
[レターの記録](../10_output/_worktrees/jev-project-selector-20261008/10_output/jev_projects_v2_review_20261009/letter_audit.json)。

原文の一致は、元の実績の全主張を独立に事実確認したことを意味しない。
今回の文章はレビュー用の草案で、送信・応募・本番接続は行っていない。
Jevを選択・採点に使う構成は有望だが、完成文書に必要な実績の組み合わせや主張の妥当性は、引き続き編集と事実監査で確認する。
