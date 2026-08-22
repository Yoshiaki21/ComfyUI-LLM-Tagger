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

---

## タスク4: 指示書6章「出力パース仕様」実装

- **完了日**: 2026-08-17
- **動作確認**: ✅済み（パース単体テスト18ケース＋実機Lemonade Serverで3モード全てのend-to-end確認）
- **新規ファイル**: なし
- **修正ファイル**:
  - `llm_caption_node.py` : 応答パース処理と結合フォーマットを実装
- **変更内容**:
  - `CaptionParseError` 例外を追加（6.2の「応答不正」。7章のリトライ対象だがリトライ自体は未実装のため現状は上位へ送出）
  - `strip_thinking()` : `</think>` 以降のみを抽出。`<think>` が無い／閉じタグが無い場合は全体を対象。複数回出現時は**最後**の `</think>` 以降を採用
  - `split_both_parts()` : `both` のときのみ、`"---"` のみの行（ハイフン3個以上を許容）で PART1/PART2 に分割（`maxsplit=1` なのでPART2内の `---` は保持）
  - `normalize_tag_list()` : タグ区切りを `", "` に正規化。末尾のピリオドを除去。LLMがトリガーワードを出力に含めた場合は大文字小文字を無視して重複除去
  - `combine_both_output()` : 6.1の結合フォーマット `{trigger_word}, {tags}. {caption}` を組み立て。トリガーワードはプログラム側で先頭に確実に挿入し、空欄（空白のみも同様）なら省略
  - `parse_response()` : `</think>` 除去→トリム→`MIN_VALID_RESPONSE_CHARS`(4) 未満なら応答不正。`both` は分割＋結合、`tags_only`/`caption_only` は応答全体をそのまま返す
  - `generate()` を `parse_response()` 経由に変更（生応答出力をやめた）
  - `max_tokens` の既定値を 2048 → **8192** に変更（下記備考の実測理由による。指示書の目安2048から意図的に逸脱）
- **備考**:
  - **判定できるパース失敗**: `---` が無い／PART1が空／PART2が空／応答が4文字未満／PART1から有効タグが0件。いずれも `CaptionParseError` を送出
  - **実機で判明した重要な注意点**: `gemma-4-26B-A4B-it-QAT-GGUF` は `enable_thinking=True` のとき thinking だけで **約4400トークン** 消費した。`max_tokens=1500` および `4096` では thinking 途中で打ち切られ `</think>` 以降が空になり応答不正になった → 既定値を8192に引き上げた。thinking OFF時は同じ入力で43トークンしか使わない
  - モデルは `PART 1 —` のようなラベルを応答に含めなかったため、ラベル除去処理は不要と判断（実機応答で確認）
  - 参考: トリガーワード空欄で `caption_training_both.txt` を使うと、モデルがプロンプト内の例文をそのまま使い `@charactername` と出力するケースがあった。プロンプト文面側の課題であり6章のパース範囲外
  - 7章（リトライ・エラーハンドリング・ログ出力）は今回未着手

---

## タスク5: 「応答が短すぎます (0文字)」バグ修正（5章／6章の不整合）

- **完了日**: 2026-08-23
- **動作確認**: ✅済み（実機Lemonade Server `192.168.85.57:13305` / `gemma-4-26B-A4B-it-QAT-GGUF` で4ケース検証）
- **新規ファイル**: なし
- **修正ファイル**:
  - `llm_caption_node.py` : `extract_response_text()` の本文なし時の扱いを修正、`<think>` 関連コメントを実機挙動に合わせて更新
