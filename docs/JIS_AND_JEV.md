# JIS × Jev: System One 型安全セマンティック判定アーキテクチャ

> 作成日: 2026-09-20  
> 対象リポジトリ: `00_Kazuki/career/Job-Intelligence-System`  
> 関連仕様: [EXPANSION_2026-08-29.md](../EXPANSION_2026-08-29.md), [loop-budget.md](../loop-budget.md), [ARCHITECTURE.md](../ARCHITECTURE.md)

---

## 1. 概要と背景

Job Intelligence System (JIS) は、求人検索・解析・フィルタリング・マッチング・書類生成（CV/CL）を行う自律的キャリア支援基盤である。

JISはこれまで、生成AIのハルシネーションやフォーマット崩れ、推論遅延、人物像のブレといった課題に対抗するため、**「確定的Pythonコードが主、LLMは局所的補助」**という徹底した Code-First 思想で構築されてきた。

しかし、一晩のバッチ処理（Nightly Scout）において、依然として従来の自己回帰型LLM（Mistral-medium, Groq, Claude）を呼び出している箇所がボトルネックとなっている。

ここへ **TypeSafe AI の System One モデル「Jev」** を導入することで、JISの基本思想を完全に維持したまま、推論レイテンシを10〜20倍高速化し、LLMトークン消費を激減させることが可能となる。

---

## 2. 現状のボトルネック（実測値）

`loop-budget.md` に記録されている実測データは、従来のチャット型・テキスト生成型LLMをバッチ処理に組み込んだ際の歪みを如実に示している：

| 指標 | 現行の実測値 (Nightly Scout) | 原因 |
|---|---|---|
| **呼び出し回数** | 一晩で **614 calls** (`analyzer` 単体) | 求人ごとの職種分類・タイトル救済判定 |
| **中央値レイテンシ** | **18.5秒 / call** (Mistral-medium) | 自己回帰的テキスト生成・JSON構築オーバーヘッド |
| **LLM総消費時間** | 一晩で **16,293秒（約4.5時間）** | 夜間バッチ全体の62%を占有 |
| **品質・安定性** | スキル抽出漏れ（Groq 76件 vs Mistral 40件）、パースエラー | プロンプト表現の揺らぎ、マークダウン装飾崩れ |

---

## 3. 思想の完全一致: JIS × Jev

Jevは文章生成（System Two）ではなく、**「型付けされた判定と確率分布（System One）」** を返すマイクロモデルである。この特性は、JISの既存アーキテクチャ設計と100%合致する。

```
┌────────────────────────────────────────────────────────────────────────┐
│                        JIS Core (Python Code)                          │
│   - Scraping / Deduplication (URL, jk)                                 │
│   - Exact Rule Filtering & Salary Band Math (EXPANSION §E)             │
│   - State & Workflow Control                                           │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
                                    ▼
       ┌─────────────────────────────────────────────────────────┐
       │   Jev (System One / TypeSafe AI)                        │
       │   - Sub-second Latency (200-500ms)                      │
       │   - Typed Decisions (Choice / Noul / Score)             │
       │   - Calibrated Probabilities (Confidence)               │
       │   - Output Token Cost ≈ 0                               │
       └─────────────────────────────────────────────────────────┘
```

- **Code owns the workflow**: パイプライン制御、給与計算、しきい値判定はすべてPythonコードが握る。
- **Filter, Not Persuasion**: 候補者の実績や語り口をLLMに勝手に生成させず、確定ファクトの選択と照合に徹する。
- **Calibrated Decisions**: 単なる0/1ではなく、統計的に調整された確率（Confidence）を得ることで、境界線の求人を安全側に倒す制御が可能。

---

## 4. Jev プリミティブの具体的適用先

### ① `Noul`（二値確率判定）
- **ビザ・スポンサーシップ判定 (`filter.py` / `invariants.py`)**
  - 入力: 求人票のビザ・労働許可関連センテンス
  - 判定: `sponsorship_available` (0.0 〜 1.0)
  - 制御: `prob >= 0.8` で提供あり、`0.4 <= prob < 0.8` で人間確認フラグ、`prob < 0.4` で不問/除外。
- **Title Relevance Rescue (`analyzer.py`)**
  - 入力: 未知の職種タイトル + 会社概要
  - 判定: 「Creative Technologist / Hybrid Dev の領域に属するか？」
  - 効果: 重いLLM呼び出しなしに、ホワイトリスト漏れの優良求人をサブセカンドで救済。
- **Citation Check / Invariants Verification**
  - 入力: ドラフト文書の一文 + `letter_facts_v1.md`
  - 判定: 「この主張はマスターデータに根拠があるか？」

### ② `Choice`（多クラス候補選択）
- **Role Family / Ladder 分類 (`cv_generator.py`)**
  - 候補: `[core_design, creative_technology, hybrid_design_dev, bridge]`
  - 効果: キーワード頻度カウント（タイトル×10、本文×1）の誤爆を解消し、文脈から最適なプロファイルを単一パスで選定。
- **Seniority / Level Fit 判定**
  - 候補: `[entry, mid, senior, lead]`
  - 効果: 単語マッチ（"junior art director" vs "senior art director"）の誤判定を防止。

