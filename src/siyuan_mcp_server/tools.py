import re


def is_siyuan_timestamp(text: str) -> bool:
    """
    判断文本是否为思源时间戳
    
    格式: 14位纯数字 (YYYYMMDDHHMMSS)
    例如: 20250325161145
    """
    pattern = r'^\d{14}$'
    return bool(re.match(pattern, text.strip()))
