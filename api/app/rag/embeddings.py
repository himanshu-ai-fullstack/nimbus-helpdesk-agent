import hashlib
import math
import re
from typing import Protocol

import numpy as np
from openai import AsyncOpenAI


class Embedder(Protocol):
    dim: int

    async def embed(self, texts: list[str]) -> list[np.ndarray]: ...


class OpenAIEmbedder:
    def __init__(self, api_key: str, model: str, dim: int, batch_size: int = 128):
        self._client = AsyncOpenAI(api_key=api_key)
        self._model = model
        self.dim = dim
        self._batch_size = batch_size

    async def embed(self, texts: list[str]) -> list[np.ndarray]:
        out: list[np.ndarray] = []
        for i in range(0, len(texts), self._batch_size):
            batch = texts[i : i + self._batch_size]
            resp = await self._client.embeddings.create(
                model=self._model, input=batch, dimensions=self.dim
            )
            out.extend(np.array(d.embedding, dtype=np.float32) for d in resp.data)
        return out


class HashEmbedder:
    """Deterministic bag-of-words embedder. No network, so tests and offline dev
    still exercise the real pgvector queries; shared words give nearby vectors."""

    def __init__(self, dim: int):
        self.dim = dim

    async def embed(self, texts: list[str]) -> list[np.ndarray]:
        return [self._embed_one(t) for t in texts]

    def _embed_one(self, text: str) -> np.ndarray:
        vec = np.zeros(self.dim, dtype=np.float32)
        for token in re.findall(r"[a-z0-9]+", text.lower()):
            h = int.from_bytes(hashlib.blake2b(token.encode(), digest_size=8).digest(), "big")
            vec[h % self.dim] += 1.0
        norm = math.sqrt(float(vec @ vec)) or 1.0
        return vec / norm


def build_embedder(kind: str, api_key: str, model: str, dim: int) -> Embedder:
    if kind == "hash":
        return HashEmbedder(dim)
    return OpenAIEmbedder(api_key, model, dim)
