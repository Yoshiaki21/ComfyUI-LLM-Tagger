# ComfyUI カスタムノード実装指示書：LLM Caption Generator（仮称）

## 0. 目的

既存の LoRA Caption Load → WD14 Tagger → LoRA Caption Save のパイプラインに割り込ませる形で、
WD14 Tagger のタグ出力と画像を Vision 対応 LLM（Lemonade Server 経由）に渡し、
学習用の「タグ＋自然言語キャプション」を生成する ComfyUI カスタムノードを実装する。

```
LoRA Caption Load ──┬── image list ────────────┐
                     └── (path/namelist) ───────┼── LoRA Caption Save
                                                 │        ↑ text
                          WD14 Tagger ── tags ───┤        │
                                                 │        │
                          [新規ノード] ───────────┴────────┘
                          (image list, tags) → (out_text)
```

---

## 1. ノード基本仕様

- **ノードクラス名**：`LLMCaptionGenerator`（表示名は日本語可、例：「LLM Caption Generator」）
- **カテゴリ**：既存の WD14-Tagger / Image-Captioning-in 系ノードと同じカテゴリ配下に配置
- **実装言語**：Python（既存 ComfyUI-WD14-Tagger フォークと同様の構成に準拠）

---

## 2. 入出力定義

### 2.1 入力（Inputs）

| 名前 | 型 | 必須 | 説明 |
|---|---|---|---|
| `image` | `IMAGE` | 必須 | LoRA Caption Load の image list から接続。バッチ（リスト）対応 |
| `tags` | `STRING` | 必須 | WD14 Tagger の文字列出力から接続。空文字の場合は該当画像を失敗扱い |
| `trigger_word` | `STRING`（ウィジェット直接入力） | 任意 | 空欄可。学習用途では入力、単純タグ/自然文抽出では省略可 |
| `system_prompt_file` | `STRING`（コンボボックス、動的） | 必須 | 指定フォルダ内の `.txt` 一覧から選択。ファイル冒頭のメタデータ行から`output_mode`を自動判定する（ウィジェットとしての`output_mode`は廃止。詳細は4章） |
| `lemonade_host` | `STRING`（ウィジェット） | 必須 | 例：`127.0.0.1` |
| `lemonade_port` | `INT`（ウィジェット） | 必須 | 例：`8000` |
| `lemonade_api_key` | `STRING`（ウィジェット） | 任意 | 将来の認証用。空欄可 |
| `model` | `STRING`（コンボボックス、動的） | 必須 | Lemonade Server から取得したモデル一覧（詳細は3章） |
| `enable_thinking` | `BOOLEAN` | 必須 | デフォルト `True`（常時ON運用想定だが切替可能にしておく） |
| `temperature` | `FLOAT` | 必須 | デフォルト `0.3` 程度、範囲 0.0〜2.0 |
| `max_tokens` | `INT` | 必須 | **初期値**。デフォルト `8192`。13.2/13.6の自動増量ロジックの起点として使用する（ウィジェット値そのものを固定上限として使うわけではない） |
| `timeout_sec` | `INT` | 必須 | デフォルト `120` |
| `max_retries` | `INT`（ウィジェット） | 必須 | デフォルト `3`。1画像あたりの最大試行回数（**初回送信を含む総試行回数**）。範囲 1〜10（下限1＝リトライなし、上限は暴走時の待ち時間が膨らむのを防ぐため10）。7.1の4分類はこのカウンタを共有する。**ノード上のウィジェット表示順は本表の位置ではなく `log_prompt` の次（`required` の末尾）**：ComfyUI は保存済みワークフローの `widgets_values` をウィジェット定義順で位置対応させるため、既存ウィジェットの間に挿入すると古いワークフローの値がずれるため【2026-08-23 追加】 |
| `always_regenerate` | `BOOLEAN` | 必須 | ON時は `IS_CHANGED` で毎回キャッシュ無効化 |
| `log_prompt` | `BOOLEAN` | 必須 | 既定 `False`。ON時のみ `logs/prompt.log` に送信内容と生応答を記録（7.3.1） |
| `image_names` | `STRING`（複数行、`optional`） | 任意 | ログに記録する画像ファイル名（改行区切り）。`LoRA Caption Load` の `namelist` 相当。未接続時は `image_001` 形式の連番をラベルに使う（7.3） |

### 2.2 出力（Outputs）

| 名前 | 型 | 説明 |
|---|---|---|
| `caption_text` | `STRING`（リスト） | 選択された`system_prompt_file`のメタデータ行が示す`output_mode`に応じた最終文字列（1画像1要素、image listと同じ順序・同じ枚数） |

※ `LoRA Caption Save` の `text` 入力へそのまま接続できるよう、リストの長さ・順序を `image` 入力と厳密に一致させること。

---

## 3. Lemonade Server 接続・モデル一覧取得

- OpenAI互換API（`/v1/chat/completions` 等）を想定し、`host:port` から `base_url` を組み立てる
- モデル一覧は `GET {base_url}/v1/models` 相当のエンドポイントから取得し、コンボボックスの選択肢とする
- **モデル一覧取得のタイミング**：ComfyUI の `INPUT_TYPES` はノード情報取得時（`/object_info`）に評価される。ブラウザの **F5リロードで再取得**される仕様のため、これに準拠する（サーバー起動中の動的Refreshボタンは今回のスコープ外）
- 接続失敗時は選択肢が空、またはエラー文言をリストに含める形でフォールバック（ComfyUI起動自体を止めないこと）

---

## 4. システムプロンプトファイル管理

- 指定フォルダ（例：`ComfyUI/custom_nodes/<node_dir>/system_prompts/`）内の `.txt` ファイル一覧をコンボボックスに表示
- モデル一覧と同様、**F5リロードで一覧を再取得**する仕様にする
- 用途別に以下3種類のプロンプトファイルを同梱すること（本指示書末尾のサンプルを初期データとして使用）：
  1. `caption_training_both.txt`（学習用・タグ+自然文両方、トリガーワード必須想定）
  2. `caption_tags_only.txt`（タグ抽出＋整合性チェック用）
  3. `caption_text_only.txt`（自然文のみ、トリガーワード条件付き）

### 4.1 `output_mode` の自動判定（メタデータ行方式）【2026-08-23 追加】

`output_mode`ウィジェットは廃止し、`system_prompt_file`の内容から自動判定する。ファイル冒頭に以下の形式でメタデータ行を1行だけ置く。

```
<!-- output_mode: both -->
（以降がLLMに送るsystem messageの本文）
```

- 値は `tags_only` / `caption_only` / `both` の3種類のみを許可する
- **ノードはファイル読み込み時にこの1行を解析し、`output_mode`として内部変数に保持したうえで、この行自体を取り除いてから system message として LLM に送信する**（LLMにメタデータ行を見せない）
- メタデータ行が無い、または値が3種類以外の場合：ComfyUI起動自体を止めず、該当ファイルをコンボボックスの選択肢から除外するか、選択された場合はそのファイルを**即座に失敗扱い**にしてログに `INVALID_PROMPT_FILE: <filename> reason=missing_or_invalid_output_mode_header` を記録する（実装しやすい方を採用してよい）
- 同梱する3種類のサンプルファイル（10章）には、それぞれ対応する`output_mode`のメタデータ行を付与済みとする

#### 4.1.1 実装結果【2026-08-23 実装・検証済み】

- `parse_system_prompt_file(filename)` を追加。戻り値は `(output_mode, system_message)` で、**メタデータ行を取り除いた本文だけ**を system message として返す（除去後に先頭へ残る空行も落とす）
- 判定は正規表現 `^\s*<!--\s*output_mode\s*:\s*([A-Za-z_]+)\s*-->\s*$` を**1行目のみ**に適用する。前後の空白や `<!--` 内の空白の揺れは許容するが、2行目以降に書かれていても認識しない
- **異常系は 4.1 の選択肢②（実行時に失敗扱い）を採用**した。コンボボックスからは除外せず、選択して実行した時点で失敗させる（除外方式だとファイルが黙って消え、原因が分からなくなるため）
  - `output_mode` が `None`（メタデータ行なし／値が3種類以外／ファイルが読めない）のとき、`INVALID_PROMPT_FILE: <filename> reason=missing_or_invalid_output_mode_header` を `log.log` と `error.log` に記録し、**その実行の全画像を LLM 呼び出し前にスキップ**する（7.2 の `empty_tags` と同じ扱い）
  - 各画像には `SKIPPED: <label> reason=invalid_prompt_file` を記録し、`caption_text` には空文字を入れて枚数・順序を維持する（9章）
  - ファイル読み込み時の `OSError` も握りつぶして `None` を返すため、**ComfyUI 自体は止まらない**
