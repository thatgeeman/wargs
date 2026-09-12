import os

from dotenv import load_dotenv
from openai import APIStatusError, APITimeoutError, OpenAI

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
        model_name: str = "google/gemma-4-31B-it",
        system_prompt: str = "",
        temperature: float = 0,
        max_tokens: int = 4096,
        reasoning_effort: str = None,
    ):
        super().__init__()
        self.model_name = model_name
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.system_prompt = system_prompt
        self.reasoning_effort = reasoning_effort
        # Retries are handled at the agent level, so disable the SDK's internal
        # retry loop — otherwise each "attempt" is silently 3x the configured timeout.
        self.timeout_s = 300
        self.client = OpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
            max_retries=0,
            timeout=self.timeout_s,
        )

    def call(self, prompt: str, output_schema: dict = None):
        wait_time = 10  # s time to wait if no rettry after provided
        if output_schema:
            logger.debug(
                f"Calling model '{self.model_name}' with output schema: {output_schema}"
            )
        response = None
        extra_response = {}
        messages = []
        if self.system_prompt:
            messages.append({"role": "system", "content": self.system_prompt})
        else:
            logger.warning("No system prompt provided. Proceeding without it.")
        messages.append({"role": "user", "content": prompt})

        try:
            request = {
                "model": self.model_name,
                "messages": messages,
                "temperature": self.temperature,
                "max_tokens": self.max_tokens,
                "response_format": output_schema,
            }
            if self.reasoning_effort:
                # off by default: reasoning channels can starve the structured
                # output (model answers in 'reasoning', emits '{}' in 'content')
                request["reasoning_effort"] = self.reasoning_effort
            response = self.client.chat.completions.create(**request)
        except APITimeoutError as e:
            logger.error(f"Model (OpenAI) call timed out (max: {self.timeout_s}): {e}")
            raise
        except APIStatusError as e:
            if e.status_code == 429:
                # retryable — respect Retry-After if the server sends it
                retry_after = e.response.headers.get("retry-after", 1)
                logger.warning(f"Rate limited, retry-after: {retry_after}")
                # From HF docs https://huggingface.co/docs/hub/rate-limits#rate-limit-tiers
                # When a 429 error occurs, their SDK automatically parses the RateLimit
                # header to extract the exact number of seconds until the rate limit
                # resets, then waits precisely that duration before retrying.
                # This applies to file downloads (i.e. Resolvers) and paginated Hub
                # API calls (list models, datasets, spaces, etc.).
                rate_limit_info = response.headers.get("RateLimit", "")
                # "api";r=[remaining];t=[seconds remaining until reset]
                # Parse the t=[seconds] parameter
                for part in rate_limit_info.split(";"):
                    if part.strip().startswith("t="):
                        try:
                            wait_time = int(part.split("=")[1])
                        except Exception as e:
                            logger.error(
                                f"Wait time cannot be parsed from {part} in {rate_limit_info}"
                            )
                        break

                logger.warning(f"Rate limited! Waiting for {wait_time} seconds...")
                extra_response["retry_after"] = max(retry_after, wait_time)
            elif 400 <= e.status_code < 500:
                # permanent — retrying will never help, fail fast
                logger.error(f"Permanent client error {e.status_code}: {e.message}")
                raise
            else:
                # 5xx — transient, retryable
                logger.warning(f"Server error {e.status_code}")
                extra_response["retry_after"] = wait_time
                extra_response["status_code"] = e.status_code
                logger.error(
                    f"Model call exception: {e}. Setting `extra_response` args for retry: {extra_response}"
                )
        except Exception as e:
            logger.error(f"Model call exception: {e}. ")
            raise
        return response, extra_response


if __name__ == "__main__":
    model = Model()
    prompt = "Write a short poem about the beauty of nature."
    response, extra_response = model.call(prompt)
    # print(response)
    token_usage = response.usage.model_dump_json()
    print(token_usage)
    print(response.choices[0].message.content)
    print(extra_response)
