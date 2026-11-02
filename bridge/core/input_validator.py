"""
B-004: Input Validator - validates user input before processing.
"""
from __future__ import annotations

import re
from typing import List, Optional, Tuple


class InputValidator:
    MAX_MESSAGE_LENGTH = 10000
    MAX_FILE_SIZE_MB = 50
    ALLOWED_FILE_EXTENSIONS = [
        ".pdf", ".docx", ".doc", ".txt", ".md",
        ".png", ".jpg", ".jpeg", ".gif", ".bmp",
        ".csv", ".xlsx", ".xls", ".json",
        ".py", ".js", ".ts", ".java", ".cpp", ".c",
    ]
    DANGEROUS_PATTERNS = [
        r"import\s+os\b",
        r"import\s+subprocess\b",
        r"import\s+sys\b",
        r"__import__\s*\(",
        r"eval\s*\(",
        r"exec\s*\(",
        r"open\s*\(.+['\"]w",
    ]

    @staticmethod
    def validate_chat_message(content: str) -> Tuple[bool, str]:
        if not content or not content.strip():
            return False, "Message content is empty"
        if len(content) > InputValidator.MAX_MESSAGE_LENGTH:
            return False, f"Message too long (max {InputValidator.MAX_MESSAGE_LENGTH} chars)"
        return True, ""

    @staticmethod
    def validate_file_upload(filename: str, size_bytes: int) -> Tuple[bool, str]:
        ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        if ext not in InputValidator.ALLOWED_FILE_EXTENSIONS:
            return False, f"File type not allowed: {ext}"
        if size_bytes > InputValidator.MAX_FILE_SIZE_MB * 1024 * 1024:
            return False, f"File too large (max {InputValidator.MAX_FILE_SIZE_MB}MB)"
        return True, ""

    @staticmethod
    def validate_code(code: str, language: str = "python") -> Tuple[bool, str]:
        if not code or not code.strip():
            return False, "Code content is empty"
        if len(code) > 50000:
            return False, "Code too long (max 50000 chars)"
        if language == "python":
            for pattern in InputValidator.DANGEROUS_PATTERNS:
                if re.search(pattern, code):
                    return False, f"Potentially unsafe code pattern detected"
        return True, ""

    @staticmethod
    def sanitize_input(text: str) -> str:
        text = text.strip()
        text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', text)
        return text
