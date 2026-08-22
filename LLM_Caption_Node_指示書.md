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
| `output_mode` | `STRING`（コンボボックス） | 必須 | `tags_only` / `caption_only` / `both` の3択 |
| `system_prompt_file` | `STRING`（コンボボックス、動的） | 必須 | 指定フォルダ内の `.txt` 一覧から選択（詳細は4章） |
| `lemonade_host` | `STRING`（ウィジェット） | 必須 | 例：`127.0.0.1` |
| `lemonade_port` | `INT`（ウィジェット） | 必須 | 例：`8000` |
| `lemonade_api_key` | `STRING`（ウィジェット） | 任意 | 将来の認証用。空欄可 |
| `model` | `STRING`（コンボボックス、動的） | 必須 | Lemonade Server から取得したモデル一覧（詳細は3章） |
| `enable_thinking` | `BOOLEAN` | 必須 | デフォルト `True`（常時ON運用想定だが切替可能にしておく） |
| `temperature` | `FLOAT` | 必須 | デフォルト `0.3` 程度、範囲 0.0〜2.0 |
| `max_tokens` | `INT` | 必須 | デフォルト `2048` 程度（Thinkトークン込みの想定でやや大きめ） |
| `timeout_sec` | `INT` | 必須 | デフォルト `120` |
| `always_regenerate` | `BOOLEAN` | 必須 | ON時は `IS_CHANGED` で毎回キャッシュ無効化 |
| `image_names` | `STRING`（複数行、`optional`） | 任意 | ログに記録する画像ファイル名（改行区切り）。`LoRA Caption Load` の `namelist` 相当。未接続時は `image_001` 形式の連番をラベルに使う（7.3） |

### 2.2 出力（Outputs）

| 名前 | 型 | 説明 |
|---|---|---|
| `caption_text` | `STRING`（リスト） | `output_mode` に応じた最終文字列（1画像1要素、image listと同じ順序・同じ枚数） |

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
- 選択されたファイルの中身をそのまま LLM への system message として使用
- モデル一覧と同様、**F5リロードで一覧を再取得**する仕様にする
- 用途別に以下3種類のプロンプトファイルを同梱すること（本指示書末尾のサンプルを初期データとして使用）：
  1. `caption_training_both.txt`（学習用・タグ+自然文両方、トリガーワード必須想定）
  2. `caption_tags_only.txt`（タグ抽出＋整合性チェック用）
  3. `caption_text_only.txt`（自然文のみ、トリガーワード条件付き）

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
- **`output_mode = tags_only`**：タグ部分のみ返す（システムプロンプトが「タグのみ整合性チェック」用の場合、`---`区切りなしの単純な応答形式にしてもよい。パース処理はプロンプトファイルの想定形式に合わせて2パターン用意：区切りあり／区切りなし単純テキスト）
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

### 6.2 パース失敗時の扱い
- `---` マーカーが見つからない、または期待される形式でない場合は**応答不正**とみなし、7章のリトライ処理に従う

---

## 7. エラーハンドリング・リトライ・ログ

### 7.1 リトライ対象（すべて同一カウントで統一）
- Lemonade Server への接続失敗
- タイムアウト（`timeout_sec` 超過）
- 応答のパース失敗（6.2）

→ **最大3回リトライ**。3回とも失敗した場合は該当画像を**スキップ**し、処理を継続する。

### 7.2 事前チェック（リトライ対象外・即スキップ）
- `tags` が空文字の場合：LLM呼び出し自体を行わず、即座に失敗扱い・スキップ

### 7.3 ログ出力

保存先：**ノードディレクトリ直下の `logs/` フォルダ**（例：`/app/custom_nodes/ComfyUI-LLM-Tagger/logs/`）に以下2ファイルを出力

> **【変更履歴 2026-08-23】** 当初は「入力画像と同じフォルダ」としていたが、**ComfyUI の `IMAGE` 型にはファイルパス情報が含まれず**、2.1 の入力定義にも画像フォルダの入力が無いため、ノード単体では画像フォルダを特定できない。よって出力先を**ノードディレクトリ直下の `logs/` に固定**する。
> - パスは `os.path.dirname(os.path.abspath(__file__))` から解決する（`system_prompts/` と同じ方式）
> - ログ中のファイル名は、任意入力 `image_names`（`LoRA Caption Load` の `namelist` 相当、改行区切り）から取得する。未指定の場合は `image_001` 形式の連番をラベルとして使う
> - 実行開始時に実際の出力先パスをコンソールに1行出力する（`[LLMCaptionGenerator] ログ出力先: ...`）
> - Docker運用の場合はコンテナ内パスになるため、ホストから参照するにはこのフォルダがバインドマウントされている必要がある

