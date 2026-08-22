import base64
import datetime
import io
import json
import os
import re
import urllib.error
import urllib.request

import numpy as np
from PIL import Image

DEFAULT_LEMONADE_HOST = "192.168.85.57"
DEFAULT_LEMONADE_PORT = 13305
MODELS_FETCH_TIMEOUT_SEC = 3
FALLBACK_MODEL_LABEL = "(Lemonade Server unavailable - check host/port)"

SYSTEM_PROMPTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "system_prompts")
FALLBACK_SYSTEM_PROMPT_LABEL = "(no .txt files found in system_prompts/)"

# 5.1 画像前処理：長辺がこの値を超える場合のみリサイズする（以下ならそのまま送信）
MAX_IMAGE_LONG_EDGE = 1024
IMAGE_FORMAT = "PNG"
IMAGE_MIME_TYPE = "image/png"

# 5.3 top_p は内部固定値
FIXED_TOP_P = 1.0

# 6章 出力パース
# 実機の Lemonade Server は thinking を message.reasoning_content に分離して返し、
# content にはインラインの <think> を含めない（2026-08-23 実機再確認）。
# ただし <think> をインラインで返すサーバー／モデルもあるため、保険として除去処理は残す。
THINK_CLOSE_TAG = "</think>"
# PART1 / PART2 の区切り行（"---" のみの行。ハイフン3個以上を許容）
PART_SEPARATOR_PATTERN = re.compile(r"^[ \t]*-{3,}[ \t]*$", re.MULTILINE)
# 6.2 これより短い応答は「応答不正」とみなす（タグ1個の最短ケースを潰さない範囲で設定）
MIN_VALID_RESPONSE_CHARS = 4
# 6.1 結合フォーマットの区切り文字
TAG_DELIMITER = ", "
TAGS_CAPTION_DELIMITER = ". "


# 7章 エラーハンドリング・リトライ・ログ
# 7.1 接続失敗／タイムアウト／パース失敗を同一カウンタで最大3回試行する
MAX_ATTEMPTS = 3
ERROR_LOG_FILENAME = "error.log"
FULL_LOG_FILENAME = "log.log"
# 7.3 ログの出力先。指示書は「入力画像と同じフォルダ」だが、ComfyUI の IMAGE 型には
# パス情報が含まれないため、ノードディレクトリ直下の logs/ に固定する（運用上の決定）。
LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
# 7.3 ログのタイムスタンプ書式
LOG_TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S"


class CaptionParseError(Exception):
    """6.2 応答不正。7.1 のリトライ対象。"""


def build_lemonade_base_url(host, port):
    host = (host or DEFAULT_LEMONADE_HOST).strip()
    return f"http://{host}:{port}/v1"


