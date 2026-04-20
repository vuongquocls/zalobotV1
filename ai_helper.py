"""
ai_helper.py — AI hỗ trợ viết bài truyền thông.

Hỗ trợ nhiều LLM miễn phí: OpenRouter → Groq → Gemini → Ollama (fallback).
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from dotenv import load_dotenv

load_dotenv()

DEFAULT_AI_FALLBACK = (
    "Em đang bận xử lý nên chưa trả lời ngay được. "
    "Anh/Chị thử nhắn lại sau ít phút giúp em nhé."
)

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
_ollama_models_raw = os.getenv("OLLAMA_MODELS", "kimi-k2.5:cloud,gemma4:31b-cloud")
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
    return content.strip()


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
    return str(content).strip()


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
        link="",
        row_number=4,
    )

    async def test():
        print(f"🤖 Providers: {[p['name'] for p in PROVIDERS]}")
        print("🤖 Đang gọi AI để gợi ý bài viết...")
        result = await draft_article(sample_task)
        print(result)

    asyncio.run(test())
