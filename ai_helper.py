"""
ai_helper.py — AI hỗ trợ viết bài truyền thông.

Hỗ trợ nhiều LLM miễn phí: OpenRouter → Groq → Gemini → Ollama (fallback).
"""

from __future__ import annotations

import os
import re
from typing import TYPE_CHECKING

from dotenv import load_dotenv

load_dotenv()

DEFAULT_AI_FALLBACK = (
    "Em đang bận xử lý nên chưa trả lời ngay được. "
    "Anh/Chị thử nhắn lại sau ít phút giúp em nhé."
)

FACEBOOK_STYLE_OPTIONS = ("vui vẻ", "cảm xúc mạnh", "nghiêm túc", "khoa học")
DEFAULT_FACEBOOK_STYLE = "Yok Đôn mộc mạc, cảm xúc, gần gũi; tự chia thành 3 phương án khác nhau"
FACEBOOK_STYLE_PATTERNS = {
    "vui vẻ": ("vui vẻ", "vui ve", "tươi vui", "tuoi vui", "nhẹ nhàng", "nhe nhang"),
    "cảm xúc mạnh": ("cảm xúc", "cam xuc", "cảm xúc mạnh", "cam xuc manh", "xúc động", "xuc dong"),
    "nghiêm túc": ("nghiêm túc", "nghiem tuc", "chuyên nghiệp", "chuyen nghiep", "trang trọng", "trang trong"),
    "khoa học": ("khoa học", "khoa hoc", "chuyên môn", "chuyen mon", "thông tin", "thong tin"),
}

YOKDON_CONTENT_STYLE_GUIDE = """
BẢN GHI NHỚ YOK ĐÔN CONTENT (CẬP NHẬT 2025)

Phong cách nội dung:
- Mộc mạc, tự nhiên, gần gũi nhưng có chiều sâu.
- Không lạm dụng ngôn từ hoa mỹ. Dùng cảm xúc thật, kể chuyện như hơi thở của rừng.
- Có thể pha hài hước nhẹ, bụi bụi, tỉnh táo.
- Linh hoạt giọng điệu theo bối cảnh: trang trọng, cảm xúc, dí dỏm, tâm linh vui.

Chủ đề/vibe đã triển khai:
- Kể chuyện Yok Đôn qua kiểm lâm, thiên nhiên và cộng đồng yêu rừng.
- Chống mang chó vào rừng, bảo vệ động vật hoang dã.
- Khoảnh khắc sinh sôi rừng khộp, gà rừng nở con, gặp thỏ trong đêm tuần tra.
- Câu chuyện tuần tra đêm dưới mưa, lá thư từ rừng, mùa mưa gõ cửa.
- Storytelling về những sinh linh nhỏ giữa rừng, như Tổ Yến mào non hoặc chim non Quạ Thông.
- Vibe chạy bộ/tâm linh vui: thư mời giải chạy, giấc mơ voi đeo bib, không đi race là trái ý trời.
- Giới thiệu loài mới ghi nhận, di sản, sách, sức khỏe cộng đồng và các ngày kỷ niệm phù hợp.

Câu chữ/gu từ ngữ cần nhớ:
- "Không ai báo tin, nhưng rừng biết."
- "Chạy 1km – cũng đủ biết ai thật lòng!"
- "Giữ rừng – giữ di sản – giữ chỗ cho mọi người."
- "Không mang chó vào rừng – vì rừng không phải sân chơi."
- "Rừng khô rụng lá cũng có mùa sinh nở."
- "Giấc mơ voi M’nông – hóa thành bib thật trong đời."
- "Khi mùa mưa gõ cửa, Yok Đôn cũng thức dậy."
- "Bữa ăn cuối cùng và lời từ biệt nhỏ nhất giữa rừng."

Định hướng dài hạn:
- Bảo tồn hình ảnh giản dị, chân thực, tránh màu mè hóa rừng.
- Lấy tình yêu thiên nhiên và lòng tự hào về bảo tồn làm trọng tâm.
- Duy trì vibe riêng biệt: chân thực, xúc cảm, không giật gân.
""".strip()

if TYPE_CHECKING:
    from sheet_reader import Task

# === Cấu hình LLM providers (ưu tiên từ trên xuống) ===
PROVIDERS = []

# 1. OpenRouter (miễn phí với free models)
_or_key = os.getenv("OPENROUTER_API_KEY", "")
if _or_key:
    PROVIDERS.append({
        "type": "openai",
        "name": "OpenRouter",
        "api_key": _or_key,
        "base_url": "https://openrouter.ai/api/v1",
        "model": os.getenv("OPENROUTER_MODEL", "meta-llama/llama-4-maverick:free"),
    })

