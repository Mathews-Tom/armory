"""Owned native payloads and lossless, crash-recoverable host registration.

All operations hold an advisory lock on the host root directory. A durable
ownership journal contains exact configuration and ownership preimages before
activation. Recovery never infers ownership from a path or a registration.
"""

from __future__ import annotations

import base64
import binascii
import copy
import fcntl
import hashlib
import json
import os
import re
import stat
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

import yaml
from yaml.error import Mark
from yaml.nodes import MappingNode, Node, ScalarNode, SequenceNode

from scripts.build_extensions import (
    CONTENT_MANIFEST,
    BuildError,
    assemble_feature,
    resolve_feature_dir,
    verify_artifact_dir,
    write_tree,
)
from scripts.extension_metadata import is_feature_name
from scripts.package_types import NATIVE_ACTIONS, NATIVE_HOSTS

STATE_DIR = ".armory-native"
OWNERSHIP_SCHEMA = 1
CLAUDE_SETTINGS = "settings.json"
CLAUDE_PLUGIN_DIRS_KEY = "CLAUDE_CODE_PLUGIN_DIRS"
OMP_CONFIG = "config.yml"
OMP_DISABLED_KEY = "disabledExtensions"
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_VERSION = re.compile(r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\Z")
_RECORD_KEYS = {
    "schema_version",
    "feature",
    "host",
    "target_root",
    "payload",
    "version",
    "content_manifest_sha256",
    "files",
    "state",
    "registration",
    "pending",
}


class LifecycleError(RuntimeError):
    """An action cannot proceed without risking foreign or owned state."""


@dataclass(frozen=True)
class HostLayout:
    """Paths owned by one feature in one host root."""

    root: Path
    host: str
    feature: str

    @property
    def payload_rel(self) -> str:
        if self.host == "omp":
            return f"extensions/{self.feature}"
        return f"{STATE_DIR}/claude-plugins/{self.feature}"

    @property
    def payload(self) -> Path:
        return self.root / self.payload_rel

    @property
    def ownership(self) -> Path:
        return self.root / STATE_DIR / "ownership" / f"{self.host}-{self.feature}.json"

    @property
    def staging(self) -> Path:
        return self.root / STATE_DIR / "staging"

    @property
    def omp_disabled_id(self) -> str:
        return f"extension-module:{self.feature}"

    @property
    def config(self) -> Path:
        return self.root / (OMP_CONFIG if self.host == "omp" else CLAUDE_SETTINGS)


def resolve_target_root(target_root: Path) -> Path:
    target_root = target_root.absolute()
    if target_root.is_symlink():
        raise LifecycleError(f"{target_root} is a symbolic link")
    if not target_root.is_dir():
        raise LifecycleError(
            f"target root {target_root} does not exist or is not a directory"
        )
    return target_root.resolve()


def _refuse_symlinks(root: Path, path: Path) -> None:
    try:
        parts = path.relative_to(root).parts
    except ValueError as exc:
        raise LifecycleError(f"{path} escapes {root}") from exc
    current = root
    for index, part in enumerate(parts):
        if part in ("", ".", ".."):
            raise LifecycleError(f"unsafe path {path}")
        current = current / part
        try:
            mode = current.lstat().st_mode
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(mode):
            raise LifecycleError(
                f"{current} is a symbolic link; refusing to traverse it"
            )
        if index < len(parts) - 1 and not stat.S_ISDIR(mode):
            raise LifecycleError(f"{current} is not a regular directory")


def _regular(root: Path, path: Path) -> bool:
    _refuse_symlinks(root, path)
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError:
        return False
    if not stat.S_ISREG(mode):
        raise LifecycleError(f"{path} is not a regular file")
    return True


def _ensure_dir(root: Path, path: Path) -> None:
    _refuse_symlinks(root, path)
    path.mkdir(parents=True, exist_ok=True)
    _refuse_symlinks(root, path)
    if not stat.S_ISDIR(path.lstat().st_mode):
        raise LifecycleError(f"{path} is not a regular directory")


def _sync_dir(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_atomic(path: Path, data: bytes, mode: int) -> None:
    # Exclusive, non-following creation also refuses a planted temporary leaf.
    temporary = path.parent / f".{path.name}.{uuid.uuid4().hex}"
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fchmod(handle.fileno(), mode)
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        _sync_dir(path.parent)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _rename(source: Path, destination: Path) -> None:
    os.rename(source, destination)
    _sync_dir(source.parent)
    if source.parent != destination.parent:
        _sync_dir(destination.parent)


@contextmanager
def _root_lock(root: Path) -> Iterator[None]:
    # A directory descriptor has no stale lockfile to steal or unlink; the
    # kernel releases this lock even after SIGKILL. All features share it.
    descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _image(root: Path, path: Path) -> dict[str, Any]:
    if not _regular(root, path):
        return {"data": None, "sha256": None, "mode": None}
    data = path.read_bytes()
    return {
        "data": base64.b64encode(data).decode("ascii"),
        "sha256": _sha256(data),
        "mode": stat.S_IMODE(path.lstat().st_mode),
    }


def _image_bytes(image: dict[str, Any]) -> bytes | None:
    return (
        None
        if image["data"] is None
        else base64.b64decode(image["data"], validate=True)
    )


def _validate_image(image: Any) -> None:
    if not isinstance(image, dict) or set(image) != {"data", "sha256", "mode"}:
        raise LifecycleError("malformed file preimage")
    if image["data"] is None:
        if image["sha256"] is not None or image["mode"] is not None:
            raise LifecycleError("malformed absent file preimage")
        return
    if (
        not isinstance(image["data"], str)
        or type(image["mode"]) is not int
        or not 0 <= image["mode"] <= 0o7777
    ):
        raise LifecycleError("malformed file preimage bytes or mode")
    try:
        data = _image_bytes(image)
    except (ValueError, binascii.Error) as exc:
        raise LifecycleError("malformed file preimage encoding") from exc
    if data is None or image["sha256"] != _sha256(data):
        raise LifecycleError("file preimage digest mismatch")


def _edited_image(before: dict[str, Any], text: str | None) -> dict[str, Any]:
    if text is None:
        return {"data": None, "sha256": None, "mode": None}
    data = text.encode("utf-8")
    return {
        "data": base64.b64encode(data).decode("ascii"),
        "sha256": _sha256(data),
        "mode": before["mode"] if before["data"] is not None else 0o600,
    }


def _put_image(layout: HostLayout, path: Path, image: dict[str, Any]) -> None:
    _regular(layout.root, path)
    data = _image_bytes(image)
    if data is None:
        if path.exists():
            path.unlink()
            _sync_dir(path.parent)
    else:
        _ensure_dir(layout.root, path.parent)
        _write_atomic(path, data, image["mode"])


def _relative_file(value: Any) -> bool:
    return (
        isinstance(value, str)
        and bool(value)
        and "\\" not in value
        and "\0" not in value
        and not value.startswith("/")
        and all(part not in ("", ".", "..") for part in value.split("/"))
        and PurePosixPath(value).as_posix() == value
    )


def _validate_files(files: Any) -> None:
    if not isinstance(files, dict) or CONTENT_MANIFEST not in files:
        raise LifecycleError("malformed owned file manifest")
    for name, digest in files.items():
        if (
            not _relative_file(name)
            or not isinstance(digest, str)
            or not _DIGEST.fullmatch(digest)
        ):
            raise LifecycleError("unsafe owned file path or digest")
        if any(
            parent.as_posix() in files
            for parent in PurePosixPath(name).parents
            if parent.as_posix() != "."
        ):
            raise LifecycleError("owned file path is also a directory")


def payload_problems(
    payload: Path, owned: dict[str, str], *, partial: bool = False
) -> list[str]:
    """Reject foreign files, empty foreign directories, links and special files."""
    if payload.is_symlink():
        return [f"{payload} is a symbolic link"]
    if not payload.is_dir():
        return [f"{payload} is missing or not a directory"]
    directories = {
        parent.as_posix()
        for name in owned
        for parent in PurePosixPath(name).parents
        if parent.as_posix() != "."
    }
    problems: list[str] = []
    seen: set[str] = set()
    for current, dirnames, filenames in os.walk(payload, followlinks=False):
        for name in dirnames + filenames:
            path = Path(current) / name
            rel = path.relative_to(payload).as_posix()
            mode = path.lstat().st_mode
            if stat.S_ISLNK(mode):
                problems.append(f"{rel}: symbolic link")
            elif stat.S_ISDIR(mode):
                if rel not in directories:
                    problems.append(f"{rel}: foreign directory")
            elif rel not in owned:
                problems.append(f"{rel}: foreign file")
            elif not stat.S_ISREG(mode) or _sha256(path.read_bytes()) != owned[rel]:
                problems.append(f"{rel}: locally modified")
            else:
                seen.add(rel)
    if not partial:
        problems.extend(f"{rel}: missing" for rel in sorted(set(owned) - seen))
    return problems


def _require_tree(
    root: Path, path: Path, files: dict[str, str], *, partial: bool = False
) -> None:
    _refuse_symlinks(root, path)
    problems = payload_problems(path, files, partial=partial)
    if problems:
        raise LifecycleError(
            f"{path} differs from the owned installation; nothing was changed: "
            + "; ".join(problems)
        )


def _require_record_tree(
    layout: HostLayout, path: Path, record: dict[str, Any], *, partial: bool = False
) -> None:
    _require_tree(layout.root, path, record["files"], partial=partial)
    manifest_path = path / CONTENT_MANIFEST
    if partial and not manifest_path.exists():
        return
    try:
        manifest = json.loads(manifest_path.read_bytes())
    except (ValueError, UnicodeDecodeError) as exc:
        raise LifecycleError(f"{path}: malformed owned artifact identity") from exc
    if not isinstance(manifest, dict) or any(
        manifest.get(key) != expected
        for key, expected in (
            ("schema_version", 1),
            ("feature", layout.feature),
            ("host", layout.host),
            ("version", record["version"]),
        )
    ):
        raise LifecycleError(f"{path}: artifact identity does not match ownership")
    entries = manifest.get("files")
    if not isinstance(entries, list) or any(
        not isinstance(entry, dict)
        or set(entry) != {"path", "sha256", "size"}
        or not _relative_file(entry["path"])
        or type(entry["size"]) is not int
        or entry["size"] < 0
        for entry in entries
    ):
        raise LifecycleError(f"{path}: malformed artifact file bindings")
    hashes = {entry["path"]: entry["sha256"] for entry in entries}
    expected_hashes = {
        name: digest
        for name, digest in record["files"].items()
        if name != CONTENT_MANIFEST
    }
    if len(hashes) != len(entries) or hashes != expected_hashes:
        raise LifecycleError(f"{path}: artifact file digests do not match ownership")


def _erase_tree(layout: HostLayout, path: Path, files: dict[str, str]) -> None:
    # Missing owned leaves are allowed only in the durable cleanup phase.
    _require_tree(layout.root, path, files, partial=True)
    for current, dirnames, filenames in os.walk(path, topdown=False):
        for name in filenames:
            (Path(current) / name).unlink()
        for name in dirnames:
            (Path(current) / name).rmdir()
    path.rmdir()
    _sync_dir(path.parent)


# Configuration edits use parser source marks, never whole-document dumping.
# JSON object spans are decoded with the standard decoder; YAML node marks keep
# comments, quoting, flow/block style and unrelated configuration bytes intact.
_JSON_DECODER = json.JSONDecoder()


def _json_members(text: str, start: int) -> dict[str, tuple[int, int, int, int]]:
    members: dict[str, tuple[int, int, int, int]] = {}
    index = start + 1
    while True:
        while index < len(text) and text[index].isspace():
            index += 1
        if text[index] == "}":
            return members
        key_start = index
        key, index = _JSON_DECODER.raw_decode(text, index)
        if not isinstance(key, str) or key in members:
            raise LifecycleError("duplicate or non-string JSON configuration key")
        while text[index].isspace():
            index += 1
        if text[index] != ":":
            raise LifecycleError("invalid JSON object")
        index += 1
        while text[index].isspace():
            index += 1
        value_start = index
        _value, index = _JSON_DECODER.raw_decode(text, index)
        members[key] = (key_start, value_start, index, index)
        while text[index].isspace():
            index += 1
        if text[index] == ",":
            index += 1
        elif text[index] != "}":
            raise LifecycleError("invalid JSON object separator")


def _json_set(
    text: str, object_start: int, key: str, value: Any, *, remove: bool = False
) -> str:
    members = _json_members(text, object_start)
    if key in members:
        key_start, value_start, value_end, _ = members[key]
        if not remove:
            return (
                text[:value_start]
                + json.dumps(value, ensure_ascii=False)
                + text[value_end:]
            )
        keys = list(members)
        position = keys.index(key)
        if position + 1 < len(keys):
            end = members[keys[position + 1]][0]
            return text[:key_start] + text[end:]
        start = key_start
        if position:
            previous_end = members[keys[position - 1]][2]
            start = text.index(",", previous_end, key_start)
        return text[:start] + text[value_end:]
    if remove:
        return text
    _object, end = _JSON_DECODER.raw_decode(text, object_start)
    insertion = (
        (", " if members else "")
        + json.dumps(key)
        + ": "
        + json.dumps(value, ensure_ascii=False)
    )
    return text[: end - 1] + insertion + text[end - 1 :]


def _config_text(image: dict[str, Any]) -> str:
    data = _image_bytes(image)
    try:
        return "" if data is None else data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise LifecycleError("configuration is not UTF-8") from exc


def _claude_data(image: dict[str, Any]) -> tuple[str, dict[str, Any], int]:
    text = _config_text(image)
    if image["data"] is None:
        text = "{}\n"
    try:
        data = json.loads(text)
        start = len(text) - len(text.lstrip())
        if not isinstance(data, dict):
            raise LifecycleError("settings.json: top level must be an object")
        _json_members(text, start)
        if "env" in data:
            if not isinstance(data["env"], dict):
                raise LifecycleError("settings.json: 'env' must be an object")
            env_start = _json_members(text, start)["env"][1]
            _json_members(text, env_start)
            if CLAUDE_PLUGIN_DIRS_KEY in data["env"] and not isinstance(
                data["env"][CLAUDE_PLUGIN_DIRS_KEY], str
            ):
                raise LifecycleError(
                    f"settings.json: env.{CLAUDE_PLUGIN_DIRS_KEY} must be a string"
                )
        return text, data, start
    except (ValueError, IndexError) as exc:
        raise LifecycleError(
            f"settings.json is not valid unambiguous JSON: {exc}"
        ) from exc


def _omp_data(
    image: dict[str, Any],
) -> tuple[str, MappingNode | None, SequenceNode | None, list[str]]:
    text = _config_text(image)
    try:
        node = yaml.compose(text)
    except yaml.YAMLError as exc:
        raise LifecycleError(f"config.yml is not valid YAML: {exc}") from exc
    if node is None or (
        isinstance(node, ScalarNode)
        and node.tag == "tag:yaml.org,2002:null"
        and node.value == ""
    ):
        return text, None, None, []
    if not isinstance(node, MappingNode):
        raise LifecycleError("config.yml: top level must be a mapping")
    keys: set[str] = set()
    disabled: SequenceNode | None = None
    values: list[str] = []
    for key, value in node.value:
        if (
            not isinstance(key, ScalarNode)
            or key.tag != "tag:yaml.org,2002:str"
            or key.value in keys
        ):
            raise LifecycleError("config.yml: ambiguous or duplicate mapping key")
        keys.add(key.value)
        if key.value == "<<":
            raise LifecycleError(
                "config.yml: merged top-level mappings cannot be edited safely"
            )
        if key.value == OMP_DISABLED_KEY:
            if not isinstance(value, SequenceNode) or any(
                not isinstance(item, ScalarNode) or item.tag != "tag:yaml.org,2002:str"
                for item in value.value
            ):
                raise LifecycleError(
                    f"config.yml: {OMP_DISABLED_KEY} must be a list of strings"
                )
            disabled = value
            values = [item.value for item in value.value]
    # An alias may point outside the target key, or other keys may alias it.
    # Editing that shared node would alter a foreign key's effective value.
    if disabled is not None:
        tokens = list(yaml.scan(text))
        if any(
            isinstance(token, (yaml.tokens.AnchorToken, yaml.tokens.AliasToken))
            and disabled.start_mark.index
            <= token.start_mark.index
            < disabled.end_mark.index
            for token in tokens
        ):
            raise LifecycleError(
                "config.yml: aliased disabledExtensions cannot be edited safely"
            )
        references = 0
        visited: set[int] = set()

        def count_references(current: Node) -> None:
            nonlocal references
            if current is disabled:
                references += 1
            if id(current) in visited:
                return
            visited.add(id(current))
            if isinstance(current, MappingNode):
                for child_key, child_value in current.value:
                    count_references(child_key)
                    count_references(child_value)
            elif isinstance(current, SequenceNode):
                for child in current.value:
                    count_references(child)

        count_references(node)
        if references != 1:
            raise LifecycleError(
                "config.yml: shared disabledExtensions cannot be edited safely"
            )
    return text, node, disabled, values


def _flow_separator(text: str, offset: int, has_values: bool) -> str:
    tokens = [token for token in yaml.scan(text) if token.end_mark.index <= offset]
    trailing_comma = bool(tokens) and isinstance(tokens[-1], yaml.tokens.FlowEntryToken)
    return "" if not has_values or trailing_comma else ", "


def _yaml_line_end(text: str, mark: Mark) -> int:
    # Block scalars can end at the next key rather than on their content line.
    if mark.column == 0:
        return mark.index
    newline = text.find("\n", mark.index)
    return len(text) if newline < 0 else newline + 1


def _omp_add(image: dict[str, Any], entry: str) -> dict[str, Any]:
    text, node, sequence, values = _omp_data(image)
    if entry in values:
        raise LifecycleError(
            f"config.yml already disables {entry} through configuration Armory does not own"
        )
    literal = json.dumps(entry)
    if sequence is not None:
        if sequence.flow_style:
            offset = sequence.end_mark.index - 1
            separator = _flow_separator(text, offset, bool(values))
            updated = text[:offset] + separator + literal + text[offset:]
        else:
            offset = _yaml_line_end(text, sequence.value[-1].end_mark)
            indent = next(
                token.start_mark.column
                for token in yaml.scan(text)
                if isinstance(token, yaml.tokens.BlockEntryToken)
                and sequence.start_mark.index
                <= token.start_mark.index
                < sequence.end_mark.index
            )
            line = " " * indent + "- " + literal + "\n"
            updated = (
                text[:offset]
                + ("\n" if offset and text[offset - 1] != "\n" else "")
                + line
                + text[offset:]
            )
    elif node is not None and node.flow_style:
        offset = node.end_mark.index - 1
        separator = _flow_separator(text, offset, bool(node.value))
        updated = (
            text[:offset]
            + separator
            + OMP_DISABLED_KEY
            + ": ["
            + literal
            + "]"
            + text[offset:]
        )
    else:
        ends = [
            token.start_mark.index
            for token in yaml.scan(text)
            if isinstance(token, yaml.tokens.DocumentEndToken)
        ]
        offset = ends[0] if ends else len(text)
        indent = (
            " " * node.value[0][0].start_mark.column
            if node is not None and node.value
            else ""
        )
        updated = (
            text[:offset]
            + ("\n" if offset and text[offset - 1] != "\n" else "")
            + indent
            + OMP_DISABLED_KEY
            + ": ["
            + literal
            + "]\n"
            + text[offset:]
        )
    return _edited_image(image, updated)


def _omp_drop_owned_key(text: str, node: MappingNode, sequence: SequenceNode) -> str:
    members = node.value
    index = next(
        index
        for index, (key, _value) in enumerate(members)
        if key.value == OMP_DISABLED_KEY
    )
    key = members[index][0]
    start, end = key.start_mark.index, sequence.end_mark.index
    if "#" in text[start:end]:
        raise LifecycleError(
            "owned disable key contains new comments; retaining configuration unchanged"
        )
    if node.flow_style:
        if index + 1 < len(members):
            comma = text.index(",", end, members[index + 1][0].start_mark.index)
            return text[:start] + text[end:comma] + text[comma + 1 :]
        if index:
            comma = text.index(",", members[index - 1][1].end_mark.index, start)
            return text[:comma] + text[comma + 1 : start] + text[end:]
        return text[:start] + text[end:]
    start = text.rfind("\n", 0, start) + 1
    if sequence.end_mark.column != 0:
        newline = text.find("\n", end)
        line_end = len(text) if newline < 0 else newline + 1
        tail = text[end:line_end]
        if "#" in tail:
            raise LifecycleError(
                "owned disable key contains a new comment; retaining configuration unchanged"
            )
        end = line_end
    return text[:start] + text[end:]


def _omp_remove(image: dict[str, Any], registration: dict[str, Any]) -> dict[str, Any]:
    text, node, sequence, values = _omp_data(image)
    entry = registration["entry"]
    if values.count(entry) != 1 or sequence is None or node is None:
        raise LifecycleError(
            f"config.yml: owned disable registration {entry} is missing or duplicated"
        )
    index = values.index(entry)
    item = sequence.value[index]
    if len(values) == 1 and registration["created_key"]:
        updated = _omp_drop_owned_key(text, node, sequence)
        return _edited_image(
            image, None if registration["created_file"] and not updated else updated
        )
    if len(values) == 1:
        # Keep any foreign comments; only the owned list value changes.
        if sequence.flow_style:
            updated = text[: item.start_mark.index] + text[item.end_mark.index :]
        else:
            start = text.rfind("\n", 0, item.start_mark.index) + 1
            end = _yaml_line_end(text, item.end_mark)
            tail = text[item.end_mark.index : end]
            comment = tail[tail.index("#") :] if "#" in tail else ""
            updated = (
                text[:start]
                + " " * max(item.start_mark.column - 2, 2)
                + "[]"
                + (" " + comment if comment else "\n")
                + text[end:]
            )
    elif sequence.flow_style:
        if index + 1 < len(values):
            comma = text.index(
                ",", item.end_mark.index, sequence.value[index + 1].start_mark.index
            )
            updated = (
                text[: item.start_mark.index]
                + text[item.end_mark.index : comma]
                + text[comma + 1 :]
            )
        else:
            comma = text.index(
                ",", sequence.value[index - 1].end_mark.index, item.start_mark.index
            )
            updated = (
                text[:comma]
                + text[comma + 1 : item.start_mark.index]
                + text[item.end_mark.index :]
            )
    else:
        start = text.rfind("\n", 0, item.start_mark.index) + 1
        end = _yaml_line_end(text, item.end_mark)
        tail = text[item.end_mark.index : end]
        comment = tail[tail.index("#") :] if "#" in tail else ""
        updated = (
            text[:start]
            + (" " * max(item.start_mark.column - 2, 0) + comment if comment else "")
            + text[end:]
        )
    return _edited_image(image, updated)


def _registration_add(
    layout: HostLayout, image: dict[str, Any], origin: dict[str, Any] | None = None
) -> tuple[dict[str, Any], dict[str, Any]]:
    origin = image if origin is None else origin
    if layout.host == "omp":
        _text, _node, original_sequence, _values = _omp_data(origin)
        after = _omp_add(image, layout.omp_disabled_id)
        registration = {
            "file": OMP_CONFIG,
            "entry": layout.omp_disabled_id,
            "created_file": origin["data"] is None,
            "created_key": original_sequence is None,
            "before": image,
            "after": after,
            "origin": origin,
        }
    else:
        entry = str(layout.payload)
        if os.pathsep in entry:
            raise LifecycleError(
                f"{entry} cannot be represented in {CLAUDE_PLUGIN_DIRS_KEY}"
            )
        text, data, start = _claude_data(image)
        _origin_text, original_data, _origin_start = _claude_data(origin)
        env = data.get("env", {})
        previous = env.get(CLAUDE_PLUGIN_DIRS_KEY)
        if previous is not None and entry in previous.split(os.pathsep):
            raise LifecycleError(
                f"settings.json: {entry} is already registered by configuration Armory does not own"
            )
        value = entry if previous is None else previous + os.pathsep + entry
        if "env" in data:
            env_start = _json_members(text, start)["env"][1]
            updated = _json_set(text, env_start, CLAUDE_PLUGIN_DIRS_KEY, value)
        else:
            updated = _json_set(text, start, "env", {CLAUDE_PLUGIN_DIRS_KEY: value})
        after = _edited_image(image, updated)
        registration = {
            "file": CLAUDE_SETTINGS,
            "entry": entry,
            "created_file": origin["data"] is None,
            "created_env": "env" not in original_data,
            "created_key": CLAUDE_PLUGIN_DIRS_KEY not in original_data.get("env", {}),
            "previous_value": previous,
            "before": image,
            "after": after,
            "origin": origin,
        }
    return after, registration


def _undo_registration_bytes(
    layout: HostLayout, image: dict[str, Any], registration: dict[str, Any]
) -> dict[str, Any] | None:
    """Undo the recorded splice when sibling edits left that splice intact."""
    if image == registration["after"]:
        preimage: dict[str, Any] = copy.deepcopy(registration["before"])
        return preimage
    before, after = (_config_text(registration[key]) for key in ("before", "after"))
    start = 0
    while start < min(len(before), len(after)) and before[start] == after[start]:
        start += 1
    suffix = 0
    while (
        suffix < min(len(before) - start, len(after) - start)
        and before[-suffix - 1] == after[-suffix - 1]
    ):
        suffix += 1
    fragment = after[start : len(after) - suffix if suffix else len(after)]
    previous = before[start : len(before) - suffix if suffix else len(before)]
    text = _config_text(image)
    if not fragment or text.count(fragment) != 1:
        return None
    updated = _edited_image(image, text.replace(fragment, previous, 1))
    try:
        if layout.host == "omp":
            _text, _node, _sequence, entries = _omp_data(updated)
            absent = layout.omp_disabled_id not in entries
        else:
            _text, data, _start = _claude_data(updated)
            value = data.get("env", {}).get(CLAUDE_PLUGIN_DIRS_KEY, "")
            absent = str(layout.payload) not in value.split(os.pathsep)
    except LifecycleError:
        return None
    return updated if absent else None


def _registration_remove(
    layout: HostLayout, image: dict[str, Any], registration: dict[str, Any]
) -> dict[str, Any]:
    restored = _undo_registration_bytes(layout, image, registration)
    if restored is not None:
        return restored
    if layout.host == "omp":
        return _omp_remove(image, registration)
    text, data, start = _claude_data(image)
    env = data.get("env", {})
    value = env.get(CLAUDE_PLUGIN_DIRS_KEY)
    entries = [] if value is None else value.split(os.pathsep)
    if entries.count(registration["entry"]) != 1:
        raise LifecycleError(
            "settings.json: owned plugin registration is missing or duplicated"
        )
    entries.pop(entries.index(registration["entry"]))
    env_start = _json_members(text, start)["env"][1]
    remove_key = not entries and registration["created_key"]
    updated = _json_set(
        text,
        env_start,
        CLAUDE_PLUGIN_DIRS_KEY,
        os.pathsep.join(entries),
        remove=remove_key,
    )
    if remove_key and registration["created_env"] and len(env) == 1:
        updated = _json_set(updated, start, "env", None, remove=True)
    if registration["created_file"] and json.loads(updated) == {}:
        return _edited_image(image, None)
    return _edited_image(image, updated)


def _validate_registration(layout: HostLayout, registration: Any) -> None:
    common = {
        "file",
        "entry",
        "created_file",
        "created_key",
        "before",
        "after",
        "origin",
    }
    keys = common | (
        set() if layout.host == "omp" else {"created_env", "previous_value"}
    )
    if not isinstance(registration, dict) or set(registration) != keys:
        raise LifecycleError("malformed registration ownership")
    flags = (
        ("created_file", "created_key")
        if layout.host == "omp"
        else ("created_file", "created_key", "created_env")
    )
    if any(type(registration[key]) is not bool for key in flags):
        raise LifecycleError("malformed registration ownership flags")
    for field in ("before", "after", "origin"):
        _validate_image(registration[field])
    # Recompute the exact owned edit, including preexisting empty path segments.
    _after, expected = _registration_add(
        layout, registration["before"], registration["origin"]
    )
    if registration != expected:
        raise LifecycleError(
            "registration preimage, path or configuration binding mismatch"
        )


def _registration_origin(layout: HostLayout, image: dict[str, Any]) -> dict[str, Any]:
    directory = layout.ownership.parent
    _refuse_symlinks(layout.root, directory)
    inherited: dict[str, Any] | None = None
    if directory.exists():
        for path in sorted(directory.iterdir()):
            prefix = f"{layout.host}-"
            if not path.name.startswith(prefix) or not path.name.endswith(".json"):
                continue
            name = path.name[len(prefix) : -5]
            if not is_feature_name(name):
                continue
            other = HostLayout(layout.root, layout.host, name)
            record = read_ownership(other)
            if record is None:
                continue
            if record["pending"] is not None:
                raise LifecycleError(
                    "unresolved other-feature journal; refusing to inherit configuration provenance"
                )
            if record["registration"] is None:
                continue
            registration = record["registration"]
            _require_registration_state(other, record, image)
            if any(
                registration[key] for key in ("created_file", "created_key")
            ) or registration.get("created_env", False):
                if inherited is not None and inherited != registration["origin"]:
                    raise LifecycleError(
                        "ambiguous shared-container provenance; nothing was changed"
                    )
                inherited = registration["origin"]
    return image if inherited is None else inherited


def _require_registration_state(
    layout: HostLayout, record: dict[str, Any], image: dict[str, Any]
) -> None:
    if layout.host == "omp":
        _text, _node, _sequence, values = _omp_data(image)
        count = values.count(layout.omp_disabled_id)
        expected = record["state"] == "disabled"
    else:
        _text, data, _start = _claude_data(image)
        value = data.get("env", {}).get(CLAUDE_PLUGIN_DIRS_KEY, "")
        count = value.split(os.pathsep).count(str(layout.payload))
        expected = record["state"] == "enabled"
    if count != int(expected):
        raise LifecycleError(
            "host registration changed or is foreign; nothing was changed"
        )


def _validate_record(
    layout: HostLayout, record: Any, *, pending_allowed: bool = True
) -> None:
    if not isinstance(record, dict) or set(record) != _RECORD_KEYS:
        raise LifecycleError("malformed or unknown ownership schema")
    expected = {
        "schema_version": OWNERSHIP_SCHEMA,
        "feature": layout.feature,
        "host": layout.host,
        "target_root": str(layout.root),
        "payload": layout.payload_rel,
    }
    if type(record["schema_version"]) is not int or any(
        record[key] != value for key, value in expected.items()
    ):
        raise LifecycleError(
            f"ownership record does not match {layout.host}/{layout.feature} in {layout.root}"
        )
    if (
        not isinstance(record["version"], str)
        or not _VERSION.fullmatch(record["version"])
        or record["state"] not in ("enabled", "disabled")
    ):
        raise LifecycleError("malformed owned version or state")
    _validate_files(record["files"])
    if record["content_manifest_sha256"] != record["files"][CONTENT_MANIFEST]:
        raise LifecycleError("ownership content manifest digest binding mismatch")
    registration_required = (layout.host == "claude") == (record["state"] == "enabled")
    if registration_required:
        _validate_registration(layout, record["registration"])
    elif record["registration"] is not None:
        raise LifecycleError("registration does not match host enablement state")
    if record["pending"] is not None:
        if not pending_allowed:
            raise LifecycleError("nested pending ownership journal")
        _validate_pending(layout, record)


def read_ownership(layout: HostLayout) -> dict[str, Any] | None:
    if not _regular(layout.root, layout.ownership):
        return None
    try:
        record: dict[str, Any] = json.loads(layout.ownership.read_bytes())
    except (ValueError, UnicodeDecodeError) as exc:
        raise LifecycleError(
            f"{layout.ownership}: unreadable ownership record: {exc}"
        ) from exc
    _validate_record(layout, record)
    return record


def _write_ownership(layout: HostLayout, record: dict[str, Any]) -> None:
    _ensure_dir(layout.root, layout.ownership.parent)
    _regular(layout.root, layout.ownership)
    data = (json.dumps(record, indent=2, sort_keys=True) + "\n").encode("utf-8")
    _write_atomic(layout.ownership, data, 0o600)


def _new_record(
    layout: HostLayout, manifest: dict[str, Any], files: dict[str, str]
) -> dict[str, Any]:
    return {
        "schema_version": OWNERSHIP_SCHEMA,
        "feature": layout.feature,
        "host": layout.host,
        "target_root": str(layout.root),
        "payload": layout.payload_rel,
        "version": manifest["version"],
        "content_manifest_sha256": files[CONTENT_MANIFEST],
        "files": files,
        "state": "enabled",
        "registration": None,
        "pending": None,
    }


def _require_omp_slot(layout: HostLayout, *, installing: bool) -> None:
    for suffix in (".ts", ".js"):
        collision = layout.root / "extensions" / f"{layout.feature}{suffix}"
        _refuse_symlinks(layout.root, collision)
        if collision.exists():
            raise LifecycleError(
                f"{collision} would share the OMP extension name '{layout.feature}'"
            )
    if installing:
        _text, _node, _sequence, values = _omp_data(_image(layout.root, layout.config))
        if layout.omp_disabled_id in values:
            raise LifecycleError(
                f"config.yml already disables {layout.omp_disabled_id} through configuration Armory does not own"
            )


def _new_stage(layout: HostLayout) -> Path:
    _ensure_dir(layout.root, layout.staging)
    stage = layout.staging / f"{layout.host}-{layout.feature}-{uuid.uuid4().hex}"
    stage.mkdir(mode=0o700)
    _sync_dir(layout.staging)
    return stage


def _stage_payload(
    layout: HostLayout, feature_dir: Path
) -> tuple[Path, dict[str, Any], dict[str, str]]:
    try:
        _metadata, artifacts = assemble_feature(feature_dir)
        if layout.host not in artifacts:
            raise LifecycleError(
                f"{layout.feature} does not support host '{layout.host}'"
            )
        stage = _new_stage(layout)
        write_tree(artifacts[layout.host], stage / "payload")
        manifest = verify_artifact_dir(stage / "payload")
    except BuildError as exc:
        raise LifecycleError(f"cannot build {layout.feature}: {exc}") from exc
    if manifest["feature"] != layout.feature or manifest["host"] != layout.host:
        raise LifecycleError(
            "staged artifact identity does not match the requested feature and host"
        )
    files = {
        path.relative_to(stage / "payload").as_posix(): _sha256(path.read_bytes())
        for path in (stage / "payload").rglob("*")
        if path.is_file()
    }
    _validate_files(files)
    _require_tree(layout.root, stage / "payload", files)
    for name in files:
        descriptor = os.open(stage / "payload" / name, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    for directory, _dirs, _files in os.walk(stage / "payload", topdown=False):
        _sync_dir(Path(directory))
    _sync_dir(stage)
    return stage, manifest, files


def _config_plan(
    layout: HostLayout,
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
    image: dict[str, Any],
) -> dict[str, Any]:
    if (
        before is not None
        and before["registration"] is not None
        and (after is None or after["registration"] != before["registration"])
    ):
        image = _registration_remove(layout, image, before["registration"])
    if (
        after is not None
        and after["registration"] is not None
        and (before is None or after["registration"] != before["registration"])
    ):
        image, registration = _registration_add(
            layout, image, after["registration"]["origin"]
        )
        if registration != after["registration"]:
            raise LifecycleError(
                "pending registration does not match the configuration transition"
            )
    return image


def _validate_pending(layout: HostLayout, record: dict[str, Any]) -> None:
    pending = record["pending"]
    keys = {
        "schema_version",
        "action",
        "phase",
        "staged",
        "before",
        "after",
        "ownership_before",
        "config_before",
        "config_after",
    }
    if (
        not isinstance(pending, dict)
        or set(pending) != keys
        or type(pending["schema_version"]) is not int
        or pending["schema_version"] != 1
    ):
        raise LifecycleError("malformed or unknown pending transaction schema")
    action = pending["action"]
    if action not in ("install", "update", "disable", "re-enable", "remove") or pending[
        "phase"
    ] not in ("prepared", "committed", "rolled-back"):
        raise LifecycleError("unknown pending action or phase")
    relative = pending["staged"]
    prefix = f"{STATE_DIR}/staging/{layout.host}-{layout.feature}-"
    if (
        not isinstance(relative, str)
        or not relative.startswith(prefix)
        or not re.fullmatch(r"[0-9a-f]{32}", relative[len(prefix) :])
    ):
        raise LifecycleError("unsafe pending staging path")
    _refuse_symlinks(layout.root, layout.root / relative)
    before, after = pending["before"], pending["after"]
    for value in (before, after):
        if value is not None:
            _validate_record(layout, value, pending_allowed=False)
    for key in ("ownership_before", "config_before", "config_after"):
        _validate_image(pending[key])
    preimage = _image_bytes(pending["ownership_before"])
    if before is None:
        if preimage is not None:
            raise LifecycleError("install journal has an ownership preimage")
    else:
        try:
            if preimage is None or json.loads(preimage) != before:
                raise LifecycleError("ownership preimage does not match pending record")
        except (ValueError, UnicodeDecodeError) as exc:
            raise LifecycleError("malformed ownership preimage") from exc
    if action == "install":
        valid = before is None and after is not None and after["state"] == "enabled"
    elif action == "remove":
        valid = before is not None and after is None
    elif before is None or after is None:
        valid = False
    elif action == "update":
        valid = (before["state"], before["registration"]) == (
            after["state"],
            after["registration"],
        ) and _semver(after["version"]) >= _semver(before["version"])
    else:
        expected_before, expected_after = (
            ("enabled", "disabled") if action == "disable" else ("disabled", "enabled")
        )
        valid = (
            before["state"] == expected_before
            and after["state"] == expected_after
            and all(
                before[key] == after[key]
                for key in _RECORD_KEYS - {"state", "registration"}
            )
        )
    if not valid:
        raise LifecycleError("pending action and ownership transition do not match")
    base = copy.deepcopy(before if before is not None else after)
    base["pending"] = pending
    if record != base:
        raise LifecycleError("pending journal is not bound to its ownership record")
    planned = _config_plan(layout, before, after, pending["config_before"])
    if planned != pending["config_after"]:
        raise LifecycleError(
            "pending configuration preimage/postimage binding mismatch"
        )
    # Parse even unchanged configs before any mutation or cleanup.
    for key in ("config_before", "config_after"):
        if layout.host == "omp":
            _omp_data(pending[key])
        else:
            _claude_data(pending[key])
    if before is not None:
        _require_registration_state(layout, before, pending["config_before"])
    if after is not None:
        _require_registration_state(layout, after, pending["config_after"])


def _stage_trees(
    layout: HostLayout, pending: dict[str, Any], *, partial: bool
) -> dict[str, dict[str, str]]:
    stage = layout.root / pending["staged"]
    _refuse_symlinks(layout.root, stage)
    if not stage.exists():
        return {}
    if not stage.is_dir():
        raise LifecycleError("pending staging path is not a directory")
    allowed: dict[str, dict[str, str]] = {}
    if pending["action"] in ("install", "update"):
        allowed["payload"] = pending["after"]["files"]
    if pending["action"] in ("update", "remove"):
        allowed["retired"] = pending["before"]["files"]
    found: dict[str, dict[str, str]] = {}
    for child in stage.iterdir():
        if child.name not in allowed:
            raise LifecycleError(
                f"foreign pending staging data at {child}; retaining journal and all trees"
            )
        owned = pending["after"] if child.name == "payload" else pending["before"]
        _require_record_tree(layout, child, owned, partial=partial)
        found[child.name] = allowed[child.name]
    return found


def _cleanup_stage(layout: HostLayout, pending: dict[str, Any]) -> None:
    stage = layout.root / pending["staged"]
    trees = _stage_trees(layout, pending, partial=True)
    for name, files in trees.items():
        _erase_tree(layout, stage / name, files)
    if stage.exists():
        stage.rmdir()
        _sync_dir(stage.parent)


def _journal_record(pending: dict[str, Any]) -> dict[str, Any]:
    record: dict[str, Any] = copy.deepcopy(
        pending["before"] if pending["before"] is not None else pending["after"]
    )
    record["pending"] = pending
    return record


def _finish_journal(
    layout: HostLayout, pending: dict[str, Any]
) -> dict[str, Any] | None:
    committed = pending["phase"] == "committed"
    expected: dict[str, Any] | None = (
        pending["after"] if committed else pending["before"]
    )
    config = pending["config_after"] if committed else pending["config_before"]
    if _image(layout.root, layout.config) != config:
        raise LifecycleError(
            "configuration changed during recovery; retaining journal and all trees"
        )
    _refuse_symlinks(layout.root, layout.payload)
    if expected is None:
        if layout.payload.exists():
            raise LifecycleError(
                "unexpected payload during recovery; retaining journal and all trees"
            )
    else:
        _require_record_tree(layout, layout.payload, expected)
    _stage_trees(layout, pending, partial=True)
    _cleanup_stage(layout, pending)
    if committed:
        if expected is None:
            _put_image(
                layout, layout.ownership, {"data": None, "sha256": None, "mode": None}
            )
        else:
            _write_ownership(layout, expected)
    else:
        _put_image(layout, layout.ownership, pending["ownership_before"])
    return copy.deepcopy(expected)


def recover_pending(
    layout: HostLayout, record: dict[str, Any]
) -> tuple[dict[str, Any] | None, str]:
    """Recover only a fully validated journal; ambiguity is never discarded."""
    _validate_record(layout, record)
    pending = record["pending"]
    if pending is None:
        return record, ""
    if pending["phase"] != "prepared":
        result = _finish_journal(layout, pending)
        verb = "completed" if pending["phase"] == "committed" else "rolled back"
        return result, f"{verb} an interrupted {pending['action']}"
    stage = layout.root / pending["staged"]
    trees = _stage_trees(layout, pending, partial=False)
    if not stage.is_dir():
        raise LifecycleError("pending staging directory is missing; retaining journal")
    current_config = _image(layout.root, layout.config)
    if current_config not in (pending["config_before"], pending["config_after"]):
        raise LifecycleError(
            "configuration changed during recovery; retaining journal and all trees"
        )
    _refuse_symlinks(layout.root, layout.payload)
    before, after = pending["before"], pending["after"]
    action = pending["action"]
    exists = layout.payload.exists()
    if action == "install":
        if exists:
            _require_record_tree(layout, layout.payload, after)
            if "payload" in trees:
                raise LifecycleError(
                    "ambiguous install has two payloads; retaining journal and all trees"
                )
        elif "payload" not in trees:
            raise LifecycleError(
                "interrupted install payload is missing; retaining journal"
            )
    elif action == "update":
        if "retired" in trees:
            if exists:
                _require_record_tree(layout, layout.payload, after)
                if "payload" in trees:
                    raise LifecycleError(
                        "ambiguous update has two new payloads; retaining journal and all trees"
                    )
            elif "payload" not in trees:
                raise LifecycleError(
                    "interrupted update has lost its new payload; retaining journal"
                )
        else:
            _require_record_tree(layout, layout.payload, before)
            if "payload" not in trees:
                raise LifecycleError(
                    "interrupted update has no rollback source; retaining journal"
                )
    elif action == "remove":
        if "retired" in trees:
            if exists:
                raise LifecycleError(
                    "ambiguous removal has two payloads; retaining journal and all trees"
                )
        else:
            _require_record_tree(layout, layout.payload, before)
    else:
        _require_record_tree(layout, layout.payload, before)
    # Every tree/configuration has been checked before the first recovery write.
    if action == "install" and exists:
        _rename(layout.payload, stage / "payload")
    elif action == "update" and "retired" in trees:
        if exists:
            _rename(layout.payload, stage / "payload")
        _rename(stage / "retired", layout.payload)
    elif action == "remove" and "retired" in trees:
        _rename(stage / "retired", layout.payload)
    if current_config != pending["config_before"]:
        _put_image(layout, layout.config, pending["config_before"])
    pending = {**pending, "phase": "rolled-back"}
    _write_ownership(layout, _journal_record(pending))
    result = _finish_journal(layout, pending)
    return result, f"rolled back an interrupted {action}"


def _recover_root(root: Path) -> list[tuple[HostLayout, str]]:
    directory = root / STATE_DIR / "ownership"
    _refuse_symlinks(root, directory)
    if not directory.exists():
        return []
    if not directory.is_dir():
        raise LifecycleError(f"{directory} is not a regular directory")
    records: list[tuple[HostLayout, dict[str, Any]]] = []
    for path in sorted(directory.iterdir()):
        match = re.fullmatch(r"(omp|claude)-(.+)\.json", path.name)
        if match is None or not is_feature_name(match[2]):
            continue
        layout = HostLayout(root, match[1], match[2])
        record = read_ownership(layout)
        if record is not None and record["pending"] is not None:
            records.append((layout, record))
    # Read and validate all records first. A malformed journal never permits a
    # different feature to alter the shared config before it is diagnosed.
    notes = []
    for layout, record in records:
        _result, note = recover_pending(layout, record)
        notes.append((layout, note))
    return notes


def _semver(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split("."))


def _transact(
    layout: HostLayout,
    action: str,
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
    stage: Path,
    config_before: dict[str, Any],
    config_after: dict[str, Any],
) -> None:
    _ensure_dir(layout.root, layout.payload.parent)
    pending = {
        "schema_version": 1,
        "action": action,
        "phase": "prepared",
        "staged": stage.relative_to(layout.root).as_posix(),
        "before": before,
        "after": after,
        "ownership_before": _image(layout.root, layout.ownership),
        "config_before": config_before,
        "config_after": config_after,
    }
    journal = _journal_record(pending)
    _validate_record(layout, journal)
    if _image(layout.root, layout.config) != config_before:
        raise LifecycleError(
            "configuration changed before activation; nothing was changed"
        )
    _stage_trees(layout, pending, partial=False)
    if before is None:
        _refuse_symlinks(layout.root, layout.payload)
        if layout.payload.exists():
            raise LifecycleError(
                "foreign payload appeared before activation; nothing was changed"
            )
    else:
        _require_record_tree(layout, layout.payload, before)
    _write_ownership(layout, journal)
    try:
        if action in ("update", "remove"):
            _rename(layout.payload, stage / "retired")
        if action in ("install", "update"):
            _rename(stage / "payload", layout.payload)
        if config_before != config_after:
            _put_image(layout, layout.config, config_after)
        # Persist the desired record through the existing write boundary while
        # retaining the journal until garbage collection has completed.
        committed = {**pending, "phase": "committed"}
        _write_ownership(layout, _journal_record(committed))
        _finish_journal(layout, committed)
    except Exception:
        # An actual process exit/BaseException leaves a durable journal. An
        # ordinary failure rolls back only if its pre/postimages still match.
        on_disk = read_ownership(layout)
        if on_disk is not None and on_disk["pending"] is not None:
            recover_pending(layout, on_disk)
        raise


def run_action(
    action: str, host: str, name: str, target_root: Path, source_root: Path
) -> str:
    """Run one explicit lifecycle operation; install also re-enables a feature."""
    if action not in NATIVE_ACTIONS:
        raise LifecycleError(
            f"unsupported action '{action}' (supported: {', '.join(NATIVE_ACTIONS)})"
        )
    if host not in NATIVE_HOSTS:
        raise LifecycleError(
            f"unsupported platform '{host}' (supported: {', '.join(NATIVE_HOSTS)})"
        )
    if not is_feature_name(name):
        raise LifecycleError(f"'{name}' is not a valid kebab-case feature name")
    layout = HostLayout(resolve_target_root(target_root), host, name)
    if host == "claude" and os.pathsep in str(layout.payload):
        raise LifecycleError(
            f"{layout.payload} cannot be represented in {CLAUDE_PLUGIN_DIRS_KEY}"
        )
    with _root_lock(layout.root):
        _refuse_symlinks(layout.root, layout.payload)
        _regular(layout.root, layout.config)
        notes = [
            note
            for recovered, note in _recover_root(layout.root)
            if recovered == layout
        ]
        before = read_ownership(layout)
        config_before = _image(layout.root, layout.config)
        if host == "omp":
            _omp_data(config_before)
            _require_omp_slot(layout, installing=before is None)
        else:
            _claude_data(config_before)
        if before is not None:
            _require_record_tree(layout, layout.payload, before)
            _require_registration_state(layout, before, config_before)
        elif action != "install":
            raise LifecycleError(f"{name} is not installed for {host} in {layout.root}")
        elif layout.payload.exists():
            raise LifecycleError(
                f"{layout.payload} exists but is not owned by Armory; refusing to overwrite it"
            )
        if action == "install" and before is not None and before["state"] == "enabled":
            raise LifecycleError(
                f"{name} is already installed for {host}; use --action update"
            )
        if action == "disable" and before is not None and before["state"] == "disabled":
            raise LifecycleError(f"{name} is already disabled for {host}")
        after = copy.deepcopy(before)
        config_after = config_before
        stage: Path | None = None
        transaction_action = action
        if action == "install":
            if before is None:
                # Registration refusal precedes even staging or journal creation.
                registration = None
                if host == "claude":
                    config_after, registration = _registration_add(
                        layout,
                        config_before,
                        _registration_origin(layout, config_before),
                    )
                try:
                    feature_dir = resolve_feature_dir(name, source_root)
                except BuildError as exc:
                    raise LifecycleError(str(exc)) from exc
                stage, manifest, files = _stage_payload(layout, feature_dir)
                after = _new_record(layout, manifest, files)
                after["registration"] = registration
                outcome = f"installed {name} {after['version']} for {host} at {layout.payload}"
            else:
                transaction_action = "re-enable"
                assert after is not None
                if host == "claude":
                    config_after, after["registration"] = _registration_add(
                        layout,
                        config_before,
                        _registration_origin(layout, config_before),
                    )
                else:
                    config_after = _registration_remove(
                        layout, config_before, before["registration"]
                    )
                    after["registration"] = None
                after["state"] = "enabled"
                outcome = f"re-enabled {name} {after['version']} for {host}"
        elif action == "update":
            assert before is not None and after is not None
            try:
                feature_dir = resolve_feature_dir(name, source_root)
            except BuildError as exc:
                raise LifecycleError(str(exc)) from exc
            stage, manifest, files = _stage_payload(layout, feature_dir)
            if files[CONTENT_MANIFEST] == before["content_manifest_sha256"]:
                _erase_tree(layout, stage / "payload", files)
                stage.rmdir()
                return "; ".join(
                    [
                        *notes,
                        f"{name} {before['version']} for {host} is already current",
                    ]
                )
            if _semver(manifest["version"]) < _semver(before["version"]):
                _erase_tree(layout, stage / "payload", files)
                stage.rmdir()
                raise LifecycleError(
                    f"refusing to downgrade {name} from {before['version']} to {manifest['version']}"
                )
            after.update(
                version=manifest["version"],
                files=files,
                content_manifest_sha256=files[CONTENT_MANIFEST],
            )
            outcome = f"updated {name} for {host} from {before['version']} to {manifest['version']}"
        elif action == "disable":
            assert before is not None and after is not None
            if host == "claude":
                config_after = _registration_remove(
                    layout, config_before, before["registration"]
                )
                after["registration"] = None
            else:
                config_after, after["registration"] = _registration_add(
                    layout, config_before, _registration_origin(layout, config_before)
                )
            after["state"] = "disabled"
            outcome = f"disabled {name} for {host}; files and data are kept"
        else:
            assert before is not None
            if before["registration"] is not None:
                config_after = _registration_remove(
                    layout, config_before, before["registration"]
                )
            after = None
            outcome = f"removed {name} {before['version']} for {host}"
        if stage is None:
            stage = _new_stage(layout)
        _transact(
            layout,
            transaction_action,
            before,
            after,
            stage,
            config_before,
            config_after,
        )
        return "; ".join([*notes, outcome])
