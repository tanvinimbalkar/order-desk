"""Paid Claude or Gemini only. Demo mode never calls a model."""

from __future__ import annotations

import time

from artwork_agent.config import Config, TrialSafetyError


def with_retry(fn, attempts: int = 3, sleep=time.sleep):
    last = None
    for attempt in range(attempts):
        try:
            return fn()
        except Exception as exc:
            last = exc
            if attempt + 1 >= attempts:
                break
            sleep(0.25 * (2**attempt))
    return last


def generate(config: Config, prompt: str, call=None, sleep=time.sleep) -> tuple[str | None, str | None]:
    """Return (text, error). Demo mode returns (None, None) and does not call a model."""
    if config.mode != "trial":
        return None, None
    if not config.llm_paid:
        raise TrialSafetyError("Refusing to send trial data to a free-tier model.")

    def _call():
        if call is not None:
            return call(prompt)
        if config.llm_provider == "claude":
            return _claude(config, prompt)
        return _gemini(config, prompt)

    result = with_retry(_call, sleep=sleep)
    if isinstance(result, Exception):
        return None, "could not process, will retry next sync."
    return result, None


def _gemini(config: Config, prompt: str) -> str:
    from google import genai

    client = genai.Client(api_key=config.llm_api_key)
    response = client.models.generate_content(model=config.llm_model, contents=prompt)
    return getattr(response, "text", None) or ""


def _claude(config: Config, prompt: str) -> str:
    import anthropic

    client = anthropic.Anthropic(api_key=config.llm_api_key)
    response = client.messages.create(
        model=config.llm_model,
        max_tokens=800,
        messages=[{"role": "user", "content": prompt}],
    )
    parts = []
    for block in response.content:
        text = getattr(block, "text", "")
        if text:
            parts.append(text)
    return "\n".join(parts)
