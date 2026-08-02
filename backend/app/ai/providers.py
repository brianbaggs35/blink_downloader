"""One AIProvider interface, four backends.

Every provider takes the same request (keyframes + context) and returns the
same structured result (summary, suspicion, detected entities). Providers
that support native structured/JSON-schema output (OpenAI, Anthropic,
Ollama) get it; Moondream's REST API has no such mode, so its provider
prompts for parseable JSON text and degrades honestly if parsing fails,
rather than pretending feature parity it doesn't have.

"Local" and "cloud" variants of Ollama/Moondream are the same wire protocol
at a different base_url - never a different code path - matching how the
app already treats Ollama as "some HTTP server the operator points us at",
never something this app runs itself.
"""

# ollama ships no type stubs, and the multimodal message payloads we build
# for OpenAI/Anthropic are runtime-correct (their own documented wire
# format) but don't structurally match their strict TypedDict unions once
# built up dynamically from a shared list-of-dicts helper — the same class
# of third-party-stub friction as blinkpy in app/blink/service.py.
# pyright: reportMissingTypeStubs=false
# pyright: reportUnknownMemberType=false

import base64
import json
from dataclasses import dataclass, field
from typing import Any, Protocol, cast

import httpx
from anthropic import AsyncAnthropic
from ollama import AsyncClient as AsyncOllamaClient
from openai import AsyncOpenAI

from app.ai.models import AIProviderKind
from app.logs import get_logger

logger = get_logger(__name__)

DEFAULT_MOONDREAM_CLOUD_URL = "https://api.moondream.ai/v1"
DEFAULT_MOONDREAM_LOCAL_URL = "http://localhost:2020/v1"
DEFAULT_OLLAMA_LOCAL_URL = "http://localhost:11434"
DEFAULT_OLLAMA_CLOUD_URL = "https://ollama.com"

REQUEST_TIMEOUT_SECONDS = 90.0


class AIProviderError(Exception):
    """A provider call failed — network, auth, rate limit, or a response we
    couldn't parse into the expected shape."""


@dataclass
class DetectedEntityResult:
    type: str
    confidence: float
    label: str
    bbox: tuple[float, float, float, float] | None = None  # normalized x, y, w, h
    recognized_person_id: str | None = None
    """Set locally, after the VLM call, when this entity's label was
    upgraded from generic to an enrolled person's name (see
    app.ai.pipeline._upgrade_person_labels). The VLM itself never sets or
    sees this - it has no concept of enrolled people."""


@dataclass
class AnalysisRequest:
    """images are JPEG bytes, already selected/resized by the pipeline."""

    images: list[bytes]
    camera_context: str | None = None
    baseline_context: str | None = None
    feedback_examples: list[str] = field(default_factory=list[str])
    detect_people_for_proximity: bool = False
    vehicle_description: str | None = None
    """The protected vehicle's own description (e.g. "Blue Honda Civic"), set
    alongside detect_people_for_proximity - lets the model tell the protected
    vehicle apart from any other vehicle that might also be in frame, instead
    of just being told a vehicle exists somewhere in the shot."""
    prior_tier_summary: str | None = None
    """Set only on a tier-2 escalation call: the cheaper tier's own summary
    and score, so the stronger model refines rather than starts blind."""


@dataclass
class AnalysisResult:
    summary: str
    suspicion_score: float
    entities: list[DetectedEntityResult]
    input_tokens: int
    output_tokens: int


class AIProvider(Protocol):
    async def analyze(self, request: AnalysisRequest) -> AnalysisResult: ...

    async def test_connection(self) -> None:
        """Raise AIProviderError if the provider can't be reached/authed."""
        ...


RESULT_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "summary": {
            "type": "string",
            "description": "One or two plain-English sentences describing what's happening.",
        },
        "suspicion_score": {
            "type": "number",
            "description": "0.0 (completely routine) to 1.0 (highly suspicious).",
        },
        "entities": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "type": {
                        "type": "string",
                        "enum": ["person", "vehicle", "animal", "package", "unknown"],
                    },
                    "label": {
                        "type": "string",
                        "description": "Short human label, e.g. 'delivery driver'.",
                    },
                    "confidence": {"type": "number"},
                    "bbox": {
                        "type": ["array", "null"],
                        "description": (
                            "[x, y, w, h] normalized 0-1 to the frame, tightest box around the "
                            "entity's full body/extent. Required for every person when asked to "
                            "locate people; null otherwise."
                        ),
                        "items": {"type": "number"},
                    },
                },
                "required": ["type", "label", "confidence", "bbox"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["summary", "suspicion_score", "entities"],
    "additionalProperties": False,
}