def fetch_lemonade_models(host=DEFAULT_LEMONADE_HOST, port=DEFAULT_LEMONADE_PORT, api_key=""):
    # ComfyUI の INPUT_TYPES 評価タイミング（起動時／ブラウザF5）でのみ呼ばれる。
    # ここで例外を外に投げると ComfyUI 自体の起動が止まるため、失敗時は必ず空リストを返す。
    url = f"{build_lemonade_base_url(host, port)}/models"
    headers = {"Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=MODELS_FETCH_TIMEOUT_SEC) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as e:
        print(f"[LLMCaptionGenerator] Lemonade Server のモデル一覧取得に失敗しました ({url}): {e}")
        return []

    entries = payload.get("data", []) if isinstance(payload, dict) else []
    model_ids = [entry["id"] for entry in entries if isinstance(entry, dict) and entry.get("id")]
    return model_ids


def list_system_prompt_files():
    # system_prompts/ フォルダが存在しない、または .txt が1つもない場合は空リストを返す。
    # ここも INPUT_TYPES から呼ばれるため、例外で ComfyUI 起動を止めないこと。
    try:
        filenames = [f for f in os.listdir(SYSTEM_PROMPTS_DIR) if f.lower().endswith(".txt")]
    except OSError as e:
        print(f"[LLMCaptionGenerator] system_prompts フォルダの読み取りに失敗しました ({SYSTEM_PROMPTS_DIR}): {e}")
        return []
    return sorted(filenames)


def read_system_prompt_file(filename):
    path = os.path.join(SYSTEM_PROMPTS_DIR, filename)
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def iter_images(image):
    # ComfyUI の IMAGE は通常 [B, H, W, C] のバッチテンソルで渡ってくるが、
    # 上流ノードが OUTPUT_IS_LIST の場合はテンソルのリストで渡ってくることもある。
    # どちらでも「1枚 = [H, W, C]」の単位に平坦化して yield する。
    if isinstance(image, (list, tuple)):
        for item in image:
            yield from iter_images(item)
        return

    if getattr(image, "ndim", None) == 4:
        for i in range(image.shape[0]):
            yield image[i]
    else:
        yield image


def tensor_to_pil(image_tensor):
    # ComfyUI の IMAGE は float32 0.0〜1.0、形状 [H, W, C]
    array = image_tensor.cpu().numpy() if hasattr(image_tensor, "cpu") else np.asarray(image_tensor)
    array = np.clip(array * 255.0, 0, 255).astype(np.uint8)

    if array.ndim == 2:
        return Image.fromarray(array, mode="L").convert("RGB")
    if array.shape[2] == 1:
        return Image.fromarray(array[:, :, 0], mode="L").convert("RGB")
    # RGBA で来た場合はアルファを捨てて RGB に揃える
    return Image.fromarray(array[:, :, :3], mode="RGB")


def resize_if_needed(pil_image, max_long_edge=MAX_IMAGE_LONG_EDGE):
    # 5.1 長辺が max_long_edge を超える場合のみアスペクト比維持でリサイズ
    width, height = pil_image.size
    long_edge = max(width, height)
    if long_edge <= max_long_edge:
        return pil_image

    scale = max_long_edge / long_edge
    new_size = (max(1, round(width * scale)), max(1, round(height * scale)))
    return pil_image.resize(new_size, Image.LANCZOS)


def encode_image_base64(pil_image):
    buffer = io.BytesIO()
    pil_image.save(buffer, format=IMAGE_FORMAT)
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def build_user_text(tags, trigger_word):
    # 5.2 トリガーワードの有無で2パターン
    tags_block = f"Candidate tags from WD14 (verify against the image, correct as needed):\n{tags}"
    trigger_word = (trigger_word or "").strip()
    if trigger_word:
        return f"Trigger word: {trigger_word}\n{tags_block}"
    return tags_block


def build_messages(system_prompt_text, tags, trigger_word, image_base64):
    # 5.2 テキスト部と画像部は同一 user message 内のパートとして含める
    return [
        {"role": "system", "content": system_prompt_text},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": build_user_text(tags, trigger_word)},
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{IMAGE_MIME_TYPE};base64,{image_base64}"},
                },
            ],
        },
    ]


def build_chat_payload(model, messages, enable_thinking, temperature, max_tokens):
    # 5.3 enable_thinking は chat template 側のフラグとして渡す（llama.cpp / vLLM 系の
    # OpenAI互換サーバー共通の指定方法）。サーバー側が未対応の場合は無視されるだけで害はない。
    return {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "top_p": FIXED_TOP_P,
        "chat_template_kwargs": {"enable_thinking": bool(enable_thinking)},
    }


def request_chat_completion(host, port, api_key, payload, timeout_sec):
    # 7章のリトライ・エラーハンドリングは未実装。ここでは例外はそのまま呼び出し元へ送出する。
    url = f"{build_lemonade_base_url(host, port)}/chat/completions"
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    with urllib.request.urlopen(request, timeout=timeout_sec) as response:
        return json.loads(response.read().decode("utf-8"))


def extract_response_text(response_payload):
    # HTTP応答から生のテキストを取り出すだけ（パースは parse_response 側で行う）
    choice = response_payload["choices"][0]
    message = choice["message"]
    content = (message.get("content") or "").strip()
    if content:
        return content

    # 実機のサーバーは thinking を reasoning_content に分離するため、
    # content が空 = 本文が1文字も生成されていない状態。ここで理由を確定させておかないと
    # 6章のパースで「応答が短すぎます (0文字)」という原因不明のエラーになる。
    finish_reason = choice.get("finish_reason")
    thinking_chars = len((message.get("reasoning_content") or "").strip())
    if finish_reason == "length":
        raise CaptionParseError(
            f"max_tokens に達したため本文が生成されませんでした"
            f"（thinking で {thinking_chars} 文字を消費）。"
            f"max_tokens を増やすか enable_thinking を OFF にしてください"
        )
    raise CaptionParseError(
        f"モデルが本文を返しませんでした (finish_reason={finish_reason}, "
        f"thinking {thinking_chars} 文字)"
    )


