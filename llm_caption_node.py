import base64
import datetime
import http.client
import io
import json
import os
import re
import time
import uuid
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

# 4.1 output_mode はウィジェットではなく、プロンプトファイル1行目のメタデータ行から判定する
#     例: <!-- output_mode: both -->
OUTPUT_MODE_HEADER_PATTERN = re.compile(r"^\s*<!--\s*output_mode\s*:\s*([A-Za-z_]+)\s*-->\s*$")
VALID_OUTPUT_MODES = ("tags_only", "caption_only", "both")
# 4.1 メタデータ行が無い／値が不正なファイルを選択したときのログ・スキップ理由
INVALID_PROMPT_FILE_REASON = "missing_or_invalid_output_mode_header"
REASON_INVALID_PROMPT_FILE = "invalid_prompt_file"

# 5.1 画像前処理：長辺がこの値を超える場合のみリサイズする（以下ならそのまま送信）
MAX_IMAGE_LONG_EDGE = 1024
IMAGE_FORMAT = "PNG"
IMAGE_MIME_TYPE = "image/png"

# 5.3 top_p は内部固定値
FIXED_TOP_P = 1.0

# 13.5 リクエストはストリーミングで送る。
# Lemonade Server は「クライアントへ書き込む際に接続をポーリングする」実装（v11.7.0 PR #3133）
# のため、非ストリーミングだと生成フェーズでの切断がサーバーへ伝わらず、打ち切ったはずの生成が
# 最後まで走り続ける（実機で 4/4 再現。stream=True では 4/4 即解放）。
CHAT_COMPLETIONS_PATH = "/v1/chat/completions"
SSE_DATA_PREFIX = "data:"
SSE_DONE_MARKER = "[DONE]"
# HTTPエラー時に読み取る本文の上限
MAX_ERROR_BODY_BYTES = 2048

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
# log_prompt が ON のときだけ書き出す、LLMへの送信内容と生応答の記録
PROMPT_LOG_FILENAME = "prompt.log"
# prompt.log の多行本文につけるインデント（行指向のログと混ざらないようにする）
PROMPT_LOG_INDENT = "    "
# 7.3 ログの出力先。指示書は「入力画像と同じフォルダ」だが、ComfyUI の IMAGE 型には
# パス情報が含まれないため、ノードディレクトリ直下の logs/ に固定する（運用上の決定）。
LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
# 7.3 ログのタイムスタンプ書式
LOG_TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S"

# 13章 Thinkモード暴走対策
# 13.1 タイムアウト時にサーバー側の生成を明示的に中断させるキャンセルAPIのパス。
# 【2026-08-23 実サーバー調査結果】Lemonade Server 11.5.0 にはキャンセル用エンドポイントが
# 存在しない（/openapi.json /docs は404。/api/v1 配下の halt / stop / cancel / abort /
# interrupt / terminate / kill / requests / generate-stop、および OpenAI Responses API 形式の
# /responses/{id}/cancel、DELETE /chat/completions/{id} をすべて確認し全て404）。
# 唯一 POST /api/v1/unload が200を返すが、これはモデル自体をアンロードするため
# 他の処理・他の利用者にも影響し、キャンセル用途には使えない。
# → 空文字の間はキャンセル呼び出しをスキップする。将来サーバーが対応したらここにパスを設定するだけでよい
#    （例: "/api/v1/cancel"）。リクエストのボディは {"request_id": ...} で送る。
LEMONADE_CANCEL_PATH = ""
CANCEL_TIMEOUT_SEC = 5

# 7.1 / 6.3 リトライ対象の失敗分類
REASON_CONNECTION = "connection"
REASON_TIMEOUT = "timeout"
REASON_PARSE_LENGTH = "parse_length"
REASON_PARSE_FORMAT = "parse_format"
# 13.2 の縮小方向の調整を適用する分類（それ以外はパラメータを据え置く）
SHRINK_REASONS = (REASON_TIMEOUT, REASON_PARSE_FORMAT)

# 13.2 リトライ時のパラメータ調整（インデックスは 試行回数-1）。ウィジェットには公開しない。
# 2回目は max_tokens 半分・temperature +0.2、3回目は 1/4・+0.4。下限/上限でクリップする。
RETRY_MAX_TOKENS_SCALE = (1.0, 0.5, 0.25)
RETRY_MAX_TOKENS_FLOOR = (0, 512, 256)
RETRY_TEMPERATURE_DELTA = (0.0, 0.2, 0.4)
RETRY_TEMPERATURE_CEILING = 1.0

