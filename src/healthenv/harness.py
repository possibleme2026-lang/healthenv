"""Adapters that drive one environment through three different agent harnesses.

The scientific question is whether a task compiled by HealthEnv is robust to
*who* is driving the browser, so the comparison has to hold everything except
the harness fixed:

* the same model behind every harness (``tierflow_pro`` over an OpenAI-compatible
  endpoint), so a difference is attributable to the harness and not the weights;
* the same task instances, chosen by the same stratified sampler;
* the same tool surface (the HTTP API in :mod:`healthenv.agentenv`) and the same
  prompt text;
* the same offline scoring, computed by the driver after the episode ends.

Each adapter only knows how to turn a prompt into a non-interactive command. The
three CLIs disagree about almost everything else: ``pi`` and ``codex`` block on
stdin unless it is closed, and ``dsh`` needs a patch overlay to point its
pi-ai route at the endpoint. Those quirks are recorded here so an evaluation run
is reproducible rather than a transcript of trial and error.
"""

from __future__ import annotations

import os
import shlex
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from .agentenv import TOOL_MANIFEST

# All three harnesses are pointed at the same OpenAI-compatible endpoint.
DEFAULT_PROVIDER = "tierflow"
DEFAULT_MODEL = "tierflow_pro"
DEFAULT_BASE_URL = "https://tierflow.cn/v1"

# The file the prompt is written to, and how each harness reaches it. Multi-line
# argv prompts are truncated to their first line on Windows, which was measured
# with a sentinel prompt: codex got zero of two markers that sat on later lines,
# then told the user to "send the follow-up lines". pi reads ``@PROMPT.txt`` and
# inlines it; codex reads the whole prompt from stdin when argv is ``-``; dsh has
# no prompt-on-stdin channel, so it is handed a one-line pointer and does the
# read itself, which is how dsh is normally driven.
PROMPT_FILENAME = "PROMPT.txt"
PROMPT_TRANSPORT_FILE = "file"  # inline the file via the CLI's own @file syntax
PROMPT_TRANSPORT_STDIN = "stdin"  # pipe the whole prompt down stdin
PROMPT_TRANSPORT_POINTER = "pointer"  # one-line argv pointer; the agent reads the file


def prompt_file(prompt: str) -> str:
    """The on-disk form of the prompt, so a harness can read it whole."""
    return prompt


def prompt_pointer() -> str:
    """The one-line argv prompt for a harness that can read the file itself."""
    return f"Read the file {PROMPT_FILENAME} in the current directory and follow it exactly."


def build_prompt(base_url: str, tools: tuple[dict[str, Any], ...] = TOOL_MANIFEST) -> str:
    """The one prompt every harness receives, identical byte for byte.

    It describes the tool surface and the workflow but never the gold answer,
    the evidence set, or the verifier. The model has to read the records and
    decide which of them support the conclusion.

    The documented call is a GET with query parameters rather than a POST with a
    JSON body. That is deliberate and load-bearing: measured on this machine the
    JSON-body form is silently corrupted by PowerShell 5.1, which is the shell
    ``codex`` and ``dsh`` drive on Windows, while the query form is transmitted
    identically by bash and PowerShell. ``POST /tool`` still works for callers
    that prefer it, but the prompt must not teach a call that fails in half the
    harnesses for reasons unrelated to the task.
    """
    lines = [
        "You are operating a clinical records workspace through an HTTP tool API.",
        "",
        f"Base URL: {base_url}",
        "",
        "Call one tool per command. Each tool is a GET whose arguments are query",
        "parameters. Read-only tools take no arguments:",
        "",
        f"  curl -s -G {base_url}/tool --data-urlencode tool=<name>",
        "",
        "Tools that take arguments add one --data-urlencode per argument:",
        "",
        f'  curl -s -G {base_url}/tool --data-urlencode tool=select_record \\',
        '    --data-urlencode record_id=<id> --data-urlencode selected=true',
        "",
        "Use this form exactly, including the URL-encoding, so a value containing",
        "spaces or punctuation is transmitted intact.",
        "",
        "Tools:",
    ]
    for tool in tools:
        schema = tool["parameters"]
        properties = schema.get("properties", {})
        args = ", ".join(f"{name}: {spec.get('type', 'any')}" for name, spec in properties.items())
        lines.append(f"- {tool['name']}({args}) — {tool['description']}")
    lines += [
        "",
        "Workflow:",
        "1. Call get_task to read the instruction and the participant header.",
        "2. Call list_records to read every observation. Records are read-only; there is no edit tool.",
        "3. Select exactly the records that support the conclusion. Selecting extra or unrelated",
        "   records is an error, and so is leaving out a record the conclusion depends on.",
        "4. Set the care note to a concise conclusion, and set the workflow priority.",
        "5. Call submit. The episode ends there and you receive no feedback about correctness.",
        "",
        "Order matters: select the records and set the note and priority before submitting, because",
        "nothing can be edited afterwards. Work autonomously and stop once submit succeeds.",
        "",
        submission_note(""),
    ]
    return "\n".join(lines)