- 7.4.1 の設定値サマリ行では `mode=` に判定結果を出力する（不正時は `mode=INVALID`）
- **検証結果**：
  | 入力 | 判定 |
  |---|---|
  | `<!-- output_mode: both -->` ほか同梱3ファイル | `both` / `tags_only` / `caption_only`。本文に `output_mode` 行が残っていないことを確認 |
  | メタデータ行なし | `None`（失敗扱い） |
  | `<!-- output_mode: whatever -->` | `None`（失敗扱い） |
  | 空ファイル | `None`（失敗扱い） |
  | 2行目にメタデータ行 | `None`（1行目のみ判定するため） |
  | `   <!--   output_mode :  both   -->   ` | `both`（空白の揺れは許容） |
  | 存在しないファイル | `None`（例外を出さず失敗扱い） |
  - 実機で3モードすべてを実行し、`mode=both` / `mode=tags_only` / `mode=caption_only` が自動判定されて正しい形式の文字列が出力されることを確認
  - `prompt.log` に `output_mode` の文字列が **0件**であること（メタデータ行がLLMに送られていないこと）を確認
  - メタデータ行なしのファイルを2枚バッチで選択 → `INVALID_PROMPT_FILE` を記録して2枚ともスキップ、出力は空文字2件で枚数維持

---

## 5. LLMへのメッセージ構築

### 5.1 画像前処理
- 長辺が1024pxを超える場合のみ1024pxにリサイズ（アスペクト比維持）。既に1024px以下の学習用画像はそのまま使用可
- PNGまたはJPEGでbase64エンコードし、画像パートとして送信

### 5.2 メッセージ構成（固定テンプレート、コード側で組み立て。ユーザーが編集する必要はない）

**system message**：選択された `.txt` ファイルの内容をそのまま使用

**user message（テキスト部）**：

トリガーワードが入力されている場合：
```
Trigger word: {trigger_word}
Candidate tags from WD14 (verify against the image, correct as needed):
{tags}
```

トリガーワードが空欄の場合：
```
Candidate tags from WD14 (verify against the image, correct as needed):
{tags}
```

**user message（画像部）**：base64エンコード済み画像（上記テキストと同一 user message 内に画像パートとして含める）

#### 5.2.1 `parse_format` 失敗時の訂正指示【2026-08-23 追加・実装済み】

**背景**：`---`区切りが無いフォーマット崩れ（`parse_format`）が起きた際、13.2 の temperature 上昇・`max_tokens` 縮小だけでは同じ失敗パターンが3回とも再現し、リトライが実質的に機能しない事例を実運用ログで確認した。temperature の調整はランダムな揺さぶりに過ぎず、モデルに具体的な訂正内容を伝えていないため。

**仕様**：直前の試行の失敗理由が `parse_format` だった場合のみ、リトライ時の user message（テキスト部）の**末尾に改行して**以下を追記する。

```
Note: Your previous response did not follow the required output format. Output PART 1 (the corrected tag list) first, then a line containing only "---", then PART 2 (the natural language sentences). Do not swap the order of the two parts, and do not output the section headings themselves (no "PART 1 ...:" or "PART 2 ...:" line) — output only the tags, the "---" line, and the sentences.
```

> **【2026-08-23 更新】** 6.1.2 の順序崩れ（パターンB）も `parse_format` として本訂正指示の対象になるため、文言を「`---` が無い」ことに限定せず、**順序と見出し**もあわせて訂正する内容に変更した。

- **追記するのは直前が `parse_format` の場合のみ**。`timeout` / `connection` / `parse_length` はフォーマットの問題ではないため追記しない
- 2回連続で `parse_format` が続いた場合も**毎回この固定文言を追記する**（前回効かなかったことへの言及は不要）
- 画像パート・トリガーワード行・タグ行の**構成順序は変更しない**。訂正指示は末尾に追記するのみ
- 13.2 のパラメータ調整（temperature 上昇・`max_tokens` 縮小）は**そのまま維持して併用**する。訂正指示は user message への追加であり、パラメータ調整とは独立した対処
- 13.6（`parse_length` 時の `max_tokens` 倍増）には影響しない
- **【実装時の判断】訂正文は `---` 区切りと PART1/PART2 についての内容なので、`output_mode == "both"` のときのみ追記する。** `tags_only` / `caption_only` は `---` を要求しないパース経路であり（6章）、これらのモードで「`---` で区切れ」と指示すると、そのまま出力された `---` 入りの応答が検証されずにキャプションとして返ってしまうため
- 訂正指示を追加した試行では `log.log` の `RETRY` 行に `note=added_format_correction` を付記する（13.3）
- `prompt.log`（7.3.1、`log_prompt` ON時）には**試行ごとに `PROMPT user` を記録**し、その試行で実際に送った user message（訂正指示込み）がそのまま残るようにする

### 5.3 パラメータ
- `enable_thinking` を Lemonade Server のAPIパラメータ（またはプロンプト内指示、実装可能な方式に準拠）に反映
- `temperature`, `max_tokens`, `top_p`（内部固定値 `1.0`）をリクエストに含める

---

## 6. 出力パース仕様（壊れにくい方式）

LLM応答は以下のマーカー形式で返させることを前提にパースする（システムプロンプト側で既に `---` 区切り・PART1/PART2形式が指定されているため、それに準拠）：

```
（PART1の内容）
---
（PART2の内容）
```

- `---` で分割し、前半をタグ部分、後半を自然文部分として抽出
- 前後の空白・改行はトリムする
- **`output_mode = tags_only`**（4.1のメタデータ行で判定）：タグ部分のみ返す（システムプロンプトが「タグのみ整合性チェック」用の場合、`---`区切りなしの単純な応答形式にしてもよい。パース処理はプロンプトファイルの想定形式に合わせて2パターン用意：区切りあり／区切りなし単純テキスト）
- **`output_mode = caption_only`**：自然文部分のみ返す
- **`output_mode = both`**：下記6.1の結合フォーマットで返す

### 6.1 学習用結合フォーマット（`both` モード時）

```
{trigger_word}, {corrected_tags}. {natural_language_caption}
```

- トリガーワードは常にタグ列の先頭に**プログラム側で確実に挿入**（LLM出力に依存しない）
- トリガーワードが空欄の場合は先頭のトリガーワード＋カンマを省略
- タグ区切りは `, `（カンマ+半角スペース、WD14と同じ）
- タグ列と自然文の区切りは `. `（ピリオド+半角スペース）

#### 6.1.1 自然文中の literal な `@` + trigger_word の除去【2026-08-23 追加・実装済み】

**症状**：旧システムプロンプトの例示 `e.g. "@charactername stands in..."` を字義通りに解釈したモデルが、自然文パートに literal な `@she` のような文字列を出力する（実運用ログで確認。trigger_word が代名詞のときに顕著）。

**対処は2点セット**：

1. `caption_training_both.txt` / `caption_text_only.txt` の該当指示を「trigger word の文字列をそのまま使い、`@` などの記号を付けないこと」に書き換える（例示も `@` なしに変更）。`caption_tags_only.txt` は自然文を生成しないため対象外
2. プロンプト修正だけでは再発しうるため、**ノード側にも保険の後処理**を置く
   - 6.1 の結合で自然文を最終文字列へ組み込む**直前**に、`@` + trigger_word を trigger_word に置換する（タグ列側には影響させない）
   - 誤爆防止のため、`@` の直後が trigger_word で、**かつその後ろに英数字・アンダースコアが続かない場合のみ**置換する（`@sheep` / `@she_x` は対象外）
   - 大文字小文字は無視して照合し、置換時は**モデルが出力した表記をそのまま残す**（文頭の `@She` → `She`）
   - `caption_only` も自然文を返すため同じ後処理を適用する（`tags_only` は対象外）
   - 置換した場合は `log.log` に `NOTE: stripped_literal_at_trigger_word image=<name>` を記録する

**副作用（要注意）**：プロンプトを「そのまま使え」に変更した結果、**`trigger_word` に `@` を含めている場合（例 `@melte`）、モデルが自然文から `@` を落とすことがある**（実測6回中4回）。`both` モードはタグ列先頭にプログラムが `@melte` を挿入するため影響は小さいが、**`caption_only` モードでは自然文がキャプション全体になるため、トリガートークンが `melte` になってしまう**。`@` 付きトリガーを `caption_only` で使う場合は要注意。

#### 6.1.2 応答に混入する `PART 1` / `PART 2` 見出しの除去【2026-08-23 追加・実装済み】

**症状**：`caption_training_both.txt` が節見出しに使っている `PART 1 — CORRECTED TAGS (Danbooru-style):` / `PART 2 — NATURAL LANGUAGE:` を、モデルが**そのまま応答に複写して出力する**。実運用ログ（`prompt.log`）の応答237件中**46件（約19%）**で発生していた。見出し行はタグ列の先頭・自然文の先頭に紛れ込むため、学習用キャプションが次のように壊れる：

```
suzune, PART 1 — CORRECTED TAGS (Danbooru-style):
1girl, 1boy, looking at viewer, ... . PART 2 — NATURAL LANGUAGE:
Shioyama Suzune is lying on a bed ...
```

