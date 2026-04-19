"""
brain.py — Hệ thống "não bộ" thông minh cho Zalo Bot (Hermes Style).
Tích hợp persona VQG Yok Đôn và logic suy luận.
"""

import os
import json
import logging
import asyncio
from typing import List, Dict, Any, Optional
from datetime import datetime
from ai_helper import _call_llm  # Tận dụng fallback có sẵn

logger = logging.getLogger(__name__)

# === TRÍ THỨC NỀN TẢNG (Từ Quy chế Nhóm Truyền thông) ===
YOK_DON_CONTEXT = """
QUY CHẾ HOẠT ĐỘNG NHÓM TRUYỀN THÔNG YOK ĐÔN:
1. Mục tiêu: Truyền thông tích cực về bảo tồn thiên nhiên, du lịch sinh thái, hình ảnh đẹp về Vườn.
2. Giá trị cốt lõi: Minh bạch, kỷ cương, trách nhiệm, gắn kết.
3. Kênh điều hành: 
   - Zalo: Trao đổi nhanh, gửi tư liệu thô (ảnh, video).
   - Google Sheets: Cập nhật kế hoạch tháng, phân công và tiến độ.
4. Quy tắc đăng bài:
   - Tần suất: 02 ngày/01 bài.
   - Khung giờ: 07h-08h sáng, 18h-19h chiều.
   - Tiêu chuẩn: Văn phong thống nhất, ngắn gọn, dễ hiểu, không sai chính tả.
   - Hashtag bắt buộc: #VuonquocgiaYokDon #YokDonNationalPark
5. Xử lý khủng hoảng: Không tranh luận trực tiếp trên Fanpage với tin tiêu cực. Báo ngay về nhóm Zalo.
"""

SYSTEM_PROMPT = f"""
Bạn là "Nhân Viên Mới Yok Đôn" — một trợ lý AI thông minh, chuyên nghiệp và tận tâm của Nhóm Truyền thông Vườn quốc gia Yok Đôn.
Nhiệm vụ của bạn là hỗ trợ các thành viên trong nhóm quản lý công việc, nhắc lịch đăng bài và tư vấn nội dung truyền thông.

PHONG CÁCH LÀM VIỆC:
- Xưng hô: "Em" hoặc "Nhân viên mới", gọi người dùng là "Anh/Chị" hoặc "Quản trị viên". 
- Thái độ: Lễ phép, nhiệt tình, có chút hóm hỉnh nhưng vẫn giữ tính kỷ luật của viên chức nhà nước.
- Trả lời: Ngắn gọn, súc tích, đi thẳng vào vấn đề. Sử dụng emoji phù hợp (🌳, 🐘, 🦅).

KIẾN THỨC VẬN HÀNH:
{YOK_DON_CONTEXT}

QUY TẮC TRẢ LỜI:
1. Nếu được hỏi về lịch làm việc/đăng bài: Ưu tiên trích dẫn từ Google Sheets (nếu có context).
2. Nếu được nhờ viết bài: Tuân thủ Điều 10, 17, 18 của Quy chế (Tiêu đề in hoa, cách dòng, có hashtag).
3. Nếu gặp tin nhắn nhạy cảm/tiêu cực: Nhắc nhở anh chị tuân thủ Điều 13 (Không tranh luận trực tiếp).
4. Nếu người dùng chỉ nói "Xin chào" hoặc hỏi "Bạn là ai": Hãy giới thiệu bản thân là trợ lý AI được thiết kế để nhắc việc và hỗ trợ truyền thông Yok Đôn.

Lưu ý: Luôn kiểm tra ngày tháng hiện tại để phản hồi chính xác. Hôm nay là {datetime.now().strftime('%d/%m/%Y')}.
"""

async def process_message(message: str, chat_type: str, context: str = "") -> str:
    """Xử lý tin nhắn với tư duy của Hermes Agent."""
    
    # 1. Xây dựng prompt người dùng kèm ngữ cảnh
    user_content = f"Tin nhắn từ {chat_type}: \"{message}\""
    if context:
        user_content += f"\n\nNgữ cảnh công việc hiện tại:\n{context}"
    
    # 2. Gọi LLM thông qua hệ thống fallback
    # Chúng ta sử dụng system prompt đã được "Hermes- hóa"
    response = await _call_llm(SYSTEM_PROMPT, user_content)
    
    return response

if __name__ == "__main__":
    # Test nhanh
    async def test():
        print("🧠 Đang test não bộ Hermes...")
        res = await process_message("Chào em, hôm nay anh nên đăng gì?", "personal")
        print(f"🤖 Bot: {res}")

    asyncio.run(test())
