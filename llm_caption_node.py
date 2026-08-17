import json
import urllib.error
import urllib.request

DEFAULT_LEMONADE_HOST = "192.168.85.57"
DEFAULT_LEMONADE_PORT = 13305
MODELS_FETCH_TIMEOUT_SEC = 3
FALLBACK_MODEL_LABEL = "(Lemonade Server unavailable - check host/port)"


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


class LLMCaptionGenerator:
    # 1. 入力ウィジェット・入力ソケットの定義
    @classmethod
    def INPUT_TYPES(cls):
        model_list = fetch_lemonade_models(DEFAULT_LEMONADE_HOST, DEFAULT_LEMONADE_PORT)
        if not model_list:
            model_list = [FALLBACK_MODEL_LABEL]

        return {
            "required": {
                "image": ("IMAGE",),
                "tags": ("STRING", {"multiline": True, "default": ""}),
                "trigger_word": ("STRING", {"default": ""}),
                "output_mode": (["tags_only", "caption_only", "both"],),
                "lemonade_host": ("STRING", {"default": DEFAULT_LEMONADE_HOST}),
                "lemonade_port": ("INT", {"default": DEFAULT_LEMONADE_PORT, "min": 1, "max": 65535}),
                "lemonade_api_key": ("STRING", {"default": ""}),
                "model": (model_list,),
            }
        }

    # 2. 出力ソケットの型（複数なら型のタプル）
    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("caption_text",)

    # 3. 実際の処理を行うメソッド名（ComfyUIがこの名前で呼び出す）
    FUNCTION = "generate"

    # 4. ノード一覧で表示されるカテゴリ（サイドバーの分類）
    CATEGORY = "Image-Captioning-in"

    def generate(self, image, tags, trigger_word, output_mode, lemonade_host, lemonade_port, lemonade_api_key, model):
        # LLM呼び出し本体（5〜6章）は未実装。接続情報の受け渡しのみ確認できるダミー実装。
        result = f"{trigger_word}, {tags}. (dummy caption, model={model})"
        return (result,)