@dataclass(slots=True)
class HarnessSpec:
    """How to invoke one harness non-interactively."""

    name: str
    display_name: str
    vendor: str
    build_command: Callable[[str, str], list[str]]
    # How the prompt reaches this CLI; see PROMPT_TRANSPORT_* above.
    prompt_transport: str = PROMPT_TRANSPORT_STDIN
    env: dict[str, str] = field(default_factory=dict)
    # Some harnesses need a scratch file written before the run (dsh's overlay).
    setup_files: dict[str, str] = field(default_factory=dict)
    notes: str = ""


def _pi_command(prompt: str, cwd: str) -> list[str]:
    # `pi` blocks forever on an inherited stdin, so the prompt cannot go there.
    # argv is safe only because pi expands ``@file`` references itself: the
    # multi-line text is read from PROMPT.txt and inlined before the model sees
    # it, which a sentinel probe confirmed arrives whole (an argv multi-line
    # string itself is truncated to its first line on Windows).
    del cwd
    return [
        "pi",
        "--print",
        "--no-session",
        "--no-context-files",
        "--no-extensions",
        "--no-skills",
        "--no-prompt-templates",
        "--no-themes",
        "--provider",
        DEFAULT_PROVIDER,
        "--model",
        DEFAULT_MODEL,
        "--tools",
        "bash",
        f"@{PROMPT_FILENAME}",
    ]


def find_bash() -> str:
    """Locate a real bash for harnesses that drive one.

    pi's bundled shell discovery only probes ``C:\\Program Files\\Git`` and the
    x86 variant, so on a machine whose Git lives anywhere else its ``bash`` tool
    fails with "No bash shell found" and the agent cannot act at all. Pointing
    the tool at a working shell is part of making the harness runnable.
    """
    candidates = [
        os.environ.get("HEALTHENV_BASH", ""),
        r"C:\Program Files\Git\bin\bash.exe",
        r"C:\Program Files (x86)\Git\bin\bash.exe",
        r"D:\Git\bin\bash.exe",
        r"C:\Users\less\AppData\Local\Programs\WorkBuddy\resources\vendor\PortableGit\bin\bash.exe",
    ]
    for candidate in candidates:
        if candidate and os.path.isfile(candidate):
            return candidate
    from shutil import which

    return which("bash") or ""


def pi_settings() -> str:
    """Project-level pi settings that make its bash tool usable.

    A shell path is passed per-run as a settings file in the working directory
    rather than written into the user's global config, so an evaluation run
    never rewrites a colleague's own harness setup.
    """
    shell = find_bash()
    if not shell:
        return "{}\n"
    escaped = shell.replace("\\", "\\\\")
    return f'{{\n  "shellPath": "{escaped}"\n}}\n'


def _codex_command(prompt: str, cwd: str) -> list[str]:
    # The prompt goes in over stdin (``-``), not argv. Measured on Windows, a
    # multi-line argv prompt reaches codex truncated to its first line: the agent
    # then reasons about an instruction it never fully received ("The user says:
    # ... This is a very vague prompt") and spends the episode exploring the
    # filesystem instead of the tool API. A sentinel prompt returned zero of two
    # later-line markers through argv and both through stdin.
    del prompt, cwd
    return [
        "codex",
        "exec",
        "--skip-git-repo-check",
        "--sandbox",
        "danger-full-access",
        "--model",
        DEFAULT_MODEL,
        "-",
    ]


def _dsh_command(prompt: str, cwd: str) -> list[str]:
    patch = os.path.join(cwd, "tierflow.patch.yml")
    # dsh has no prompt-on-stdin channel, so it gets a one-line pointer and reads
    # PROMPT.txt itself -- how dsh is normally driven, and it sidesteps the argv
    # truncation codex hits.
    del prompt
    return [
        "npx",
        "@deepseek-ai/dsh",
        "--profile",
        "headless",
        "--patch",
        patch,
        prompt_pointer(),
    ]


# A harness that finishes its work is not obliged to exit: codex and dsh keep a
# session alive after the last tool call, which would burn the whole timeout. The
# completion signal is the episode itself -- the tool server knows the moment
# ``submit`` lands -- rather than a token scraped from the transcript. A token is
# not usable here: codex echoes the prompt to stderr, so the marker we asked the
# agent to print also appears in the echo, and a naive match kills the run the
# instant it starts.
GRACE_SECONDS = 3.0


def submission_note(base_url: str) -> str:
    """The closing instruction: work autonomously and submit when done."""
    del base_url
    return "Work autonomously. Stop once `submit` has succeeded."


