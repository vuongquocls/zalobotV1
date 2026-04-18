"""
ai_helper.py — AI hỗ trợ viết bài truyền thông.

Hỗ trợ nhiều LLM miễn phí: OpenRouter → Groq → Gemini (fallback).
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from dotenv import load_dotenv

load_dotenv()

if TYPE_CHECKING:
    from sheet_reader import Task

# === Cấu hình LLM providers (ưu tiên từ trên xuống) ===
PROVIDERS = []

# 1. OpenRouter (miễn phí với free models)
_or_key = os.getenv("OPENROUTER_API_KEY", "")
if _or_key:
    PROVIDERS.append({
        "name": "OpenRouter",
        "api_key": _or_key,
        "base_url": "https://openrouter.ai/api/v1",
        "model": os.getenv("OPENROUTER_MODEL", "meta-llama/llama-4-maverick:free"),
    })

# 2. Groq (miễn phí, nhanh)
_groq_key = os.getenv("GROQ_API_KEY", "")
if _groq_key:
    PROVIDERS.append({
        "name": "Groq",
        "api_key": _groq_key,
        "base_url": "https://api.groq.com/openai/v1",
        "model": os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"),
    })

# 3. Gemini (fallback cuối)
_gemini_key = os.getenv("GEMINI_API_KEY", "")
if _gemini_key:
    PROVIDERS.append({
        "name": "Gemini",
        "api_key": _gemini_key,
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "model": os.getenv("GEMINI_MODEL", "gemini-2.0-flash"),
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


async def _call_llm(system: str, user: str, max_tokens: int = 1500) -> str:
    """Gọi LLM với fallback qua nhiều provider."""
    if not PROVIDERS:
        return "Chưa cấu hình API key cho bất kỳ LLM nào (OPENROUTER_API_KEY, GROQ_API_KEY, GEMINI_API_KEY)."

    from openai import AsyncOpenAI

    last_error = ""
    for provider in PROVIDERS:
        try:
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
            result = content.strip()
            if result:
                print(f"   ✅ AI: dùng {provider['name']} ({provider['model']})")
                return result
        except Exception as e:
            last_error = f"{provider['name']}: {e}"
            print(f"   ⚠️ {last_error}")
            continue

    return f"Tất cả LLM đều lỗi. Lỗi cuối: {last_error}"


async def draft_article(task: "Task", extra_request: str = "") -> str:
    """Gợi ý nội dung bài viết dựa trên thông tin task từ Google Sheet."""
    prompt = _build_article_prompt(task, extra_request)
    system = "Bạn là trợ lý truyền thông VQG Yok Đôn, chuyên soạn bài viết và gợi ý nội dung."
    return await _call_llm(system, prompt)


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