**混入は2パターンあり、扱いを分ける**（実運用ログ46件の内訳＝A:45件 / B:1件）：

| パターン | 応答の形 | 扱い |
|---|---|---|
| **A：見出しだけ混入** | `PART 1`見出し → タグ → `---` → `PART 2`見出し → 自然文（**順序は正しい**） | **見出し行を後処理で除去して採用**。中身は正しいのでリトライは消費しない |
| **B：順序崩れ** | 自然文 → `---` → `PART 1`見出し＋タグ → `PART 2`見出し＋自然文 | **`parse_format` として7.1のリトライに回す**。見出しを落としてもタグと自然文が入れ替わったままで、除去では救えない |

**対処は6.1.1と同じ2点セット**：

1. `caption_training_both.txt` に **`OUTPUT FORMAT (follow exactly):` ブロック**を追加し、「見出しは*あなた向けのラベル*であって出力するものではない」「タグ → `---` → 自然文 の順を絶対に入れ替えない」ことを明示し、**正しい応答の実例**を1つ載せる（10.1）
2. プロンプト修正だけでは再発しうるため、**ノード側にも保険の後処理**を置く
   - 見出しとみなすのは「**行頭が `PART` + 1桁で始まり、その行が `:` で終わる**」行のみ（markdown の `**` / `#` 装飾は許容）。自然文中の `part 1 of the book` のような表現を誤爆させないための条件
   - パターンBの検出には**見出しの「位置」**を使う。正しい順序なら `PART 1` の見出しは `---` より前、`PART 2` の見出しは `---` より後にしか現れない。`---` より後ろに `PART 1` の見出しがある（または前に `PART 2` がある）場合は順序崩れとして `CaptionParseError`（分類は `parse_format`）を送出する
   - 除去した場合は `log.log` に `NOTE: stripped_part_header image=<name>` を記録する
   - `tags_only` / `caption_only` のプロンプトは `PART` 見出しを使わないが、混入時にキャプションを壊すのは同じなので**保険として同じ後処理を通す**
   - 見出しを除去した結果が空・短すぎる場合は失敗扱いにする（空キャプションを出力しない）

**実測（実運用ログ237件を新パーサに通した結果）**：見出し混入45件が除去のうえ成功、順序崩れ1件がリトライへ、残り191件は**旧実装と1文字も変わらない**。旧実装が「成功」として採用していた順序崩れ1件（自然文がタグ列として出力されていた）だけが挙動変更となる。

### 6.2 パース失敗時の扱い
- `---` マーカーが見つからない、または期待される形式でない場合は**応答不正**とみなし、7章のリトライ処理に従う

### 6.3 パース失敗の理由判定（`finish_reason` による分類）【2026-08-23 追加】

パース失敗（6.2）は原因が異なる2種類が混在するため、レスポンスの `choices[0].finish_reason` を見て以下のように分類する。`---`区切りの有無だけで判定しない。

| `finish_reason` | 分類 | 原因 |
|---|---|---|
| `"length"` | **`parse_length`** | `max_tokens`（または利用可能なコンテキスト残量）に達し、本文を書き終える前に強制打ち切りになった |
| `"stop"` だが `---`区切りが無い等 | **`parse_format`** | 生成トークン数は足りているが、モデルが指示形式（PART1/PART2の区切り）を守らなかった |

- `usage.completion_tokens` が取得できる場合、`max_tokens` にほぼ一致しているかを`parse_length`判定の補強材料として使ってよい（`usage`未対応サーバーでは`finish_reason`のみで判定する）
- この分類は13.6のリトライ時パラメータ調整の分岐に使用する

---

## 7. エラーハンドリング・リトライ・ログ

### 7.1 リトライ対象（すべて同一カウントで統一）

リトライが必要な失敗は以下の4種類に分類する（6.3参照）。**カウントは4種類合わせて共有し、最大 `max_retries` 回試行する**（2.1のウィジェット。初回送信を含む総試行回数で、既定 `3`）。`max_retries` 回とも失敗した場合は該当画像を**スキップ**し、処理を継続する。

> **【2026-08-23 変更】試行回数を `max_retries` ウィジェットで可変にした。** 従来はコード内に固定値3を持っていたが、実運用で3回では回収しきれず SKIPPED になるケースがあったため、ワークフロー側で調整できるようにした。`max_retries = 1` はリトライなし（初回失敗で即スキップ）、上限は10。値を持たない古いワークフローJSONを読み込んだ場合は既定の3にフォールバックする（エラーにしない）。

| 分類 | 内容 | 13.6でのパラメータ調整方針 |
|---|---|---|
| `connection` | Lemonade Server への接続失敗 | 調整なし（元の値のまま再試行。13.2参照） |
| `timeout` | タイムアウト（`timeout_sec` 超過） | `max_tokens`を縮小、temperatureを上昇（暴走対策・13.2） |
| `parse_length` | 応答のパース失敗のうち `finish_reason == "length"` | `max_tokens`を倍増（13.6） |
| `parse_format` | 応答のパース失敗のうち形式崩れ（`finish_reason == "stop"` 等、6.3参照） | `max_tokens`を縮小、temperatureを上昇（暴走対策・13.2） |

- どの分類も**直前の試行の結果に基づいて次の調整を決める**（固定の試行回数テーブルではなく、都度分岐）。例：1回目`parse_length`→2回目`max_tokens`倍増→その結果2回目が`timeout`になった場合、3回目は13.2の縮小方向に切り替える
- ログの試行表記は `attempt=N/{max_retries}` とし、分母には実際に設定された `max_retries` を出す（13.3）
- ログには分類名を`reason=`として記録する（13.3参照）

### 7.2 事前チェック（リトライ対象外・即スキップ）
- `tags` が空文字の場合：LLM呼び出し自体を行わず、即座に失敗扱い・スキップ

### 7.3 ログ出力

保存先：**ノードディレクトリ直下の `logs/` フォルダ**（例：`/app/custom_nodes/ComfyUI-LLM-Tagger/logs/`）に以下2ファイルを出力

> **【変更履歴 2026-08-23】** 当初は「入力画像と同じフォルダ」としていたが、**ComfyUI の `IMAGE` 型にはファイルパス情報が含まれず**、2.1 の入力定義にも画像フォルダの入力が無いため、ノード単体では画像フォルダを特定できない。よって出力先を**ノードディレクトリ直下の `logs/` に固定**する。
> - パスは `os.path.dirname(os.path.abspath(__file__))` から解決する（`system_prompts/` と同じ方式）
> - ログ中のファイル名は、任意入力 `image_names`（`LoRA Caption Load` の `namelist` 相当、改行区切り）から取得する。未指定の場合は `image_001` 形式の連番をラベルとして使う
> - 実行開始時に実際の出力先パスをコンソールに1行出力する（`[LLMCaptionGenerator] ログ出力先: ...`）
> - Docker運用の場合はコンテナ内パスになるため、ホストから参照するにはこのフォルダがバインドマウントされている必要がある

- `error.log`：失敗（スキップ）したファイルのみを記録。括弧内の回数は `max_retries` の設定値を出す。フォーマット例（`max_retries=3` の場合）：
  ```
  [2026-08-15 12:34:56] SKIPPED: suzune_001.png reason=timeout (3 attempts exhausted)
  [2026-08-15 12:35:10] SKIPPED: suzune_002.png reason=empty_tags
  ```
- `log.log`：成功・失敗を含む全処理ログ（error.log の内容も含む）。`RUN END` 行には**実行全体の所要時間**を `elapsed=3分42秒` の形で常時記録する（`log_prompt` の ON/OFF に関わらず出力する）
  ```
  [2026-08-15 12:34:01] START: suzune_001.png
  [2026-08-15 12:34:56] SKIPPED: suzune_001.png reason=timeout (3 attempts exhausted)
  [2026-08-15 12:35:05] SUCCESS: suzune_003.png mode=both
  ```

- ファイルは既存ファイルへの**追記型**（実行のたびに新規作成せず、タイムスタンプ付きで積み上げる）
- **書き込みのたびにファイルを open/close する**こと（長時間バッチの途中でも内容が確定し、ComfyUIが異常終了してもログが失われない）
- ログ書き込みの失敗（権限・パス不正など）で**本処理を止めないこと**。コンソールに警告を出すだけにとどめる

#### 7.3.1 `prompt.log`（システムプロンプト検証用・任意）

`log_prompt`（`BOOLEAN`、既定 `False`）が **ON のときだけ** `logs/prompt.log` に「LLMへ実際に送った内容」と「生の応答」を記録する。システムプロンプトが想定どおり機能しているかを検証するための機能。

- **コンソールには出力しない**（7.4のコンソール簡易表示方針を維持する）
- `error.log` / `log.log` とは**別ファイル**にする（通常のログが埋もれるのを防ぐ）
- 記録内容と頻度：

