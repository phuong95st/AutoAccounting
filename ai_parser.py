import json
import re
import urllib.request
import urllib.error
import ssl
import base64
from typing import Dict, Any, Optional, Tuple, List
from pathlib import Path
from config import (
    GEMINI_API_KEY_PRIMARY,
    GEMINI_API_KEY_BACKUP,
    GEMINI_MODELS,
    RULES_PATH
)

ssl_ctx = ssl.create_default_context()

class RulesManager:
    """Manages clinic categories, keyword rules, and learned knowledge."""
    def __init__(self, filepath: Path):
        self.filepath = filepath
        self.rules = self.load()

    def load(self) -> Dict[str, Any]:
        if not self.filepath.exists():
            return {"categories": {"thu": [], "chi": []}, "learned_rules": []}
        try:
            with open(self.filepath, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"Error loading rules: {e}")
            return {"categories": {"thu": [], "chi": []}, "learned_rules": []}

    def save(self):
        try:
            with open(self.filepath, "w", encoding="utf-8") as f:
                json.dump(self.rules, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"Error saving rules: {e}")

    def teach(self, keyword: str, tx_type: str, category: str):
        """Teach new rule / keyword mapping."""
        keyword = keyword.lower().strip()
        tx_type = tx_type.lower().strip()
        # Remove existing if any
        self.rules["learned_rules"] = [
            r for r in self.rules.get("learned_rules", [])
            if r.get("keyword") != keyword
        ]
        self.rules["learned_rules"].append({
            "keyword": keyword,
            "type": tx_type,
            "category": category
        })
        self.save()

    def get_learned_rules_text(self) -> str:
        lines = []
        for r in self.rules.get("learned_rules", []):
            lines.append(f"- Từ khóa '{r['keyword']}' => Loại: {r['type']}, Danh mục: '{r['category']}'")
        return "\n".join(lines) if lines else "Chưa có quy tắc bổ sung."


rules_mgr = RulesManager(RULES_PATH)


import unicodedata

def remove_accents(input_str: str) -> str:
    """Normalize Vietnamese accents to plain characters."""
    s = unicodedata.normalize('NFD', input_str)
    s = ''.join(c for c in s if unicodedata.category(c) != 'Mn')
    return s.replace('đ', 'd').replace('Đ', 'D')


