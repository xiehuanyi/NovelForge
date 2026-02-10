import json
import logging
import os
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

from google import genai

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

PROVIDER_GEMINI = "gemini"
PROVIDER_ZHIPU = "zhipu"


class BaseLLM(ABC):
    def __init__(self, model_id: str, context_length: int, output_length: int):
        self.model_id = model_id
        self.context_length = context_length
        self.output_length = output_length

    @abstractmethod
    def call_text(self, system_prompt: str, user_content: str, temperature: float = 0.5,
                  max_tokens: Optional[int] = None) -> str:
        raise NotImplementedError

    def _get_max_tokens(self, requested: Optional[int]) -> Optional[int]:
        if requested is None:
            return None
        return min(requested, self.output_length)


class GeminiLLM(BaseLLM):
    def __init__(self, model_id: str, context_length: int, output_length: int, client: genai.Client):
        super().__init__(model_id, context_length, output_length)
        self.client = client

    def call_text(self, system_prompt: str, user_content: str, temperature: float = 0.5,
                  max_tokens: Optional[int] = None) -> str:
        prompt = f"{system_prompt}\n\n{user_content}" if system_prompt else user_content
        response = self.client.models.generate_content(
            model=self.model_id,
            contents=prompt,
        )
        return response.text or ""


import threading
import time

try:
    from zhipuai import ZhipuAI
except ImportError:
    ZhipuAI = None
    logger.warning("zhipuai library not installed. Zhipu provider will fail.")

# Global semaphore to strictly limit Zhipu concurrency across all instances
zhipu_semaphore = threading.Semaphore(1)

class ZhipuLLM(BaseLLM):
    def __init__(self, model_id: str, context_length: int, output_length: int, api_key: str):
        super().__init__(model_id, context_length, output_length)
        if not ZhipuAI:
            raise ImportError("zhipuai library required for ZhipuLLM")
        self.client = ZhipuAI(api_key=api_key)

    def call_text(self, system_prompt: str, user_content: str, temperature: float = 0.5,
                  max_tokens: Optional[int] = None) -> str:
        max_tokens = self._get_max_tokens(max_tokens)
        
        # Acquire semaphore to ensure only 1 request happens at a time
        with zhipu_semaphore:
            retries = 3
            last_error = None
            
            for attempt in range(retries):
                try:
                    resp = self.client.chat.completions.create(
                        model=self.model_id,
                        messages=[
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_content},
                        ],
                        temperature=temperature,
                        max_tokens=max_tokens,
                    )
                    return resp.choices[0].message.content or ""
                except Exception as e:
                    # Check for 429 or similar rate limit errors
                    error_str = str(e)
                    if "429" in error_str or "concurrency" in error_str.lower():
                        logger.warning(f"Zhipu Rate Limit hit (Attempt {attempt+1}/{retries}). Waiting...")
                        time.sleep(2 * (attempt + 1))  # Simple backoff: 2s, 4s, 6s
                        last_error = e
                        continue
                    
                    logger.error(f"Zhipu LLM Call Failed ({self.model_id}): {e}")
                    raise e
            
            # If we exhausted retries
            if last_error:
                raise last_error
            return ""


class LLMManager:
    def __init__(self, config_path: str):
        self.config_path = config_path
        self.config = self._load_config()
        self.instances: Dict[str, BaseLLM] = {}
        self.gemini_client = genai.Client(api_key=os.getenv("GEMINI_API_KEY", ""))

    def _load_config(self) -> Dict[str, Any]:
        if not os.path.exists(self.config_path):
            logger.warning("Config file not found. Using empty defaults.")
            return {"models": {}, "default_role_models": {}}
        with open(self.config_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def get_role_model_id(self, role: str) -> str:
        return self.config.get("default_role_models", {}).get(role, "")

    def get_model_config(self, model_id: str) -> Optional[Dict[str, Any]]:
        return self.config.get("models", {}).get(model_id)

    def get_llm(self, model_id: str) -> BaseLLM:
        if model_id in self.instances:
            return self.instances[model_id]

        model_conf = self.get_model_config(model_id) or {
            "provider": PROVIDER_GEMINI,
            "model_id": model_id,
            "context_length": 32768,
            "output_length": 4096,
        }
        provider = model_conf.get("provider", PROVIDER_GEMINI)
        context_len = model_conf.get("context_length", 32768)
        output_len = model_conf.get("output_length", 4096)
        actual_model_id = model_conf.get("model_id", model_id)

        if provider == PROVIDER_ZHIPU:
            key = os.getenv("ZHIPUAI_API_KEY", "")
            if not key:
                raise ValueError("ZHIPUAI_API_KEY not set")
            instance = ZhipuLLM(actual_model_id, context_len, output_len, key)
        elif provider == PROVIDER_GEMINI:
            instance = GeminiLLM(actual_model_id, context_len, output_len, self.gemini_client)
        else:
            raise ValueError(f"Unsupported provider: {provider}")

        self.instances[model_id] = instance
        return instance


class LLMService:
    def __init__(self, config_path: str):
        self.manager = LLMManager(config_path)

    def call_text(self, role: str, system_prompt: str, user_prompt: str, temperature: float = 0.7,
                  max_tokens: Optional[int] = None, model_id: Optional[str] = None) -> str:
        chosen = model_id or self.manager.get_role_model_id(role)
        if not chosen:
            raise RuntimeError(f"No model configured for role: {role}")
        llm = self.manager.get_llm(chosen)
        return llm.call_text(system_prompt, user_prompt, temperature=temperature, max_tokens=max_tokens)
