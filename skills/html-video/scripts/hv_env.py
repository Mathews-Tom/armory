"""Explicit bootstrap, environment lock and pinned invocation of the Hyperframes CLI.

Bootstrap is the only code path that installs or downloads anything. It records
the exact tools in ``.html-video/environment.json``. Every other command loads
that record, re-verifies it without network, and invokes the project-local CLI
through Node directly; it never calls ``npx`` or any package manager.
"""

from __future__ import annotations

import json
import os
import platform
import re
import shutil
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from hv_config import Config

LOCK_DIR = ".html-video"
LOCK_FILE = f"{LOCK_DIR}/environment.json"
SCHEMA_VERSION = 1
INSTALL_TIMEOUT_S = 900
BROWSER_ENV_VARS = ("HYPERFRAMES_BROWSER_PATH", "PRODUCER_HEADLESS_SHELL_PATH")

_LOCKFILES = {
    "package-lock.json": "npm",
    "npm-shrinkwrap.json": "npm",
    "pnpm-lock.yaml": "pnpm",
    "yarn.lock": "yarn",
    "bun.lock": "bun",
    "bun.lockb": "bun",
}


class EnvError(RuntimeError):
    """The toolchain is missing, mismatched or could not be provisioned."""


@dataclass(frozen=True)
class Tool:
    path: str
    version: str


@dataclass(frozen=True)
class Browser:
    path: str
    version: str
    source: str


@dataclass(frozen=True)
class Environment:
    package: str
    hyperframes_version: str
    cli: str
    package_manager: str
    node: Tool
    ffmpeg: Tool
    ffprobe: Tool
    browser: Browser
    platform: str
    recorded_at: str

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": SCHEMA_VERSION,
            "recorded_at": self.recorded_at,
            "platform": self.platform,
            "hyperframes": {
                "package": self.package,
                "version": self.hyperframes_version,
                "cli": self.cli,
                "package_manager": self.package_manager,
            },
            "node": {"path": self.node.path, "version": self.node.version},
            "ffmpeg": {"path": self.ffmpeg.path, "version": self.ffmpeg.version},
            "ffprobe": {"path": self.ffprobe.path, "version": self.ffprobe.version},
            "browser": {
                "path": self.browser.path,
                "version": self.browser.version,
                "source": self.browser.source,
            },
        }


# --------------------------------------------------------------------------
# Process helpers
# --------------------------------------------------------------------------


