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

## タスク11: 処理時間・トークン生成速度のログ記録

- **完了日**: 2026-08-23
- **動作確認**: ✅済み（整形ヘルパーの単体テスト＋実機Lemonade Serverでの記録内容を確認。リトライが実際に発生したケースも観測）
- **新規ファイル**: なし
- **修正ファイル**:
  - `llm_caption_node.py` : 所要時間・トークン生成速度の計測と記録を追加
  - `LLM_Caption_Node_指示書.md` : 7.3.1の `RESPONSE` 記録内容と計測方針、7.3の `log.log` 説明を更新
- **決定事項（ユーザー判断）**:
  1. LLM1回あたりの所要時間に加え、**トークン生成速度も記録する**
  2. 失敗（タイムアウト・接続失敗）時の経過時間は**記録しない**
  3. 実行全体の所要時間は **`log_prompt` の ON/OFF に関わらず常時記録**する
- **変更内容**:
  - `import time` を追加
  - `format_duration(seconds)` を追加。`3.1秒` / `12分34秒` / `1時間2分3秒` の形に整形（負値は0秒扱い）
  - `format_response_timing(elapsed_sec, response_payload)` を追加。`50.4秒, 23.5 tok/s` の形。**`usage` を返さないサーバー向けに tok/s は取得できたときだけ付ける**（`usage` なし／空dict／`elapsed=0` では秒数のみ）
  - `generate()` の冒頭で `run_started = time.monotonic()` を記録
  - リトライループ内で `request_chat_completion()` の前後を計測し、`prompt.log` の `RESPONSE` 見出しに反映
  - `log.log` の `RUN END` 行に `elapsed=...` を追加（常時）
- **検証結果**:
  - `format_duration`: `0.0秒` / `3.1秒` / `59.9秒` / `1分0秒` / `12分34秒` / `1時間2分3秒`、負値も `0.0秒`
  - `format_response_timing`: usage あり → `50.4秒, 23.5 tok/s`、usage なし・空dict・`elapsed=0` → 秒数のみ
  - 実機の `prompt.log`:
    ```
    RESPONSE melte0001.png (attempt 1/3, 196.2秒, 41.8 tok/s):
    RESPONSE melte0001.png (attempt 2/3, 25.8秒, 52.5 tok/s):
    RESPONSE melte0001.png (attempt 1/3, 68.8秒, 49.0 tok/s):
    ```
  - 実機の `log.log`: `RUN END: success=1 skipped=0 elapsed=3分42秒` / `elapsed=1分8秒`
- **備考（実機で観測した重要な事象）**:
  - 検証中に**1回目の試行で thinking が暴走**し、`max_tokens=8192` を使い切って本文が生成されないケースが実際に発生した（`thinking で 26729 文字を消費`）。**7章のリトライが働いて2回目で成功**し、`SUCCESS: melte0001.png mode=both attempt=2` として記録された
  - つまり `max_tokens=8192` でも thinking 暴走は起こりうる。リトライ機構が実運用で機能していることの実証にもなった
  - 同じ入力でも所要時間は 25.8秒〜196.2秒（thinking量に依存）と大きく変動する。tok/s は 41.8〜52.5 と比較的安定しており、モデル・設定の比較にはこちらが有用

---

## タスク12: 指示書13章「Thinkモード暴走対策」実装

- **完了日**: 2026-08-23
- **動作確認**: ✅済み（パラメータ調整の単体テスト6パターン＋実機タイムアウト／パース失敗／接続失敗の3シナリオでログを確認）
- **新規ファイル**: なし
- **修正ファイル**:
  - `llm_caption_node.py` : `X-Request-Id` 付与、キャンセル呼び出し、リトライ時パラメータ調整、ログ反映
  - `LLM_Caption_Node_指示書.md` : 13.1にキャンセルAPI調査結果を追記、13.4の保留事項を更新
- **13.1 キャンセルAPIの調査結果（重要）**:
  - **Lemonade Server 11.5.0 にはキャンセル用エンドポイントが存在しないことを実機で確認した**
  - 404だったもの: `/openapi.json` `/docs` `/api/openapi.json` `/api/v1/docs` `/v1/docs`（APIリファレンス自体が非公開）、`/api/v1/` 配下の `halt` `stop` `cancel` `abort` `interrupt` `terminate` `kill` `requests` `generate/stop` `chat/completions/cancel` `completions/cancel`、OpenAI Responses API 形式の `POST /api/v1/responses/{id}/cancel` `POST /v1/responses/{id}/cancel` `DELETE /api/v1/responses/{id}` `DELETE /api/v1/chat/completions/{id}`
  - 唯一 `POST /api/v1/unload` が200を返すが、**モデル自体をアンロードする**ため他の処理・他の利用者に影響する。単一リクエストのキャンセル用途には使えないため**採用しなかった**
  - **対応方針**: 仕組みは実装済みとし、パスを定数 `LEMONADE_CANCEL_PATH`（既定 `""`）で切り替え可能にした。空文字の間はキャンセルをスキップして `CANCEL_SKIPPED ... reason=no_endpoint_configured` を記録する。将来サーバーが対応したら**定数にパスを設定するだけで有効になる**
