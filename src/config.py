import logging
import os
import pathlib

from dotenv import load_dotenv

load_dotenv()  # Load environment variables from .env file


class Config:
    config_dir = pathlib.Path.home() / ".wahrgus"

    log_level = logging.INFO
    log_format = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    log_handler = logging.StreamHandler()

    def get_logger(self, name):
        logger = logging.getLogger(name)
        logger.setLevel(self.log_level)
        self.log_handler.setFormatter(self.log_format)
        logger.addHandler(self.log_handler)
        return logger


class SecretsManager:
    """Stores env vars that start with 'WG_' and provides access to them."""

    def __init__(self):
        self.secrets = {}
        self.config = Config()
        self.logger = self.config.get_logger("SecretsManagerLogger")
        self.load_secrets()

    def get_secret(self, key):
        try:
            return self.secrets[key]
        except KeyError:
            self.logger.error(
                f"Secret '{key}' not found. Ensure it is set in the environment variables and starts with 'WG_'."
            )
            raise KeyError(
                f"Secret '{key}' not found. Ensure it is set in the environment variables and starts with 'WG_'."
            )

    def load_secrets(self):
        for key, value in os.environ.items():
            if key.startswith("WG_"):
                self.secrets[key] = value
