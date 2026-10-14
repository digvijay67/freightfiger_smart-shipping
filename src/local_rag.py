"""Optional local Ollama embeddings, vector retrieval, and grounded explanations.

No model is downloaded automatically. The existing deterministic note matcher is
the safety fallback and remains authoritative for route/date/evidence eligibility.
"""
from __future__ import annotations

import json
import logging
import math
import os
import re
from dataclasses import dataclass
from datetime import date
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from src.note_retriever import retrieve_notes

LOGGER = logging.getLogger(__name__)
WORD = re.compile(r"[A-Za-z0-9]+")
SAFE_CONNECTORS = {
    "a", "an", "and", "as", "at", "because", "by", "during", "for", "from",
    "in", "is", "it", "its", "note", "of", "on", "route", "the", "this", "to",
    "was", "were", "which", "with",
}


@dataclass(frozen=True)
class RagSettings:
    base_url: str = "http://127.0.0.1:11434"
    embedding_model: str = ""
    chat_model: str = ""
    timeout_seconds: float = 8.0
    top_k: int = 3
    minimum_similarity: float = 0.15
    seed: int = 42

    @classmethod
    def from_environment(cls) -> "RagSettings":
        return cls(
            base_url=os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/"),
            embedding_model=os.getenv("OLLAMA_EMBED_MODEL", "").strip(),
            chat_model=os.getenv("OLLAMA_CHAT_MODEL", "").strip(),
            timeout_seconds=_env_float("OLLAMA_TIMEOUT_SECONDS", 8.0, minimum=0.1),
            top_k=_env_int("RAG_TOP_K", 3, minimum=1, maximum=10),
            minimum_similarity=_env_float("RAG_MIN_SIMILARITY", 0.15, minimum=-1.0, maximum=1.0),
            seed=_env_int("OLLAMA_SEED", 42, minimum=0),
        )

    @property
    def configured(self) -> bool:
        return bool(self.embedding_model and self.chat_model)


def _env_float(name: str, default: float, *, minimum: float, maximum: float | None = None) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except ValueError:
        return default
    if not math.isfinite(value) or value < minimum or (maximum is not None and value > maximum):
        return default
    return value


def _env_int(name: str, default: int, *, minimum: int, maximum: int | None = None) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        return default
    if value < minimum or (maximum is not None and value > maximum):
        return default
    return value


def _cosine(left: list[float], right: list[float]) -> float:
    if not left or len(left) != len(right):
        raise ValueError("Ollama returned incompatible embedding dimensions")
    dot = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if not left_norm or not right_norm:
        return 0.0
    return dot / (left_norm * right_norm)


def _words(text: str) -> set[str]:
    return {word.casefold() for word in WORD.findall(text)}


