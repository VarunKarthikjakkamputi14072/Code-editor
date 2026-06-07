import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from app.config import settings


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
async def embed(text: str) -> list[float]:
    async with httpx.AsyncClient(base_url=settings.ollama_base_url, timeout=60) as client:
        resp = await client.post("/api/embeddings", json={"model": settings.embed_model, "prompt": text})
        resp.raise_for_status()
        return resp.json()["embedding"]


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
async def generate(prompt: str, context_chunks: list[str]) -> str:
    system = (
        "You are a helpful assistant. Answer the question using ONLY the provided context. "
        "If the context is insufficient, say so clearly."
    )
    context_text = "\n\n---\n\n".join(context_chunks)
    full_prompt = (
        f"Context:\n{context_text}\n\n"
        f"Question: {prompt}\n\n"
        f"Answer:"
    )
    async with httpx.AsyncClient(
        base_url=settings.ollama_base_url,
        timeout=settings.generation_timeout,
    ) as client:
        resp = await client.post(
            "/api/generate",
            json={"model": settings.gen_model, "prompt": full_prompt, "system": system, "stream": False},
        )
        resp.raise_for_status()
        return resp.json()["response"].strip()