- **不具合の内容**:
  - ノード実行時、パース失敗が常に `応答が短すぎます (0文字)` になり原因が特定できなかった
  - **原因**: 5章実装時は「thinking は `content` の先頭にインラインで `<think>...</think>` として入る」と観測していたが、実機を再確認したところ**現在は `message.reasoning_content` に分離され、`content` には `<think>` が入らない**。そのため `content` が空（＝本文が1文字も生成されていない）の場合に 5章のデバッグ用フォールバック `<think>{reasoning_content}</think>` が返り、6章の `strip_thinking()` が `</think>` 以降だけを取るため**必ず空文字**になっていた
  - 本来「max_tokens不足で本文未生成」と分かるべきエラーが、5章のフォールバックと6章のパースの組み合わせで無意味なメッセージに化けていた
- **変更内容**:
  - `extract_response_text()` : `content` が空のときに `reasoning_content` を `<think>` で包んで返すフォールバックを廃止。代わりに `choices[0].finish_reason` を見て `CaptionParseError` を理由付きで送出
    - `finish_reason == "length"` → `max_tokens に達したため本文が生成されませんでした（thinking で N 文字を消費）。max_tokens を増やすか enable_thinking を OFF にしてください`
    - それ以外 → `モデルが本文を返しませんでした (finish_reason=..., thinking N 文字)`
  - `strip_thinking()` / `THINK_CLOSE_TAG` : 実機では通常ノーオペになる旨と、インライン `<think>` を返す他サーバー／モデル向けの保険として残す旨をコメントに明記
- **備考**:
  - **実機で再確認したAPI仕様（タスク3の備考を上書き）**: `gemma-4-26B-A4B-it-QAT-GGUF` は thinking を `message.reasoning_content` に分離して返す。`content` にインラインの `<think>` は含まれない
  - 実測値: 同一入力で `max_tokens=8192` → `finish_reason: stop` / completion 1197トークン（`content` 238文字、`reasoning_content` 4045文字）。`max_tokens=200` → `finish_reason: length` / `content` 0文字
  - 検証4ケース: トークン切れ／正常／`content`空+`finish_reason=stop`／インライン`<think>`（保険経路）すべて期待どおり
  - `.py` の変更のためブラウザF5では反映されず、ComfyUIサーバーの再起動が必要
  - 例外は現状そのまま上位へ伝播する（リトライ・ログ出力は7章のため引き続き未実装）

---

## タスク6: デバッグ用コンソールログの整備（設定値サマリ行の追加）

- **完了日**: 2026-08-23
- **動作確認**: ✅済み（実機Lemonade Server `192.168.85.57:13305` / `gemma-4-26B-A4B-it-QAT-GGUF` / 2枚バッチ・`both` モードで出力を確認）
- **新規ファイル**: なし
- **修正ファイル**:
  - `llm_caption_node.py` : `generate()` に設定値サマリ行を追加、画像ごとの進捗行を簡易化
  - `LLM_Caption_Node_指示書.md` : 7.4.1 を新設、12章チェックリストに1項目追加
- **背景**:
  - タスク5の不具合（`max_tokens` 不足による本文未生成）のように、**送信パラメータが分からないと切り分けができない**ケースがあったため、実行時の設定値をコンソールに残すようにした
- **変更内容（コード）**:
  - `generate()` のループ**前**に、実行開始時1回だけ設定値サマリを出力
    - 出力項目: 画像枚数 / `model` / `enable_thinking` / `temperature` / `top_p`（内部固定値 `FIXED_TOP_P`。UIに出ないため明示） / `max_tokens` / `timeout_sec`
    - バッチ内でこれらの値は不変のため、画像ごとには出力しない（100枚処理で同じ設定が100回出るのを避ける）
  - 画像ごとの進捗行から `model` を削除し `(size=WxH)` のみの簡易表示に変更（サマリ行と重複するため）
  - 「7.4のコンソール出力簡略化を行う際もこの行は残すこと」をコード上のコメントにも明記