# 13.6 parse_length（finish_reason=="length"）時は max_tokens を直前の2倍にして再試行する
RETRY_MAX_TOKENS_GROWTH = 2
# 13.6.1 クランプ後もこれを下回らせない
MIN_MAX_TOKENS = 256
# 13.6.1 プロンプト側トークン数の概算。usage.prompt_tokens が取れる場合はそちらを優先する
CHARS_PER_TOKEN_ESTIMATE = 4
IMAGE_PROMPT_TOKENS_ESTIMATE = 1024
# 13.6.1 max_context_window ぎりぎりを避けるための余裕
CONTEXT_SAFETY_MARGIN_TOKENS = 256
CLAMP_LOG_NOTE = "note=clamped_by_max_context_window"

# 3章のモデル一覧取得時に拾う max_context_window のキャッシュ（13.6.1のクランプに使う）
MODEL_CONTEXT_WINDOWS = {}


class CaptionParseError(Exception):
    """6.2 応答不正。7.1 のリトライ対象。

    category には 6.3 の分類（parse_length / parse_format）を持たせ、
    13.2（縮小）と 13.6（増量）のどちらへ分岐するかの判断に使う。
    """

    def __init__(self, message, category=REASON_PARSE_FORMAT):
        super().__init__(message)
        self.category = category


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
    model_ids = []
    for entry in entries:
        if not isinstance(entry, dict) or not entry.get("id"):
            continue
        model_ids.append(entry["id"])
        # 13.6.1 の上限クランプで使うためコンテキスト長も保持しておく
        window = entry.get("max_context_window")
        if isinstance(window, int) and window > 0:
            MODEL_CONTEXT_WINDOWS[entry["id"]] = window
    return model_ids


def get_model_context_window(host, port, api_key, model):
    # 13.6.1 クランプ用の max_context_window。3章のモデル一覧取得時のキャッシュを使い、
    # 未取得なら一度だけ取りに行く。取得できなければ None を返し、その場合クランプは行わない。
    if model in MODEL_CONTEXT_WINDOWS:
        return MODEL_CONTEXT_WINDOWS[model]

    fetch_lemonade_models(host, port, api_key)
    # 取得できなかった場合も None をキャッシュし、画像ごとに再取得しにいかないようにする
    MODEL_CONTEXT_WINDOWS.setdefault(model, None)
    return MODEL_CONTEXT_WINDOWS[model]


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


def parse_system_prompt_file(filename):
    """4.1 1行目のメタデータ行から output_mode を判定し、その行を除いた本文を返す。

    戻り値は (output_mode, system_message)。メタデータ行が無い・値が3種類以外・
    ファイルが読めない場合は output_mode を None にして返す（呼び出し側で失敗扱いにする）。
    ComfyUI 自体を止めないため、ここでは例外を送出しない。
    """
    try:
        text = read_system_prompt_file(filename)
    except OSError as e:
        print(f"[LLMCaptionGenerator] system prompt の読み込みに失敗しました ({filename}): {e}")
        return None, ""

    lines = text.splitlines()
    match = OUTPUT_MODE_HEADER_PATTERN.match(lines[0]) if lines else None
    if not match:
        return None, text

    output_mode = match.group(1).strip()
    if output_mode not in VALID_OUTPUT_MODES:
        return None, text

    # メタデータ行はLLMに見せない。除去後に先頭へ残る空行も落とす
    return output_mode, "\n".join(lines[1:]).lstrip("\n")


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
        # 13.5 切断をサーバーに伝えるためストリーミングで受け取る（上のコメント参照）。
        # include_usage を付けると最終チャンクに usage が入り、6.3 の分類・13.6 のクランプ・
        # tok/s の算出にそのまま使える（実機で取得できることを確認済み）。
        "stream": True,
        "stream_options": {"include_usage": True},
    }


def read_sse_completion(conn, response, deadline):
    """13.5 SSE を読み、非ストリーミング応答と同じ形の dict に集約して返す。

    deadline（`time.monotonic()` 基準の絶対時刻）を超えたら TimeoutError を送出する。
    ストリーミングではソケットの timeout は「チャンク間隔」にしか効かないため、
    総経過時間の管理は自前で行い、読み取りごとに残り時間をソケットへ設定する。
    """
    content_parts = []
    reasoning_parts = []
    finish_reason = None
    usage = None

    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            # 呼び出し元の finally で接続を閉じ、切断をサーバーへ伝える
            raise TimeoutError("timed out")
        if conn.sock is not None:
            conn.sock.settimeout(remaining)

        raw_line = response.readline()
        if not raw_line:
            break

        line = raw_line.decode("utf-8", "replace").strip()
        if not line.startswith(SSE_DATA_PREFIX):
            continue
        data = line[len(SSE_DATA_PREFIX):].strip()
        if data == SSE_DONE_MARKER:
            break

        try:
            chunk = json.loads(data)
        except json.JSONDecodeError:
            # 壊れた行は読み飛ばす（全体を失敗させない）
            continue

        if chunk.get("usage"):
            usage = chunk["usage"]
        for choice in chunk.get("choices") or []:
            if choice.get("finish_reason"):
                finish_reason = choice["finish_reason"]
            delta = choice.get("delta") or {}
            if delta.get("content"):
                content_parts.append(delta["content"])
            if delta.get("reasoning_content"):
                reasoning_parts.append(delta["reasoning_content"])

    # 6.3 の分類・13.6 のクランプ・各種ログ処理を変更せずに使えるよう、
    # 非ストリーミング応答と同じ構造に組み立てて返す
    return {
        "choices": [{
            "finish_reason": finish_reason,
            "message": {
                "content": "".join(content_parts),
                "reasoning_content": "".join(reasoning_parts),
            },
        }],
        "usage": usage or {},
    }


