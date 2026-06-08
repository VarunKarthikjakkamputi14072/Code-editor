from __future__ import annotations

from app.config import settings

# Ordered from coarsest to finest. The splitter tries each separator in turn,
# only moving to the next when a segment is still larger than chunk_size.
_SEPARATORS = ["\n\n", "\n", ". ", "! ", "? ", " ", ""]


def chunk_text(
    text: str,
    size: int = settings.chunk_size,
    overlap: int = settings.chunk_overlap,
) -> list[str]:
    """Recursive character text splitter.

    Splits on paragraph breaks first, then sentence boundaries, then words,
    then characters - ensuring chunks contain complete, coherent thoughts
    rather than arbitrary word-count windows that sever sentences mid-thought.
    """
    return _split(text.strip(), size, overlap, _SEPARATORS)


def _split(text: str, size: int, overlap: int, separators: list[str]) -> list[str]:
    if len(text) <= size:
        return [text] if text else []

    separator = separators[0] if separators else ""
    remaining = separators[1:] if separators else []

    segments = text.split(separator) if separator else list(text)

    chunks: list[str] = []
    current = ""

    for segment in segments:
        piece = (current + separator + segment).lstrip(separator) if current else segment

        if len(piece) <= size:
            current = piece
        else:
            # Flush what we have
            if current:
                chunks.append(current)
                # Build overlap carry-forward from the tail of current chunk
                words = current.split()
                overlap_text = " ".join(words[-overlap:]) if overlap else ""
                current = (overlap_text + separator + segment).lstrip(separator) if overlap_text else segment
            else:
                # Single segment is still too large - recurse with finer separator
                if remaining:
                    chunks.extend(_split(segment, size, overlap, remaining))
                else:
                    # Character-level fallback: hard split with overlap
                    for i in range(0, len(segment), size - overlap):
                        chunks.append(segment[i : i + size])
                current = ""

    if current:
        chunks.append(current)

    return [c for c in chunks if c.strip()]
