"""HealthEnv: compile health QA seeds into verifiable CUA environments."""

from .compiler import compile_seed, compile_seed_file
from .schema import QuestionSeed, TaskSpec
from .seedgen import generate_seeds, write_seed_file
from .verifier import VerificationReport, verify_state

__all__ = [
    "QuestionSeed",
    "TaskSpec",
    "VerificationReport",
    "compile_seed",
    "compile_seed_file",
    "generate_seeds",
    "verify_state",
    "write_seed_file",
]

__version__ = "0.2.0"