- **変更内容（13.1）**:
  - `import uuid` を追加。リクエストごとに `uuid.uuid4()` で一意なIDを発行し `X-Request-Id` ヘッダーとして送信（`request_chat_completion()` に `request_id` 引数を追加）
  - `cancel_request()` を追加。タイムアウト検知時のみ呼ばれ、`{"request_id": ...}` を POST する。**ベストエフォート**で、失敗しても例外を外に出さずリトライ処理を継続する（`CANCEL_FAILED` を記録）
  - `CANCEL_TIMEOUT_SEC = 5`
- **変更内容（13.2）**:
  - `adjust_retry_params(attempt, base_max_tokens, base_temperature, adjust=True)` を追加
  - 定数はファイル冒頭にまとめた: `RETRY_MAX_TOKENS_SCALE = (1.0, 0.5, 0.25)` / `RETRY_MAX_TOKENS_FLOOR = (0, 512, 256)` / `RETRY_TEMPERATURE_DELTA = (0.0, 0.2, 0.4)` / `RETRY_TEMPERATURE_CEILING = 1.0` / `NO_PARAM_ADJUST_REASONS = ("connection_failed",)`。**ウィジェットには公開していない**
  - 下限でクリップした後に**元の設定値を超えないようにクリップ**している（ユーザーが `max_tokens=300` のように下限より小さい値を設定した場合に、リトライで逆に増えてしまうのを防ぐため）
  - `temperature` は浮動小数の誤差を避けるため `round(..., 2)`（`0.3 + 0.4 = 0.7000000000000001` 対策）
  - 添字は `min(attempt - 1, len(...) - 1)` でクリップし、`MAX_ATTEMPTS` を増やしても添字が溢れないようにした
  - `payload` の構築をリトライループの**内側**へ移動（試行ごとにパラメータが変わるため）
- **変更内容（13.3）**:
  - `RETRY` 行の書式を13.3の例に合わせて変更: `RETRY: melte0001.png attempt=2/3 max_tokens=4096 temperature=0.5 reason=timeout detail=...`
  - `CANCEL_REQUEST_SENT` / `CANCEL_FAILED` / `CANCEL_SKIPPED` を `log.log` に記録
  - `prompt.log` の `RESPONSE` 見出しに使用パラメータを付記: `(attempt 2/3, 25.8秒, 52.5 tok/s, max_tokens=4096, temp=0.5)`
- **検証結果**:
  - パラメータ調整（`max_tokens=8192, temp=0.3`）: 1回目 `8192/0.3` → 2回目 `4096/0.5` → 3回目 `2048/0.7`
  - 下限クリップ（`max_tokens=600`）: `600` → `512` → `256`
  - 元の値を超えない（`max_tokens=300`）: `300` → `300` → `256`
  - `temperature` 上限クリップ（base=0.9）: `0.9` → `1.0` → `1.0`
  - 接続失敗（`adjust=False`）: 3回とも `8192/0.3` のまま
  - `attempt=5` でも添字が溢れず `(2048, 0.7)`
  - 実機タイムアウト: `CANCEL_SKIPPED request_id=19a3ee54-... reason=no_endpoint_configured` → `RETRY: ... attempt=1/3 max_tokens=8192 temperature=0.3 reason=timeout` → 2回目 `4096/0.5` → 3回目 `2048/0.7` → `SKIPPED`
  - パース失敗: 同様にパラメータが段階的に変化し、`request_id` が試行ごとに異なることを確認
  - 接続失敗: 3回とも `max_tokens=8192 temperature=0.3` で据え置き（13.2の規定どおり）
- **備考**:
  - キャンセルできない以上、**タイムアウト後もサーバー側の生成はしばらく走り続ける可能性がある**。13.2 のパラメータ調整が実質的な暴走対策の主軸となる（指示書13.4にも追記）
  - Lemonade Server内部の約5分タイムアウトは引き続きクライアント側からは変更できない

---

## タスク13: 指示書13.5「接続切断による暗黙的キャンセル」実装（v11.7.0対応）

- **完了日**: 2026-08-23
- **動作確認**: ✅済み（CPythonソースでのクローズ経路確認＋ソケットリーク検査＋実機タイムアウトのログ確認＋バックエンド停止の間接測定）
- **新規ファイル**: なし
- **修正ファイル**:
  - `llm_caption_node.py` : `request_chat_completion()` の接続クローズを明示化、`CONNECTION_ABORTED` ログを追加
  - `LLM_Caption_Node_指示書.md` : 13.5.4「実装結果」を新設
- **サーバー状況の確認**:
  - `GET /api/v1/health` → **`"version":"11.7.0"`。既にアップデート済みだった**
  - v11.7.0 でも `POST /api/v1/requests/{id}/cancel` `POST /v1/requests/{id}/cancel` `/api/v1/cancel` `/api/v1/halt` `/api/v1/stop` `/v1/chat/completions/{id}/cancel` `/openapi.json` はすべて404。**正式なキャンセルAPIは未提供のまま**（指示書13.1の記述どおり）。`LEMONADE_CANCEL_PATH` は空文字のまま維持
