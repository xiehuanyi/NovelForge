"""LLM client with OpenAI-compatible API (targeting qwen3.5-flash via DashScope).

Design notes:
  - Single model, single client — keeps things simple.
  - Supports streaming and thinking mode.
  - Automatic retry with exponential backoff for transient errors.
"""

from __future__ import annotations

import time
import logging
from dataclasses import dataclass
from typing import Generator, Optional

from openai import OpenAI

from novelforge.core.config import LLMConfig

logger = logging.getLogger(__name__)


@dataclass
class LLMResponse:
    """Structured response from LLM, separating thinking from content."""
    content: str
    thinking: str = ""
    input_tokens: int = 0
    output_tokens: int = 0


class LLMClient:
    """Thin wrapper around OpenAI-compatible API.

    Architecture choice: we use a single shared client rather than per-agent
    clients because all agents use the same model. This mirrors how Claude Code
    manages its LLM calls — through a centralized service with role-based
    prompt injection, not role-based model selection.
    """

    def __init__(self, config: LLMConfig):
        self.config = config
        self.client = OpenAI(api_key=config.api_key, base_url=config.base_url)
        self.total_input_tokens = 0
        self.total_output_tokens = 0

    # -- Synchronous call (blocking) ------------------------------------------

    def chat(
        self,
        system: str,
        user: str,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        enable_thinking: Optional[bool] = None,
    ) -> LLMResponse:
        """Send a chat request and return the full response.

        Retries up to 3 times on transient errors (rate limits, timeouts).
        """
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": user})

        thinking = enable_thinking if enable_thinking is not None else self.config.enable_thinking
        max_tok = max_tokens or self.config.max_tokens

        for attempt in range(3):
            try:
                resp = self.client.chat.completions.create(
                    model=self.config.model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tok,
                    extra_body={"enable_thinking": thinking},
                )
                choice = resp.choices[0]
                content = choice.message.content or ""
                think_text = ""
                if hasattr(choice.message, "reasoning_content"):
                    think_text = choice.message.reasoning_content or ""

                usage = resp.usage
                inp = usage.prompt_tokens if usage else 0
                out = usage.completion_tokens if usage else 0
                self.total_input_tokens += inp
                self.total_output_tokens += out

                return LLMResponse(
                    content=content,
                    thinking=think_text,
                    input_tokens=inp,
                    output_tokens=out,
                )
            except Exception as e:
                if attempt < 2 and _is_retriable(e):
                    wait = 2 ** (attempt + 1)
                    logger.warning("LLM call failed (attempt %d), retrying in %ds: %s", attempt + 1, wait, e)
                    time.sleep(wait)
                    continue
                raise

        # Should not reach here, but just in case
        return LLMResponse(content="")

    # -- Streaming call --------------------------------------------------------

    def chat_stream(
        self,
        system: str,
        user: str,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        enable_thinking: Optional[bool] = None,
    ) -> Generator[tuple[str, str], None, None]:
        """Stream a chat response. Yields (type, text) tuples.

        type is either "thinking" or "content".
        """
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": user})

        thinking = enable_thinking if enable_thinking is not None else self.config.enable_thinking
        max_tok = max_tokens or self.config.max_tokens

        stream = self.client.chat.completions.create(
            model=self.config.model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tok,
            extra_body={"enable_thinking": thinking},
            stream=True,
        )

        for chunk in stream:
            delta = chunk.choices[0].delta
            if hasattr(delta, "reasoning_content") and delta.reasoning_content:
                yield ("thinking", delta.reasoning_content)
            if hasattr(delta, "content") and delta.content:
                yield ("content", delta.content)


def _is_retriable(error: Exception) -> bool:
    """Check if an error is transient and worth retrying."""
    msg = str(error).lower()
    return any(kw in msg for kw in ("429", "rate", "timeout", "connection", "server"))