def build_prompt(request: AnalysisRequest) -> str:
    parts = [
        (
            "You are a home security analyst reviewing keyframes extracted from one "
            "short security camera clip, in chronological order. Describe what is "
            "happening and assess how suspicious it is."
        ),
    ]
    if request.camera_context:
        parts.append(f"This camera's context (set by the homeowner): {request.camera_context}")
    if request.baseline_context:
        parts.append(f"What this camera normally sees: {request.baseline_context}")
    if request.prior_tier_summary:
        parts.append(
            "A faster preliminary pass found this and flagged it for a closer look: "
            f"{request.prior_tier_summary}. Confirm, refine, or correct this assessment."
        )
    if request.feedback_examples:
        examples = "\n".join(f"- {ex}" for ex in request.feedback_examples)
        parts.append(f"This household previously corrected similar clips:\n{examples}")
    if request.detect_people_for_proximity:
        vehicle_ref = (
            f"a {request.vehicle_description}" if request.vehicle_description else "a vehicle"
        )
        parts.append(
            f"The homeowner's protected vehicle ({vehicle_ref}) is visible in this "
            "camera's frame — use that description to tell it apart from any other "
            "vehicle that might also be in the shot. For every person detected, "
            "include a tight bounding box around their full body (needed to measure "
            "distance from the protected vehicle) — this is required, not optional, "
            "for person entities."
        )
    parts.append(
        "Routine activity (the household coming and going, mail/deliveries, "
        "pets, parked cars) should score low. Reserve high scores for genuinely "
        "unusual activity: lingering, attempting entry, prowling, or anything "
        "out of place for this camera and time. Respond with the structured "
        "result only."
    )
    return "\n\n".join(parts)


def _encode_jpeg_data_uri(image: bytes) -> str:
    return f"data:image/jpeg;base64,{base64.b64encode(image).decode('ascii')}"


def _parse_entities(raw: list[dict[str, Any]]) -> list[DetectedEntityResult]:
    entities: list[DetectedEntityResult] = []
    for item in raw:
        bbox_raw = item.get("bbox")
        bbox = tuple(float(v) for v in bbox_raw) if bbox_raw else None
        entities.append(
            DetectedEntityResult(
                type=str(item.get("type", "unknown")),
                confidence=float(item.get("confidence", 0.0)),
                label=str(item.get("label", "")),
                bbox=bbox,  # type: ignore[arg-type]
            )
        )
    return entities


class OpenAIProvider:
    def __init__(self, model: str, api_key: str, base_url: str | None = None) -> None:
        self._model = model
        self._client = AsyncOpenAI(
            api_key=api_key, base_url=base_url, timeout=REQUEST_TIMEOUT_SECONDS
        )

    async def analyze(self, request: AnalysisRequest) -> AnalysisResult:
        content: list[dict[str, Any]] = [{"type": "text", "text": build_prompt(request)}]
        content.extend(
            {
                "type": "image_url",
                "image_url": {"url": _encode_jpeg_data_uri(image), "detail": "high"},
            }
            for image in request.images
        )
        try:
            response = await self._client.chat.completions.create(
                model=self._model,
                messages=cast("Any", [{"role": "user", "content": content}]),
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": "clip_analysis",
                        "schema": RESULT_JSON_SCHEMA,
                        "strict": True,
                    },
                },
                # max_completion_tokens, never max_tokens: GPT-5-class models
                # reject max_tokens outright, while GPT-4-class models accept
                # max_completion_tokens as its documented replacement - so
                # this one kwarg is correct for every model, unconditionally.
                max_completion_tokens=1024,
            )
        except Exception as exc:
            raise AIProviderError(f"OpenAI request failed: {exc}") from exc

        message = response.choices[0].message.content
        if not message:
            raise AIProviderError("OpenAI returned an empty response.")
        try:
            parsed = json.loads(message)
        except json.JSONDecodeError as exc:
            raise AIProviderError(f"OpenAI returned unparseable JSON: {exc}") from exc

        usage = response.usage
        return AnalysisResult(
            summary=str(parsed["summary"]),
            suspicion_score=float(parsed["suspicion_score"]),
            entities=_parse_entities(parsed.get("entities", [])),
            input_tokens=usage.prompt_tokens if usage else 0,
            output_tokens=usage.completion_tokens if usage else 0,
        )

    async def test_connection(self) -> None:
        try:
            await self._client.models.list()
        except Exception as exc:
            raise AIProviderError(f"Could not reach OpenAI: {exc}") from exc


