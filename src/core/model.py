from dotenv import load_dotenv
import os
from openai import OpenAI
import logging
from ..config import Config

load_dotenv()  # Load environment variables from .env file

assert "OPENAI_API_KEY" in os.environ, "OPENAI_API_KEY is not set in the environment variables."
assert "OPENAI_BASE_URL" in os.environ, "OPENAI_BASE_URL is not set in the environment variables."

cfg = Config()
logger = cfg.get_logger("ModelLogger")

class ModelConfig:
    def __init__(self):
        self.api_key = os.environ.get("OPENAI_API_KEY")
        self.base_url = os.environ.get("OPENAI_BASE_URL")

class Model(ModelConfig):
    def __init__(self, model_name: str = "google/gemma-3-27b-it", system_prompt: str = "", temperature: float = 0.7, max_tokens: int = 1500, reasoning_effort: str = "medium"):
        super().__init__()
        self.model_name = model_name
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.system_prompt = system_prompt
        self.reasoning_effort = reasoning_effort
        self.client = OpenAI(api_key=self.api_key, base_url=self.base_url)

    def call(self, prompt: str, output_schema: dict = None):
        if output_schema:
            logger.debug(f"Calling model '{self.model_name}' with output schema: {output_schema}") 

        messages = []
        if self.system_prompt:
            messages.append({"role": "system", "content": self.system_prompt})
        else:
            logger.warning("No system prompt provided. Proceeding without it.")
        messages.append({"role": "user", "content": prompt})

        response = self.client.chat.completions.create(
            model=self.model_name,
            messages=messages,
            temperature=self.temperature,
            max_tokens=self.max_tokens, 
            reasoning_effort=self.reasoning_effort, 
            response_format=output_schema,
        )
        return response 

if __name__ == "__main__":
    model = Model()
    prompt = "Write a short poem about the beauty of nature."
    response = model.call(prompt)
    print(response.choices[0].message.content)