- **変更内容（13.5.1）**:
  - 指示書は `requests` / `httpx` を前提に書かれているが、**本ノードは標準ライブラリの `urllib`（非ストリーミング）を使用**しているため、そちらでクローズを確認・保証した
  - `request_chat_completion()` を `with urllib.request.urlopen(...)` から `try/finally` 構成に変更し、`finally: response.close()` で明示クローズするようにした
  - CPython の `urllib/request.py` `AbstractHTTPHandler.do_open` を読んで2経路とも閉じられることを確認し、根拠をコードコメントに残した
    - **応答ヘッダ待ちでのタイムアウト（Thinkモードの長いprefillはこの経路）** → `h.getresponse()` の例外を `except: h.close(); raise` が捕捉してソケットを即クローズ
    - **ヘッダ受信後の `read()` 中のタイムアウト** → `do_open` が既に `h.sock.close()` 済み。残る `HTTPResponse` を実装側の `finally` で閉じる
  - 将来ストリーミングに変更する場合もこの `finally` は必須である旨をコメントに明記
- **変更内容（13.5.2）**:
  - タイムアウト検知時、**キャンセルAPI呼び出しより先に** `CONNECTION_ABORTED` を記録するよう順序を変更（13.5.1の処理順序に準拠）
  - 記録例: `CONNECTION_ABORTED: melte0001.png reason=timeout note=prefill_cancel_supported_v11.7+`
  - `LEMONADE_CANCEL_PATH` 未設定時は従来どおり `CANCEL_SKIPPED ... reason=no_endpoint_configured` も併記され、**どちらのキャンセル手段が働いたか後から判別できる**
- **検証結果**:
  - **ソケットリーク検査**: タイムアウトを3回連続で発生させ、開いているソケット数が 前=0／後=0 で変化しないことを確認
  - **実機タイムアウト（`timeout_sec=1`）の `log.log`**:
    ```
    CONNECTION_ABORTED: melte0001.png reason=timeout note=prefill_cancel_supported_v11.7+
    CANCEL_SKIPPED request_id=521b051e-... reason=no_endpoint_configured
    RETRY: melte0001.png attempt=1/3 max_tokens=8192 temperature=0.3 reason=timeout detail=timed out
    ```
    3試行とも同じ順序で記録され、13.2のパラメータ調整（8192/0.3 → 4096/0.5 → 2048/0.7）も併存して動作
  - **バックエンド停止の間接測定（13.5.3の3項目め）**: 長い生成を投げて3秒で切断し、直後に短いリクエストの応答時間を測定
    | 条件 | 応答時間 |
    |---|---|
    | アイドル時の基準（4回） | 0.24 / 0.24 / 0.24 / 0.25 秒 |
    | 切断直後（3回） | **1.49 / 1.01 / 52.80 秒** |
    - 切断後もバックエンドが `max_tokens=8192` を生成し続けていれば約160秒（実測50 tok/s換算）塞がるはずで、**3回中2回が約1〜1.5秒で復帰したことから、接続切断でバックエンド側の生成も中断されていると判断できる**
    - ただし1回だけ52.80秒かかっており、原因特定にはサーバー側のログ・GPU使用率の確認が必要。**本ノード側からは確認できないため未検証のまま残した**（指示書13.5.4にも明記）
- **備考**:
  - 13.1〜13.4 のキャンセルAPI呼び出しの仕組みはそのまま維持しており、将来 `LEMONADE_CANCEL_PATH` にパスを設定すれば二重措置として機能する
  - 「指示書の3.5」とのご指示だったが、3章に3.5は存在せず内容が一致する **13.5** として実装した

---

## タスク14: 指示書6.3・7.1・13.2・13.6「finish_reasonによる分類とリトライ分岐化」実装

- **完了日**: 2026-08-23
- **動作確認**: ✅済み（分類・クランプの単体テスト＋5シナリオの分岐テスト＋実機で `finish_reason=="length"` を発生させた倍増確認）
- **新規ファイル**: なし
- **修正ファイル**:
  - `llm_caption_node.py` : 失敗分類の4分類化、リトライの分岐ロジック化、`max_tokens` 自動増量とクランプ、ログ更新
  - `LLM_Caption_Node_指示書.md` : 13.6.4「実装結果」を新設
- **変更内容（6.3 finish_reason による分類）**:
  - `CaptionParseError` に `category` 属性を追加（既定 `parse_format`）
  - `classify_parse_failure(response_payload, requested_max_tokens)` を追加。`finish_reason == "length"` → `parse_length`。加えて **`usage.completion_tokens >= 要求max_tokens` なら `finish_reason == "stop"` でも `parse_length`** とみなす（6.3の補強材料）。`usage` 未対応サーバーでは `finish_reason` のみで判定
  - `parse_response()` に `failure_category` 引数を追加し、内部で送出される例外に分類を付与する構造にした（本体は `_parse_response_body()` へ分離）
  - `extract_response_text()` の「本文なし」例外も `finish_reason` に応じて `parse_length` / `parse_format` を付与
