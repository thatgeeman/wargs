import logging
import os
import pathlib

from dotenv import load_dotenv

load_dotenv()  # Load environment variables from .env file


class Config:
    config_dir = pathlib.Path.home() / ".wargs"

    log_level = logging.INFO
    log_format = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    log_handler = logging.StreamHandler()
    model = "Qwen/Qwen3.8-27B" #"google/gemma-4-31B-it"
    max_tokens = 4096
    temperature = 0
    # pacing for model calls: minimum interval between requests is derived
    # from this quota (60 / rpm); <= 0 disables the throttle
    requests_per_minute = 200

    _session_log_handler = None  # class-level: the active run's FileHandler

    def get_logger(self, name):
        logger = logging.getLogger(name)
        logger.setLevel(self.log_level)
        self.log_handler.setFormatter(self.log_format)
        logger.addHandler(self.log_handler)
        return logger

    @classmethod
    def init_session_logging(cls, session_id):
        """Mirror all log output into a run-specific file inside the
        session's config_dir (next to the traces). Attached to the root
        logger so every named logger propagates into it; replaces any
        previous session's handler (one active run per process)."""
        root = logging.getLogger()
        if cls._session_log_handler is not None:
            root.removeHandler(cls._session_log_handler)
            cls._session_log_handler.close()
        log_dir = cls.config_dir / f"trace_{session_id}"
        log_dir.mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler(log_dir / "run.log")
        handler.setFormatter(cls.log_format)
        root.addHandler(handler)
        cls._session_log_handler = handler
        return log_dir / "run.log"

    def to_dict(self):
        """JSON-safe snapshot for state dumps (picked up by WargsEncoder).
        Excludes the non-serializable logging internals."""
        return {
            "config_dir": str(self.config_dir),
            "log_level": logging.getLevelName(self.log_level),
            "model": self.model,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "requests_per_minute": self.requests_per_minute,
        }


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