def strip_thinking(text):
    # </think> 以降のみを抽出する。<think> が無い場合は全体を対象とする。
    # 複数回出現した場合は最後の </think> 以降を採用する。
    # 実機のサーバーは thinking を分離して返すためここは通常ノーオペだが、
    # インラインで <think> を返す構成向けの保険として残している。
    text = text or ""
    _, separator, after = text.rpartition(THINK_CLOSE_TAG)
    return after if separator else text


def split_both_parts(text):
    # 6章 both モード：最初の "---" 行で PART1（タグ）/ PART2（自然文）に分割
    parts = PART_SEPARATOR_PATTERN.split(text, maxsplit=1)
    if len(parts) < 2:
        raise CaptionParseError("'---' 区切りが見つかりません")

    tags_part, caption_part = parts[0].strip(), parts[1].strip()
    if not tags_part:
        raise CaptionParseError("'---' より前（PART1: タグ）が空です")
    if not caption_part:
        raise CaptionParseError("'---' より後（PART2: 自然文）が空です")
    return tags_part, caption_part


def normalize_tag_list(tags_part, trigger_word):
    # 6.1 タグ区切りを ", " に正規化する。末尾のピリオドは自然文との区切りと重複するため落とす。
    tags = [tag.strip() for tag in tags_part.rstrip().rstrip(".").split(",")]
    tags = [tag for tag in tags if tag]

    # トリガーワードはプログラム側で先頭に挿入するため、
    # LLMが出力に含めてしまっていた場合は重複を避けて除去する
    trigger_word = (trigger_word or "").strip()
    if trigger_word:
        tags = [tag for tag in tags if tag.lower() != trigger_word.lower()]
    return tags


def combine_both_output(tags_part, caption_part, trigger_word):
    # 6.1 学習用結合フォーマット: {trigger_word}, {corrected_tags}. {natural_language_caption}
    tags = normalize_tag_list(tags_part, trigger_word)

    trigger_word = (trigger_word or "").strip()
    if trigger_word:
        # トリガーワードは常にタグ列の先頭へ確実に挿入（LLM出力に依存しない）
        tags.insert(0, trigger_word)

    tag_line = TAG_DELIMITER.join(tags)
    if not tag_line:
        raise CaptionParseError("PART1 から有効なタグを抽出できませんでした")
    return f"{tag_line}{TAGS_CAPTION_DELIMITER}{caption_part}"


def parse_response(raw_response, output_mode, trigger_word):
    # 6章 パース本体。失敗時は CaptionParseError を送出する（7章のリトライ処理は未実装のため、
    # 現状は例外がそのまま呼び出し元へ伝播する）。
    body = strip_thinking(raw_response).strip()
    if len(body) < MIN_VALID_RESPONSE_CHARS:
        raise CaptionParseError(f"応答が短すぎます ({len(body)}文字): {body!r}")

    if output_mode == "both":
        tags_part, caption_part = split_both_parts(body)
        return combine_both_output(tags_part, caption_part, trigger_word)

    # tags_only / caption_only は </think> 除去後の応答全体をそのまま使う
    # （プロンプト側で "---" 区切りなしの単純テキストを返すよう指示している）
    return body


def split_image_name_entries(image_names):
    # 改行区切り（カンマ区切りも許容）のファイル名／パス一覧を配列にする
    return [entry.strip() for entry in re.split(r"[\r\n,]+", image_names or "") if entry.strip()]


def ensure_log_dir():
    # 7.3 ログ出力先（LOG_DIR）を用意する。作成に失敗してもログ書き込み側で握りつぶすため、
    # ここでは警告を出すだけで本処理は止めない。
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
    except OSError as e:
        print(f"[LLMCaptionGenerator] ログ出力先の作成に失敗しました ({LOG_DIR}): {e}")
    return LOG_DIR


def resolve_image_labels(image_name_entries, count):
    # ログに出す画像名。namelist が渡っていればそのファイル名、無ければ連番で補う。
    labels = []
    for i in range(count):
        if i < len(image_name_entries):
            labels.append(os.path.basename(image_name_entries[i]) or image_name_entries[i])
        else:
            labels.append(f"image_{i + 1:03d}")
    return labels