class RuleEngine:
    """Fallback Rule-based parser using regular expressions and domain dictionary."""

    @staticmethod
    def normalize_typos(text: str) -> str:
        t = text.lower()
        # Common Vietnamese typing/teencode/slang typos
        typos = {
            r'\bwa\b': 'qua',
            r'\bran\b': 'rang',
            r'\bran su\b': 'rang su',
            r'\brăn\b': 'rang',
            r'\brang\b': 'rang',
            r'\bhuog\b': 'huong',
            r'\bkhug\b': 'khung',
            r'\bck\b': 'chuyen khoan',
            r'\btk\b': 'tai khoan',
            r'\bmat\b': 'tien mat',
            r'\btm\b': 'tien mat',
        }
        for pat, rep in typos.items():
            t = re.sub(pat, rep, t)
        return t

    @staticmethod
    def parse_amount(text: str) -> Optional[int]:
        text = text.lower().replace(",", ".").strip()
        
        # Match '1tr2' -> 1,200,000 or '1tr5' -> 1,500,000
        m = re.search(r'(\d+)\s*(?:tr|triệu)\s*(\d+)', text)
        if m:
            main_part = int(m.group(1)) * 1_000_000
            sub_str = m.group(2)
            if len(sub_str) == 1:
                sub_part = int(sub_str) * 100_000
            elif len(sub_str) == 2:
                sub_part = int(sub_str) * 10_000
            else:
                sub_part = int(sub_str)
            return main_part + sub_part

        # Match '1.5tr', '1.5 triệu', '2tr', '2 m'
        m = re.search(r'(\d+(?:\.\d+)?)\s*(?:tr|triệu|m)\b', text)
        if m:
            return int(float(m.group(1)) * 1_000_000)

        # Match '500k', '70 k'
        m = re.search(r'(\d+(?:\.\d+)?)\s*k\b', text)
        if m:
            return int(float(m.group(1)) * 1_000)

        # Match full number with dots or plain: '70.000', '70000', '1.500.000'
        m = re.search(r'(\d{1,3}(?:\.\d{3})+|\d{4,9})', text)
        if m:
            num_clean = m.group(1).replace(".", "")
            return int(num_clean)

        return None

    @classmethod
    def parse(cls, text: str) -> Optional[Dict[str, Any]]:
        raw_text = text.strip()
        text_lower = raw_text.lower()
        text_norm = cls.normalize_typos(text_lower)
        text_unaccent = remove_accents(text_norm)

        # Determine type
        tx_type = None
        if (text_lower.startswith("+") or 
            " thu " in f" {text_lower} " or 
            text_lower.startswith("thu ") or 
            "khách trả" in text_lower or 
            "khach tra" in text_unaccent or
            "benh nhan tra" in text_unaccent):
            tx_type = "thu"
        elif (text_lower.startswith("-") or 
              " chi " in f" {text_lower} " or 
              text_lower.startswith("chi ") or 
              "trả tiền" in text_lower or 
              "mua " in text_lower or
              "tra tien" in text_unaccent):
            tx_type = "chi"
        else:
            tx_type = "chi" if any(w in text_unaccent for w in ["mua", "tra", "tieu", "het", "chi"]) else "thu"

        # Extract amount
        amount = cls.parse_amount(text_lower)
        if not amount:
            return None

        # Determine payment method
        payment_method = "cash"
        if any(w in text_lower for w in ["ck", "chuyển khoản", "chuyen khoan", "tk", "ngân hàng", "bank"]):
            payment_method = "transfer"

        # Check learned rules first
        category = None
        for lr in rules_mgr.rules.get("learned_rules", []):
            kw_norm = remove_accents(lr["keyword"].lower())
            if kw_norm in text_unaccent or lr["keyword"].lower() in text_lower:
                category = lr["category"]
                if not tx_type:
                    tx_type = lr["type"]
                break

        # Check standard categories
        if not category:
            cat_list = rules_mgr.rules.get("categories", {}).get(tx_type, [])
            for cat in cat_list:
                for kw in cat.get("keywords", []):
                    kw_clean = remove_accents(kw.lower())
                    if kw_clean in text_unaccent or kw.lower() in text_lower:
                        category = cat["name"]
                        break
                if category:
                    break


        if not category:
            category = "Doanh thu Dịch vụ" if tx_type == "thu" else "Chi khác"

        # Clean description
        desc = raw_text
        for prefix in ["+", "-", "thu ", "chi "]:
            if desc.lower().startswith(prefix):
                desc = desc[len(prefix):].strip()
        # Remove matched amount part from description for cleaner display
        desc = re.sub(r'\b\d+(?:[\.,]\d+)?\s*(?:k|tr|triệu|m|vnd|đ)?\b', '', desc, flags=re.IGNORECASE).strip()
        desc = re.sub(r'\b(ck|tiền mặt|mat|chuyển khoản)\b', '', desc, flags=re.IGNORECASE).strip()
        if not desc:
            desc = category

        return {
            "type": tx_type,
            "amount": amount,
            "category": category,
            "description": desc.strip(" ,-"),
            "payment_method": payment_method,
            "engine": "rule"
        }


