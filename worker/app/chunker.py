from app.config import settings


def chunk_text(text: str, size: int = settings.chunk_size, overlap: int = settings.chunk_overlap) -> list[str]:
    """Split text into overlapping word-boundary chunks."""
    words = text.split()
    if not words:
        return []

    chunks: list[str] = []
    start = 0
    while start < len(words):
        end = min(start + size, len(words))
        chunks.append(" ".join(words[start:end]))
        if end == len(words):
            break
        start += size - overlap

    return chunks