DSH_PATCH = """\
# Route the pi-ai provider at the shared OpenAI-compatible endpoint.
- id: llm-pi-ai
  config:
    providers:
      tierflow:
        apiKeyEnv: TIERFLOW_API_KEY
        api: openai-completions
        baseURL: https://tierflow.cn/v1
        compat:
          supportsDeveloperRole: false
          supportsReasoningEffort: false
        models:
          - id: tierflow_pro
            name: TierFlow Pro
            contextWindow: 128000
            maxTokens: 8192
- id: agent-default-model
  config:
    provider: tierflow
    model: tierflow_pro
# The Windows ACL sandbox cannot provision write access to the workspace it is
# handed (SetNamedSecurityInfoW fails with error 5 on the session directory), so
# under workspace-write every command is refused before it runs and the agent
# can only report being blocked. Codex runs this benchmark with full access too,
# so the modes match across harnesses.
- id: sandbox-policy
  config:
    mode: danger-full-access
"""


def harness_specs() -> dict[str, HarnessSpec]:
    """The three harnesses, keyed by short name."""
    shared_env = {
        # the endpoint is reachable directly; the local tool server must not be proxied
        "NO_PROXY": "localhost,127.0.0.1",
        "no_proxy": "localhost,127.0.0.1",
    }
    return {
        "pi": HarnessSpec(
            name="pi",
            display_name="pi",
            vendor="mariozechner/pi",
            build_command=_pi_command,
            # prompt arrives via @PROMPT.txt because argv multi-line is truncated
            prompt_transport=PROMPT_TRANSPORT_FILE,
            env={**shared_env, "HEALTHENV_BASH": find_bash()},
            # pi's shell discovery misses a Git installed outside Program Files;
            # a project-level settings file supplies shellPath for this run only.
            setup_files={os.path.join(".pi", "settings.json"): pi_settings()},
            notes="stdin closed; tool allowlist; shellPath; prompt via @file",
        ),
        "codex": HarnessSpec(
            name="codex",
            display_name="Codex CLI",
            vendor="OpenAI",
            build_command=_codex_command,
            # the whole prompt has to go over stdin; argv is truncated to line 1
            prompt_transport=PROMPT_TRANSPORT_STDIN,
            env=shared_env,
            notes="stdin carries the prompt; sandbox widened for the local tool server",
        ),
        "deepseek": HarnessSpec(
            name="deepseek",
            display_name="DeepSeek Harness",
            vendor="DeepSeek AI",
            build_command=_dsh_command,
            # argv-only CLI: a one-line pointer, and the agent reads PROMPT.txt
            prompt_transport=PROMPT_TRANSPORT_POINTER,
            env={**shared_env, "DSH_HOME": "", "TIERFLOW_API_KEY": ""},
            setup_files={"tierflow.patch.yml": DSH_PATCH},
            notes="patch overlay routes pi-ai at the endpoint; reads the prompt file",
        ),
    }


def _npm_global_bin() -> str:
    """Windows shims live in the npm user bin and are not on the eval subprocess PATH."""
    appdata = os.environ.get("APPDATA")
    if appdata:
        candidate = os.path.join(appdata, "npm")
        if os.path.isdir(candidate):
            return candidate
    return ""


def resolve_command(argv: list[str], env: dict[str, str]) -> list[str]:
    """Resolve ``argv[0]`` to a real file the OS can execute.

    On Windows a CLI installed through npm is a shell script plus a ``.cmd``
    shim, and ``CreateProcess`` needs the shim with its extension. ``shutil.which``
    already honours ``PATHEXT``, so pointing it at the augmented ``PATH`` is
    enough; anywhere else the name is returned untouched.
    """
    from shutil import which

    resolved = which(argv[0], path=env.get("PATH"))
    if resolved:
        return [resolved, *argv[1:]]
    return argv


def harness_env(spec: HarnessSpec, api_key: str, base_url: str, home: str) -> dict[str, str]:
    """Build the process environment for one harness invocation."""
    env = dict(os.environ)
    env.update(spec.env)
    env["PI_OFFLINE"] = "1"  # skip startup network chatter; the model call still goes out
    # every harness family reads credentials from a differently named variable
    env["OPENAI_API_KEY"] = api_key
    env["TIERFLOW_API_KEY"] = api_key
    env["DEEPSEEK_API_KEY"] = api_key
    env["DEEPSEEK_BASE_URL"] = base_url
    if env.get("DSH_HOME") == "":
        env["DSH_HOME"] = os.path.join(home, "dsh-home")
    npm_bin = _npm_global_bin()
    if npm_bin:
        env["PATH"] = f"{npm_bin}{os.pathsep}{env.get('PATH', '')}"
    return env


def describe_command(argv: list[str], api_key: str) -> str:
    """A printable command with the credential redacted."""
    redacted = [arg.replace(api_key, "***") if api_key else arg for arg in argv]
    return " ".join(shlex.quote(arg) for arg in redacted[:12]) + (" ..." if len(redacted) > 12 else "")
