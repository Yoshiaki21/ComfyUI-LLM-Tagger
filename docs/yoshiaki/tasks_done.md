# 完了タスク記録

## 記録フォーマット
完了タスクは以下の形式で追記すること。


```
---

## タスク[番号]: [タイトル]

- **完了日**: YYYY-MM-DD
- **動作確認**: ✅済み / ⬜未確認
- **新規ファイル**:
  - `パス/ファイル名` : 用途
- **修正ファイル**:
  - `パス/ファイル名` : 変更内容を一言で
- **変更内容**:
  - 箇条書きで何をしたか
- **備考**: ハマった点・注意事項（なければ省略）
```

<!-- 以下に完了タスクを追記 -->

---

## タスク1: 指示書3章「Lemonade Server 接続・モデル一覧取得」実装

- **完了日**: 2026-08-17
- **動作確認**: ✅済み（サーバー無し時のフォールバック、モック `/v1/models` からの正常取得をスクリプトで確認。さらに実機のLemonade Server（`192.168.85.57:13305`）に接続し、実際のノードUI上でモデル一覧が表示されることをユーザーが確認済み）
- **新規ファイル**: なし
- **修正ファイル**:
  - `llm_caption_node.py` : Lemonade Server接続ウィジェットとモデル一覧取得処理を追加
- **変更内容**:
  - `fetch_lemonade_models(host, port, api_key)` を追加。`http://{host}:{port}/v1/models` から `GET` し、レスポンスの `data[].id` をモデルID一覧として返す
  - 接続失敗・タイムアウト・不正JSON・HTTPエラー等はすべて例外を握りつぶして空リストを返す設計（ComfyUI起動を止めない）
  - `INPUT_TYPES` に `lemonade_host`（STRING, デフォルト `192.168.85.57`）、`lemonade_port`（INT, デフォルト `13305`）、`lemonade_api_key`（STRING, 空欄可）を追加
  - `model` コンボボックスを `fetch_lemonade_models()` の結果で動的構築。取得失敗時は `"(Lemonade Server unavailable - check host/port)"` の1項目にフォールバック
  - `generate()` は上記4引数を追加で受け取るのみのダミー実装のまま（LLM呼び出し本体は未実装）
- **備考**:
  - モデル一覧取得は指示書通り `INPUT_TYPES` 評価時（ComfyUI起動時／ブラウザF5リロード時）のみ実行され、動的リフレッシュボタンは未実装（指示書3章・11章で明示的にスコープ外）
  - `DEFAULT_LEMONADE_HOST`/`DEFAULT_LEMONADE_PORT` 等のモジュールレベル定数を書き換えた場合、ブラウザF5だけでは反映されない。ComfyUIサーバー（Pythonプロセス）自体の再起動が必要（Pythonのモジュールキャッシュのため）。F5はあくまで「サーバー起動中のコードのまま `INPUT_TYPES()` を再実行しモデル一覧を再取得する」動作
  - 5〜6章（LLM呼び出し本体・出力パース）は今回未着手

---

## タスク3: 指示書5章「LLMへのメッセージ構築」実装

- **完了日**: 2026-08-17
- **動作確認**: ✅済み（helper単体テスト＋実機Lemonade Server `192.168.85.57:13305` / `gemma-4-26B-A4B-it-QAT-GGUF` へのend-to-endリクエストで確認）
- **新規ファイル**: なし
- **修正ファイル**:
  - `llm_caption_node.py` : 画像前処理・メッセージ構築・Lemonade Serverへのリクエスト送信を実装