class LocalRagNotes:
    """Per-run local vector index over eligible notes; never controls numeric flags."""

    def __init__(self, settings: RagSettings | None = None):
        self.settings = settings or RagSettings.from_environment()
        self.note_vectors: dict[tuple[str, str], list[float]] = {}
        self.usage = {
            "ollama_chat_calls": 0,
            "ollama_embedding_calls": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "embedding_tokens": None,
        }
        self.diagnostics: dict[str, int] = {}
        self.diagnostic_messages: list[str] = []
        self._embedding_tokens_reported = False

    def _diagnostic(self, code: str, message: str, *, warning: bool = False) -> None:
        self.diagnostics[code] = self.diagnostics.get(code, 0) + 1
        self.diagnostic_messages.append(f"{code}: {message}")
        log = LOGGER.warning if warning else LOGGER.info
        log("RAG status=%s: %s", code, message)

    def _post(self, path: str, payload: dict[str, object]) -> dict[str, object]:
        request = Request(
            f"{self.settings.base_url}{path}",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.settings.timeout_seconds) as response:
                decoded = json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, OSError, UnicodeError, json.JSONDecodeError) as exc:
            underlying = getattr(exc, "reason", None)
            detail = type(underlying).__name__ if underlying is not None else type(exc).__name__
            raise RuntimeError(f"Ollama request failed: {type(exc).__name__} ({detail})") from exc
        if not isinstance(decoded, dict):
            raise RuntimeError("Ollama returned a non-object response")
        return decoded

    def _embed(self, texts: list[str]) -> list[list[float]]:
        self.usage["ollama_embedding_calls"] += 1
        response = self._post("/api/embed", {"model": self.settings.embedding_model, "input": texts})
        embeddings = response.get("embeddings")
        if not isinstance(embeddings, list) or len(embeddings) != len(texts):
            raise RuntimeError("Ollama embedding response has the wrong shape")
        vectors = []
        for vector in embeddings:
            if not isinstance(vector, list) or not vector:
                raise RuntimeError("Ollama returned an empty embedding")
            try:
                parsed = [float(value) for value in vector]
            except (TypeError, ValueError):
                raise RuntimeError("Ollama returned a malformed embedding") from None
            if not all(math.isfinite(value) for value in parsed):
                raise RuntimeError("Ollama embedding contains a non-finite value")
            vectors.append(parsed)
        # Ollama embedding responses do not consistently include token counts.
        if "prompt_eval_count" in response:
            self._embedding_tokens_reported = True
            self.usage["embedding_tokens"] = int(self.usage["embedding_tokens"] or 0) + int(response["prompt_eval_count"])
        return vectors

    def _rank(self, query: str, eligible: list[dict[str, str]]) -> list[tuple[float, dict[str, str]]]:
        missing = [note for note in eligible if (note["note_id"], note["note"]) not in self.note_vectors]
        texts = [query] + [note["note"] for note in missing]
        vectors = self._embed(texts)
        query_vector = vectors[0]
        for note, vector in zip(missing, vectors[1:]):
            self.note_vectors[(note["note_id"], note["note"])] = vector
        ranked = [
            (_cosine(query_vector, self.note_vectors[(note["note_id"], note["note"])]), note)
            for note in eligible
        ]
        return sorted(ranked, key=lambda item: (-item[0], item[1]["note_id"]))

    @staticmethod
    def _validate_generated(payload: object, candidates: list[dict[str, str]]) -> tuple[dict[str, str], str, str]:
        if not isinstance(payload, dict):
            raise ValueError("generated response is not a JSON object")
        note_id = payload.get("note_id")
        explanation = payload.get("explanation")
        quote = payload.get("evidence_quote")
        if not all(isinstance(value, str) for value in (note_id, explanation, quote)):
            raise ValueError("generated response must contain note_id, explanation, and evidence_quote strings")
        note = next((item for item in candidates if item["note_id"] == note_id), None)
        if note is None:
            raise ValueError("generated note ID was not among the retrieved eligible evidence")
        if not quote or quote not in note["note"]:
            raise ValueError("generated evidence quote is not an exact substring of the retrieved note")
        explanation = explanation.strip()
        if not explanation or len(explanation) > 400:
            raise ValueError("generated explanation is empty or too long")
        unsupported_words = _words(explanation) - _words(note["note"]) - SAFE_CONNECTORS
        if unsupported_words:
            raise ValueError("generated explanation contains words absent from its evidence: " + ", ".join(sorted(unsupported_words)))
        return note, explanation, quote

    def explain(self, route: str, week: date, eligible_notes: list[dict[str, str]]) -> dict[str, str] | None:
        """Return a validated model explanation or None for deterministic fallback.

        `eligible_notes` must come from retrieve_notes(), which applies route/date
        and positive/negative evidence rules before vector ranking.
        """
        if not eligible_notes:
            self._diagnostic("unexplained_no_eligible_note", f"no supporting note for {route} {week}")
            return None
        if not self.settings.configured:
            self._diagnostic("fallback_model_not_configured", "set both Ollama model names to enable local RAG")
            return None
        try:
            query = f"Explain the documented cost increase for route {route} in week {week.isoformat()}."
            ranked = self._rank(query, eligible_notes)
            ranked = [item for item in ranked if item[0] >= self.settings.minimum_similarity]
            if not ranked:
                self._diagnostic("fallback_below_similarity_threshold", "no eligible note met the configured similarity threshold")
                return None
            retrieved = [note for _, note in ranked[:self.settings.top_k]]
            evidence = [{"note_id": n["note_id"], "date": n["date"], "note": n["note"]} for n in retrieved]
            self.usage["ollama_chat_calls"] += 1
            response = self._post("/api/chat", {
                "model": self.settings.chat_model,
                "stream": False,
                "format": "json",
                "messages": [
                    {"role": "system", "content": (
                        "Write one brief explanation using only the supplied notes. "
                        "Return JSON with note_id, explanation, evidence_quote. The quote must be copied "
                        "exactly from that note. Do not add causes, dates, routes, amounts, or claims not stated there."
                    )},
                    {"role": "user", "content": json.dumps({"route": route, "week_of": week.isoformat(), "eligible_notes": evidence}, ensure_ascii=False)},
                ],
                "options": {"temperature": 0, "seed": self.settings.seed},
            })
            self.usage["input_tokens"] += int(response.get("prompt_eval_count", 0) or 0)
            self.usage["output_tokens"] += int(response.get("eval_count", 0) or 0)
            message = response.get("message")
            if not isinstance(message, dict) or not isinstance(message.get("content"), str):
                raise ValueError("Ollama chat response has no text content")
            generated = json.loads(message["content"])
            note, explanation, quote = self._validate_generated(generated, retrieved)
            self._diagnostic("rag_grounded_success", f"retrieved and validated note {note['note_id']} for {route} {week}")
            return {"note_id": note["note_id"], "explanation": explanation, "evidence_quote": quote}
        except (RuntimeError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
            self._diagnostic("fallback_rag_failure", str(exc), warning=True)
            return None

    def note_candidates(self, route: str, week: date, notes: list[dict[str, str]]) -> list[dict[str, str]]:
        """Apply hard route/date/support constraints before semantic ranking."""
        return retrieve_notes(route, week, notes)


def summarize_usage(services: list["LocalRagNotes"]) -> dict[str, object]:
    """Aggregate actual API-reported usage and observable fallback counts."""
    total: dict[str, object] = {
        "ollama_chat_calls": 0,
        "ollama_embedding_calls": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "embedding_tokens": 0,
        "embedding_tokens_reported": True,
        "diagnostics": {},
        "diagnostic_messages": [],
        "chat_models": sorted({service.settings.chat_model for service in services if service.settings.chat_model}),
        "embedding_models": sorted({service.settings.embedding_model for service in services if service.settings.embedding_model}),
    }
    for service in services:
        for key in ("ollama_chat_calls", "ollama_embedding_calls", "input_tokens", "output_tokens"):
            total[key] += service.usage[key]
        if service.usage["embedding_tokens"] is None:
            total["embedding_tokens_reported"] = False
        else:
            total["embedding_tokens"] += service.usage["embedding_tokens"]
        for code, count in service.diagnostics.items():
            diagnostics = total["diagnostics"]
            diagnostics[code] = diagnostics.get(code, 0) + count
        total["diagnostic_messages"].extend(service.diagnostic_messages)
    if not total["embedding_tokens_reported"]:
        total["embedding_tokens"] = None
    return total