def append_log_line(log_dir, filename, line):
    # 7.3 追記型。書き込みのたびに open/close する（長時間バッチの途中でも内容が確定し、
    # ComfyUIが落ちてもログが失われない）。ログ書き込みの失敗で本処理を止めないこと。
    path = os.path.join(log_dir, filename)
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError as e:
        print(f"[LLMCaptionGenerator] ログ書き込みに失敗しました ({path}): {e}")


def write_log(log_dir, message, is_error=False):
    # log.log は全処理ログ、error.log は失敗のみ（error.log の内容は log.log にも含まれる）
    line = f"[{datetime.datetime.now().strftime(LOG_TIMESTAMP_FORMAT)}] {message}"
    append_log_line(log_dir, FULL_LOG_FILENAME, line)
    if is_error:
        append_log_line(log_dir, ERROR_LOG_FILENAME, line)


def classify_error(error):
    # 7.3/7.4 のログ・コンソール表示用の簡易理由
    if isinstance(error, CaptionParseError):
        return "parse_error"
    if isinstance(error, urllib.error.HTTPError):
        return f"http_{error.code}"
    # 読み取りタイムアウトは TimeoutError、接続タイムアウトは URLError(reason=TimeoutError) で来る
    if isinstance(error, TimeoutError) or isinstance(getattr(error, "reason", None), TimeoutError):
        return "timeout"
    if isinstance(error, urllib.error.URLError):
        return "connection_failed"
    if isinstance(error, (json.JSONDecodeError, KeyError, IndexError)):
        return "invalid_response"
    return type(error).__name__


# 7.1 リトライ対象の例外。
# urllib.error.URLError / HTTPError / TimeoutError はいずれも OSError のサブクラスなので
# 接続失敗・タイムアウトは OSError で捕捉できる。JSON/キー欠落は応答異常、
# CaptionParseError は 6.2 の応答不正。
RETRYABLE_EXCEPTIONS = (OSError, json.JSONDecodeError, KeyError, IndexError, CaptionParseError)