def run(
    argv: list[str],
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    timeout: float = 120,
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            argv,
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise EnvError(f"cannot run {' '.join(argv[:3])}: {exc}") from exc


def _tail(text: str, lines: int = 8) -> str:
    return "\n".join(text.strip().splitlines()[-lines:])


def _first_line(text: str) -> str:
    return next((line.strip() for line in text.splitlines() if line.strip()), "")


def tool_version(path: str, flag: str) -> str:
    proc = run([path, flag], timeout=30)
    version = _first_line(proc.stdout) or _first_line(proc.stderr)
    if proc.returncode != 0 or not version:
        raise EnvError(f"{path} {flag} failed: {_tail(proc.stderr or proc.stdout)}")
    return version


def node_major(version: str) -> int:
    match = re.match(r"^v?(\d+)\.", version.strip())
    if match is None:
        raise EnvError(f"cannot parse Node version {version!r}")
    return int(match.group(1))


# --------------------------------------------------------------------------
# Package manager and installed CLI
# --------------------------------------------------------------------------


def detect_package_manager(project: Path) -> str:
    """Package manager implied by the project's lockfile; npm for a fresh project."""
    found = {
        manager: name
        for name, manager in _LOCKFILES.items()
        if (project / name).exists()
    }
    if len(found) > 1:
        names = ", ".join(sorted(found.values()))
        raise EnvError(
            f"multiple package-manager lockfiles ({names}); keep exactly one so the install is unambiguous"
        )
    return next(iter(found), "npm")


def install_command(manager: str, spec: str) -> list[str]:
    commands = {
        "npm": ["npm", "install", "--save-exact", "--no-audit", "--no-fund", spec],
        "pnpm": ["pnpm", "add", "--save-exact", spec],
        "yarn": ["yarn", "add", "--exact", spec],
        "bun": ["bun", "add", "--exact", spec],
    }
    return commands[manager]


def installed_cli(project: Path, cfg: Config) -> tuple[Path, str]:
    """Locate the project-local CLI entry point and its installed version."""
    package_json = project / "node_modules" / cfg.package / "package.json"
    if not package_json.is_file():
        raise EnvError(
            f"{cfg.package} is not installed in {project}; run `html_video.py bootstrap` first"
        )
    try:
        meta: object = json.loads(package_json.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise EnvError(f"cannot read {package_json}: {exc}") from exc
    if not isinstance(meta, dict):
        raise EnvError(f"{package_json} is not a package manifest")
    fields = {str(k): v for k, v in meta.items()}  # pyright: ignore[reportUnknownVariableType, reportUnknownArgumentType]
    version = fields.get("version")
    if version != cfg.version:
        raise EnvError(
            f"installed {cfg.package} is {version!r}, pinned version is {cfg.version}; re-run bootstrap"
        )
    bin_field = fields.get("bin")
    if isinstance(bin_field, dict):
        bin_field = {str(k): v for k, v in bin_field.items()}.get(cfg.package)  # pyright: ignore[reportUnknownVariableType, reportUnknownArgumentType]
    if not isinstance(bin_field, str):
        raise EnvError(f"{package_json} declares no {cfg.package} executable")
    cli = (package_json.parent / bin_field).resolve()
    if not cli.is_file():
        raise EnvError(f"CLI entry point {cli} is missing; re-run bootstrap")
    return cli, cfg.version


# --------------------------------------------------------------------------
# Child process environment and invocation
# --------------------------------------------------------------------------


def child_env(
    cfg: Config, env: Environment | None, base: dict[str, str] | None = None
) -> dict[str, str]:
    merged = {
        k: v
        for k, v in (base if base is not None else dict(os.environ)).items()
        if k not in cfg.scrubbed_env
    }
    for name in BROWSER_ENV_VARS:
        merged.pop(name, None)
    merged.update(cfg.forced_env)
    if env is not None:
        merged["HYPERFRAMES_BROWSER_PATH"] = env.browser.path
        merged["PRODUCER_HEADLESS_SHELL_PATH"] = env.browser.path
        merged["HYPERFRAMES_FFMPEG_PATH"] = env.ffmpeg.path
        merged["HYPERFRAMES_FFPROBE_PATH"] = env.ffprobe.path
    return merged


def hyperframes(
    project: Path, cfg: Config, env: Environment, args: list[str], timeout: float
) -> subprocess.CompletedProcess[str]:
    return run(
        [env.node.path, str(project / env.cli), *args],
        cwd=project,
        env=child_env(cfg, env),
        timeout=timeout,
    )


# --------------------------------------------------------------------------
# Lock read / verify
# --------------------------------------------------------------------------


def _tool(raw: object, name: str) -> Tool:
    if isinstance(raw, dict):
        data = {str(k): v for k, v in raw.items()}  # pyright: ignore[reportUnknownVariableType, reportUnknownArgumentType]
        if isinstance(data.get("path"), str) and isinstance(data.get("version"), str):
            return Tool(str(data["path"]), str(data["version"]))
    raise EnvError(f"{LOCK_FILE}: {name} record is malformed; re-run bootstrap")


def _read_lock(project: Path) -> Environment:
    path = project / LOCK_FILE
    if not path.is_file():
        raise EnvError(f"{LOCK_FILE} not found; run `html_video.py bootstrap` first")
    try:
        raw: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise EnvError(f"cannot read {LOCK_FILE}: {exc}") from exc
    if not isinstance(raw, dict):
        raise EnvError(f"{LOCK_FILE} is malformed")
    top = {str(k): v for k, v in raw.items()}  # pyright: ignore[reportUnknownVariableType, reportUnknownArgumentType]
    hf = top.get("hyperframes")
    br = top.get("browser")
    if (
        top.get("schema") != SCHEMA_VERSION
        or not isinstance(hf, dict)
        or not isinstance(br, dict)
    ):
        raise EnvError(f"{LOCK_FILE} has an unsupported shape; re-run bootstrap")
    hfd = {str(k): v for k, v in hf.items()}  # pyright: ignore[reportUnknownVariableType, reportUnknownArgumentType]
    brd = {str(k): v for k, v in br.items()}  # pyright: ignore[reportUnknownVariableType, reportUnknownArgumentType]
    texts = [hfd.get(k) for k in ("package", "version", "cli", "package_manager")] + [
        brd.get(k) for k in ("path", "version", "source")
    ]
    if not all(isinstance(t, str) and t for t in texts):
        raise EnvError(f"{LOCK_FILE} has missing fields; re-run bootstrap")
    package, version, cli, manager, bpath, bversion, bsource = (str(t) for t in texts)
    return Environment(
        package=package,
        hyperframes_version=version,
        cli=cli,
        package_manager=manager,
        node=_tool(top.get("node"), "node"),
        ffmpeg=_tool(top.get("ffmpeg"), "ffmpeg"),
        ffprobe=_tool(top.get("ffprobe"), "ffprobe"),
        browser=Browser(bpath, bversion, bsource),
        platform=str(top.get("platform", "")),
        recorded_at=str(top.get("recorded_at", "")),
    )


def verify_environment(
    project: Path, cfg: Config
) -> tuple[Environment | None, list[str]]:
    """Re-verify the recorded toolchain without network. Returns every problem found."""
    try:
        env = _read_lock(project)
    except EnvError as exc:
        return None, [str(exc)]
    problems: list[str] = []

    def check(label: str, tool: Tool | Browser, flag: str) -> None:
        if not Path(tool.path).is_file():
            problems.append(f"{label} recorded at {tool.path} no longer exists")
            return
        try:
            actual = tool_version(tool.path, flag)
        except EnvError as exc:
            problems.append(str(exc))
            return
        if actual != tool.version:
            problems.append(
                f"{label} changed since bootstrap: recorded {tool.version!r}, now {actual!r}"
            )

    if env.hyperframes_version != cfg.version or env.package != cfg.package:
        problems.append(
            f"lock records {env.package}@{env.hyperframes_version} but config.toml pins {cfg.spec}; re-run bootstrap"
        )
    try:
        installed_cli(project, cfg)
    except EnvError as exc:
        problems.append(str(exc))
    check("node", env.node, "--version")
    try:
        if node_major(env.node.version) < cfg.node_min_major:
            problems.append(
                f"Node {env.node.version} is older than required major {cfg.node_min_major}"
            )
    except EnvError as exc:
        problems.append(str(exc))
    check("ffmpeg", env.ffmpeg, "-version")
    check("ffprobe", env.ffprobe, "-version")
    check("browser", env.browser, "--version")
    return env, problems


def load_environment(project: Path, cfg: Config) -> Environment:
    env, problems = verify_environment(project, cfg)
    if problems or env is None:
        raise EnvError("; ".join(problems))
    return env


# --------------------------------------------------------------------------
# Bootstrap (the only provisioning path)
# --------------------------------------------------------------------------


def _require_binary(name: str, hint: str) -> str:
    path = shutil.which(name)
    if path is None:
        raise EnvError(
            f"{name} not found on PATH. {hint} Bootstrap does not install system binaries."
        )
    return path


def bootstrap(
    project: Path,
    cfg: Config,
    *,
    browser_path: Path | None = None,
    download_browser: bool = False,
) -> Environment:
    if browser_path is not None and download_browser:
        raise EnvError("choose either --browser-path or --download-browser, not both")
    if not project.is_dir():
        raise EnvError(f"project directory {project} does not exist")
    existing: Environment | None = None
    if browser_path is None and not download_browser:
        try:
            existing = _read_lock(project)
        except EnvError as exc:
            raise EnvError(
                "a browser must be chosen explicitly: pass --browser-path PATH (an existing Chrome or chrome-headless-shell) "
                "or --download-browser (runs the pinned CLI's `browser ensure`)"
            ) from exc

    node = _require_binary("node", f"Install Node.js {cfg.node_min_major} or newer.")
    node_ver = tool_version(node, "--version")
    if node_major(node_ver) < cfg.node_min_major:
        raise EnvError(
            f"Node {node_ver} is older than the required major {cfg.node_min_major}"
        )
    ffmpeg = _require_binary(
        "ffmpeg", "Install FFmpeg with your system package manager."
    )
    ffprobe = _require_binary("ffprobe", "Install FFmpeg (it provides ffprobe).")

    manager = detect_package_manager(project)
    try:
        cli, _ = installed_cli(project, cfg)
    except EnvError:
        _require_binary(manager, f"The project lockfile selects {manager}.")
        package_json = project / "package.json"
        if not package_json.exists():
            name = (
                re.sub(r"[^a-z0-9-]+", "-", project.resolve().name.lower()).strip("-")
                or "html-video-project"
            )
            package_json.write_text(
                json.dumps(
                    {"name": name, "version": "0.0.0", "private": True}, indent=2
                )
                + "\n",
                encoding="utf-8",
            )
        proc = run(
            install_command(manager, cfg.spec),
            cwd=project,
            env=child_env(cfg, None),
            timeout=INSTALL_TIMEOUT_S,
        )
        if proc.returncode != 0:
            raise EnvError(
                f"`{' '.join(install_command(manager, cfg.spec))}` failed:\n{_tail(proc.stderr or proc.stdout)}"
            )
        cli, _ = installed_cli(project, cfg)

    if existing is not None:
        browser = existing.browser
    elif browser_path is not None:
        if not browser_path.is_file():
            raise EnvError(f"--browser-path {browser_path} is not a file")
        browser = Browser(str(browser_path.resolve()), "", "user-path")
    else:
        node_cli = [node, str(cli)]
        proc = run(
            [*node_cli, "browser", "ensure"],
            cwd=project,
            env=child_env(cfg, None),
            timeout=INSTALL_TIMEOUT_S,
        )
        if proc.returncode != 0:
            raise EnvError(
                f"`browser ensure` failed:\n{_tail(proc.stderr or proc.stdout)}"
            )
        located = run(
            [*node_cli, "browser", "path"],
            cwd=project,
            env=child_env(cfg, None),
            timeout=60,
        )
        path_line = _first_line(
            "\n".join(reversed(located.stdout.strip().splitlines()))
        )
        if located.returncode != 0 or not path_line or not Path(path_line).is_file():
            raise EnvError(
                f"`browser path` did not report an existing executable: {_tail(located.stderr or located.stdout)}"
            )
        browser = Browser(
            str(Path(path_line).resolve()), "", "hyperframes-browser-ensure"
        )
    browser = Browser(
        browser.path, tool_version(browser.path, "--version"), browser.source
    )

    env = Environment(
        package=cfg.package,
        hyperframes_version=cfg.version,
        cli=str(cli.relative_to(project.resolve()))
        if cli.is_relative_to(project.resolve())
        else str(cli),
        package_manager=manager,
        node=Tool(node, node_ver),
        ffmpeg=Tool(ffmpeg, tool_version(ffmpeg, "-version")),
        ffprobe=Tool(ffprobe, tool_version(ffprobe, "-version")),
        browser=browser,
        platform=f"{platform.system().lower()}-{platform.machine().lower()}",
        recorded_at=datetime.now(UTC).isoformat(timespec="seconds"),
    )
    (project / LOCK_DIR).mkdir(exist_ok=True)
    (project / LOCK_FILE).write_text(
        json.dumps(env.as_dict(), indent=2) + "\n", encoding="utf-8"
    )
    return env