class AnthropicProvider:
    _TOOL_NAME = "report_clip_analysis"

    def __init__(self, model: str, api_key: str, base_url: str | None = None) -> None:
        self._model = model
        self._client = AsyncAnthropic(
            api_key=api_key, base_url=base_url, timeout=REQUEST_TIMEOUT_SECONDS
        )

    async def analyze(self, request: AnalysisRequest) -> AnalysisResult:
        content: list[dict[str, Any]] = [{"type": "text", "text": build_prompt(request)}]
        content.extend(
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/jpeg",
                    "data": base64.b64encode(image).decode("ascii"),
                },
            }
            for image in request.images
        )
        try:
            response = await self._client.messages.create(
                model=self._model,
                max_tokens=1024,
                messages=cast("Any", [{"role": "user", "content": content}]),
                tools=[
                    {
                        "name": self._TOOL_NAME,
                        "description": "Report the structured result of analyzing the clip.",
                        "input_schema": RESULT_JSON_SCHEMA,
                        "strict": True,
                    }
                ],
                tool_choice={"type": "tool", "name": self._TOOL_NAME},
            )
        except Exception as exc:
            raise AIProviderError(f"Anthropic request failed: {exc}") from exc

        tool_use = next((block for block in response.content if block.type == "tool_use"), None)
        if tool_use is None:
            raise AIProviderError("Anthropic did not return the expected tool call.")
        # tool_use.input is typed Dict[str, object]; our own schema guarantees
        # the actual shape (strict=True), so Any is fine for our own parsing.
        parsed = cast("dict[str, Any]", tool_use.input)

        return AnalysisResult(
            summary=str(parsed["summary"]),
            suspicion_score=float(parsed["suspicion_score"]),
            entities=_parse_entities(parsed.get("entities", [])),
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
        )

    async def test_connection(self) -> None:
        try:
            await self._client.models.list(limit=1)
        except Exception as exc:
            raise AIProviderError(f"Could not reach Anthropic: {exc}") from exc


class OllamaProvider:
    """Local or Cloud - same wire protocol, api_key only set for Cloud."""

    def __init__(self, model: str, base_url: str, api_key: str | None = None) -> None:
        self._model = model
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else None
        self._client = AsyncOllamaClient(
            host=base_url, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS
        )

    async def analyze(self, request: AnalysisRequest) -> AnalysisResult:
        try:
            response = await self._client.chat(
                model=self._model,
                messages=[
                    {"role": "user", "content": build_prompt(request), "images": request.images}
                ],
                format=RESULT_JSON_SCHEMA,
                options={"num_predict": 1024},
            )
        except Exception as exc:
            raise AIProviderError(f"Ollama request failed: {exc}") from exc

        raw_content = response.message.content
        if not raw_content:
            raise AIProviderError("Ollama returned an empty response.")
        try:
            parsed = json.loads(raw_content)
        except json.JSONDecodeError as exc:
            raise AIProviderError(f"Ollama returned unparseable JSON: {exc}") from exc

        return AnalysisResult(
            summary=str(parsed["summary"]),
            suspicion_score=float(parsed["suspicion_score"]),
            entities=_parse_entities(parsed.get("entities", [])),
            input_tokens=response.prompt_eval_count or 0,
            output_tokens=response.eval_count or 0,
        )

    async def test_connection(self) -> None:
        try:
            await self._client.list()
        except Exception as exc:
            raise AIProviderError(f"Could not reach Ollama: {exc}") from exc

    async def list_models(self) -> list[str]:
        """The models this Ollama server actually has pulled/available - lets
        the settings UI offer a real, always-accurate picker instead of a
        static guess, unlike the fixed-catalog providers."""
        try:
            response = await self._client.list()
        except Exception as exc:
            raise AIProviderError(f"Could not list Ollama models: {exc}") from exc
        return [str(item.model) for item in response.models]