# 2. Groq (miễn phí, nhanh)
_groq_key = os.getenv("GROQ_API_KEY", "")
if _groq_key:
    PROVIDERS.append({
        "type": "openai",
        "name": "Groq",
        "api_key": _groq_key,
        "base_url": "https://api.groq.com/openai/v1",
        "model": os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"),
    })

# 3. Gemini (fallback cuối)
_gemini_key = os.getenv("GEMINI_API_KEY", "")
if _gemini_key:
    PROVIDERS.append({
        "type": "openai",
        "name": "Gemini",
        "api_key": _gemini_key,
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "model": os.getenv("GEMINI_MODEL", "gemini-2.0-flash"),
    })

# 4. Ollama local/cloud models (không cần API key ở code bot)
_ollama_base_url = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
_ollama_models_raw = os.getenv("OLLAMA_MODELS", "gemma4:31b-cloud,kimi-k2.5:cloud")
for _ollama_model in [model.strip() for model in _ollama_models_raw.split(",") if model.strip()]:
    PROVIDERS.append({
        "type": "ollama",
        "name": "Ollama",
        "base_url": _ollama_base_url,
        "model": _ollama_model,
    })


def _build_article_prompt(task: "Task", extra_request: str = "") -> str:
    """Tạo prompt gợi ý bài viết dựa trên thông tin task."""
    lines = [
        "Bạn là chuyên gia truyền thông của Vườn quốc gia Yok Đôn.",
        "Hãy viết nội dung bài truyền thông theo thông tin sau:",
        "",
        f"- Chủ đề: {task.topic}",
        f"- Nhóm nội dung: {task.content_group}",
        f"- Kênh đăng: {task.channel}",
        f"- Định dạng: {task.format_type}",
    ]
    if extra_request:
        lines.append(f"\nYêu cầu thêm: {extra_request}")
    lines.extend([
        "",
        "Lưu ý:",
        "- Viết bằng tiếng Việt, giọng chuyên nghiệp nhưng gần gũi.",
        "- Phù hợp với kênh đăng tải.",
        "- Nếu là bài viết + ảnh, gợi ý caption và mô tả ảnh cần chụp.",
        "- Nếu là video ngắn, gợi ý kịch bản ngắn gọn.",
        "- Độ dài: khoảng 150-300 từ cho bài viết, 50-100 từ cho caption.",
    ])
    return "\n".join(lines)


def _clean_model_output(text: str) -> str:
    """Loại bỏ thought/reasoning nếu model lỡ trả chung vào content."""
    cleaned = text or ""
    cleaned = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", cleaned)
    cleaned = re.sub(r"<think>.*?</think>", "", cleaned, flags=re.IGNORECASE | re.DOTALL)
    cleaned = re.sub(
        r"<\|channel\>thought.*?<channel\|>",
        "",
        cleaned,
        flags=re.IGNORECASE | re.DOTALL,
    )
    cleaned = re.sub(
        r"(?is)^\s*thinking\.\.\..*?\.\.\.done thinking\.\s*",
        "",
        cleaned,
    )
    return cleaned.strip()


def _strip_accents(value: str) -> str:
    import unicodedata

    normalized = unicodedata.normalize("NFD", value or "")
    without_marks = "".join(char for char in normalized if unicodedata.category(char) != "Mn")
    return without_marks.replace("đ", "d").replace("Đ", "D")


def detect_facebook_style(request_text: str) -> str:
    """Nhan dien phong cach viet bai Facebook nguoi dung da neu trong yeu cau."""
    normalized = _strip_accents(request_text or "").lower()
    for style, patterns in FACEBOOK_STYLE_PATTERNS.items():
        if any(_strip_accents(pattern).lower() in normalized for pattern in patterns):
            return style
    return ""


def build_facebook_style_question(request_text: str) -> str:
    """Hoi lai phong cach truoc khi viet bai de tranh ket qua chung chung."""
    topic = (request_text or "").strip()
    example = "/hotrobai cảm xúc mạnh - Trên đường HDV cứu hộ chim non Quạ Thông"
    lines = [
        "Anh muốn em viết theo phong cách nào: vui vẻ, cảm xúc mạnh, nghiêm túc hay khoa học?",
    ]
    if topic:
        lines.append(f"Chủ đề em đã nhận: {topic}")
    lines.append(f"Anh có thể nhắn lại theo mẫu: {example}")
    return "\n".join(lines)


def resolve_facebook_style(request_text: str) -> str:
    """Dung style nguoi dung neu co; neu khong thi van viet ngay theo gu Yok Don."""
    return detect_facebook_style(request_text) or DEFAULT_FACEBOOK_STYLE