- **変更内容（7.1 分類名の統一）**:
  - `classify_error()` が返す名前を4分類に統一: `connection`（旧 `connection_failed`）/ `timeout` / `parse_length` / `parse_format`（旧 `parse_error`）
  - 4分類に当てはまらないもの（`http_{code}` / `invalid_response`）は独自名を返し、**パラメータ調整の対象外（据え置き）**として扱う
- **変更内容（13.2/13.6 リトライの分岐化）**:
  - 固定テーブル方式の `adjust_retry_params()` を廃止し、**直前の試行の失敗理由で分岐する** `next_attempt_params()` に置き換え
    - `parse_length` → 13.6：直前に使用した値の**2倍**（`temperature` は据え置き）
    - `timeout` / `parse_format` → 13.2：`shrink_retry_params()`（表を試行回数で索く。基準はウィジェット設定値）
    - `connection` ほか → 調整なし（直前に使用した値のまま再試行）
  - リトライ予算は7.1どおり**4分類共有で合計3回**。`parse_length` 専用の別枠は設けていない
- **変更内容（13.6.1 上限クランプ）**:
  - `fetch_lemonade_models()` が `/v1/models` の `max_context_window` を `MODEL_CONTEXT_WINDOWS` にキャッシュするよう変更
  - `get_model_context_window()` を追加。キャッシュミス時は1回だけ再取得し、取得できなければ `None` をキャッシュしてクランプを行わない（画像ごとの再取得を避ける）
  - `estimate_prompt_tokens()` : テキスト文字数 ÷ 4 ＋ 画像分1024トークンの概算。**ただし応答の `usage.prompt_tokens` が取れた時点で実測値へ差し替える**（base64の文字数で数えると1MB≒25万トークン相当になり無意味なため、画像は固定値見積もりにした）
  - `clamp_max_tokens()` : `max_context_window - プロンプト推定 - 256(余裕)` を上限とし、`MIN_MAX_TOKENS = 256` を下回らせない
  - コンテキスト長はバッチ内で不変のため、`generate()` の画像ループ**前**に1回だけ解決する
- **変更内容（2.1 ウィジェットの意味変更）**:
  - `max_tokens` の名前・型・既定値（8192）は変更せず、**ツールチップを追加**して「初期値。尻切れ時に自動で倍増（`max_context_window` でクランプ）」の意味に更新
- **変更内容（13.3/13.6.2 ログ）**:
  - `RETRY` 行の `reason=` が4分類名になった
  - クランプ発生時は同じ行に `note=clamped_by_max_context_window` を付記
- **検証結果**:
  | シナリオ | 各試行の `max_tokens` / `temperature` |
  |---|---|
  | `parse_length` ×3（window=32768, prompt=911） | `8192/0.3` → `16384/0.3` → **`31601/0.3`（クランプ）** |
  | `parse_length` → `timeout` → 3回目 | `8192/0.3` → `16384/0.3` → **`2048/0.7`（13.2の縮小へ切替）** |
  | `parse_format` ×3 | `8192/0.3` → `4096/0.5` → `2048/0.7` |
  | `connection` ×3 | `8192/0.3` ×3（据え置き） |
  | 1回目で成功 | `8192/0.3` のみ |
  - 分類の単体テスト: `finish_reason=length` → `parse_length` / `stop`+区切りなし → `parse_format` / `stop` だが `completion==max_tokens` → `parse_length` / `usage`なし+`stop` → `parse_format`
  - クランプの単体テスト: `desired=32768,window=32768` → `31601`(clamped) / `window=None` → クランプなし / `window=2000` → `833`（下限256は割らない）
  - **実機検証**: `gemma-4-26B-A4B-it-QAT-GGUF` の `max_context_window` が **262144** としてサーバーから取得できることを確認。`max_tokens=8` を指定して実際に `finish_reason=="length"` を発生させ、**`8 → 16 → 32` と倍増**することを確認
  - 13.5（接続切断まわり）のロジックは変更しておらず、`CONNECTION_ABORTED` → `CANCEL_SKIPPED` → `RETRY` の順序も従来どおり動作
- **確認事項（指示書の記述の食い違い・要判断）**:
  - 13.2の補足「1回目`parse_length`→2回目`timeout`となった場合、2回目のtimeout対応は本表の『2回目』の行を適用する」は、表が試行回数で索かれる設計と整合しない（2回目の試行が失敗したとき調整対象になるのは**3回目**の試行のため）
  - 指示の「`timeout`/`parse_format` は**既存の13.2ロジック**を適用」と表の構造から、**表の行番号＝試行回数**（既存実装どおり）と解釈して実装した。上表の「`parse_length` → `timeout`」で3回目が `2048/0.7`（3回目の行）になっているのはこの解釈による
  - もし「2回目の行（`4096/0.5`）」が正しい場合は、`shrink_retry_params()` の索引の取り方を1行変えるだけで切り替え可能

---