- **変更内容**:
  - 依存追加: `numpy` / `PIL`（ComfyUI同梱のため追加インストール不要）
  - `iter_images(image)` : ComfyUIの `IMAGE`（`[B,H,W,C]` バッチテンソル）と、上流が `OUTPUT_IS_LIST` の場合のテンソルのリスト、単枚 `[H,W,C]` のいずれでも「1枚単位」に平坦化して yield
  - `tensor_to_pil()` : float32 0.0〜1.0 → uint8 PIL画像。グレースケール／RGBA も RGB に正規化
  - `resize_if_needed()` : 長辺が `MAX_IMAGE_LONG_EDGE`(1024) を**超える場合のみ** LANCZOS でアスペクト比維持リサイズ。1024px以下は元オブジェクトをそのまま返す
  - `encode_image_base64()` : PNGでbase64エンコード
  - `build_user_text()` : 5.2の2パターン（`trigger_word` が空白のみの場合も空欄扱いで `Trigger word:` 行を省略）
  - `build_messages()` : system message＝プロンプトファイルの中身そのまま、user message＝テキストパート＋`image_url`（`data:image/png;base64,...`）を同一message内に格納
  - `build_chat_payload()` : `temperature` / `max_tokens` / `top_p`（内部固定 `FIXED_TOP_P = 1.0`）／`chat_template_kwargs.enable_thinking` を反映
  - `request_chat_completion()` : `POST {base_url}/chat/completions` を `timeout_sec` 付きで送信
  - `extract_response_text()` : 6章のパースは未実装のため生応答をそのまま返す。`content` が空で `reasoning_content` のみ返るサーバー実装向けに `<think>` で包むフォールバックのみ用意
  - `INPUT_TYPES` に `enable_thinking`(BOOLEAN, default True) / `temperature`(FLOAT, 0.3, 0.0〜2.0) / `max_tokens`(INT, 2048) / `timeout_sec`(INT, 120) を追加
  - `OUTPUT_IS_LIST = (True,)` を追加し、`caption_text` を入力画像と同枚数・同順序のリストとして返すよう変更（指示書2.2 / 9章の要件）
- **備考**:
  - **実機で確認できたAPI仕様（指示書11章の申し送り事項）**:
    - 画像添付は OpenAI互換の `image_url` + `data:image/png;base64,...` 形式でそのまま通る
    - `enable_thinking` は `chat_template_kwargs: {"enable_thinking": bool}` で有効。`True` にすると応答の `content` **先頭にインラインで `<think>...</think>` が含まれる**（`reasoning_content` として分離はされない）。→ **6章のパース実装時に `<think>` ブロックの除去が必須**
    - `False` 指定時は `<think>` ブロックが出ないことも確認済み
  - 確認済みの挙動: 1200x800→1024x683にリサイズされて送信／640x480はリサイズなし／バッチ2枚が入力順どおり2件のリストで返る
  - 6章（出力パース）・7章（リトライ／エラーハンドリング）は今回未着手。現状は例外がそのまま上位に送出される
  - テスト用に scratchpad へ pillow/numpy 入りの一時venvを作成（システムPythonにnumpy/PILが無く、`data/comfyui/venv` もsite-packagesがpython3.12・binのpythonが3.14で不整合のため）

## タスク2: 指示書4章「システムプロンプトファイル管理」実装

- **完了日**: 2026-08-17
- **動作確認**: ✅済み（ファイル一覧取得・読み込み・フォールバック（空フォルダ／フォルダ不在）・`generate()` 全体の動作をスクリプトで確認）
- **新規ファイル**:
  - `system_prompts/caption_training_both.txt` : 学習用（タグ+自然文両方）システムプロンプト
  - `system_prompts/caption_tags_only.txt` : タグ抽出・整合性チェック用システムプロンプト
  - `system_prompts/caption_text_only.txt` : 自然文のみ生成用システムプロンプト
- **修正ファイル**:
  - `llm_caption_node.py` : システムプロンプトファイル一覧取得・読み込み処理を追加
- **変更内容**:
  - `list_system_prompt_files()` を追加。`system_prompts/`（ノード自身のディレクトリ基準）内の `.txt` ファイル名一覧をソートして返す。フォルダ不在・読み取り不可時は例外を握りつぶして空リストを返す
  - `read_system_prompt_file(filename)` を追加。指定ファイルの中身をUTF-8でそのまま読み込んで返す
  - `INPUT_TYPES` に `system_prompt_file` コンボボックスを追加。候補が0件の場合は `"(no .txt files found in system_prompts/)"` にフォールバック
  - `generate()` は `system_prompt_file` を受け取り中身を読み込むところまで実装。LLMメッセージ構築（5章）へはまだ組み込んでいない（ダミー出力に文字数だけ含めて動作確認）
- **備考**:
  - モデル一覧と同様、ファイル一覧・中身の読み込みは `INPUT_TYPES`／`generate()` 呼び出しのたびに実行されるため、`.txt` の追加・編集はComfyUIサーバー再起動なしでも次回実行時に反映される（ただしコンボボックスの選択肢自体は他ウィジェットと同じくF5リロードが必要）
  - 5〜6章（LLM呼び出し本体・出力パース）は今回未着手