- **変更内容（指示書）**:
  - `### 7.4 コンソール出力` の直下に `#### 7.4.1 設定値サマリ行（デバッグ用・必須）` を新設。出力例・出力項目・画像ごとに出さない理由を記載
  - 7.4.1 に **「7章のコンソール出力簡略化を実装する際も削除・省略しないこと」を「重要」として明記**（`max_tokens` 不足による本文未生成の切り分けに必須であった経緯も併記）
  - 12章チェックリストに `- [ ] 実行開始時に設定値サマリ行（枚数/model/thinking/temperature/top_p/max_tokens/timeout）が1回だけ出力される（7.4.1）` を追加
- **実際の出力例**:
  ```
  [LLMCaptionGenerator] 開始: 2枚, model=gemma-4-26B-A4B-it-QAT-GGUF, thinking=False, temp=0.3, top_p=1.0, max_tokens=8192, timeout=600s
  [LLMCaptionGenerator] 1/2 送信中 (size=1024x768)
  [LLMCaptionGenerator] 2/2 送信中 (size=1024x768)
  ```
- **備考**:
  - 7章実装時にこの行が消されないよう、指示書7.4.1 / 12章チェックリスト / コード内コメントの**3箇所**に根拠を残してある
  - 7章（リトライ・エラーハンドリング・ログファイル出力）は引き続き未着手。7.4のコンソール出力簡略化もこれから

---

## タスク7: 指示書7章「エラーハンドリング・リトライ・ログ」実装

- **完了日**: 2026-08-23
- **動作確認**: ✅済み（実機Lemonade Server `192.168.85.57:13305` / `gemma-4-26B-A4B-it-QAT-GGUF` で、正常／タグ空文字／接続失敗／タイムアウト／パース失敗の5パターンをend-to-endで確認）
- **新規ファイル**:
  - `logs/error.log`, `logs/log.log` : 実行時に自動生成されるログ（リポジトリには含めない想定）
- **修正ファイル**:
  - `llm_caption_node.py` : 事前チェック・リトライ・ログ出力・コンソール出力を実装
  - `LLM_Caption_Node_指示書.md` : 7.3のログ保存先を変更、2.1に `image_names` を追加、12章チェックリストを修正
- **変更内容（7.2 事前チェック）**:
  - `tags` が空文字（空白のみ含む）の場合、画像変換もLLM呼び出しも行わず即スキップ。リトライ対象外
  - `tags` はバッチ全体で1つの文字列のため、空の場合は**全画像がスキップ**される（現行の入力設計どおり）
- **変更内容（7.1 リトライ）**:
  - `MAX_ATTEMPTS = 3` の**単一カウンタ**で、接続失敗／タイムアウト／パース失敗をまとめて再試行
  - `RETRYABLE_EXCEPTIONS = (OSError, json.JSONDecodeError, KeyError, IndexError, CaptionParseError)`
    - `urllib.error.URLError` / `HTTPError` / `TimeoutError` はいずれも `OSError` のサブクラスなので接続失敗・タイムアウトはこれで捕捉できる
  - `classify_error()` を追加し、簡易理由を `timeout` / `connection_failed` / `http_{code}` / `parse_error` / `invalid_response` に分類
  - **「最大3回リトライ」は合計3回試行と解釈**（指示書の「3回とも失敗した場合」に合わせた）。初回＋3回＝計4回にする場合は `MAX_ATTEMPTS = 4` に変えるだけ
- **変更内容（9章 枚数維持）**:
  - スキップ時は `caption_text` に空文字を入れ、入力画像と同じ枚数・順序を維持
- **変更内容（7.3 ログ）**:
  - `write_log(log_dir, message, is_error=False)` : `log.log` には常時、`is_error=True` のときは `error.log` にも同じ行を追記
  - `append_log_line()` : **書き込みのたびに `open`/`close`**（指示どおり）。書き込み失敗は `print` するだけで本処理は止めない
  - `ensure_log_dir()` : 出力先 `LOG_DIR` を `os.makedirs(exist_ok=True)` で用意
  - 記録内容: `RUN 開始:...` / `START:` / `RETRY n/3:`（詳細な例外メッセージ付き）/ `SUCCESS:` / `SKIPPED:` / `RUN END: success=N skipped=M`
