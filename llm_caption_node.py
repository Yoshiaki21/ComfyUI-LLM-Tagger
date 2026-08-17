import base64
import io
import json
import os
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
    # 6章のパースは未実装。ここでは生の応答テキストをそのまま取り出すだけ。
    message = response_payload["choices"][0]["message"]
    content = (message.get("content") or "").strip()

    # thinking を content と分離して返すサーバー実装もあるため、
    # content が空のときだけ reasoning_content を可視化して返す（動作確認用）。
    reasoning = (message.get("reasoning_content") or "").strip()
    if not content and reasoning:
        return f"<think>{reasoning}</think>"
    return content


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
                "max_tokens": ("INT", {"default": 2048, "min": 1, "max": 32768}),
                "timeout_sec": ("INT", {"default": 120, "min": 1, "max": 3600}),
            }
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
                 timeout_sec):
        # 6章（出力パース）・7章（リトライ／エラーハンドリング）は未実装。
        # 現状は LLM の生応答をそのまま caption_text に出力して動作確認する段階。
        if system_prompt_file == FALLBACK_SYSTEM_PROMPT_LABEL:
            system_prompt_text = ""
        else:
            system_prompt_text = read_system_prompt_file(system_prompt_file)

        results = []
        images = list(iter_images(image))
        for index, image_tensor in enumerate(images, start=1):
            pil_image = resize_if_needed(tensor_to_pil(image_tensor))
            image_base64 = encode_image_base64(pil_image)

            messages = build_messages(system_prompt_text, tags, trigger_word, image_base64)
            payload = build_chat_payload(model, messages, enable_thinking, temperature, max_tokens)

            print(f"[LLMCaptionGenerator] {index}/{len(images)} 送信中 "
                  f"(size={pil_image.size[0]}x{pil_image.size[1]}, model={model})")
            response_payload = request_chat_completion(
                lemonade_host, lemonade_port, lemonade_api_key, payload, timeout_sec
            )
            results.append(extract_response_text(response_payload))

        return (results,)