class LLMCaptionGenerator:
    # 1. 入力ウィジェット・入力ソケットの定義
    @classmethod
    def INPUT_TYPES(cls):
        model_list = fetch_lemonade_models(DEFAULT_LEMONADE_HOST, DEFAULT_LEMONADE_PORT)
        if not model_list:
            model_list = [FALLBACK_MODEL_LABEL]

        system_prompt_files = list_system_prompt_files()
        if not system_prompt_files:
            system_prompt_files = [FALLBACK_SYSTEM_PROMPT_LABEL]

        return {
            "required": {
                "image": ("IMAGE",),
                "tags": ("STRING", {"multiline": True, "default": ""}),
                "trigger_word": ("STRING", {"default": ""}),
                "output_mode": (["tags_only", "caption_only", "both"],),
                "system_prompt_file": (system_prompt_files,),
                "lemonade_host": ("STRING", {"default": DEFAULT_LEMONADE_HOST}),
                "lemonade_port": ("INT", {"default": DEFAULT_LEMONADE_PORT, "min": 1, "max": 65535}),
                "lemonade_api_key": ("STRING", {"default": ""}),
                "model": (model_list,),
                "enable_thinking": ("BOOLEAN", {"default": True}),
                "temperature": ("FLOAT", {"default": 0.3, "min": 0.0, "max": 2.0, "step": 0.05}),
                # enable_thinking=True では thinking だけで4000トークン超を消費する実測値があるため、
                # 指示書の目安(2048)より大きめの既定値にしている（不足すると本体が出力されず応答不正になる）
                "max_tokens": ("INT", {"default": 8192, "min": 1, "max": 32768}),
                "timeout_sec": ("INT", {"default": 120, "min": 1, "max": 3600}),
            },
            # ログに出す画像のファイル名（任意）。ComfyUI の IMAGE 型にはパス情報が
            # 含まれないため、LoRA Caption Load の namelist 相当を別途受け取る。
            # 未指定の場合は image_001 形式の連番をログのラベルに使う。
            "optional": {
                "image_names": ("STRING", {"default": "", "multiline": True}),
            },
        }

    # 2. 出力ソケットの型（複数なら型のタプル）
    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("caption_text",)

    # caption_text は image と同じ枚数・同じ順序のリストとして返す（指示書2.2 / 9章）
    OUTPUT_IS_LIST = (True,)

    # 3. 実際の処理を行うメソッド名（ComfyUIがこの名前で呼び出す）
    FUNCTION = "generate"

    # 4. ノード一覧で表示されるカテゴリ（サイドバーの分類）
    CATEGORY = "Image-Captioning-in"

    def generate(self, image, tags, trigger_word, output_mode, system_prompt_file, lemonade_host,
                 lemonade_port, lemonade_api_key, model, enable_thinking, temperature, max_tokens,
                 timeout_sec, image_names=""):
        if system_prompt_file == FALLBACK_SYSTEM_PROMPT_LABEL:
            system_prompt_text = ""
        else:
            system_prompt_text = read_system_prompt_file(system_prompt_file)

        images = list(iter_images(image))
        name_entries = split_image_name_entries(image_names)
        log_dir = ensure_log_dir()
        labels = resolve_image_labels(name_entries, len(images))

        # 7.4.1 デバッグ用の設定値サマリ。バッチ内で値は不変のため実行開始時に1回だけ出力する
        # （7.4 のコンソール出力簡略化を行う際もこの行は残すこと）
        summary = (f"開始: {len(images)}枚, model={model}, mode={output_mode}, "
                   f"prompt={system_prompt_file}, thinking={enable_thinking}, temp={temperature}, "
                   f"top_p={FIXED_TOP_P}, max_tokens={max_tokens}, timeout={timeout_sec}s")
        print(f"[LLMCaptionGenerator] {summary}")
        print(f"[LLMCaptionGenerator] ログ出力先: {log_dir}")
        write_log(log_dir, f"RUN {summary}")

        # 7.2 事前チェック：tags が空文字ならLLMを呼ばずに即スキップ（リトライ対象外）
        tags_is_empty = not (tags or "").strip()

        results = []
        success_count = 0
        for index, image_tensor in enumerate(images, start=1):
            label = labels[index - 1]
            write_log(log_dir, f"START: {label}")

            if tags_is_empty:
                print(f"[LLMCaptionGenerator] SKIPPED: {label} (empty_tags)")
                write_log(log_dir, f"SKIPPED: {label} reason=empty_tags", is_error=True)
                # 9章：スキップしても枚数・順序を崩さないよう空文字を入れる
                results.append("")
                continue

            pil_image = resize_if_needed(tensor_to_pil(image_tensor))
            image_base64 = encode_image_base64(pil_image)
            messages = build_messages(system_prompt_text, tags, trigger_word, image_base64)
            payload = build_chat_payload(model, messages, enable_thinking, temperature, max_tokens)

            print(f"[LLMCaptionGenerator] {index}/{len(images)} 送信中 "
                  f"(size={pil_image.size[0]}x{pil_image.size[1]})")

            # 7.1 接続失敗・タイムアウト・パース失敗を同一カウンタで最大 MAX_ATTEMPTS 回試行
            caption = ""
            for attempt in range(1, MAX_ATTEMPTS + 1):
                try:
                    response_payload = request_chat_completion(
                        lemonade_host, lemonade_port, lemonade_api_key, payload, timeout_sec
                    )
                    raw_response = extract_response_text(response_payload)
                    caption = parse_response(raw_response, output_mode, trigger_word)
                    write_log(log_dir, f"SUCCESS: {label} mode={output_mode} attempt={attempt}")
                    success_count += 1
                    break
                except RETRYABLE_EXCEPTIONS as e:
                    reason = classify_error(e)
                    write_log(log_dir,
                              f"RETRY {attempt}/{MAX_ATTEMPTS}: {label} reason={reason} detail={e}")
                    if attempt == MAX_ATTEMPTS:
                        # 7.4 コンソールはファイル名＋簡易理由のみ。詳細はログファイル参照
                        print(f"[LLMCaptionGenerator] SKIPPED: {label} ({reason})")
                        write_log(log_dir,
                                  f"SKIPPED: {label} reason={reason} "
                                  f"({MAX_ATTEMPTS} attempts exhausted)",
                                  is_error=True)
                        # 9章：失敗時も空文字で枚数を揃える
                        caption = ""

            results.append(caption)

        skipped_count = len(images) - success_count
        print(f"[LLMCaptionGenerator] 完了: 成功 {success_count}件 / スキップ {skipped_count}件"
              + (f"（詳細は {os.path.join(log_dir, ERROR_LOG_FILENAME)} を参照）"
                 if skipped_count else ""))
        write_log(log_dir, f"RUN END: success={success_count} skipped={skipped_count}")

        return (results,)
