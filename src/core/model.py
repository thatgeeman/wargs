import os

from dotenv import load_dotenv
from openai import APITimeoutError, OpenAI

from ..config import Config

load_dotenv()  # Load environment variables from .env file

assert "OPENAI_API_KEY" in os.environ, (
    "OPENAI_API_KEY is not set in the environment variables."
)
assert "OPENAI_BASE_URL" in os.environ, (
    "OPENAI_BASE_URL is not set in the environment variables."
)

cfg = Config()
logger = cfg.get_logger("ModelLogger")


class ModelConfig:
    def __init__(self):
        self.api_key = os.environ.get("OPENAI_API_KEY")
        self.base_url = os.environ.get("OPENAI_BASE_URL")


class Model(ModelConfig):
    def __init__(
        self,
        model_name: str = "google/gemma-3-27b-it",
        system_prompt: str = "",
        temperature: float = 0.7,
        max_tokens: int = 1500,
        reasoning_effort: str = "medium",
    ):
        super().__init__()
        self.model_name = model_name
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.system_prompt = system_prompt
        self.reasoning_effort = reasoning_effort
        # Retries are handled at the agent level, so disable the SDK's internal
        # retry loop — otherwise each "attempt" is silently 3x the configured timeout.
        self.client = OpenAI(
            api_key=self.api_key, base_url=self.base_url, max_retries=0
        )
        self.timeout_s = 60

    def call(self, prompt: str, output_schema: dict = None):
        if output_schema:
            logger.debug(
                f"Calling model '{self.model_name}' with output schema: {output_schema}"
            )
        response = None
        messages = []
        if self.system_prompt:
            messages.append({"role": "system", "content": self.system_prompt})
        else:
            logger.warning("No system prompt provided. Proceeding without it.")
        messages.append({"role": "user", "content": prompt})

        try:
            response = self.client.chat.completions.create(
                model=self.model_name,
                messages=messages,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
                reasoning_effort=self.reasoning_effort,
                response_format=output_schema,
                timeout=self.timeout_s,
            )
        except APITimeoutError:
            logger.error(f"Model (OpenAI) call timed out (max: {self.timeout_s})")
            raise
        except Exception as e:
            logger.error(f"Model call exception: {e}")
            raise e
        return response


if __name__ == "__main__":
    model = Model()
    prompt = "Write a short poem about the beauty of nature."
    response = model.call(prompt)
    print(response.choices[0].message.content)