## タスク15: 指示書4.1「output_mode の自動判定（メタデータ行方式）」実装

- **完了日**: 2026-08-23
- **動作確認**: ✅済み（メタデータ判定の単体テスト7ケース＋実機で3モード＋異常系＋13.6リトライの回帰確認）
- **新規ファイル**: なし
- **修正ファイル**:
  - `llm_caption_node.py` : `output_mode` ウィジェット廃止、メタデータ行の解析と異常系処理を追加
  - `system_prompts/caption_training_both.txt` : 1行目に `<!-- output_mode: both -->` を追加
  - `system_prompts/caption_tags_only.txt` : 1行目に `<!-- output_mode: tags_only -->` を追加
  - `system_prompts/caption_text_only.txt` : 1行目に `<!-- output_mode: caption_only -->` を追加
  - `LLM_Caption_Node_指示書.md` : 4.1.1「実装結果」を新設
- **変更内容**:
  - `INPUT_TYPES` から `output_mode` コンボボックスを削除。指示書8.1の規約どおり `IS_CHANGED` と `generate()` の引数も同時に削除して3箇所を揃えた（現在15項目）
  - `parse_system_prompt_file(filename)` を追加。戻り値は `(output_mode, system_message)` で、**メタデータ行を取り除いた本文だけ**を返す（除去後に先頭へ残る空行も落とす）
  - 判定は `OUTPUT_MODE_HEADER_PATTERN = ^\s*<!--\s*output_mode\s*:\s*([A-Za-z_]+)\s*-->\s*$` を**1行目のみ**に適用。空白の揺れは許容するが2行目以降は認識しない
  - `VALID_OUTPUT_MODES = ("tags_only", "caption_only", "both")` 以外の値は不正扱い
  - `generate()` 内で判定結果を内部変数 `output_mode` として保持し、`parse_response()` / サマリ行 / `SUCCESS` ログの参照先を差し替えた
- **異常系の実装方針（指示書4.1の選択肢②を採用）**:
  - コンボボックスからの除外（①）ではなく、**選択して実行した時点で失敗させる**方式にした。除外方式だとファイルが一覧から黙って消え、ユーザーが原因を特定できなくなるため
  - `output_mode` が `None`（メタデータ行なし／値が3種類以外／ファイルが読めない）の場合、`INVALID_PROMPT_FILE: <filename> reason=missing_or_invalid_output_mode_header` を `log.log` と `error.log` に記録し、**その実行の全画像を LLM 呼び出し前にスキップ**する（7.2の `empty_tags` と同じ扱い）
  - 各画像には `SKIPPED: <label> reason=invalid_prompt_file` を記録し、`caption_text` には空文字を入れて枚数・順序を維持（9章）
  - ファイル読み込み時の `OSError` も握りつぶして `None` を返すため **ComfyUI 自体は止まらない**
  - サマリ行では不正時に `mode=INVALID` と表示する
- **検証結果**:
  | 入力 | 判定 |
  |---|---|
  | 同梱3ファイル | `both` / `tags_only` / `caption_only`。本文に `output_mode` 行が残っていないことを確認 |
  | メタデータ行なし | `None`（失敗扱い） |
  | `<!-- output_mode: whatever -->` | `None`（失敗扱い） |
  | 空ファイル | `None`（失敗扱い） |
  | 2行目にメタデータ行 | `None`（1行目のみ判定） |
  | `   <!--   output_mode :  both   -->   ` | `both`（空白の揺れを許容） |
  | 存在しないファイル | `None`（例外を出さず失敗扱い） |
  - **実機で3モードすべて実行**し、`mode=both` / `mode=tags_only` / `mode=caption_only` が自動判定されて各形式の文字列が出力されることを確認
  - **`prompt.log` に `output_mode` の文字列が0件**（メタデータ行がLLMに送られていない）ことを確認
  - メタデータ行なしのファイルを2枚バッチで選択 → `INVALID_PROMPT_FILE` を記録して2枚ともスキップ、出力は空文字2件で枚数維持
  - `INPUT_TYPES` / `IS_CHANGED` / `generate()` の引数一致を `inspect` で再検証
- **回帰確認**:
  - 13.6のリトライ分岐（`parse_length` 倍増→クランプ、`timeout` への切替、`connection` 据え置き）が従来どおり動作することを再テストで確認
  - 6章の `---` 区切りパース処理には手を入れていない（`parse_response()` の引数の渡し元が変わっただけ）
- **備考**:
  - 既存のワークフローには `output_mode` ウィジェットが残っているため、**ノードを配置し直すか、ワークフローを開き直して不要になったウィジェットを取り除く必要**がある可能性がある
  - ユーザーが独自に追加した `.txt` がある場合、1行目にメタデータ行を追加しないと `INVALID_PROMPT_FILE` として失敗する

---

## タスク16: タイムアウト時のキャンセルが効かない問題の原因特定と修正（ストリーミング化）

