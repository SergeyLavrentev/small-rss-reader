import hashlib

def compute_article_id(entry: dict) -> str:
    unique_string = entry.get('id') or entry.get('guid') or entry.get('link') or (entry.get('title', '') + entry.get('published', ''))
    return hashlib.md5(unique_string.encode('utf-8')).hexdigest()