def request_chat_completion(host, port, api_key, payload, timeout_sec, request_id=None):
    """ストリーミングでリクエストし、SSE を集約した応答 dict を返す。

    例外はそのまま呼び出し元（7.1 のリトライ処理）へ送出する。
    `timeout_sec` は「総経過時間」の上限として扱う（read_sse_completion 参照）。
    """
    host = (host or DEFAULT_LEMONADE_HOST).strip()
    url = f"http://{host}:{port}{CHAT_COMPLETIONS_PATH}"
    headers = {"Content-Type": "application/json", "Accept": "text/event-stream"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    # 13.1 タイムアウト時にサーバー側の生成を特定・中断できるよう一意なIDを付与する
    if request_id:
        headers["X-Request-Id"] = request_id

    body = json.dumps(payload).encode("utf-8")
    deadline = time.monotonic() + timeout_sec

    # 13.5.1 ストリーミングでは接続の明示クローズが必須。urllib ではなく http.client を
    # 直接使うことで、読み取りごとの残り時間設定と finally での確実な close を保証する。
    conn = http.client.HTTPConnection(host, port, timeout=timeout_sec)
    try:
        conn.request("POST", CHAT_COMPLETIONS_PATH, body=body, headers=headers)
        response = conn.getresponse()
        if response.status >= 400:
            detail = response.read(MAX_ERROR_BODY_BYTES).decode("utf-8", "replace")
            # classify_error が http_{code} を返せるよう urllib の例外型に合わせる
            raise urllib.error.HTTPError(url, response.status, detail, response.headers, None)
        return read_sse_completion(conn, response, deadline)
    finally:
        # 13.5 タイムアウト・例外時に確実にTCP接続を閉じ、切断をサーバーへ伝える。
        # 生成フェーズの切断がサーバーへ届くのはストリーミングだからで、
        # 非ストリーミングだと打ち切った生成が最後まで走り続ける（実機確認済み）。
        conn.close()


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
        # 6.3 parse_length。13.6 の max_tokens 増量で回復を狙う
        raise CaptionParseError(
            f"max_tokens に達したため本文が生成されませんでした"
            f"（thinking で {thinking_chars} 文字を消費）",
            REASON_PARSE_LENGTH,
        )
    raise CaptionParseError(
        f"モデルが本文を返しませんでした (finish_reason={finish_reason}, "
        f"thinking {thinking_chars} 文字)",
        REASON_PARSE_FORMAT,
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


def classify_parse_failure(response_payload, requested_max_tokens):
    # 6.3 パース失敗の理由を finish_reason で分類する（"---" の有無だけで判定しない）。
    choices = response_payload.get("choices") or [{}]
    choice = choices[0] if isinstance(choices[0], dict) else {}
    if choice.get("finish_reason") == "length":
        return REASON_PARSE_LENGTH

    # usage が取れる場合は補強材料として使う（completion_tokens が max_tokens に張り付いていれば
    # finish_reason が "stop" でも打ち切りとみなす）。usage 未対応サーバーでは finish_reason のみ。
    usage = response_payload.get("usage") or {}
    completion_tokens = usage.get("completion_tokens")
    if (requested_max_tokens and isinstance(completion_tokens, (int, float))
            and completion_tokens >= requested_max_tokens):
        return REASON_PARSE_LENGTH
    return REASON_PARSE_FORMAT


def parse_response(raw_response, output_mode, trigger_word, failure_category=REASON_PARSE_FORMAT):
    # 6章 パース本体。失敗時は CaptionParseError を送出する（7.1 のリトライ対象）。
    # failure_category には 6.3 の分類を渡し、送出する例外に付与する。
    try:
        return _parse_response_body(raw_response, output_mode, trigger_word)
    except CaptionParseError as e:
        e.category = failure_category
        raise


def _parse_response_body(raw_response, output_mode, trigger_word):
    body = strip_thinking(raw_response).strip()
    if len(body) < MIN_VALID_RESPONSE_CHARS:
        raise CaptionParseError(f"応答が短すぎます ({len(body)}文字): {body!r}")

    if output_mode == "both":
        tags_part, caption_part = split_both_parts(body)
        return combine_both_output(tags_part, caption_part, trigger_word)

    # tags_only / caption_only は </think> 除去後の応答全体をそのまま使う
    # （プロンプト側で "---" 区切りなしの単純テキストを返すよう指示している）
    return body


def first_value(value, default=None):
    # INPUT_IS_LIST = True のため全入力がリストで届く。ウィジェット値は要素1個のリストになる。
    # 未接続の optional 入力は素の値（関数定義のデフォルト）で来る場合もあるため両方許容する。
    if isinstance(value, list):
        return value[0] if value else default
    return default if value is None else value


def resolve_tags_per_image(tags, count):
    # WD14 Tagger は OUTPUT_IS_LIST=(True,) で「画像1枚につき1件」のタグ文字列を返すため、
    # i番目の画像に i番目のタグを対応させる。
    # 手入力やSTRING直結で1件しか来ない場合は、全画像に同じタグを適用する（従来の挙動）。
    entries = list(tags) if isinstance(tags, list) else [tags]
    entries = [entry if isinstance(entry, str) else "" for entry in entries]

    if not entries:
        return [""] * count
    if len(entries) == 1:
        return [entries[0]] * count
    # 件数が画像より多ければ切り捨て、少なければ空文字で埋める
    # （空文字は 7.2 の事前チェックで empty_tags としてスキップ・記録される）
    resolved = entries[:count]
    resolved.extend([""] * (count - len(resolved)))
    return resolved


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


def log_timestamp():
    return datetime.datetime.now().strftime(LOG_TIMESTAMP_FORMAT)


def write_log(log_dir, message, is_error=False):
    # log.log は全処理ログ、error.log は失敗のみ（error.log の内容は log.log にも含まれる）
    line = f"[{log_timestamp()}] {message}"
    append_log_line(log_dir, FULL_LOG_FILENAME, line)
    if is_error:
        append_log_line(log_dir, ERROR_LOG_FILENAME, line)


def write_prompt_log(log_dir, header, body=""):
    # log_prompt が ON のときだけ呼ばれる。多行の本文はインデントして1ブロックとして追記する。
    block = f"[{log_timestamp()}] {header}"
    if body:
        indented = "\n".join(PROMPT_LOG_INDENT + line for line in body.splitlines())
        block = f"{block}\n{indented}"
    append_log_line(log_dir, PROMPT_LOG_FILENAME, block)


def format_duration(seconds):
    # 実行全体の所要時間表示用
    seconds = max(0.0, seconds)
    if seconds < 60:
        return f"{seconds:.1f}秒"
    minutes, secs = divmod(int(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}時間{minutes}分{secs}秒"
    return f"{minutes}分{secs}秒"


def format_response_timing(elapsed_sec, response_payload):
    # RESPONSE の見出し用。usage を返さないサーバーもあるため tok/s は取れるときだけ付ける。
    parts = [f"{elapsed_sec:.1f}秒"]
    usage = response_payload.get("usage") or {}
    completion_tokens = usage.get("completion_tokens")
    if isinstance(completion_tokens, (int, float)) and elapsed_sec > 0:
        parts.append(f"{completion_tokens / elapsed_sec:.1f} tok/s")
    return ", ".join(parts)


def describe_image_part(pil_image, image_base64):
    # 画像パートの base64 は1枚で1MBを超えるため、ログには要約だけを残す
    approx_kb = len(image_base64) * 3 // 4 // 1024
    width, height = pil_image.size
    return f"<image {width}x{height} {IMAGE_FORMAT} 約{approx_kb}KB / base64は省略>"


def format_response_for_log(response_payload):
    # 生応答の記録用。thinking は content と分離して返るサーバーがあるため両方を残す。
    # ここで例外を出すとリトライ判定に紛れ込むため、すべて defensive に取り出す。
    choices = response_payload.get("choices") or [{}]
    choice = choices[0] if isinstance(choices[0], dict) else {}
    message = choice.get("message") or {}
    content = message.get("content") or ""
    reasoning = message.get("reasoning_content") or ""

    blocks = [f"finish_reason={choice.get('finish_reason')} usage={response_payload.get('usage')}"]
    if reasoning:
        blocks.append(f"--- reasoning_content ({len(reasoning)}文字) ---\n{reasoning}")
    blocks.append(f"--- content ({len(content)}文字) ---\n{content}")
    return "\n".join(blocks)


def classify_error(error):
    # 7.1 の4分類（connection / timeout / parse_length / parse_format）を返す。
    # 4分類に当てはまらないもの（HTTPエラー・不正JSON等）は独自の名前を返し、
    # パラメータ調整の対象外（据え置き）として扱う。
    if isinstance(error, CaptionParseError):
        return getattr(error, "category", REASON_PARSE_FORMAT)
    if isinstance(error, urllib.error.HTTPError):
        return f"http_{error.code}"
    # 読み取りタイムアウトは TimeoutError、接続タイムアウトは URLError(reason=TimeoutError) で来る
    if isinstance(error, TimeoutError) or isinstance(getattr(error, "reason", None), TimeoutError):
        return REASON_TIMEOUT
    if isinstance(error, urllib.error.URLError):
        return REASON_CONNECTION
    if isinstance(error, (json.JSONDecodeError, KeyError, IndexError)):
        return "invalid_response"
    return type(error).__name__


def estimate_prompt_tokens(system_prompt_text, user_text, has_image=True):
    # 13.6.1 プロンプト側トークン数の概算。厳密なトークナイザ計算は不要で、
    # 「明らかに超過する組み合わせを避ける」ことが目的。
    # 実応答の usage.prompt_tokens が取れる場合はそちらを優先する（呼び出し側で差し替える）。
    chars = len(system_prompt_text or "") + len(user_text or "")
    estimate = chars // CHARS_PER_TOKEN_ESTIMATE
    if has_image:
        # 画像はbase64の文字数ではなく画像トークンとして数えられるため固定値で見積もる
        estimate += IMAGE_PROMPT_TOKENS_ESTIMATE
    return estimate


def clamp_max_tokens(desired_max_tokens, prompt_tokens, max_context_window):
    # 13.6.1 「プロンプト側の推定トークン数 + max_tokens」が max_context_window を
    # 超えないようクランプする。戻り値は (max_tokens, クランプしたか)。
    if not max_context_window:
        return desired_max_tokens, False

    allowed = max_context_window - prompt_tokens - CONTEXT_SAFETY_MARGIN_TOKENS
    allowed = max(MIN_MAX_TOKENS, allowed)
    if desired_max_tokens > allowed:
        return allowed, True
    return desired_max_tokens, False


def shrink_retry_params(attempt, base_max_tokens, base_temperature):
    # 13.2 暴走の再発防止。表は「試行回数」で索く（基準はウィジェット設定値）。
    index = min(attempt - 1, len(RETRY_MAX_TOKENS_SCALE) - 1)
    scaled = int(base_max_tokens * RETRY_MAX_TOKENS_SCALE[index])
    # 下限でクリップしたうえで、元の設定値を超えないようにする
    # （ユーザーが下限より小さい max_tokens を設定している場合に増えてしまうのを防ぐ）
    max_tokens = min(base_max_tokens, max(RETRY_MAX_TOKENS_FLOOR[index], scaled))
    # 浮動小数の誤差がログに出ないよう丸める（0.3 + 0.4 = 0.7000000000000001 対策）
    temperature = round(min(RETRY_TEMPERATURE_CEILING,
                            base_temperature + RETRY_TEMPERATURE_DELTA[index]), 2)
    return max_tokens, temperature


def next_attempt_params(previous_reason, attempt, current_max_tokens, current_temperature,
                        base_max_tokens, base_temperature, max_context_window, prompt_tokens):
    """7.1 直前の試行の失敗理由で次の試行のパラメータを決める（固定の試行回数テーブルではない）。

    戻り値は (max_tokens, temperature, クランプしたか)。
    - parse_length            : 13.6 直前に使用した値の2倍（max_context_window でクランプ）
    - timeout / parse_format  : 13.2 の縮小テーブル（試行回数で索く。基準はウィジェット設定値）
    - connection / その他     : 調整なし（直前に使用した値のまま再試行）
    """
    if attempt <= 1:
        return base_max_tokens, base_temperature, False

    if previous_reason == REASON_PARSE_LENGTH:
        desired = current_max_tokens * RETRY_MAX_TOKENS_GROWTH
        max_tokens, clamped = clamp_max_tokens(desired, prompt_tokens, max_context_window)
        # 13.6 は max_tokens のみを調整し temperature は据え置く
        return max_tokens, current_temperature, clamped

    if previous_reason in SHRINK_REASONS:
        max_tokens, temperature = shrink_retry_params(attempt, base_max_tokens, base_temperature)
        return max_tokens, temperature, False

    return current_max_tokens, current_temperature, False


def cancel_request(log_dir, host, port, api_key, request_id):
    # 13.1 タイムアウト時にサーバー側の生成を明示的に中断させる。
    # ベストエフォートであり、失敗しても 7.1 のリトライ処理は継続する（成功は必須条件にしない）。
    if not LEMONADE_CANCEL_PATH:
        write_log(log_dir,
                  f"CANCEL_SKIPPED request_id={request_id} reason=no_endpoint_configured")
        return False

    host = (host or DEFAULT_LEMONADE_HOST).strip()
    url = f"http://{host}:{port}{LEMONADE_CANCEL_PATH}"
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    body = json.dumps({"request_id": request_id}).encode("utf-8")
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=CANCEL_TIMEOUT_SEC):
            pass
    except (OSError, ValueError) as e:
        write_log(log_dir, f"CANCEL_FAILED request_id={request_id} reason={e}")
        return False

    write_log(log_dir, f"CANCEL_REQUEST_SENT request_id={request_id}")
    return True


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
                # 4.1 output_mode ウィジェットは廃止。system_prompt_file 1行目の
                # メタデータ行（<!-- output_mode: ... -->）から自動判定する
                "system_prompt_file": (system_prompt_files,),
                "lemonade_host": ("STRING", {"default": DEFAULT_LEMONADE_HOST}),
                "lemonade_port": ("INT", {"default": DEFAULT_LEMONADE_PORT, "min": 1, "max": 65535}),
                "lemonade_api_key": ("STRING", {"default": ""}),
                "model": (model_list,),
                "enable_thinking": ("BOOLEAN", {"default": True}),
                "temperature": ("FLOAT", {"default": 0.3, "min": 0.0, "max": 2.0, "step": 0.05}),
                # 13.6 これは固定の生成上限ではなく「自動増量の初期値」。
                # finish_reason=="length"（parse_length）で失敗すると次の試行で倍増する。
                "max_tokens": ("INT", {
                    "default": 8192, "min": 1, "max": 32768,
                    "tooltip": "生成トークン数の初期値。応答が尻切れ(finish_reason=length)に"
                               "なった場合、リトライで自動的に倍増します"
                               "（モデルの max_context_window でクランプ）。",
                }),
                "timeout_sec": ("INT", {"default": 120, "min": 1, "max": 3600}),
                # 8章 ON にすると IS_CHANGED が毎回異なる値を返しキャッシュを無効化する
                "always_regenerate": ("BOOLEAN", {"default": False}),
                # ON にすると LLM への送信内容と生応答を prompt.log に記録する（既定OFF）。
                # システムプロンプトの検証用。コンソールには出さない（7.4準拠）。
                "log_prompt": ("BOOLEAN", {"default": False}),
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

    # 9章 WD14 Tagger は OUTPUT_IS_LIST=(True,) で画像枚数分のタグをリストで返す。
    # INPUT_IS_LIST を宣言しないと ComfyUI がリスト要素ごとにノードを再実行してしまい
    # （execution.py の map_node_over_list）、タグと画像の対応が崩れて N×N 回 LLM を呼ぶことになる。
    # 全入力をリストで受け取り、対応付けはノード側で行う。
    INPUT_IS_LIST = True

    # caption_text は image と同じ枚数・同じ順序のリストとして返す（指示書2.2 / 9章）
    OUTPUT_IS_LIST = (True,)

    # 3. 実際の処理を行うメソッド名（ComfyUIがこの名前で呼び出す）
    FUNCTION = "generate"

    # 4. ノード一覧で表示されるカテゴリ（サイドバーの分類）
    CATEGORY = "Image-Captioning-in"

    # 5. 8章 キャッシュ制御。引数は INPUT_TYPES と同じ並び（optional の image_names のみ既定値あり）。
    #    INPUT_IS_LIST = True のため IS_CHANGED にも全入力がリストで渡る（execution.py の
    #    IsChangedCache が generate() と同じ _async_map_node_over_list 経由で呼ぶため）。
    #    なお他ノードから接続された入力は IS_CHANGED 呼び出し時点では確定しておらず (None,) で届く。
    @classmethod
    def IS_CHANGED(cls, image, tags, trigger_word, system_prompt_file, lemonade_host,
                   lemonade_port, lemonade_api_key, model, enable_thinking, temperature, max_tokens,
                   timeout_sec, always_regenerate, log_prompt, image_names=""):
        if first_value(always_regenerate, False):
            # ON: NaN は自身との等値比較が成立しないため、ComfyUI は常に「変化あり」と判断する
            return float("nan")
        # OFF: 固定値を返して ComfyUI 標準のキャッシュ挙動に任せる。
        # キャッシュキーには IS_CHANGED の戻り値に加えて全入力値と上流ノードの署名が含まれるため
        # （comfy_execution/caching.py の get_immediate_node_signature）、入力が変われば再実行される。
        return False

    def generate(self, image, tags, trigger_word, system_prompt_file, lemonade_host,
                 lemonade_port, lemonade_api_key, model, enable_thinking, temperature, max_tokens,
                 timeout_sec, always_regenerate=False, log_prompt=False, image_names=""):
        # always_regenerate はキャッシュ制御（IS_CHANGED）専用のため、生成処理では使用しない
        run_started = time.monotonic()
        # INPUT_IS_LIST = True のため全入力がリストで届く。tags 以外は単一値として取り出す。
        trigger_word = first_value(trigger_word, "")
        system_prompt_file = first_value(system_prompt_file)
        lemonade_host = first_value(lemonade_host, DEFAULT_LEMONADE_HOST)
        lemonade_port = first_value(lemonade_port, DEFAULT_LEMONADE_PORT)
        lemonade_api_key = first_value(lemonade_api_key, "")
        model = first_value(model)
        enable_thinking = first_value(enable_thinking, True)
        temperature = first_value(temperature)
        max_tokens = first_value(max_tokens)
        timeout_sec = first_value(timeout_sec)
        log_prompt = first_value(log_prompt, False)
        image_names = first_value(image_names, "")

        # 4.1 メタデータ行から output_mode を判定し、その行を除いた本文を system message にする
        if system_prompt_file == FALLBACK_SYSTEM_PROMPT_LABEL:
            output_mode, system_prompt_text = None, ""
        else:
            output_mode, system_prompt_text = parse_system_prompt_file(system_prompt_file)
        prompt_file_is_invalid = output_mode is None

        # image はバッチテンソル1個のリスト、または上流によってはテンソルのリストで届く
        images = list(iter_images(image))
        tags_per_image = resolve_tags_per_image(tags, len(images))
        name_entries = split_image_name_entries(image_names)
        log_dir = ensure_log_dir()
        labels = resolve_image_labels(name_entries, len(images))

        # 7.4.1 デバッグ用の設定値サマリ。バッチ内で値は不変のため実行開始時に1回だけ出力する
        # （7.4 のコンソール出力簡略化を行う際もこの行は残すこと）
        summary = (f"開始: {len(images)}枚, model={model}, mode={output_mode or 'INVALID'}, "
                   f"prompt={system_prompt_file}, thinking={enable_thinking}, temp={temperature}, "
                   f"top_p={FIXED_TOP_P}, max_tokens={max_tokens}, timeout={timeout_sec}s")
        print(f"[LLMCaptionGenerator] {summary}")
        print(f"[LLMCaptionGenerator] ログ出力先: {log_dir}")
        write_log(log_dir, f"RUN {summary}")

        # system message はバッチ内で不変のため実行開始時に1回だけ記録する
        if log_prompt:
            write_prompt_log(log_dir, f"==== RUN {summary} ====")
            write_prompt_log(
                log_dir,
                f"PROMPT system ({system_prompt_file}, {len(system_prompt_text)}文字):",
                system_prompt_text,
            )

        # 4.1 メタデータ行が無い／不正な場合は、この実行のすべての画像を失敗扱いにする
        if prompt_file_is_invalid:
            print(f"[LLMCaptionGenerator] INVALID_PROMPT_FILE: {system_prompt_file} "
                  f"({INVALID_PROMPT_FILE_REASON})")
            write_log(log_dir,
                      f"INVALID_PROMPT_FILE: {system_prompt_file} "
                      f"reason={INVALID_PROMPT_FILE_REASON}",
                      is_error=True)

        # 9章 タグと画像の件数が食い違うと対応がずれるため警告する（処理自体は継続）
        tag_count = len(tags) if isinstance(tags, list) else 1
        if tag_count > 1 and tag_count != len(images):
            warning = f"WARNING: タグ {tag_count}件 と 画像 {len(images)}枚 の件数が一致しません"
            print(f"[LLMCaptionGenerator] {warning}")
            write_log(log_dir, warning)

        # 13.6.1 上限クランプ用のコンテキスト長。バッチ内で不変なのでここで1回だけ解決する
        max_context_window = get_model_context_window(
            lemonade_host, lemonade_port, lemonade_api_key, model
        )

        results = []
        success_count = 0
        for index, image_tensor in enumerate(images, start=1):
            label = labels[index - 1]
            image_tags = tags_per_image[index - 1]
            write_log(log_dir, f"START: {label}")

            # 4.1 事前チェック：プロンプトファイルが不正ならLLMを呼ばずに即スキップ
            if prompt_file_is_invalid:
                print(f"[LLMCaptionGenerator] SKIPPED: {label} ({REASON_INVALID_PROMPT_FILE})")
                write_log(log_dir,
                          f"SKIPPED: {label} reason={REASON_INVALID_PROMPT_FILE}", is_error=True)
                # 9章：スキップしても枚数・順序を崩さないよう空文字を入れる
                results.append("")
                continue

            # 7.2 事前チェック：tags が空文字ならLLMを呼ばずに即スキップ（リトライ対象外）
            if not image_tags.strip():
                print(f"[LLMCaptionGenerator] SKIPPED: {label} (empty_tags)")
                write_log(log_dir, f"SKIPPED: {label} reason=empty_tags", is_error=True)
                # 9章：スキップしても枚数・順序を崩さないよう空文字を入れる
                results.append("")
                continue

            pil_image = resize_if_needed(tensor_to_pil(image_tensor))
            image_base64 = encode_image_base64(pil_image)
            messages = build_messages(system_prompt_text, image_tags, trigger_word, image_base64)

            print(f"[LLMCaptionGenerator] {index}/{len(images)} 送信中 "
                  f"(size={pil_image.size[0]}x{pil_image.size[1]})")

            if log_prompt:
                user_text = build_user_text(image_tags, trigger_word)
                write_prompt_log(
                    log_dir,
                    f"PROMPT user {label} ({index}/{len(images)}):",
                    f"{user_text}\n{describe_image_part(pil_image, image_base64)}",
                )

            # 7.1 4分類（connection / timeout / parse_length / parse_format）を
            # 同一カウンタで最大 MAX_ATTEMPTS 回試行する
            caption = ""
            # 13.6.1 クランプに使うプロンプト側トークン数。応答の usage が取れたら実測値へ差し替える
            prompt_tokens = estimate_prompt_tokens(
                system_prompt_text, build_user_text(image_tags, trigger_word)
            )
            attempt_max_tokens, attempt_temperature, attempt_clamped = max_tokens, temperature, False
            # 7.1 直前の試行の失敗理由に応じて次の試行のパラメータを分岐させる
            previous_reason = None
            for attempt in range(1, MAX_ATTEMPTS + 1):
                attempt_max_tokens, attempt_temperature, attempt_clamped = next_attempt_params(
                    previous_reason, attempt, attempt_max_tokens, attempt_temperature,
                    max_tokens, temperature, max_context_window, prompt_tokens
                )
                payload = build_chat_payload(model, messages, enable_thinking,
                                             attempt_temperature, attempt_max_tokens)
                # 13.1 リクエストごとに一意なIDを発行し、タイムアウト時のキャンセルに使う
                request_id = str(uuid.uuid4())
                try:
                    request_started = time.monotonic()
                    response_payload = request_chat_completion(
                        lemonade_host, lemonade_port, lemonade_api_key, payload, timeout_sec,
                        request_id=request_id
                    )
                    elapsed = time.monotonic() - request_started
                    # 13.6.1 実測のプロンプトトークン数が取れれば概算より優先する
                    actual_prompt_tokens = (response_payload.get("usage") or {}).get("prompt_tokens")
                    if isinstance(actual_prompt_tokens, int) and actual_prompt_tokens > 0:
                        prompt_tokens = actual_prompt_tokens
                    if log_prompt:
                        timing = format_response_timing(elapsed, response_payload)
                        write_prompt_log(
                            log_dir,
                            f"RESPONSE {label} (attempt {attempt}/{MAX_ATTEMPTS}, {timing}, "
                            f"max_tokens={attempt_max_tokens}, temp={attempt_temperature}):",
                            format_response_for_log(response_payload),
                        )
                    raw_response = extract_response_text(response_payload)
                    # 6.3 パース失敗時にどちらの分類として扱うかを finish_reason から決めておく
                    failure_category = classify_parse_failure(response_payload, attempt_max_tokens)
                    caption = parse_response(raw_response, output_mode, trigger_word,
                                             failure_category)
                    write_log(log_dir, f"SUCCESS: {label} mode={output_mode} attempt={attempt}")
                    success_count += 1
                    break
                except RETRYABLE_EXCEPTIONS as e:
                    reason = classify_error(e)
                    previous_reason = reason
                    if reason == REASON_TIMEOUT:
                        # 13.5 HTTP接続の切断そのものがキャンセル手段として機能する。
                        # Lemonade Server v11.7.0 の PR #3133 により、prefill中（初トークン
                        # 生成前）の切断も上流リクエストへ伝わり生成が中断される。
                        # 接続は request_chat_completion() の finally で確実に閉じている。
                        write_log(log_dir,
                                  f"CONNECTION_ABORTED: {label} reason=timeout "
                                  f"note=prefill_cancel_supported_v11.7+")
                        # 13.5.1 その上で、正式なキャンセルAPIが設定されていれば保険として呼ぶ
                        cancel_request(log_dir, lemonade_host, lemonade_port,
                                       lemonade_api_key, request_id)
                    # 13.3 / 13.6.2 各試行で実際に使用したパラメータと分類を記録する。
                    # クランプが発生した試行には note= を付記する。
                    clamp_note = f" {CLAMP_LOG_NOTE}" if attempt_clamped else ""
                    write_log(log_dir,
                              f"RETRY: {label} attempt={attempt}/{MAX_ATTEMPTS} "
                              f"max_tokens={attempt_max_tokens} temperature={attempt_temperature} "
                              f"reason={reason}{clamp_note} detail={e}")
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
        write_log(log_dir, f"RUN END: success={success_count} skipped={skipped_count} "
                           f"elapsed={format_duration(time.monotonic() - run_started)}")

        return (results,)
