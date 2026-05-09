import re


def slugify(name: str, fallback: str = "model", max_len: int = 40) -> str:
    s = name.lower()
    s = re.sub(r'[\s_]+', '-', s)
    s = re.sub(r'[^a-z0-9-]', '', s)
    s = re.sub(r'-+', '-', s).strip('-')
    s = s[:max_len].rstrip('-')
    return s if s else fallback