- **完了日**: 2026-08-23
- **動作確認**: ✅済み（実機での切り分け測定＋ノードのコード経路での再測定＋全モード・リトライ分岐の回帰確認）
- **新規ファイル**: なし
- **修正ファイル**:
  - `llm_caption_node.py` : リクエストをストリーミング化、SSE集約、`timeout_sec` を総経過時間として実装
  - `LLM_Caption_Node_指示書.md` : 13.5.4の誤った結論を訂正、13.5.5を新設、12章チェックリストに2項目追加
- **報告された事象**:
  - タイムアウト後もサーバー側の生成が走り続け、リトライがその後ろで待たされて遅くなる
- **原因（実機で特定）**:
  - **リクエストが非ストリーミングだったことが原因**
  - v11.7.0 の PR #3133 は `post_stream()`（**クライアントへ書き込みながら接続をポーリングする経路**）の修正であり、**prefill中の切断は非ストリーミングでも効く**
  - しかし**生成フェーズ**では、非ストリーミングだと生成完了までクライアントへ1バイトも書かないため切断を検知する機会がなく、打ち切ったはずの生成が最後まで走り続ける
  - Thinkモードの暴走でタイムアウトするのはまさに生成フェーズであり、**対策が必要な場面でだけ効かない**状態だった
  - 切り分け測定（画像付きリクエストを切断し、直後に同じリクエストを投げて所要時間を測定。基準値1.3〜2.9秒）:
    | 条件 | 切断後の基準リクエスト | 判定 |
    |---|---|---|
    | 2秒で切断（prefill中・非ストリーミング） | 1.40 / 3.15 秒 | 解放される |
    | **10秒で切断（生成中・非ストリーミング）** | **96.97 / 55.99 / 25.38 / 17.47 秒** | **4/4 で占有継続** |
    | 10秒で切断（生成中・`stream: true`） | 5.15 / 5.66 / 4.15 / 4.41 秒 | 4/4 で解放 |
  - なお**クライアント側のクローズ処理自体は正しかった**（ソケットリークなし、`urllib` の `do_open` が例外時に `h.close()` する経路も確認済み）。問題はサーバー側が切断を検知できない点にあった
- **タスク13（13.5.4）の結論の訂正**:
  - 「3回中2回は約1〜1.5秒で復帰したので中断されていると判断できる」と記録していたが、**あれはテキストのみの短いプロンプトで、切断時点がまだprefill段階だった可能性が高い**。画像付き・生成フェーズで測り直すと4/4で解放されなかった。指示書13.5.4に取り消し線付きで訂正済み
- **変更内容**:
  - `build_chat_payload()` に **`"stream": True`** と **`"stream_options": {"include_usage": True}`** を追加
  - `read_sse_completion(conn, response, deadline)` を追加。SSE を読み、**非ストリーミング応答と同じ構造の dict に集約**して返す（`choices[0].finish_reason` / `message.content` / `message.reasoning_content` / `usage`）。これにより **6.3の分類・13.6のクランプ・7.3.1のログ処理は変更不要**
  - **`timeout_sec` を「総経過時間の上限」として実装**。ストリーミングではソケットの timeout は「チャンク間隔」にしか効かない（実測：`timeout=5` を渡しても100秒かかっても打ち切られなかった）ため、期限を自前で管理し読み取りごとに残り時間をソケットへ設定する
  - HTTPクライアントを `urllib` から **`http.client` 直接利用**へ変更。13.5.1が要求する明示的クローズを `finally: conn.close()` で保証し、読み取りごとの残り時間設定も可能にした
  - HTTPエラー時は `urllib.error.HTTPError` を組み立てて送出し、`classify_error()` が従来どおり `http_{code}` を返せるようにした
  - 壊れたSSE行は読み飛ばす（全体を失敗させない）
- **検証結果**:
  - **ノードのコード経路で再測定：10秒で打ち切り → 直後の基準リクエストが 1.91 / 1.83 / 1.59 / 1.57 秒（4/4 で解放）**。修正前は 17〜97秒で 4/4 占有継続
  - 打ち切り時間が毎回きっかり `10.00秒` になり、総経過時間で制御できていることを確認
  - SSEから `finish_reason`（`stop` / `length`）と `usage`（`completion_tokens` / `prompt_tokens`）が取得でき、`reasoning_content` も `delta` 経由で連結できることを確認
  - 回帰確認: 3つの `output_mode`、`parse_length` の自動増量（8→16→32、および 8192→16384 で2回目に成功）、`timeout` の3回リトライ（`timeout_sec=5` で総計15.15秒＝5秒×3）、`CONNECTION_ABORTED` → `CANCEL_SKIPPED` → `RETRY` の順序、tok/s の算出がいずれも従来どおり動作
- **備考**:
  - `CONNECTION_ABORTED` の `note=prefill_cancel_supported_v11.7+` は指示書13.5.2が定めた固定文字列のためそのままにしているが、**実際には prefill だけでなく生成フェーズでも有効になった**
  - `LEMONADE_CANCEL_PATH` は引き続き空（キャンセルAPIは v11.7.0 でも未提供）。実際のキャンセル手段はTCP切断のみ

---