class GeminiParser:
    """Gemini AI parser with primary/backup key failover and rule-based fallback."""

    SYSTEM_PROMPT = """Bạn là trợ lý AI chuyên nghiệp phân tích thu chi cho Phòng khám Răng / Nha khoa.
Nhiệm vụ của bạn: Đọc tin nhắn hoặc giao dịch của người quản lý phòng khám và trích xuất thông tin thu/chi thành JSON.

DANH MỤC THU CHUẨN:
- Doanh thu Dịch vụ (Trám răng, nhổ răng, răng sứ, niềng răng, implant, cạo vôi, tẩy trắng, khám...)
- Thu khác

DANH MỤC CHI CHUẨN:
- Chi phí Labo (Đặt làm răng sứ, xưởng labo, hàm giả, mắc cài, máng tẩy)
- Vật tư & Thuốc men (Thuốc tê, găng tay, khẩu trang, bông gòn, composite, kim tiêm, dụng cụ)
- Chi phí Tâm linh & Sinh hoạt (Hoa quả thắp hương, lễ bái, trà, cafe, ăn trưa nhân viên, giấy vệ sinh)
- Chi phí Vận hành & Tiện ích (Mặt bằng, điện nước, internet, rác y tế, bảo trì)
- Lương & Nhân sự (Lương, phụ cấp, hoa hồng, ứng lương bác sĩ/phụ tá)
- Chi khác

QUY TẮC BỔ SUNG ĐÃ HỌC:
{learned_rules}

HÌNH THỨC THANH TOÁN (payment_method):
- "transfer": nếu có nhắc đến ck, chuyển khoản, ngân hàng, bank, tk.
- "cash": tiền mặt (mặc định nếu không nhắc đến ck).

ĐỊNH DẠNG JSON TRẢ VỀ DUY NHẤT:
{{
  "type": "thu" hoặc "chi",
  "amount": số tiền nguyên dương VND (ví dụ: 500k -> 500000, 1.2tr -> 1200000, 70k -> 70000),
  "category": "Tên danh mục phù hợp nhất",
  "description": "Nội dung ngắn gọn",
  "payment_method": "cash" hoặc "transfer"
}}
Chỉ trả về JSON thuần, không kèm markdown hay lời dẫn.
"""

    @classmethod
    def _call_gemini_api(cls, prompt: str, image_b64: Optional[str] = None, mime_type: str = "image/jpeg") -> Optional[str]:
        keys = [GEMINI_API_KEY_PRIMARY, GEMINI_API_KEY_BACKUP]
        models = GEMINI_MODELS

        for key in keys:
            if not key:
                continue
            for model in models:
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
                parts = []
                if image_b64:
                    parts.append({
                        "inline_data": {
                            "mime_type": mime_type,
                            "data": image_b64
                        }
                    })
                parts.append({"text": prompt})

                body = {
                    "contents": [{"parts": parts}],
                    "generationConfig": {
                        "responseMimeType": "application/json",
                        "temperature": 0.1
                    }
                }
                data = json.dumps(body).encode("utf-8")
                req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
                try:
                    with urllib.request.urlopen(req, timeout=9, context=ssl_ctx) as resp:
                        res = json.loads(resp.read().decode("utf-8"))
                        candidates = res.get("candidates", [])
                        if candidates:
                            text = candidates[0]["content"]["parts"][0]["text"].strip()
                            return text
                except urllib.error.HTTPError as e:
                    # 429 = Rate Limit / Quota, 503 = Service Unavailable -> Try next key or model
                    print(f"Gemini API {model} with key {key[:8]} failed: HTTP {e.code}")
                    continue
                except Exception as e:
                    print(f"Gemini API {model} with key {key[:8]} failed: {e}")
                    continue

        return None

    @classmethod
    def parse_text(cls, text: str) -> Optional[Dict[str, Any]]:
        """Parse natural text using Gemini AI with fallback to RuleEngine."""
        # 1. Attempt Gemini AI
        learned_rules_text = rules_mgr.get_learned_rules_text()
        system_instruction = cls.SYSTEM_PROMPT.format(learned_rules=learned_rules_text)
        full_prompt = f"{system_instruction}\n\nTin nhắn người dùng: \"{text}\""

        try:
            ai_resp = cls._call_gemini_api(full_prompt)
            if ai_resp:
                # Clean json if wrapped in ```json
                clean_json = ai_resp.strip()
                if clean_json.startswith("```json"):
                    clean_json = clean_json[7:]
                if clean_json.endswith("```"):
                    clean_json = clean_json[:-3]
                data = json.loads(clean_json.strip())
                if "amount" in data and "type" in data and data["amount"] > 0:
                    data["engine"] = "gemini-ai"
                    return data
        except Exception as e:
            print(f"AI parse error: {e}")

        # 2. Seamless Fallback to Rule-based engine
        print("Falling back to RuleEngine...")
        return RuleEngine.parse(text)

    @classmethod
    def parse_receipt_image(cls, image_bytes: bytes, mime_type: str = "image/jpeg") -> Optional[Dict[str, Any]]:
        """Parse receipt / invoice photo using Gemini Vision."""
        b64 = base64.b64encode(image_bytes).decode("utf-8")
        prompt = """Bạn là trợ lý kế toán phòng khám răng. Hãy nhìn vào ảnh hóa đơn/phiếu thu/biên lai này và trích xuất:
- Tổng số tiền thanh toán (amount)
- Nội dung chi/mua hàng gì (description)
- Danh mục phù hợp nhất (category) trong: Chi phí Labo, Vật tư & Thuốc men, Chi phí Tâm linh & Sinh hoạt, Chi phí Vận hành, Chi khác
- Hình thức: "cash" (tiền mặt) hoặc "transfer" (chuyển khoản)
- Loại: "chi" (hầu hết hóa đơn là chi) hoặc "thu"

Trả về JSON duy nhất:
{
  "type": "chi",
  "amount": 150000,
  "category": "Vật tư & Thuốc men",
  "description": "Mua găng tay y tế",
  "payment_method": "cash"
}"""
        try:
            ai_resp = cls._call_gemini_api(prompt, image_b64=b64, mime_type=mime_type)
            if ai_resp:
                clean_json = ai_resp.strip()
                if clean_json.startswith("```json"):
                    clean_json = clean_json[7:]
                if clean_json.endswith("```"):
                    clean_json = clean_json[:-3]
                data = json.loads(clean_json.strip())
                data["engine"] = "gemini-vision"
                return data
        except Exception as e:
            print(f"Image OCR error: {e}")

        return None