def _build_facebook_options_prompt(request_text: str, style: str, context: str = "") -> str:
    """Prompt rieng cho workflow /hotrobai viet bai Facebook."""
    lines = [
        "Hãy viết như một trợ lý nội dung kiểu Hermes của Vườn quốc gia Yok Đôn.",
        "Mục tiêu: giúp người phụ trách truyền thông có bản nháp Facebook dùng được ngay, không phải một câu trả lời chatbot chung chung.",
        "",
        f"Yêu cầu của người dùng: {request_text.strip()}",
        f"Phong cách ưu tiên: {style}",
        "",
        YOKDON_CONTENT_STYLE_GUIDE,
        "",
        "Yêu cầu đầu ra:",
        "- Trả lời bằng tiếng Việt có dấu.",
        "- Mở đầu ngắn gọn: \"Em xin phép gửi Anh/Chị 3 phương án để chọn.\"",
        "- Tạo đúng 3 phương án.",
        "- Mỗi phương án có: tên phương án, caption Facebook hoàn chỉnh, gợi ý ảnh/tư liệu nếu phù hợp, hashtag.",
        "- Phương án 1: thiên về cảm xúc và lan tỏa yêu thương.",
        "- Phương án 2: thiên về thông tin/chuyên nghiệp, phù hợp xây dựng hình ảnh chuyên môn.",
        "- Phương án 3: ngắn gọn, có lời kêu gọi hành động, phù hợp tương tác nhanh.",
        "- Nếu người dùng chưa chọn phong cách, vẫn viết ngay 3 phương án khác nhau; không hỏi lại.",
        "- Ưu tiên câu chữ cụ thể, mộc mạc, có hình ảnh đời thường của Yok Đôn.",
        "- Không bịa số liệu, tên người, kết quả cứu hộ hoặc chi tiết chuyên môn nếu không có trong yêu cầu/ngữ cảnh.",
        "- Nếu thiếu chi tiết, viết theo hướng an toàn và gợi ý phần cần bổ sung.",
        "- Giọng văn Yok Đôn: gần gũi, tôn trọng thiên nhiên, có trách nhiệm bảo tồn, không quảng cáo quá đà.",
        "- Tránh văn mẫu sáo rỗng như: \"bước ngoặt quan trọng\", \"tương lai xanh đẹp hơn\", \"chung tay bảo vệ thiên nhiên\" nếu không có ngữ cảnh cụ thể.",
        "- Không dùng tiếng Anh cho tiêu đề như Option 1/Option 2; dùng \"Phương án 1\".",
        "- Hạn chế emoji; nếu dùng, chỉ 1-2 ký tự đơn giản và không để emoji thay nội dung.",
        "",
        "Ví dụ chất giọng mong muốn:",
        "- Không ai báo tin, nhưng rừng biết.",
        "- Rừng không cần những lời quá lớn. Rừng cần những câu chuyện thật, được kể tử tế.",
        "- Từ hôm nay, nhóm truyền thông Yok Đôn có thêm một việc: gom những điều nhỏ của rừng, kể lại bằng tiếng nói gần gũi hơn.",
    ]
    if context:
        lines.extend(["", "Ngữ cảnh được phép dùng:", context])
    return "\n".join(lines)


async def _call_llm(
    system: str,
    user: str,
    max_tokens: int = 1500,
    fallback_message: str = DEFAULT_AI_FALLBACK,
) -> str:
    """Gọi LLM với fallback qua nhiều provider."""
    if not PROVIDERS:
        print("   ⚠️ Chưa cấu hình LLM provider nào.")
        return fallback_message

    last_error = ""
    for provider in PROVIDERS:
        try:
            if provider["type"] == "ollama":
                result = await _call_ollama(provider, system, user, max_tokens)
            else:
                result = await _call_openai_compatible(provider, system, user, max_tokens)
            result = _clean_model_output(result)
            if result:
                print(f"   ✅ AI: dùng {provider['name']} ({provider['model']})")
                return result
        except Exception as e:
            last_error = f"{provider['name']}: {e}"
            print(f"   ⚠️ {last_error}")
            continue

    print(f"   ❌ Tất cả LLM đều lỗi. Lỗi cuối: {last_error}")
    return fallback_message


async def _call_openai_compatible(provider: dict, system: str, user: str, max_tokens: int) -> str:
    """Gọi các provider có API tương thích OpenAI."""
    from openai import AsyncOpenAI

    client = AsyncOpenAI(
        api_key=provider["api_key"],
        base_url=provider["base_url"],
    )
    response = await client.chat.completions.create(
        model=provider["model"],
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        max_tokens=max_tokens,
        temperature=0.7,
    )
    content = response.choices[0].message.content or ""
    return _clean_model_output(content)