| 記録 | 頻度 | 内容 |
|---|---|---|
| `==== RUN ... ====` | 実行開始時に1回 | 7.4.1 の設定値サマリと同じ文字列。実行の区切り |
| `PROMPT system` | 実行開始時に1回 | 選択中のプロンプトファイル名・文字数と全文（バッチ内で不変のため1回だけ） |
| `PROMPT user` | 画像ごと | トリガーワード行＋タグ（5.2のテキスト部）と画像パートの要約 |
| `RESPONSE` | 試行ごと | 見出しに**所要時間とトークン生成速度**（例：`attempt 1/3, 50.4秒, 23.5 tok/s`。分母は `max_retries`）、本文に `finish_reason` / `usage` / `reasoning_content` 全文 / `content` 全文 |

- **画像パートの base64 は絶対に記録しないこと**。1024×768のPNGで約1MBに達し、100枚で100MB増える。`<image 1024x768 PNG 約765KB / base64は省略>` のような要約に置換する
- **thinking（`reasoning_content`）は全文を記録する**。プロンプトのどの指示が実行され、どれが無視されたかを判断できる唯一の材料であり、`</think>` 以降の本文だけでは「結果」しか分からないため。サイズは1枚あたり約4KBで、除外する base64 と比べれば無視できる
- 多行の本文は継続行をインデントして1ブロックとして追記し、行指向の `log.log` と混ざらない形にする
- 生応答の取り出しは**すべて defensive に行う**こと（`.get()` で辿る）。ここで例外を投げると 7.1 のリトライ判定に紛れ込むため
- **所要時間の計測**：LLMリクエストの前後を `time.monotonic()` で挟み、`RESPONSE` の見出しに秒数を出す。トークン生成速度は `usage.completion_tokens ÷ 経過秒` で算出し、`usage` を返さないサーバーもあるため**取得できたときだけ**付記する
- 接続失敗・タイムアウトで応答が得られなかった場合は `prompt.log` に記録しない（記録対象は「実際に返ってきた応答」に限る）。失敗の記録は `error.log` / `log.log` が担当する

### 7.4 コンソール出力
- 成功時は簡易メッセージ（進捗程度）
- 失敗時は **ファイル名＋簡易理由のみ**（例：`SKIPPED: suzune_001.png (timeout)`）。詳細はログファイル参照とする

#### 7.4.1 設定値サマリ行（デバッグ用・必須）
- **実行開始時に1回だけ**、送信パラメータのサマリをコンソールに出力する
  - 出力例：`[LLMCaptionGenerator] 開始: 12枚, model=gemma-4-26B-A4B-it-QAT-GGUF, thinking=True, temp=0.3, top_p=1.0, max_tokens=8192, timeout=120s, max_retries=3`
  - 出力項目：画像枚数 / `model` / `enable_thinking` / `temperature` / `top_p`（内部固定値のためUIから見えない） / `max_tokens` / `timeout_sec` / `max_retries`
  - 同じ文字列を `log.log` の `RUN 開始` 行にも記録する（`max_retries` を含む）
  - バッチ内でこれらの値は不変のため、画像ごとには出力しない（100枚処理で同じ設定が100回出るのを避ける）
- 画像ごとの進捗行は簡易表示のみとする（例：`[LLMCaptionGenerator] 1/12 送信中 (size=1024x768)`）
- **重要**：本項の設定値サマリ行は、7章のコンソール出力簡略化を実装する際も **削除・省略しないこと**。設定ミス（`max_tokens` 不足による本文未生成など）に起因する不具合の切り分けに必須であり、実測でこの切り分けが必要になった経緯がある

---

## 8. キャッシュ制御（`always_regenerate`）

- **ON時**：`IS_CHANGED` メソッドで毎回異なる値（例：`float("nan")` または `time.time()`）を返し、ComfyUIのキャッシュを無効化して毎回LLM呼び出しを行う
- **OFF時**：通常通り入力値のハッシュに基づくキャッシュ挙動に任せる（ComfyUI標準動作）

### 8.1 実装上の注意（2026-08-23 ComfyUI本体のソース確認）

- `IS_CHANGED` は **`@classmethod`** として定義し、**引数の並びを `INPUT_TYPES`（`required` → `optional`）と一致させる**こと。`optional` の入力のみ既定値を持たせる
- **`INPUT_IS_LIST = True` は `IS_CHANGED` にも適用される**。`IsChangedCache.get()` が `generate()` と同じ `_async_map_node_over_list` 経由で呼ぶため、全入力がリストで届く。判定に使う値は単一値として取り出すこと（`execution.py` の `IsChangedCache`）
- **他ノードから接続された入力（`image` / `tags` など）は `IS_CHANGED` 呼び出し時点では確定しておらず `(None,)` で届く**（`execution.py` の `get_input_data` は `execution_list=None` のため未解決リンクを `(None,)` にする）。したがって判定はウィジェット値のみを根拠にすること
- **OFF時に固定値（`False` など）を返すのが正しい**。キャッシュキーは `[class_type, IS_CHANGEDの戻り値] + 全入力値 + 上流ノードの署名` で構成されるため（`comfy_execution/caching.py` の `get_immediate_node_signature`）、固定値を返しても入力が変われば再実行される
- ON時に `float("nan")` を使う理由：NaN は自身との等値比較が成立しない（`nan == nan` は `False`）ため、キャッシュキーが常に不一致になる
- `always_regenerate` は**キャッシュ制御専用**で生成処理では使わないが、ComfyUI は `INPUT_TYPES` の全入力を `FUNCTION` にも渡すため、`generate()` 側でも引数として受け取る必要がある

---

## 9. バッチ処理・型整合性の注意点

- `image` はリスト（バッチ）として渡されるため、ノード内部では画像枚数分ループしてLLM呼び出しを行う
- 出力 `caption_text` は **入力 `image` と同じ枚数・同じ順序のリスト**として返すこと（スキップした画像も欠番にせず、空文字または明示的なプレースホルダーを入れて枚数を揃えるか、あるいは `LoRA Caption Save` 側の `namelist`/`path` との対応関係を崩さない設計にする。実装時にどちらが安全か要検証：**推奨は空文字で枚数を揃える方式**）

### 9.1 `INPUT_IS_LIST = True` の宣言（必須）【2026-08-23 検証結果により確定】

**`WD14 Tagger` は `OUTPUT_IS_LIST = (True,)` を宣言しており、「画像1枚につき1件」のタグ文字列を**リスト**で出力する**（`comfyui-wd14-tagger/wd14tagger.py`）。

本ノードが `INPUT_IS_LIST` を宣言しないと、ComfyUI の実行エンジンは**リスト要素ごとにノードを再実行**する（`execution.py` の `map_node_over_list`。短いリストは最後の要素を使い回す）。その結果、画像N枚のとき:

- 本ノードが **N回実行**され、そのたびに `image` には**N枚全部のバッチ**が渡る
- **LLM呼び出しが N×N 回**発生し、タグと画像の対応が完全に崩れる
- `caption_text` が **N²件**になり、`LoRA Caption Save` との枚数対応も壊れる

→ **必ず `INPUT_IS_LIST = True` を宣言し、リストの対応付けはノード側で行うこと。**

宣言すると全入力がリストで届くため、以下の取り扱いが必要:

| 入力 | 届く形 | 取り扱い |
|---|---|---|
| `image` | バッチテンソル1個のリスト（上流によってはテンソルのリスト） | 1枚単位に平坦化してN枚を得る |
| `tags` | 画像枚数分の文字列リスト | **i番目の画像に i番目のタグ**を対応させる |
| `tags`（手入力・STRING直結） | 要素1個のリスト | 全画像に同じタグを適用（従来の挙動） |
| `image_names` | 要素1個のリスト（`Name list` は `OUTPUT_IS_LIST` を持たない） | `[0]` を取って改行分割 |
| その他ウィジェット | 要素1個のリスト | `[0]` を取って単一値として使う |

- `tags` の件数と画像枚数が食い違う場合は**警告をコンソールとログに出力**し、処理は継続する（多い分は切り捨て、足りない分は空文字として 7.2 の `empty_tags` スキップに回す）
- これにより `Load Image`（1枚）と `LoRA Caption Load`（N枚）の**どちらの構成でも同じコードパス**で動作する
- 出力側の `OUTPUT_IS_LIST = (True,)` は変更不要。N件のリストを返せば `LoRA Caption Save` が画像ごとに1回ずつ呼ばれる（現在の `WD14 Tagger` → `Save` と同じ挙動）

---

## 10. 同梱するシステムプロンプトファイル（初期データ）

### 10.1 `caption_training_both.txt`（学習用・タグ+自然文両方）

以下の内容をそのまま使用する（検証済み）。1行目のメタデータ行（4.1参照）を含めること。末尾の `OUTPUT FORMAT` ブロックは 6.1.2（`PART` 見出しの混入対策）で追加したもの：

