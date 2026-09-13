import argparse
import random
import time

from src.config import Config
from src.core.orchestrator.investigator import (
    InvestigationState,
    ResumeInvestigationState,
)

cfg = Config()
logger = cfg.get_logger("MainAppLogger")


def main():
    session_id = time.time()
    input_texts = (
        "If an LLM/AI model solves a big math problem, who gets the credit for it from a philosophical standpoint?",
        "Infineon is doing much better financially than NVIDIA.",
        "Morning are great for productive technical work. For junor developers to complete the coding tasks on their list.",
    )
    parser = argparse.ArgumentParser(
        description="Tool to research the internet for hypothetical scenarios."
    )
    parser.add_argument(
        "-q",
        default=None,
        metavar="QUESTION",
    )
    parser.add_argument(
        "-b",
        help="Budget for agentic loop",
        default=10,
        type=int,
        metavar="BUDGET",
    )
    parser.add_argument(
        "-r",
        action="store_true",
        help="Run a random input_text",
    )
    # subcommand to resume
    sub_parser = parser.add_subparsers(description="To resume from a past run")
    parser_resume = sub_parser.add_parser("resume")
    parser_resume.add_argument("file_name", help="Path to a file", default=None)
    # parse
    args = parser.parse_args()

    input_text = args.q or (random.choice(input_texts) if args.r else None)
    budget = args.b
    file_name = getattr(args, "file_name", None)

    if not file_name:
        state = InvestigationState(
            question=input_text,
            session_id=session_id,
            budget=budget,
        )
        state.run_order()
        logger.info(
            f"""
            Report:\n{state.report_path}
            """
        )
    else:
        state = ResumeInvestigationState.resume(
            path=file_name,
            budget=budget,
        )
        state.run_resume_order()
        logger.info(
            f"""
            Report:\n{state.report_path}
            """
        )


if __name__ == "__main__":
    main()