## タスク17: 自然文への literal `@trigger_word` 混入の修正／13.6分岐の調査（不具合報告2件）

- **完了日**: 2026-08-23
- **動作確認**: ✅済み（単体10ケース＋実機6ケース＋リトライパス再現＋13.6回帰5シナリオ＋全モード実機回帰）
- **新規ファイル**: なし
- **修正ファイル**:
  - `system_prompts/caption_training_both.txt` / `caption_text_only.txt` : trigger word の指示文を修正
  - `llm_caption_node.py` : `@trigger_word` 除去の後処理を追加、`RETRY` 行に `applied=` を追加
  - `LLM_Caption_Node_指示書.md` : 6.1.1新設、10章サンプル更新、13.3に`applied=`追記、12章に1項目追加

### 不具合1: 自然文に literal な `@` + trigger_word が混入する → 修正済み

- **原因**: 旧プロンプトの例示 `e.g. "@charactername stands in..."` を字義通り解釈したモデルが `@she` を出力していた
- **対処1（プロンプト側）**: `caption_training_both.txt` と `caption_text_only.txt` の該当行を「trigger word の文字列を EXACTLY そのまま使い、`@` などの記号を付けるな」に書き換え、例示も `@` なしに変更（`caption_tags_only.txt` は自然文を生成しないため対象外）
- **対処2（ノード側の保険）**: `strip_literal_at_trigger_word(text, trigger_word)` を追加
  - 6.1 の結合で自然文を最終文字列へ組み込む**直前**に適用（タグ列側には影響させない）
  - 誤爆防止のため `@` の直後が trigger_word で**その後ろに英数字・アンダースコアが続かない場合のみ**置換（`@sheep` / `@she_x` は対象外）
  - **大文字小文字を無視して照合し、置換時はモデルの表記を保つ**（`@She` → `She`）。文頭で大文字化されるケースに対応するための判断
  - `caption_only` も自然文を返すため同じ後処理を適用（`tags_only` は対象外）
  - 置換時は `log.log` に `NOTE: stripped_literal_at_trigger_word image=<name>` を記録
  - `parse_response()` / `combine_both_output()` の戻り値を `(caption_text, 置換したか)` に変更してログまで伝搬
- **検証**:
  - 単体10ケース: `@she`/`@She`/複数箇所/`@suzune` は置換、`@sheep`・`@she_x`・`@about`(tw=`a`) は非置換、trigger_word空は無処理、`trigger_word="@melte"` のときタグ列 `@melte` は保持
  - **実機**: `trigger_word="she"` で `caption_training_both.txt` / `caption_text_only.txt` × temperature 0.3/0.5/0.7 の**6/6すべてで `@she` の混入なし**
  - **リトライパス**: 1・2回目を形式崩れで失敗させ temperature が 0.3→0.5→0.7 と上がる状況を再現し、3回目の `@She ... @she` 入り応答が `She ... she` に置換され `NOTE:` が記録されることを確認
- **副作用（要注意・未対処）**:
  - プロンプトを「そのまま使え」にした結果、**`trigger_word` に `@` を含めている場合（例 `@melte`）、モデルが自然文から `@` を落とすことがある**（実測6回中4回）
  - `both` モードはタグ列先頭にプログラムが `@melte` を挿入するため影響は小さいが、**`caption_only` モードでは自然文がキャプション全体になるため、トリガートークンが `melte` になってしまう**
  - 指示書6.1.1に注意書きとして記載済み

### 不具合2: 13.6の倍増が「2回目の試行」でだけ効かない → **コードの不具合ではなかった**

- **調査結果**: `next_attempt_params()` は `attempt <= 1` の判定の直後に**必ず `previous_reason` で分岐**しており、試行回数による特別扱いは存在しない。2回目だけ13.2が優先される経路は無い
- **報告されたログを再現**したところ、`8197 → 4098 → 8196` と完全に一致したが、これは**仕様どおりの正しい動作**だった:
  - 1回目は 8197 を使い **timeout** で失敗 → 13.2 の縮小で2回目 4098（正しい）
  - 2回目は 4098 を使い **parse_length** で失敗 → 13.6 の倍増で3回目 8196（正しい）
- **誤読の原因**: `RETRY` 行の `reason=` は「**その試行が失敗した理由**」であって「**そのパラメータを選んだ理由**」ではない。同じ行に並んでいるため、2行目の `max_tokens=4098` と `reason=parse_length` が結び付けて読まれてしまった
- **対処（ログの改善）**: `RETRY` 行に `applied=` を追加し、パラメータを決めた分岐を明示するようにした
  ```
  RETRY: suzune_001.png attempt=1/3 max_tokens=8197 temperature=0.3 applied=initial reason=timeout
  RETRY: suzune_001.png attempt=2/3 max_tokens=4098 temperature=0.5 applied=13.2_shrink(prev=timeout) reason=parse_length
  RETRY: suzune_001.png attempt=3/3 max_tokens=8196 temperature=0.5 applied=13.6_grow(prev=parse_length) reason=parse_length
  ```
  値は `initial` / `13.2_shrink(prev=...)` / `13.6_grow(prev=...)` / `keep(prev=...)`