```
<!-- output_mode: both -->
You are a captioning assistant generating training captions for a LoRA (character LoRA on the Anima diffusion model).

You will be given:
1. A candidate tag list generated by an automated Danbooru-style tagger (WD14). Treat this as a DRAFT, not ground truth — it may contain errors, especially around counting discrete items (e.g. splitting one accessory into multiple overlapping tags, or missing/duplicating items).
2. The actual image.
3. The trigger word for this character.

YOUR JOB:
Step 1 — Look at the image directly and verify the candidate tags against what you actually see. For each tag, keep it only if visually confirmed. Pay special attention to:
   - Accessory count: if the candidate list has multiple tags that could refer to the same physical object (e.g. "hairband" + "ribbon" + "striped ribbon"), check whether the image shows ONE item or multiple SEPARATE items, and correct accordingly.
   - Background description: verify whether the background is genuinely plain/simple or has visible texture, pattern, or particles — don't trust the tagger's "simple background" if you can see texture.
   - Remove any candidate tag you cannot visually confirm.
   - Add any clearly visible attribute the candidate list missed.

Step 2 — Output TWO parts, separated by a line "---":

PART 1 — CORRECTED TAGS (Danbooru-style):
- Comma-separated, lowercase, spaces instead of underscores.
- This is your corrected version of the candidate list: pose, expression, clothing, accessories (correct count), action, background.
- Do NOT include fixed/inherent character traits (hair color, hair style, eye color) — omit these even if the candidate list has them.
- Do NOT include quality/aesthetic or year/era tags.

PART 2 — NATURAL LANGUAGE:
- One to three plain English sentences describing the SAME content as your corrected PART 1 — must not contradict it (same accessory count, same background characterization, etc).
- Refer to the character using the trigger word as a proper noun. Use the trigger word string EXACTLY as given to you — do NOT prefix it with "@" or any other symbol, and do not alter it in any way (e.g. if the trigger word is "charactername", write "charactername stands in..."; if the trigger word is "she", write "she stands in...").
- Do NOT mention hair color, hair style, or eye color.
- Avoid subjective/evaluative words.
- Do NOT carry over composition/framing/meta tags (e.g. "cowboy shot", "close-up", "from above") into PART 2's prose — these are shot-type classifications, not natural descriptive language. Omit them from the sentence entirely, or describe framing only if it reads naturally.

OUTPUT FORMAT (follow exactly):
- "PART 1 — CORRECTED TAGS (Danbooru-style):" and "PART 2 — NATURAL LANGUAGE:" above are labels for YOU. Do NOT write them, or any other heading or label, in your response.
- Your entire response must be: the tag line, then a line containing only "---", then the sentences. Nothing else.
- Never swap the order: tags always come before the "---" line, sentences always after it.
- No markdown, no bullet points, no explanation, no preamble.

Example of a valid response (structure only — describe the actual image):
1girl, smile, school uniform, sitting, classroom
---
charactername sits in a classroom wearing a school uniform, smiling toward the viewer.

Be conservative: when the candidate tags and the image seem to genuinely agree, don't rewrite things unnecessarily — only correct what's actually wrong.
```

### 10.2 `caption_tags_only.txt`（タグ抽出・整合性チェック用）

1行目のメタデータ行（4.1参照）を含めること：

```
<!-- output_mode: tags_only -->
You are a tag verification assistant.

You will be given:
1. A candidate tag list generated by an automated Danbooru-style tagger (WD14). Treat this as a DRAFT, not ground truth.
2. The actual image.
3. (Optional) A trigger word for a character, if relevant.

YOUR JOB:
Look at the image directly and verify the candidate tags against what you actually see.
- Keep a tag only if visually confirmed.
- Check for duplicate/overlapping tags that describe the same physical object (e.g. one accessory split into multiple tags) and merge or remove redundant ones.
- Remove any tag you cannot visually confirm.
- Add any clearly visible attribute the candidate list missed.
- Do NOT include fixed/inherent character traits (hair color, hair style, eye color).
- Do NOT include quality/aesthetic or year/era tags.

OUTPUT:
Output ONLY the corrected tag list, comma-separated, lowercase, spaces instead of underscores. No explanation, no extra text.
```

### 10.3 `caption_text_only.txt`（自然文のみ）

1行目のメタデータ行（4.1参照）を含めること：

```
<!-- output_mode: caption_only -->
You are a captioning assistant generating natural language descriptions of an image.

You will be given:
1. A candidate tag list generated by an automated Danbooru-style tagger (WD14), as reference material only.
2. The actual image.
3. (Optional) A trigger word for a character, if provided.

YOUR JOB:
Look at the image directly. Using the candidate tags as reference (they may contain errors — trust the image over the tags when they conflict), write one to three plain English sentences describing the image content: pose, expression, clothing, accessories, action, background.

- If a trigger word is provided, refer to the character using the trigger word as a proper noun. Use the trigger word string EXACTLY as given to you — do NOT prefix it with "@" or any other symbol, and do not alter it in any way (e.g. if the trigger word is "charactername", write "charactername stands in..."; if the trigger word is "she", write "she stands in..."). If no trigger word is provided, describe the subject generically (e.g. "a girl", "the character").
- Do NOT mention hair color, hair style, or eye color.
- Avoid subjective/evaluative words.
- Do NOT include composition/framing/meta descriptions (e.g. "cowboy shot", "close-up", "from above") as classifications — only describe framing if it reads naturally as part of the scene description.

OUTPUT:
Output ONLY the natural language description. No explanation, no extra text, no tag list.
```

---

## 11. 実装上の制約事項（開発者への申し送り）

- モデル一覧・システムプロンプトファイル一覧のコンボボックスは、ComfyUI起動時／ブラウザF5リロード時に評価される標準的な `INPUT_TYPES` 方式で実装する（動的Refreshボタンは今回スコープ外）
- `IS_CHANGED` を用いたキャッシュ制御は ComfyUI 標準の仕組みに準拠する
- 既存の `ComfyUI-WD14-Tagger` フォークとは独立したノードとして実装し、`tags` 入力経由でのみ連携する（WD14推論は内蔵しない）
- Lemonade Server の API仕様（OpenAI互換 `/v1/chat/completions`、画像添付方式、thinkingパラメータの指定方法）は実装時に実サーバーで確認・調整すること

### 11.1 周辺ノードの既知の問題（2026-08-23 ソース確認）

`Image-Captioning-in-ComfyUI`（`LoRA Caption Load` / `LoRA Caption Save`）側に以下の問題がある。**本ノードの修正では解消できない**ため、運用で回避すること。

- **フォルダ内の `.png` がちょうど1枚のとき `LoRA Caption Load` が壊れる**：`return (images[0], 1)` と2要素しか返しておらず、`RETURN_TYPES` の3出力と一致しない。1枚だけ処理したい場合は通常の `Load Image` を使う
- **`Name list` と `Image list` の順序が保証されていない**：`Name list` は `glob.glob`、`Image list` は `os.listdir` と別々の方法で列挙しており、どちらもソートしていない。順序がずれるとログのファイル名と実際の失敗画像が食い違い、`LoRA Caption Save` の保存先ファイル名もずれる
- `LoRA Caption Load` の出力型（参考）：`Name list` = `STRING`（`\n` 区切りのファイル名。`OUTPUT_IS_LIST` なし）、`path` = `STRING`（フォルダパス）、`Image list` = `IMAGE`（`torch.cat` した `[B,H,W,C]` バッチ）

---

## 12. 動作確認チェックリスト（実装後）