- **変更内容（7.4 コンソール）**:
  - 失敗時は `[LLMCaptionGenerator] SKIPPED: melte0001.png (timeout)` のみ。リトライ詳細はログファイルだけに記録
  - 完了時に `完了: 成功 N件 / スキップ M件` を出力（スキップがある場合のみ `error.log` のパスを併記）
- **ログ出力先の仕様変更（指示書7.3を書き換え）**:
  - **問題**: 指示書7.3は「入力画像と同じフォルダ」にログを出す仕様だが、**ComfyUI の `IMAGE` 型にはファイルパス情報が含まれず**、2.1の入力定義にも画像フォルダの入力が無いため、ノード単体では画像フォルダを特定できない
  - 当初は `image_folder` / `image_names` の2つを `optional` 入力として追加し「①`image_folder` → ②`image_names`のフルパスの親 → ③ノード配下 `logs/`」の順で解決する実装にしたが、**ユーザー判断でノードディレクトリ直下の `logs/` に固定**する方針に変更
  - `LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")`（`system_prompts/` と同じ解決方式）。Dockerで `/app/custom_nodes/ComfyUI-LLM-Tagger/` に配置した場合は `/app/custom_nodes/ComfyUI-LLM-Tagger/logs/` になる
  - `image_folder` 入力は用途が消えたため**削除**。`image_names`（改行区切り、`namelist` 相当）は**ログのファイル名として引き続き必要なので残した**。未指定時は `image_001` 形式の連番ラベル
  - 実行開始時に `[LLMCaptionGenerator] ログ出力先: ...` を出力し、実際のパスを確認できるようにした
  - 指示書側は 7.3 に【変更履歴 2026-08-23】として理由付きで反映済み。併せて 2.1 に `image_names` の行を追加、12章チェックリストを `logs/` 基準に修正
- **検証結果**:
  | ケース | コンソール | error.log |
  |---|---|---|
  | 正常（2枚） | 成功 2件 / スキップ 0件 | 記録なし |
  | タグ空文字 | `SKIPPED: melte0001.png (empty_tags)` | `reason=empty_tags`（RETRY行なし） |
  | 接続失敗（port 1） | `SKIPPED: ... (connection_failed)` | `reason=connection_failed (3 attempts exhausted)` |
  | タイムアウト（`timeout_sec=1`） | `SKIPPED: ... (timeout)` | `reason=timeout (3 attempts exhausted)` |
  | パース失敗（`both`＋tags_only用プロンプト） | `SKIPPED: ... (parse_error)` | `reason=parse_error (3 attempts exhausted)` |
  - いずれのケースも `caption_text` は入力と同じ2件（失敗分は空文字）を返すことを確認
  - 複数回の実行で `log.log` が追記されること（新規作成にならないこと）も確認
- **備考**:
  - `logs/` はリポジトリ直下に作られるため、`.gitignore` に `logs/` と `__pycache__/` を入れることを推奨（**未対応**）
  - Docker運用ではコンテナ内パスになるため、ホストから読むにはそのフォルダのバインドマウントが必要
  - 8章（`always_regenerate` / `IS_CHANGED`）は今回未着手

---

## タスク8: 指示書9章「バッチ処理・型整合性」対応（`INPUT_IS_LIST = True`）

- **完了日**: 2026-08-23
- **動作確認**: ✅済み（送信内容を捕捉したペアリング検証＋実機Lemonade Serverでの1枚構成、件数不一致の警告、ヘルパー単体6パターン）
- **新規ファイル**: なし
- **修正ファイル**:
  - `llm_caption_node.py` : `INPUT_IS_LIST = True` を宣言し、リスト入力の取り扱いを実装
  - `LLM_Caption_Node_指示書.md` : 9.1を新設、11.1（周辺ノードの既知問題）を新設、12章チェックリストに3項目追加