class MoondreamProvider:
    """Local (Station) or Cloud - same /v1/query shape, api_key only for Cloud.

    Moondream's REST API takes a single image and has no structured-output
    mode, unlike the other three providers - it's a small, fast model built
    for lightweight captioning, not multi-image structured extraction. We
    ask for parseable JSON text on the single most representative keyframe
    and degrade to a plain-summary fallback if parsing fails, rather than
    silently pretending it has capabilities it doesn't.
    """

    def __init__(
        self,
        model: str,
        base_url: str,
        api_key: str | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._client = client or httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS)

    def _auth_headers(self) -> dict[str, str]:
        return {"X-Moondream-Auth": self._api_key} if self._api_key else {}

    async def analyze(self, request: AnalysisRequest) -> AnalysisResult:
        if not request.images:
            raise AIProviderError("No keyframes to analyze.")
        keyframe = request.images[len(request.images) // 2]
        prompt = (
            build_prompt(request)
            + "\n\nRespond with ONLY a single JSON object matching this shape, no other text: "
            + json.dumps(RESULT_JSON_SCHEMA["properties"])
        )
        payload = {
            "model": self._model,
            "image_url": _encode_jpeg_data_uri(keyframe),
            "question": prompt,
        }
        try:
            response = await self._client.post(
                f"{self._base_url}/query", json=payload, headers=self._auth_headers()
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise AIProviderError(f"Moondream request failed: {exc}") from exc

        body = response.json()
        answer = body.get("answer", "")
        try:
            parsed = json.loads(answer)
            summary = str(parsed["summary"])
            suspicion = float(parsed["suspicion_score"])
            entities = _parse_entities(parsed.get("entities", []))
        # json.JSONDecodeError is a ValueError subclass, already covered below.
        except (KeyError, TypeError, ValueError):  # fmt: skip
            logger.warning("moondream.unstructured_response", answer=answer[:200])
            summary = answer or "Moondream did not return a usable description."
            suspicion = 0.0
            entities = []

        metrics = body.get("metrics", {})
        return AnalysisResult(
            summary=summary,
            suspicion_score=suspicion,
            entities=entities,
            input_tokens=int(metrics.get("input_tokens", 0)),
            output_tokens=int(metrics.get("output_tokens", 0)),
        )

    async def test_connection(self) -> None:
        try:
            response = await self._client.post(
                f"{self._base_url}/query",
                json={
                    "model": self._model,
                    "image_url": _TEST_PIXEL_DATA_URI,
                    "question": "test",
                },
                headers=self._auth_headers(),
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise AIProviderError(f"Could not reach Moondream: {exc}") from exc


# A single opaque black pixel, valid JPEG — enough for providers' connection
# tests to exercise a real round trip without needing a real photo.
_TEST_PIXEL_DATA_URI = (
    "data:image/jpeg;base64,/9j/4AAQSkZJRgABAQEAYABgAAD/2wBDAAMCAgICAgMCAgIDAwMDBAYEBAQEBAgGBgUGCQgKCgkI"
    "CQkKDA8MCgsOCwkJDRENDg8QEBEQCgwSExIQEw8QEBD/wAALCAABAAEBAREA/8QAFAABAAAAAAAAAAAAAAAAAAAACf/EABQQAQAA"
    "AAAAAAAAAAAAAAAAAAD/2gAIAQEAAD8AVN//2Q=="
)


def _require_api_key(provider_name: str, api_key: str | None) -> str:
    if not api_key:
        raise AIProviderError(f"{provider_name} requires an API key.")
    return api_key


def build_provider(
    kind: AIProviderKind, model: str, api_key: str | None, base_url: str | None
) -> AIProvider:
    if kind is AIProviderKind.OPENAI:
        return OpenAIProvider(model, _require_api_key("OpenAI", api_key), base_url)
    if kind is AIProviderKind.ANTHROPIC:
        return AnthropicProvider(model, _require_api_key("Anthropic", api_key), base_url)
    if kind is AIProviderKind.OLLAMA:
        return OllamaProvider(model, base_url or DEFAULT_OLLAMA_LOCAL_URL)
    if kind is AIProviderKind.OLLAMA_CLOUD:
        return OllamaProvider(
            model, base_url or DEFAULT_OLLAMA_CLOUD_URL, _require_api_key("Ollama Cloud", api_key)
        )
    if kind is AIProviderKind.MOONDREAM:
        return MoondreamProvider(model, base_url or DEFAULT_MOONDREAM_LOCAL_URL)
    if kind is AIProviderKind.MOONDREAM_CLOUD:
        return MoondreamProvider(
            model,
            base_url or DEFAULT_MOONDREAM_CLOUD_URL,
            _require_api_key("Moondream Cloud", api_key),
        )
    msg = f"Unsupported provider: {kind}"
    raise AIProviderError(msg)