- **13.6.3のチェック項目も再確認**: `parse_length`×3で `8192→16384→31601(クランプ)`、`parse_length→timeout` で3回目が `2048/0.7` に切替、`parse_format`×3で `8192→4096→2048`、`connection`×3で据え置き

### 回帰確認

- 6.3（`finish_reason` 分類）、13.1〜13.5（キャンセル・接続切断・ストリーミング）のロジックは**未変更**
- 実機で3モード（`both` / `tags_only` / `caption_only`）と `INVALID_PROMPT_FILE` の異常系が従来どおり動作することを確認

### 備考

- 指示書10章のサンプル全文は**旧文面のままだったため、実ファイルに合わせて更新した**（「更新済み」とのご指示だったが差分が入っていなかった）

---

## タスク18: parse_format 失敗時の訂正指示（corrective instruction）の追加

- **完了日**: 2026-08-23
- **動作確認**: ✅済み（分岐5シナリオ＋caption_only の parse_format ケース＋ログ確認＋実機で全モード回帰）
- **新規ファイル**: なし
- **修正ファイル**:
  - `llm_caption_node.py` : 訂正指示の追記、試行ごとの `PROMPT user` 記録、`RETRY` 行の note 複数対応
  - `LLM_Caption_Node_指示書.md` : 5.2.1新設、13.3に note を追記、12章に2項目追加
- **背景**:
  - `---`区切りが無いフォーマット崩れ（`parse_format`）で、13.2の temperature 上昇・`max_tokens` 縮小だけでは同じ失敗が3回とも再現し、リトライが実質機能しない事例が実運用ログで確認された
  - temperature の調整はランダムな揺さぶりに過ぎず、モデルに具体的な訂正内容を伝えていなかった
- **変更内容**:
  - 定数 `FORMAT_CORRECTION_NOTE` を追加（指定の英文をそのまま使用）
  - `build_user_text(tags, trigger_word, format_correction=False)` / `build_messages(..., format_correction=False)` に引数を追加。**訂正指示は末尾に改行して追記するのみ**で、トリガーワード行・タグ行・画像パートの構成順序は変更していない
  - `generate()` のリトライループ内で `format_correction = (previous_reason == REASON_PARSE_FORMAT)` を判定。`params_source` と同じく **`previous_reason` を上書きする前**に決める
  - **`messages` の構築をループ前からループ内へ移動**（試行ごとに user message が変わるため）
  - 2回連続で `parse_format` が続いた場合も毎回同じ固定文言を追記する
  - 13.2 のパラメータ調整はそのまま維持して併用。13.6（`parse_length` の倍増）には影響なし
- **ログ**:
  - `RETRY` 行を複数 note に対応させ、訂正指示を追加した試行に `note=added_format_correction` を付記
  - **`prompt.log` の `PROMPT user` を「画像ごと1回」から「試行ごと1回」に変更**（見出しに `attempt N/3` を追加）。従来のままでは訂正指示込みの user message が記録されず、指示の「その試行の user message 全文がそのまま記録されること」を満たせないため
- **実装時の判断（指示からの逸脱・要確認）**:
  - **訂正文は `---` 区切りと PART1/PART2 についての内容なので、`output_mode == "both"` のときのみ追記する**ようにした
  - `tags_only` / `caption_only` は `---` を要求しないパース経路であり（6章）、これらのモードで「`---` で区切れ」と指示すると、そのまま出力された `---` 入りの応答が検証されずにキャプションとして返ってしまうため
  - `caption_only` でも `parse_format`（本文なし・応答が短すぎる）は発生しうるが、その場合も訂正指示は追加されないことを確認済み
  - モード無条件で追記すべき場合は、`format_correction` の条件から `output_mode == "both"` を外すだけで切り替え可能
- **検証結果**:
  | シナリオ | 訂正指示の追加 |
  |---|---|
  | `parse_format` ×3 | 試行1なし → **試行2・3にあり** |
  | `timeout` → `parse_format` → … | 試行1・2なし → **試行3にあり**（timeout の次には付かない） |
  | `parse_length` ×3 | 3回とも追加なし |
  | `connection` ×3 | 3回とも追加なし |
  | `caption_only` で `parse_format` ×3 | 3回とも追加なし（上記の判断による） |
  - `log.log` 実例:
    ```
    RETRY: suzune028.png attempt=2/3 max_tokens=4096 temperature=0.5 applied=13.2_shrink(prev=parse_format) reason=parse_format note=added_format_correction detail=...
    ```
  - `prompt.log` に試行ごとの `PROMPT user ... (attempt 2/3)` が記録され、末尾に訂正指示の全文が入っていることを確認
  - 実機で3モード（`both` / `tags_only` / `caption_only`）と `INVALID_PROMPT_FILE` の異常系が従来どおり動作することを確認
- **備考**:
  - `prompt.log` はリトライ時に user message が試行回数分記録されるようになったため、リトライが多発するとログがやや増える（`log_prompt` は既定OFFのため通常運用への影響はなし）

---