- **背景（発見した不具合）**:
  - `LoRA Caption Load → WD14 Tagger → 本ノード → LoRA Caption Save` の構成を検討する中で発覚
  - **`WD14 Tagger` は `OUTPUT_IS_LIST = (True,)` を宣言しており、「画像1枚につき1件」のタグ文字列をリストで返す**（`comfyui-wd14-tagger/wd14tagger.py:185-186`）
  - 本ノードが `INPUT_IS_LIST` を宣言していなかったため、ComfyUIの実行エンジンが**リスト要素ごとにノードを再実行**する（`execution.py` の `map_node_over_list`。短いリストは最後の要素を使い回す仕様）
  - 結果、画像N枚のとき **ノードがN回実行され、そのたびにN枚全部のバッチが渡る → LLM呼び出しが N×N 回**発生し、**タグと画像の対応が完全に崩れ**、`caption_text` が N²件になっていた
  - 指示書9章の「実装時にどちらが安全か要検証」がまさにこの箇所だった
- **変更内容**:
  - クラスに **`INPUT_IS_LIST = True`** を宣言（`OUTPUT_IS_LIST = (True,)` は変更なし）
  - `first_value(value, default)` を追加。リストで届くウィジェット値から単一値を取り出す。未接続の `optional` が素の値で届くケースにも対応
  - `resolve_tags_per_image(tags, count)` を追加
    - i番目の画像に i番目のタグを対応させる
    - タグが1件のみ（手入力・STRING直結）なら全画像に同じタグを適用（従来の挙動を維持）
    - 多い分は切り捨て、足りない分は空文字で埋める（空文字は7.2の `empty_tags` としてスキップ・記録される）
  - `generate()` 冒頭で `tags` 以外の全入力を `first_value()` 経由で取得
  - 7.2の空タグ判定を**バッチ全体 → 画像ごと**に変更
  - タグ件数と画像枚数の不一致時に警告をコンソールとログへ出力（処理は継続）
- **検証結果**:
  - 3枚バッチ・タグ3件 → **LLM呼び出し3回**（修正前の設計なら9回）。1回目`1girl, standing` / 2回目`1girl, sitting` / 3回目`1girl, lying` と**正しく1対1対応**。出力3件
  - ログにも `Name list` 由来の実ファイル名が `melte0001.png` → `0002` → `0003` の順で記録
  - 通常の `Load Image` 1枚・`image_names` 未接続 → 実機で正常にキャプション生成（`image_names` 引数自体が渡らないケースも `first_value` のフォールバックで動作）
  - 件数不一致（タグ2件・画像3枚）→ `WARNING: タグ 2件 と 画像 3枚 の件数が一致しません` を出力し、3枚目は `SKIPPED: image_003 (empty_tags)`、出力は3件を維持
- **`image_names` の扱い**:
  - ユーザー判断で**残す**ことに決定。`IMAGE` 型にファイル名が無い以上、`LoRA Caption Load` の `Name list` を受け取る経路はこれだけであり、削除すると `error.log` が `image_001` の連番になり失敗画像を特定できなくなるため
  - `Name list` は `OUTPUT_IS_LIST` を持たない普通の STRING 出力なので、`INPUT_IS_LIST = True` 下では要素1個のリストで届く。`[0]` を取って改行分割すればよく、既存ロジックがそのまま使える
  - 参考: `WD14 Tagger` にファイル名の入力が無いのは、同ノードがファイルもログも書かないため。ファイル名は `LoRA Caption Load` → `LoRA Caption Save` へ直接流れており、WD14 Tagger を迂回している
