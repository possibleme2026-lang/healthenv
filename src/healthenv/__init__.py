"""HealthEnv: compile health QA seeds into verifiable CUA environments."""

from .compiler import compile_seed, compile_seed_file
from .schema import QuestionSeed, TaskSpec
from .verifier import VerificationReport, verify_state

__all__ = [
    "QuestionSeed",
    "TaskSpec",
    "VerificationReport",
    "compile_seed",
    "compile_seed_file",
    "verify_state",
]

__version__ = "0.1.0"