- `error.log`：失敗（スキップ）したファイルのみを記録。フォーマット例：
  ```
  [2026-08-15 12:34:56] SKIPPED: suzune_001.png reason=timeout (3 retries exhausted)
  [2026-08-15 12:35:10] SKIPPED: suzune_002.png reason=empty_tags
  ```
- `log.log`：成功・失敗を含む全処理ログ（error.log の内容も含む）
  ```
  [2026-08-15 12:34:01] START: suzune_001.png
  [2026-08-15 12:34:56] SKIPPED: suzune_001.png reason=timeout (3 retries exhausted)
  [2026-08-15 12:35:05] SUCCESS: suzune_003.png mode=both
  ```

- ファイルは既存ファイルへの**追記型**（実行のたびに新規作成せず、タイムスタンプ付きで積み上げる）
- **書き込みのたびにファイルを open/close する**こと（長時間バッチの途中でも内容が確定し、ComfyUIが異常終了してもログが失われない）
- ログ書き込みの失敗（権限・パス不正など）で**本処理を止めないこと**。コンソールに警告を出すだけにとどめる

### 7.4 コンソール出力
- 成功時は簡易メッセージ（進捗程度）
- 失敗時は **ファイル名＋簡易理由のみ**（例：`SKIPPED: suzune_001.png (timeout)`）。詳細はログファイル参照とする

#### 7.4.1 設定値サマリ行（デバッグ用・必須）
- **実行開始時に1回だけ**、送信パラメータのサマリをコンソールに出力する
  - 出力例：`[LLMCaptionGenerator] 開始: 12枚, model=gemma-4-26B-A4B-it-QAT-GGUF, thinking=True, temp=0.3, top_p=1.0, max_tokens=8192, timeout=120s`
  - 出力項目：画像枚数 / `model` / `enable_thinking` / `temperature` / `top_p`（内部固定値のためUIから見えない） / `max_tokens` / `timeout_sec`
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

以下の内容をそのまま使用する（検証済み）：

```
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
- Refer to the character using the trigger word as a proper noun (e.g. "@charactername stands in...").
- Do NOT mention hair color, hair style, or eye color.
- Avoid subjective/evaluative words.
- Do NOT carry over composition/framing/meta tags (e.g. "cowboy shot", "close-up", "from above") into PART 2's prose — these are shot-type classifications, not natural descriptive language. Omit them from the sentence entirely, or describe framing only if it reads naturally.

Be conservative: when the candidate tags and the image seem to genuinely agree, don't rewrite things unnecessarily — only correct what's actually wrong.
```

### 10.2 `caption_tags_only.txt`（タグ抽出・整合性チェック用）

```
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

```
You are a captioning assistant generating natural language descriptions of an image.

You will be given:
1. A candidate tag list generated by an automated Danbooru-style tagger (WD14), as reference material only.
2. The actual image.
3. (Optional) A trigger word for a character, if provided.

YOUR JOB:
Look at the image directly. Using the candidate tags as reference (they may contain errors — trust the image over the tags when they conflict), write one to three plain English sentences describing the image content: pose, expression, clothing, accessories, action, background.

- If a trigger word is provided, refer to the character using the trigger word as a proper noun (e.g. "@charactername stands in..."). If no trigger word is provided, describe the subject generically (e.g. "a girl", "the character").
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
- [ ] `output_mode` の3パターンそれぞれで正しい文字列が出力される
- [ ] トリガーワード空欄時にメッセージからトリガーワード行が省略される
- [ ] タグ空文字入力時に即スキップ・ログ記録される
- [ ] タイムアウト／接続失敗／パース失敗がそれぞれ3回リトライ後にスキップされる
- [ ] `error.log` と `log.log` がノードディレクトリ直下の `logs/` に正しく追記される（7.3）
- [ ] コンソール出力が簡易表示のみになっている
- [ ] 実行開始時に設定値サマリ行（枚数/model/thinking/temperature/top_p/max_tokens/timeout）が1回だけ出力される（7.4.1）
- [ ] `always_regenerate` ONで毎回再生成、OFFでキャッシュが効く
- [ ] LoRA Caption Load → 本ノード → LoRA Caption Save の接続で実際にバッチ処理が通る
- [ ] `INPUT_IS_LIST = True` が宣言され、画像N枚に対しLLM呼び出しがN回（N²回でない）であること（9.1）
- [ ] i番目の画像にi番目のタグが対応していること（9.1）
- [ ] 通常の `Load Image`（1枚）と `LoRA Caption Load`（N枚）の両構成で動作すること（9.1）