- **備考（周辺ノードの既知の問題・本ノードでは解消不可）**:
  - **フォルダ内の `.png` がちょうど1枚のとき `LoRA Caption Load` が壊れる**（`LoRAcaption.py:150` で `return (images[0], 1)` と2要素しか返さず `RETURN_TYPES` の3出力と不一致）。1枚だけ処理する場合は通常の `Load Image` を使うこと
  - **`Name list` と `Image list` の順序が保証されていない**（前者は `glob.glob`、後者は `os.listdir`、どちらもソートなし）。ずれるとログのファイル名と実際の失敗画像が食い違う
  - `image_names` の区切りは改行とカンマだが、カンマを含むファイル名は使わない運用のため対処不要と判断
  - 8章（`always_regenerate` / `IS_CHANGED`）は引き続き未着手

---

## タスク9: 指示書8章「キャッシュ制御（always_regenerate）」実装

- **完了日**: 2026-08-23
- **動作確認**: ✅済み（`INPUT_TYPES` と `IS_CHANGED` / `generate()` の引数一致を `inspect` で検証、ON/OFF両モードの戻り値、ComfyUIが実際に渡す形での呼び出し、`generate()` の後方互換）
- **新規ファイル**: なし
- **修正ファイル**:
  - `llm_caption_node.py` : `always_regenerate` ウィジェットと `IS_CHANGED` を追加
  - `LLM_Caption_Node_指示書.md` : 8.1（実装上の注意）を新設
- **変更内容**:
  - `INPUT_TYPES` の `required` 末尾に `"always_regenerate": ("BOOLEAN", {"default": False})` を追加（指示書2.1の並びに合わせて `timeout_sec` の後ろ）
  - `IS_CHANGED` を `@classmethod` として実装
    - ON → `float("nan")` を返す。NaN は自身との等値比較が成立しない（`nan == nan` は `False`）ためキャッシュキーが常に不一致になり、毎回LLMを呼ぶ
    - OFF → 固定値 `False` を返し、ComfyUI標準のキャッシュ挙動に任せる
  - 引数の並びを `INPUT_TYPES`（`required` → `optional`）と完全一致させ、`optional` の `image_names` のみ既定値を持たせた
  - `generate()` にも `always_regenerate` を追加（キャッシュ制御専用のため生成処理では未使用。コメントで明記）
- **ComfyUI本体のソースで確認した点（指示書8.1に反映済み）**:
  - **`INPUT_IS_LIST = True` は `IS_CHANGED` にも適用される**。`IsChangedCache.get()` が `generate()` と同じ `_async_map_node_over_list` 経由で呼ぶため全入力がリストで届く → `always_regenerate` は `first_value()` で取り出す必要がある（タスク8で追加したヘルパーを流用）
  - **接続済みの入力は `IS_CHANGED` 呼び出し時点で未確定であり `(None,)` で届く**（`execution.py` の `get_input_data` が `execution_list=None` のとき未解決リンクを `(None,)` にする）。判定はウィジェット値のみを根拠にすること
  - **OFF時に固定値を返すのが正しい**。キャッシュキーは `[class_type, IS_CHANGEDの戻り値] + 全入力値 + 上流ノードの署名` で構成されるため（`comfy_execution/caching.py` の `get_immediate_node_signature`）、固定値でも入力が変われば再実行される
- **検証結果**:
  ```
  引数一致 IS_CHANGED == INPUT_TYPES : True
  引数一致 generate()  == INPUT_TYPES : True
  ON  -> nan    isnan=True   自身と等しい？ False
  OFF -> False  実行ごとに同値？ True
  ```
  - `image_names`（optional）を省略した呼び出しも成功
  - ComfyUIが実際に渡す形（全入力リスト＋接続済み入力は `(None,)`）でON/OFF両方を確認
  - `generate()` が `always_regenerate` を受け取っても従来どおり動作（2枚 → 出力2件）
- **備考**:
  - これで指示書の**3章〜9章がすべて実装済み**（1〜2章は定義、10章は同梱データ、11〜12章は申し送り・チェックリスト）
  - `.gitignore`（`logs/` と `__pycache__/`）は引き続き**未対応**

---

## タスク10: プロンプト・生応答のログ出力（`prompt.log` / `log_prompt`）