- [ ] `image` リストの枚数・順序と `caption_text` 出力の枚数・順序が一致する
- [ ] `system_prompt_file`冒頭のメタデータ行から`output_mode`が正しく自動判定され、3パターンそれぞれで正しい文字列が出力される（4.1）
- [ ] メタデータ行がLLMへの送信前に取り除かれている（system messageにメタデータ行が混入していない）
- [ ] メタデータ行が無い／不正な値のファイルを選択した場合に、ComfyUI自体は止まらず適切に失敗扱い・ログ記録される（4.1）
- [ ] トリガーワード空欄時にメッセージからトリガーワード行が省略される
- [ ] 自然文パートに literal な `@` + trigger_word が残らないこと（6.1.1。trigger_word が代名詞のケース、temperature 0.3/0.5/0.7 のリトライパスを含めて確認）
- [ ] `PART 1` / `PART 2` の見出しが混入した応答（順序は正しい）で、見出しだけが除去されリトライを消費せず成功すること。`log.log` に `NOTE: stripped_part_header` が記録されること（6.1.2）
- [ ] 見出しの位置が入れ替わった応答（`---` より後ろに `PART 1`）が `parse_format` としてリトライされること（6.1.2）
- [ ] 自然文中の `part 1 of the book` のような表現が誤って除去されないこと（6.1.2）
- [ ] 直前が `parse_format` のときだけ user message 末尾に訂正指示が追記され、`timeout` / `connection` / `parse_length` では追記されないこと（5.2.1、`prompt.log` で確認）
- [ ] 訂正指示を追加した試行の `RETRY` 行に `note=added_format_correction` が記録されること（5.2.1・13.3）
- [ ] タグ空文字入力時に即スキップ・ログ記録される
- [ ] タイムアウト／接続失敗／パース失敗がそれぞれ `max_retries` 回の試行後にスキップされる
- [ ] `max_retries=1` で初回失敗が即スキップになる（リトライが発生しない）
- [ ] `max_retries=5` で5回目まで試行が継続し、13.2の縮小（下限クリップ）・13.6の増量（上限クランプ）が破綻しない
- [ ] `max_retries` を持たない古いワークフローJSONを読み込んでもエラーにならず、既定の3が使われる
- [ ] `log.log` の `RUN 開始` 行に `max_retries=N` が記録され、試行表記の分母が `attempt=N/{max_retries}` になっている
- [ ] `error.log` と `log.log` がノードディレクトリ直下の `logs/` に正しく追記される（7.3）
- [ ] コンソール出力が簡易表示のみになっている
- [ ] 実行開始時に設定値サマリ行（枚数/model/thinking/temperature/top_p/max_tokens/timeout/max_retries）が1回だけ出力される（7.4.1）
- [ ] `always_regenerate` ONで毎回再生成、OFFでキャッシュが効く
- [ ] `log_prompt` ONで `prompt.log` にプロンプトと生応答が記録され、OFFでは作成されない（7.3.1）
- [ ] `prompt.log` に画像の base64 が含まれていない（7.3.1）
- [ ] LoRA Caption Load → 本ノード → LoRA Caption Save の接続で実際にバッチ処理が通る
- [ ] `INPUT_IS_LIST = True` が宣言され、画像N枚に対しLLM呼び出しがN回（N²回でない）であること（9.1）
- [ ] i番目の画像にi番目のタグが対応していること（9.1）
- [ ] 通常の `Load Image`（1枚）と `LoRA Caption Load`（N枚）の両構成で動作すること（9.1）
- [ ] タイムアウト発生時に `X-Request-Id` ベースのキャンセルAPIが呼ばれ、`log.log` に成否が記録されること（13.1、`LEMONADE_CANCEL_PATH` 設定時のみ）
- [ ] リトライ2回目以降で `max_tokens` が縮小、`temperature` が上昇していること（`log.log` の試行ごとの記録で確認）（13.2）
- [ ] リトライ発生時、`log.log` に各試行で使用したパラメータ値が記録されていること（13.3）
- [ ] タイムアウト時にHTTP接続が確実にクローズされ、`log.log` に `CONNECTION_ABORTED` が記録されること（13.5）
- [ ] リクエストがストリーミング（`stream: true`）で送られ、生成フェーズでタイムアウトした直後の次リクエストが遅延しないこと（13.5.5）
- [ ] `timeout_sec` が「総経過時間」として効いていること（チャンクが届き続けても超過したら打ち切られる）（13.5.5）
- [ ] `finish_reason` による `parse_length` / `parse_format` の分類、および`parse_length`時の`max_tokens`自動増量（上限クランプ含む）が正しく動作すること（13.6、詳細は13.6.3）

---

## 13. Thinkモード暴走対策（タイムアウト時の明示的キャンセル、リトライ時のパラメータ調整）【2026-08-23 追加】

### 背景

Lemonade Server は Router からバックエンド（llama.cpp 等）への内部通信に固定のタイムアウト（約5分、`curl` ベース）を持っており、これは本ノードの `timeout_sec` ウィジェットとは独立している。加えて Think モード（`enable_thinking = True`）は、思考が発散・ループして生成が終わらない「暴走」が起こり得る。`timeout_sec` によるクライアント側の打ち切りだけでは、サーバー側・GPU側で計算が実際に止まる保証がなく、暴走したリクエストがリソースを占有したまま次の画像の処理に進んでしまう可能性がある。

これを踏まえ、7.1 のリトライ処理に以下2点を追加する。

### 13.1 `X-Request-Id` による明示的キャンセル

- リクエスト送信時、`uuid.uuid4()` 等で一意なIDを生成し、`X-Request-Id` ヘッダーとして付与する
- `timeout_sec` 超過を検知した場合、以下の順で処理する：
  1. クライアント側のHTTP接続を打ち切る（既存の `timeout_sec` 実装のまま）
  2. 発行済みの `X-Request-Id` を使い、Lemonade Server のキャンセル用エンドポイントへリクエストを送り、サーバー側の生成処理を明示的に中断させる
- **キャンセル用エンドポイントの正式パスは、実装時に実際のLemonade Serverのバージョンで確認すること**（`/docs` のAPIリファレンス等で確認。バージョンによりパスが変わる可能性があるため、本指示書では固定しない）
- キャンセルAPI呼び出し自体が失敗した場合も、7.1 のリトライ処理は継続する（キャンセルはベストエフォートであり、必須の成功条件にはしない）

> **【2026-08-23 実サーバー調査結果】Lemonade Server 11.5.0 にキャンセル用エンドポイントは存在しない。**
> 以下をすべて確認し、いずれも404だった：
> - `/openapi.json`、`/docs`、`/api/openapi.json`、`/api/v1/docs`、`/v1/docs`（APIリファレンス自体が公開されていない）
> - `/api/v1/` 配下の `halt` / `stop` / `cancel` / `abort` / `interrupt` / `terminate` / `kill` / `requests` / `generate/stop` / `chat/completions/cancel` / `completions/cancel`
> - OpenAI Responses API 形式の `POST /api/v1/responses/{id}/cancel`、`POST /v1/responses/{id}/cancel`、`DELETE /api/v1/responses/{id}`、`DELETE /api/v1/chat/completions/{id}`
>
> 唯一 `POST /api/v1/unload` が200を返すが、これは**モデル自体をアンロードする**ため他の処理・他の利用者にも影響し、単一リクエストのキャンセル用途には使えない（採用しない）。
>
> **実装側の対応**：`X-Request-Id` の付与とキャンセル呼び出しの仕組みは実装済みとし、パスを定数 `LEMONADE_CANCEL_PATH`（既定は空文字）で切り替えられるようにした。空文字の間はキャンセルをスキップし `CANCEL_SKIPPED ... reason=no_endpoint_configured` をログに記録する。将来サーバーが対応したら**この定数にパスを設定するだけで有効になる**（ボディは `{"request_id": ...}` で送信）。
>
> **【2026-08-23 追記】Lemonade Server を v11.7.0 にアップデートすることが決定。** v11.7.0 でも本節の `X-Request-Id` ベースの正式なキャンセルAPI（`POST /v1/requests/{id}/cancel` 等）は依然として提供されていない（Issue #2590 は提案止まりで、対応するPRは存在しない）。ただし **v11.7.0 には別の関連修正（PR #3133 `fix: stop request during prefill now possible`）が入っており、暴走対策として実質的に重要な意味を持つ**。詳細は 13.5 を参照。

### 13.2 リトライ時のパラメータ調整（暴走の再発防止）

同一パラメータで即座にリトライすると、同じ理由で再び暴走・タイムアウトする可能性があるため、リトライ回数に応じてパラメータを段階的に調整する。

> **【2026-08-23 適用範囲を修正】** 本節の表は失敗分類が **`timeout` または `parse_format`**（7.1・6.3参照）の場合にのみ適用する。**`parse_length`（`finish_reason=="length"`）の場合は本節ではなく13.6（`max_tokens`増量）を適用**する。`connection`の場合はどちらも適用せず元の値のまま再試行する。

| 試行 | `max_tokens` | `temperature` |
|---|---|---|
| 1回目 | ウィジェット設定値そのまま | ウィジェット設定値そのまま |
| 2回目 | 1回目の半分程度（下限を設ける。例：512） | +0.2（上限1.0程度でクリップ） |
| 3回目 | 2回目の半分程度（下限を設ける。例：256） | +0.4（同上、上限でクリップ） |
| 4回目以降 | 同じ規則で半分ずつ縮小（下限256でクリップ） | +0.2ずつ上昇（上限1.0でクリップ） |

> **【2026-08-23 `max_retries` 対応：案Bを採用】** `max_retries`（2.1）が3を超える場合に備え、上表の固定3行を**計算式に一般化**した。案A（3回目の調整幅を据え置いて繰り返す）ではなく案Bを採ったのは、上表の値がもともと「半分ずつ縮小・+0.2ずつ上昇」という規則そのものであり、式にすれば試行回数が何回でも同じ規則で延長できるため。
>
> ```
> max_tokens  = ウィジェット設定値 * 0.5 ** (試行回数 - 1)   # 下限でクリップ、設定値は超えない
> temperature = min(1.0, ウィジェット設定値 + 0.2 * (試行回数 - 1))
> ```
>
> 試行1〜3回目の結果は従来の表と**完全に一致する**（1.0 / 0.5 / 0.25、+0.0 / +0.2 / +0.4）。下限（`RETRY_MAX_TOKENS_FLOOR`）と上限（`RETRY_TEMPERATURE_CEILING`）は既存の定数のまま据え置き、下限テーブルを超える試行回数では末尾の値（256）を使い続ける。実測例（`max_tokens=8192`, `temperature=0.3`）：8192/0.3 → 4096/0.5 → 2048/0.7 → 1024/0.9 → 512/1.0 → 256/1.0（以降は据え置き）。