async def _call_ollama(provider: dict, system: str, user: str, max_tokens: int) -> str:
    """Gọi Ollama qua REST API để có thể fallback khi cloud API hết quota."""
    import httpx

    payload = {
        "model": provider["model"],
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "stream": False,
        "think": False,
        "options": {
            "temperature": 0.7,
            "num_predict": max_tokens,
        },
    }
    timeout = httpx.Timeout(connect=5.0, read=120.0, write=30.0, pool=5.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(f"{provider['base_url']}/api/chat", json=payload)
        response.raise_for_status()
        data = response.json()

    message = data.get("message") or {}
    content = message.get("content") or data.get("response") or ""
    return _clean_model_output(str(content))


async def draft_article(task: "Task", extra_request: str = "") -> str:
    """Gợi ý nội dung bài viết dựa trên thông tin task từ Google Sheet."""
    prompt = _build_article_prompt(task, extra_request)
    system = "Bạn là trợ lý truyền thông VQG Yok Đôn, chuyên soạn bài viết và gợi ý nội dung."
    return await _call_llm(
        system,
        prompt,
        fallback_message=(
            "Em tạm thời chưa soạn được bài viết vì dịch vụ AI đang bận. "
            "Anh/Chị thử lại sau ít phút giúp em nhé."
        ),
    )


async def draft_content_from_request(request_text: str, context: str = "") -> str:
    """Soan noi dung truyen thong tu yeu cau tu do cua nguoi dung."""
    system = (
        "Ban la tro ly truyen thong VQG Yok Don. "
        "Hay du thao noi dung bang tieng Viet, dung cau truc ro rang, "
        "co tieu de, phan noi dung va hashtag neu phu hop."
    )
    user = f"Hay du thao noi dung truyen thong theo yeu cau sau:\n{request_text.strip()}"
    if context:
        user += f"\n\nNgu canh bo sung:\n{context}"
    return await _call_llm(
        system,
        user,
        max_tokens=1500,
        fallback_message=(
            "Em tạm thời chưa dự thảo được nội dung vì dịch vụ AI đang bận. "
            "Anh/Chị thử lại sau ít phút giúp em nhé."
        ),
    )


async def draft_facebook_post_options(request_text: str, style: str, context: str = "") -> str:
    """Soan 3 phuong an bai Facebook theo workflow /hotrobai."""
    system = (
        "Bạn là trợ lý truyền thông giàu kinh nghiệm của Vườn quốc gia Yok Đôn. "
        "Bạn chuyên viết bài Facebook về bảo tồn, du lịch sinh thái, giáo dục môi trường "
        "với giọng văn gần gũi, có cảm xúc và không bịa dữ liệu."
    )
    user = _build_facebook_options_prompt(request_text, style, context=context)
    return await _call_llm(
        system,
        user,
        max_tokens=2200,
        fallback_message=(
            "Em tạm thời chưa dự thảo được bài Facebook vì dịch vụ AI đang bận. "
            "Anh/Chị thử lại sau ít phút giúp em nhé."
        ),
    )


async def answer_question(question: str, context: str = "") -> str:
    """Trả lời câu hỏi tự do liên quan đến công việc truyền thông."""
    system = (
        "Bạn là trợ lý công việc của nhóm Truyền thông VQG Yok Đôn. "
        "Trả lời ngắn gọn, hữu ích, bằng tiếng Việt."
    )
    user = question
    if context:
        user = f"Ngữ cảnh từ bảng công việc:\n{context}\n\nCâu hỏi: {question}"
    return await _call_llm(system, user, max_tokens=1000)


# === CLI test ===
if __name__ == "__main__":
    import asyncio
    from sheet_reader import Task

    sample_task = Task(
        month="Tháng 4",
        due_date=None,
        due_date_raw="25/04/2026",
        content_group="Du lịch sinh thái",
        topic="Trải nghiệm tour xem voi thân thiện: Một ngày làm du khách tại Yok Đôn",
        channel="Fanpage / Website",
        format_type="Video ngắn + Bài viết",
        assignee="TT GDMT&DV",
        status="Chưa bắt đầu",
        notes="Chú ý quay video dọc tỷ lệ 9:16",
        link="",
        row_number=4,
    )

    async def test():
        print(f"🤖 Providers: {[p['name'] for p in PROVIDERS]}")
        print("🤖 Đang gọi AI để gợi ý bài viết...")
        result = await draft_article(sample_task)
        print(result)

    asyncio.run(test())