- **完了日**: 2026-08-23
- **動作確認**: ✅済み（実機Lemonade Server `192.168.85.57:13305` / `gemma-4-26B-A4B-it-QAT-GGUF`、thinking ON で `prompt.log` の内容を確認。ON/OFF両方、引数一致も検証）
- **新規ファイル**:
  - `logs/prompt.log` : `log_prompt` ON時のみ生成されるプロンプト・応答ログ
- **修正ファイル**:
  - `llm_caption_node.py` : `log_prompt` ウィジェットと `prompt.log` 出力を追加
  - `LLM_Caption_Node_指示書.md` : 7.3.1を新設、2.1に `log_prompt` を追加、12章チェックリストに2項目追加
- **目的**:
  - システムプロンプトが想定どおり機能しているかを検証するため、LLMへの送信内容と生応答を記録できるようにする
- **設計判断（実装前に検討して決定）**:
  1. **出力先は `prompt.log` に分離**（`log.log` に混ぜると通常のログが埋もれるため）
  2. **生応答も記録する**（パース失敗の原因究明には「何を送って何が返ったか」の両方が要るため）
  3. **thinking は全文記録**（文字数のみでは検証に使えない。実機の thinking はプロンプトの指示を1項目ずつ検証している様子がそのまま出るため、プロンプトのどの指示が効いていて どれが無視されたかを判断できる唯一の材料。1枚あたり約4KBで、除外する base64 の1MBと比べれば無視できるサイズ）
  4. **コンソールには出さない**（7.4のコンソール簡易表示方針を維持）
- **変更内容**:
  - `INPUT_TYPES` の `required` に `"log_prompt": ("BOOLEAN", {"default": False})` を追加（`always_regenerate` の後ろ）。8.1の規約どおり `IS_CHANGED` と `generate()` の引数も同じ並びに揃えた
  - 定数 `PROMPT_LOG_FILENAME = "prompt.log"` / `PROMPT_LOG_INDENT = "    "` を追加
  - `log_timestamp()` を関数として切り出し、`write_log()` をそれに寄せた
  - `write_prompt_log(log_dir, header, body)` を追加。多行の本文は継続行をインデントして1ブロックとして追記（行指向の `log.log` と混ざらない形）
  - `describe_image_part(pil_image, image_base64)` を追加。**base64本体は記録せず** `<image 1024x768 PNG 約765KB / base64は省略>` に置換
  - `format_response_for_log(response_payload)` を追加。`finish_reason` / `usage` / `reasoning_content` 全文 / `content` 全文をラベル付きで整形。**すべて `.get()` で defensive に取り出す**（ここで例外を出すと7.1のリトライ判定に紛れ込むため）
  - 記録の頻度: `==== RUN ... ====` と `PROMPT system` は実行開始時に1回、`PROMPT user` は画像ごと、`RESPONSE` は試行ごと（リトライ時も各回記録）
- **検証結果**:
  - `log_prompt=False` → `prompt.log` が**作成されないこと**を確認
  - `log_prompt=True`（thinking ON、1枚） → 102行 / 7,991文字。内訳は system prompt 2,551文字、user テキスト部、`reasoning_content` 4,003文字、`content` 294文字
  - `<image 1024x768 PNG 約765KB / base64は省略>` の1行のみで、**base64本体は含まれない**ことを grep で確認
  - `log.log` には従来どおり `RUN` / `START` / `SUCCESS` / `RUN END` のみが記録され、プロンプトが混ざらないことを確認
  - `INPUT_TYPES` / `IS_CHANGED` / `generate()` の引数一致を `inspect` で再検証（16項目、すべて一致）
- **備考**:
  - 100枚バッチで約460KB/回の増加見込み（base64を除外しているため）。追記型なのでローテーションは未実装、肥大化したら手動削除
  - `prompt.log` も `logs/` 配下のため `.gitignore` 済み
---