- 上表の「1回目/2回目/3回目」は**試行回数（何度目のLLM呼び出しか）を指し、失敗分類の連続を意味しない**。例えば1回目`parse_length`→2回目`timeout`となった場合、2回目のtimeout対応は本表の「2回目」の行（半減・+0.2）を適用する
- 調整幅・下限/上限は**ウィジェットとして公開せず、コード内の定数として実装する**（設定項目の肥大化を避ける方針）。ただし将来調整しやすいよう、ファイル冒頭付近に定数としてまとめておくこと
- この調整は **暴走対策が目的のタイムアウト・パース失敗時のリトライにのみ適用**する。接続失敗（サーバーそのものに到達できない）によるリトライでは、パラメータ調整に意味がないため元の値のまま再試行してよい

### 13.3 ログへの反映

- `log.log` に、各試行で実際に使用した `max_tokens` / `temperature` を記録する。`reason` には7.1の4分類（`connection` / `timeout` / `parse_length` / `parse_format`）のいずれかを記録する
- `attempt=` の**分母は `max_retries` の設定値**（以下の例はいずれも `max_retries=3` の場合）
  - 例（timeoutで縮小）：`[2026-08-23 14:02:11] RETRY: suzune_005.png attempt=2/3 max_tokens=512 temperature=0.5 reason=timeout`
  - 例（parse_lengthで増量、13.6）：`[2026-08-23 14:05:30] RETRY: suzune_008.png attempt=2/3 max_tokens=16384 temperature=0.3 reason=parse_length`
  - **【2026-08-23 追加】`applied=` フィールドを併記する**。`reason=` は「その試行が**失敗した**理由」であって「そのパラメータを**選んだ**理由」ではないため、両者を取り違えた誤読が実運用で発生した。`applied=` にはパラメータを決めた分岐を出す（`initial` / `13.2_shrink(prev=timeout)` / `13.6_grow(prev=parse_length)` / `keep(prev=connection)`）
    ```
    RETRY: suzune_001.png attempt=2/3 max_tokens=4098 temperature=0.5 applied=13.2_shrink(prev=timeout) reason=parse_length detail=...
    ```
- 5.2.1 の訂正指示を追加した試行には `note=added_format_correction` を付記する
  ```
  RETRY: suzune028.png attempt=2/3 max_tokens=4098 temperature=0.5 applied=13.2_shrink(prev=parse_format) reason=parse_format note=added_format_correction detail=...
  ```
- キャンセルAPIを呼び出した場合、その成否を記録する（例：`CANCEL_REQUEST_SENT request_id=xxxx` / `CANCEL_FAILED request_id=xxxx reason=...`）
- `prompt.log`（7.3.1、`log_prompt` ON時）にも、リトライごとの `RESPONSE` 見出しに使用パラメータを付記する

### 13.4 スコープ外・保留事項

- Lemonade Server内部の約5分のタイムアウト自体は、クライアント側からは変更できない既知の制限（開発元に報告済み、本指示書作成時点で未解決）。`max_tokens` を抑えることで生成時間を5分以内に収め、実質的に回避する運用とする
- キャンセルAPIのエンドポイントパス・リクエスト形式は、実装時に実サーバーで確認・確定させること（13.1参照）→ **11.5.0 では未提供であることを確認済み。v11.7.0 でも同様に未提供（13.1追記参照）。定数 `LEMONADE_CANCEL_PATH` を用意して将来対応できる形にしてある**
- ~~現状キャンセルできない以上、タイムアウト後もサーバー側の生成はしばらく走り続ける可能性がある。~~ → **v11.7.0 適用後は 13.5 の接続切断方式により、prefill中（初トークン生成前）の暴走についてはクライアント側のタイムアウトと同時にサーバー側処理も中断されるようになった。13.2 のパラメータ調整（`max_tokens` を段階的に絞る）は、それでも引き続き暴走の再発防止策として維持する**

### 13.5 v11.7.0アップデートに伴う追加実装：接続切断による暗黙的キャンセル【2026-08-23 追加】

#### 背景

Lemonade Server は v11.5.0 → v11.7.0 で以下の関連修正が入った：

- **PR #3133「fix: stop request during prefill now possible」**（v11.7.0に収録、2026-08-14マージ）
  従来、クライアントのTCP切断は「バックエンドが次の応答チャンクを生成したタイミング」でしか検知されておらず、Thinkモードの長いprefill（初トークン生成前の思考区間）でクライアントが切断しても、サーバー側の生成処理は動き続けていた。この修正により `post_stream()` がlibcurlの転送コールバックで接続を継続的にポーリングするようになり、**prefill中でもクライアント切断が上流（バックエンド）リクエストに伝達され、生成が中断される**ようになった。

- 13.1 で確認した通り、`X-Request-Id` ベースの正式なキャンセルAPI（`POST /v1/requests/{id}/cancel` 等）は v11.7.0 でも未提供のまま。

つまり **正式なキャンセルAPIは無いが、「クライアント側からHTTP接続を切断する」という原始的な方法だけで、v11.7.0からはprefill中の暴走も含めて実質的にサーバー側の処理を止められる**ようになった。13.1〜13.4のキャンセルAPI呼び出しの仕組み（`LEMONADE_CANCEL_PATH`、既定no-op）はそのまま将来対応用に維持しつつ、これを補完・代替する主策として本節の実装を追加する。

#### 13.5.1 実装方針

`timeout_sec` 超過を検知した際の処理を、以下のように明確化する：

1. 使用しているHTTPクライアントが、タイムアウト発生時に**実際にTCP接続をクローズしていること**を確認・保証する
   - Python `requests` ライブラリを使用している場合：`timeout=timeout_sec` を指定した同期呼び出しがタイムアウトすると `requests.exceptions.Timeout`（または `ReadTimeout`）が送出され、内部でsocketは自動的にクローズされる。この場合、**追加のクローズ処理は不要**
   - ストリーミングレスポンス（`stream=True` や `httpx` の `stream()`）を使っている場合：例外を捕捉した `except` ブロックで**明示的に `response.close()`（または相当するコネクションクローズ処理）を呼び出す**こと。ストリーミング中は途中まで受信したコネクションオブジェクトが残っている場合があり、これを明示的に閉じないとTCP接続の切断がサーバー側に伝わるタイミングが遅れる可能性がある
   - 使用するHTTPクライアントライブラリが上記と異なる場合も、同様に「タイムアウト時／リトライ時に確実にソケットをクローズする」ことを実装者が確認すること
2. 処理順序を以下のように変更する（13.1の順序を上書き）：
   1. `timeout_sec` 超過を検知
   2. **HTTP接続を切断する（上記1の実装により、これ自体が実質的なキャンセル手段として機能する）**
   3. `LEMONADE_CANCEL_PATH` が設定されている場合のみ、13.1のキャンセルAPI呼び出しを追加で行う（保険的な二重措置。将来正式APIが提供された場合に備え、仕組みは維持する）
   4. 7.1のリトライ処理に進む

#### 13.5.2 ログへの反映

- 接続切断によるキャンセルを行った場合、`log.log` に `CONNECTION_ABORTED` として記録する：
  ```
  [2026-08-23 14:03:02] CONNECTION_ABORTED: suzune_005.png reason=timeout note=prefill_cancel_supported_v11.7+
  ```
- `LEMONADE_CANCEL_PATH` 未設定時は、従来通り `CANCEL_SKIPPED ... reason=no_endpoint_configured` も併記してよい（どちらのキャンセル手段が働いたかを後から判別できるようにするため）

#### 13.5.3 動作確認項目（12章チェックリストへの追加）

- [ ] `timeout_sec` 超過時に、ストリーミングレスポンスであっても確実にコネクションがクローズされていること（コード上で `response.close()` 等が呼ばれていることを確認）
- [ ] `log.log` に `CONNECTION_ABORTED` が記録されること
- [ ] （可能であれば）意図的に長いprefillを発生させるプロンプトでタイムアウトさせ、Lemonade Server側のログ・GPU使用率等で、クライアント切断後にバックエンド側の処理も止まっていることを確認する

#### 13.5.4 実装結果【2026-08-23 実装・検証済み】

