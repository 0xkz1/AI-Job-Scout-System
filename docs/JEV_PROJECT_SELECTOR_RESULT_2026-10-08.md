# Jev CV選択器の試作結果 — 2026-10-08

L2の許可を受け、専用worktreeに独立した選択器と評価コマンドを作成した。

40求人・各12プロジェクトの実API評価は全件成功。中央値0.1998秒、p95 0.2537秒。
過去のCV生成ログの中央値10.66秒に対して約53倍の速度差がある。
同一求人を既存LLMで再測定した比較ではないため、参考値として扱う。

原文をPythonで組み立て、全40件で既存の英日CVレンダラーとの一致を確認した。
関連テストは52 passed、3 skipped。

保存済みCVを比較できた18件の採用実績との重なりは76.4%、
編集ルール適用前は69.0%。これらは人間の正解ラベルに対する精度ではない。
26/40件で4位と5位の点差が0.05以下だったため、本番の自動選択にはまだ接続していない。

- [詳細な測定・選択差分・再実行方法](../10_output/_worktrees/jev-project-selector-20261008/docs/JEV_PROJECT_SELECTOR_RESULT_2026-10-08.md)
- [選択器の実装](../10_output/_worktrees/jev-project-selector-20261008/jev_project_selector.py)
- [評価コマンド](../10_output/_worktrees/jev-project-selector-20261008/evaluate_jev_projects.py)

ブランチ: `experiment/jev-project-selector-20261008`。
既存のJISソース、環境設定、CVは変更せず、試作と測定記録はworktreeに保持している。

2026-10-09の[文章内容レビュー](JEV_CONTENT_REVIEW_2026-10-09.md)で、英日80出力の原文一致を再確認した。TAIFUNOMEの優先方針の扱いと、会話AI・試作職での実績選択には内容上の懸念がある。原文保持は完成文書の品質を保証するものではない。

その後、隔離版の選択規則とCV組み立て経路を修正した。同じ40求人の再評価は中央値0.2126秒、全件成功。
完成CV日英80本と、LEGO・Staysure向けの編集草案を確認した。関連テストは76 passed、3 skipped。
[後続の修正・確認結果](JEV_CONTENT_FIX_2026-10-09.md)。