### ③ `Score`（順序付きキャリブレーション・スコアリング）
- **Semantic Match Score (`matcher.py` / `reviewer.py`)**
  - 尺度: 0（無関係）〜 3（強み・専門性の完全一致）
  - 効果: LLMに「0〜100の点数を言わせる」プロンプトハックを全廃。確率加重平均された滑らかな float 値を直接受け取り、`EXPANSION §E` の確定合成式に安全に流し込む。

---

## 5. 境界線: Jevに委ねてはいけない領域

JISの堅牢性を保つため、以下の領域は Jev および LLM を排除し、決定論的コードを維持する：

1. **完全ルール化・数値計算可能な領域（Ponytail原則）**
   - 給与計算（`salary_gain`）、契約月数計算（`runway_fit`）
   - URL/jk による重複排除
   - コールドメール作成（`email_outreach.py` の「LLM不要、完全テンプレート」原則）
2. **純粋な自然言語文章の生成領域**
   - カバーレターの **Context Bridge（35〜60語の糊付け文）**。Jevは文章生成器ではないため、この局所的な文面作成のみ軽量な生成LLM（または固定テンプレート）が担当する。

---

## 6. 導入効果の試算

| 評価軸 | 現行（Mistral / Groq） | Jev 導入後 |
|---|---|---|
| **推論速度** | 18.5秒 / call | **0.2〜0.5秒 / call（30〜90倍高速）** |
| **夜間バッチ時間** | 約4.5時間（614 calls） | **約5〜10分** |
| **トークン消費** | 入出力ともに大量消費（Mistral Key枯渇リスク） | **出力トークンほぼゼロ、入力スキーマ最小化** |
| **フォーマットエラー** | マークダウン太字崩れ、JSONパース失敗によるリトライ | **SDK型保証により原理的にゼロ** |
| **保守性** | プロンプト職人芸・正規表現パーサーのメンテが必要 | **Criteria/Instructions の定義のみで完結** |

---

## 7. Hermes Profile × Jev: 「反射神経（System 1）」と「深い思考（System 2）」

### 構造的本質：なぜモデルを入れ替えるのではなく「共鳴」させるのか

- **Jev (TypeSafe AI) = 反射神経（System 1）**
  - 出力: `Choice` / `Noul` / `Score` という型付き確率値のみ（テキストは生成しない）。
  - 特徴: サブセカンド（200〜500ms）、トークン消費ほぼゼロ、確定的な境界線判定。
- **Hermes Profile = 深い思考（System 2）**
  - 出力: 自然言語推論、ツール実行（Tool Calling / ReActループ）、書類の精読と批評。
  - 特徴: 思考と対話の自律ループ。人間への具体的なアドバイスやコード修正の提案。

### モデル割り当ての可否と設計結論

1. **Jev を Hermes のメインモデル（頭脳）に割り当てることはできるか？**
   - ❌ **不可能・破綻する**。Hermes は会話ループや Tool Call JSON を生成する Chat Completions モデルを前提としており、テキストを生成しない Jev はエージェントのメインブレインとしては動作しない。
2. **Hermes と Jev の相性は良いのか？**
   - ⭕ **道具（Tool/Skill）および前段フィルター（門番）として最高に相性が良い**。
   - 現在の Hermes が 429 エラーやトークン枯渇を起こす主因は、**「本来反射神経（System 1）で済む判定まで、すべて重い LLM の推論ループ（System 2）で処理させていること」** にある。

### 協調アーキテクチャ（2つの連携パターン）

```
┌─────────────────────────────────────────────────────────────┐
│ 【L1】Jev (System One: 反射神経 / 数ミリ秒 / 無料・極小コスト)│
│  - 求人票の職種分類（Choice: Graphic vs Web vs AI）          │
│  - 応募要件の事実判定（Noul: 経歴と一致しているか？）          │
│  - ドキュメントの適合度採点（Score: 0.88）                    │
└──────────────────────────────┬──────────────────────────────┘
                               │ 型安全な判定（PASS / Score）
                               ▼
┌─────────────────────────────────────────────────────────────┐
│ 【L3】Hermes Profile (System Two: 熟慮・自律エージェント)    │
│  @review-editor                                             │
│  - Jev の判定（PASS / Score: 0.88）を前提として受け取る       │
│  - 「求人の文脈と Kazuki の哲学をどう響き合わせるか」という   │
│    高度でクリエイティブな人間向けアドバイスだけを執筆・記録   │
└─────────────────────────────────────────────────────────────┘
```

1. **門番パターン（事前フィルタリング / 推奨）**:
   - `jis_hermes_bridge.py` が L1 で Jev を叩き、要件不一致やフォーマット不整合を 0.1 秒で足切り。
   - 合格ラインに達した案件のみ Hermes Kanban に起票してエージェントを起動。無駄なタスク起票をゼロにする。
2. **手足パターン（Hermes Skill / Tool）**:
   - Hermes エージェントのツールセットに `jev_judge` を配備。
   - `@review-editor` が監査する際、自分で長文を読んで迷う代わりに「Jev ツール」を叩いて事実整合性の確率値（0.99）を瞬時に取得する。