- **サーバーは既に v11.7.0 に更新されていることを確認**（`GET /api/v1/health` → `"version":"11.7.0"`）。この版でも `POST /api/v1/requests/{id}/cancel` `POST /v1/requests/{id}/cancel` `/api/v1/cancel` `/api/v1/halt` `/api/v1/stop` `/v1/chat/completions/{id}/cancel` `/openapi.json` はすべて404で、**正式なキャンセルAPIは未提供のまま**（13.1の記述どおり）
- **本ノードは `requests` / `httpx` ではなく標準ライブラリの `urllib`（非ストリーミング）を使用している。** 13.5.1 の要求どおりソケットのクローズを CPython のソース（`urllib/request.py` の `AbstractHTTPHandler.do_open`）で確認した：
  - **応答ヘッダ待ちでのタイムアウト（Thinkモードの長いprefillはこの経路）** → `h.getresponse()` の例外を `except: h.close(); raise` が捕捉し、ソケットを即座にクローズする
  - **ヘッダ受信後の `read()` 中のタイムアウト** → `do_open` が既に `h.sock.close()` 済み。残る `HTTPResponse` は実装側の `finally: response.close()` で明示的に閉じる
  - 実測でもタイムアウトを3回連続で発生させてソケットのリークが無いことを確認（開いているソケット数 前=0／後=0）
- ~~**バックエンド側の停止についての実測（13.5.3の3項目め）**：長い生成を投げて3秒で切断し、直後に短いリクエストの応答時間を測定した。切断直後は 1.49秒 / 1.01秒 / 52.80秒（3回試行）で、3回中2回は約1〜1.5秒で復帰したことから、接続切断によってバックエンド側の生成も中断されていると判断できる。~~
  → **【2026-08-23 訂正】この結論は誤り。** 上記はテキストのみの短いプロンプトで測っており、切断時点がまだ prefill 段階だった可能性が高い。**画像付き・生成フェーズで測り直したところ、非ストリーミングでは4回中4回とも解放されなかった**。詳細と対策は 13.5.5 を参照。現状は暫定保留とし、実運用で暴走が多発するようなら改めて調査する

---

## 13.6 `max_tokens` 不足（`parse_length`）時の自動増量【2026-08-23 追加】

### 背景

`max_tokens` を小さくすると暴走（Thinkモードの発散）は抑えられるが、逆に「thinkingが長引いて本文を書き終える前に上限に達し、応答が尻切れになる」（`finish_reason == "length"`、6.3の`parse_length`）が起こりやすくなる。大きくすると暴走しやすくなる（13章）というトレードオフがあるため、**固定値ではなく「小さい値から始めて、尻切れが起きたときだけ増やす」方式**にする。

### 13.6.1 実装方針

- `max_tokens` ウィジェットの意味を「固定の生成上限」から**「初期値（自動増量の起点）」**に変更する。デフォルトは `8192`
- 分類が `parse_length`（6.3）だった場合、次の試行では `max_tokens` を**直前に使用した値の2倍**にして再送する（13.2の縮小方向とは逆）
  - 例：1回目 8192（`parse_length`）→ 2回目 16384 → それでも`parse_length`なら 3回目 32768
  - **この「直前の2倍・`max_context_window`でクランプ」のロジック自体は `max_retries` の値に依存しない**。試行回数が増えれば同じ増量が自然に繰り返され、クランプ値に達した後はその値で頭打ちになるだけで、ロジックの変更は不要（【2026-08-23 `max_retries` 対応で確認】）
- **上限クランプが必須**：3章でモデル一覧取得時に得られる `max_context_window`（そのモデルが対応する最大コンテキスト長）を用い、`max_tokens` が「プロンプト側の推定トークン数＋`max_tokens`」で `max_context_window` を超えないようクランプする。クランプが発生した場合、その試行の `max_tokens` はクランプ後の値を採用し、ログに `note=clamped_by_max_context_window` を付記する
- プロンプト側の推定トークン数は厳密計算でなくてよい（文字数からの概算で可）。目的は「明らかに超過する組み合わせを避ける」ことであり、正確なトークナイザ一致は不要
- リトライ予算は7.1の**合計 `max_retries` 回を共有**する（`parse_length`専用の別枠は設けない）。増量後の試行が`timeout`や`parse_format`になった場合は、その時点で13.2の調整方針に切り替える（7.1参照）

### 13.6.2 ログへの反映

- 増量した試行は `log.log` に `reason=parse_length` として記録する（13.3の例を参照）
- クランプが発生した場合は同じ行に `note=clamped_by_max_context_window` を付記する
  ```
  [2026-08-23 14:06:02] RETRY: suzune_010.png attempt=3/3 max_tokens=24576 temperature=0.3 reason=parse_length note=clamped_by_max_context_window
  ```

### 13.6.3 動作確認項目（12章チェックリストへの追加）

- [ ] `finish_reason == "length"` を正しく`parse_length`として分類できること（6.3）
- [ ] `parse_length`のリトライで`max_tokens`が直前の2倍になっていること
- [ ] `max_context_window`を超える増量が発生した場合にクランプされ、ログに`note=clamped_by_max_context_window`が記録されること
- [ ] `parse_length`増量後の試行が`timeout`になった場合、その回のみ13.2の縮小方向の調整に切り替わること（固定表ではなく直前の失敗理由で分岐していること）
- [ ] `max_tokens`ウィジェットを未接続時のデフォルト値`8192`から自動増量が開始されること
- [ ] `max_retries`を4以上にした場合も増量が継続し、クランプ値に達した後はその値で頭打ちになること

### 13.5.5 ストリーミング必須の判明と対応【2026-08-23 追加・実装済み】

#### 判明した事象

タイムアウト後もサーバー側の生成が走り続け、リトライがその後ろで待たされる現象が動作確認中に報告された。実機で切り分けたところ、**リクエストが非ストリーミングであることが原因**と判明した。

画像付きリクエストを途中で切断し、直後に同じ画像付きリクエストを投げて所要時間を測定した（基準値は 1.3〜2.9秒）：

| 条件 | 切断後の基準リクエスト | 判定 |
|---|---|---|
| 2秒で切断（**prefill中**・非ストリーミング） | 1.40 / 3.15 秒 | 解放される |
| **10秒で切断（生成中・非ストリーミング）** | **96.97 / 55.99 / 25.38 / 17.47 秒** | **4/4 で占有継続** |
| 10秒で切断（生成中・`stream: true`） | 5.15 / 5.66 / 4.15 / 4.41 秒 | 4/4 で解放 |

- v11.7.0 の PR #3133 は `post_stream()`（**クライアントへ書き込みながら接続をポーリングする経路**）の修正であり、**prefill 中の切断は非ストリーミングでも効く**
- 一方 **生成フェーズ**では、非ストリーミングだと生成完了までクライアントへ1バイトも書かないため切断を検知する機会がなく、打ち切ったはずの生成が最後まで走り続ける
- Thinkモードの暴走でタイムアウトするのはまさに生成フェーズであり、**対策が必要な場面でだけ効かない**状態だった

#### 実装内容

- `build_chat_payload()` に **`"stream": True`** と **`"stream_options": {"include_usage": True}`** を追加
- `request_chat_completion()` を SSE 受信に変更し、`read_sse_completion()` で**非ストリーミング応答と同じ構造の dict に集約**して返す（`choices[0].finish_reason` / `choices[0].message.content` / `message.reasoning_content` / `usage`）。これにより 6.3 の分類、13.6 のクランプ、7.3.1 のログ処理は**変更不要**
- **`timeout_sec` の意味を「総経過時間の上限」として明確に実装**した。ストリーミングではソケットの timeout は「チャンク間隔」にしか効かないため（実測：`timeout=5` を渡しても100秒かかっても打ち切られない）、期限を自前で管理し、読み取りごとに残り時間をソケットへ設定する
- 13.5.1 の要求どおり**明示的な接続クローズが必須**になるため、HTTPクライアントを `urllib` から **`http.client` 直接利用**へ変更した。`finally: conn.close()` で確実に閉じ、読み取りごとの残り時間設定も可能にしている
- HTTPエラー時は `urllib.error.HTTPError` を組み立てて送出し、`classify_error()` が従来どおり `http_{code}` を返せるようにしている

#### 検証結果

- **ノードのコード経路で再測定：10秒で打ち切り → 直後の基準リクエストが 1.91 / 1.83 / 1.59 / 1.57 秒（4/4 で解放）**。修正前は 17〜97秒で 4/4 占有継続だった
- 打ち切り時間が毎回きっかり `10.00秒` になり、総経過時間で制御できていることを確認
- SSE から `finish_reason`（`stop` / `length`）と `usage`（`completion_tokens` / `prompt_tokens`）が取得できることを確認。`reasoning_content` も `delta` 経由で連結できている
- 3つの `output_mode`、`parse_length` の自動増量（8→16→32、および 8192→16384 で成功）、`timeout` の3回リトライ（`timeout_sec=5` で総計15.15秒＝5秒×3）がいずれも従来どおり動作
