#!/usr/bin/env python3
"""Validate an Ubuntu Core model assertion before you try to sign or build with it.

Scope is UC20 and later. Ubuntu Core 16/18 models are end-of-life and are
rejected with a migration path rather than validated.

Three independent layers, because each catches a different class of mistake:

  structural  - headers and types that snapd's own assembler enforces
                (asserts/model.go). Catching these here gives line-level,
                actionable messages instead of one opaque "cannot assemble" error.
  semantic    - things snapd happily signs but that break later: a snap-id that
                belongs to a different snap, a channel/track that does not exist,
                an architecture the kernel was never built for. snap sign does
                NOT catch any of these.
  advisory    - style and operational risk: dangerous grade, stale timestamp,
                a channel that silently falls back to a more stable risk.

Usage:
  validate_model.py MODEL.json                 # structural + advisory, offline
  validate_model.py MODEL.json --online        # also verify snap-ids/channels against the store
  validate_model.py MODEL.json --sign-check -k KEY   # also round-trip through `snap sign`
  validate_model.py MODEL.json --json          # machine-readable findings

Exit codes: 0 = no errors, 1 = at least one ERROR, 2 = could not read input.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request

STORE_INFO = "https://api.snapcraft.io/v2/snaps/info/{name}"
STORE_HEADERS = {"Snap-Device-Series": "16"}
ARCHITECTURES = {"amd64", "arm64", "armhf", "i386", "ppc64el", "s390x", "riscv64"}
GRADES = {"dangerous", "signed", "secured"}
SNAP_TYPES = {"app", "base", "gadget", "kernel", "snapd", "core"}
PRESENCE = {"required", "optional"}
MODES = {"run", "ephemeral", "recover", "factory-reset"}

# UC20+ bases are core20, core22, core24, core26, ... - the track is derived
# from the number, see base_track(). These two belong to end-of-life releases.
EOL_BASES = {"core", "core18"}

NAME_RE = re.compile(r"^(?:[a-z0-9]+-?)*[a-z](?:-?[a-z0-9])*$")
MODEL_RE = re.compile(r"^[a-z0-9](?:-?[a-z0-9])*$")
SNAP_ID_RE = re.compile(r"^[a-zA-Z0-9]{32}$")
ACCOUNT_ID_RE = re.compile(r"^[a-z0-9](?:-?[a-z0-9])*$", re.IGNORECASE)

ESSENTIAL_TYPES = {"snapd", "kernel", "boot-base", "gadget", "base", "core"}

# Rather than hardcoding a list of bases that goes stale every six months,
# derive the expected kernel/gadget track from the base name: core24 -> 24,
# core26 -> 26, and whatever comes next works without an edit here.
BASE_RE = re.compile(r"^core(\d+)$")


def base_track(base: str | None) -> str | None:
    match = BASE_RE.match(str(base or ""))
    return match.group(1) if match else None


# Ordered most stable first. The store resolves a risk with no release of its
# own by walking towards stable, never away from it.
RISKS = ["stable", "candidate", "beta", "edge"]


def split_channel(channel: str) -> tuple[str, str]:
    """Split a channel spec into (track, risk) the way snapd does.

    A bare word is ambiguous: "edge" means latest/edge, while "26" means
    26/stable. snapd disambiguates by checking whether the word is a known
    risk, and getting this backwards turns a valid channel into a phantom
    error.
    """
    parts = channel.split("/")
    if len(parts) == 1:
        return ("latest", parts[0]) if parts[0] in RISKS else (parts[0], "stable")
    # A third component is a branch, which does not affect resolution here.
    return parts[0], parts[1]


def describe_tracks(channel_map: list, arch: str | None) -> str:
    """List tracks with the version each one actually ships.

    A bare list of track names invites the wrong fix: told that a core26 kernel
    is missing and that tracks "20, 24, latest" exist, the obvious move is to
    pin 24 — which builds, and pairs a previous-generation kernel with the new
    base. Showing "24 (6.8.0-85.85)" next to a core26 model makes the mismatch
    self-evident without the reader having to query the store.
    """
    best: dict[str, tuple[int, str]] = {}
    for entry in channel_map:
        ch = entry.get("channel") or {}
        if arch is not None and ch.get("architecture") not in (arch, None):
            continue
        track = ch.get("track", "latest")
        risk = ch.get("risk", "")
        rank = RISKS.index(risk) if risk in RISKS else len(RISKS)
        version = entry.get("version") or ""
        if track not in best or rank < best[track][0]:
            best[track] = (rank, version)
    if not best:
        return "none"
    return ", ".join(
        f"{t} ({v})" if v else t for t, (_, v) in sorted(best.items())
    )


def _tracks_by_risk(channel_map: list, arch: str | None) -> dict[str, set[str]]:
    """Map track -> set of risks published, optionally for one architecture."""
    table: dict[str, set[str]] = {}
    for entry in channel_map:
        ch = entry.get("channel") or {}
        if arch is not None and ch.get("architecture") not in (arch, None):
            continue
        table.setdefault(ch.get("track", "latest"), set()).add(ch.get("risk", ""))
    return table


class Report:
    def __init__(self) -> None:
        self.findings: list[dict] = []
        # A record of what was actually checked against the store. Silence is
        # ambiguous: a reader cannot tell "I verified this and it matched" from
        # "I never looked", and in a brand-store workflow that difference is
        # the whole question.
        self.lookups: list[tuple[str, str, str]] = []

    def looked_up(self, name: str, status: str, detail: str = "") -> None:
        self.lookups.append((name, status, detail))

    def add(self, level: str, where: str, message: str, fix: str = "",
            stage: str = "sign", value: str = "") -> None:
        """stage records *when* a finding bites: "sign" means snapd's assembler
        rejects it, "build" means it signs cleanly and fails later in
        ubuntu-image. Collapsing the two into one verdict is actively
        misleading — an engineer told "will not sign" goes looking for a
        structural problem that is not there."""
        self.findings.append(
            {"level": level, "where": where, "message": message, "fix": fix,
             "stage": stage, "value": value}
        )

    error = lambda self, w, m, f="", s="sign": self.add("ERROR", w, m, f, s)  # noqa: E731
    # Anything the store told us is about the build, not the signature:
    # snap sign never contacts the store.
    build_error = lambda self, w, m, f="": self.add("ERROR", w, m, f, "build")  # noqa: E731
    warn = lambda self, w, m, f="": self.add("WARN", w, m, f)  # noqa: E731
    info = lambda self, w, m, f="": self.add("INFO", w, m, f)  # noqa: E731
    # CONFIRM is for things that are legal and may well be right, but that are
    # wrong often enough — and silently enough — that a human should say yes.
    # `value` is what the model currently says. Keeping it as its own field lets
    # the report put every value a human should eyeball into one table, which is
    # a different reading task from working through prose questions one by one.
    confirm = lambda self, w, m, f="", v="": self.add("CONFIRM", w, m, f, "sign", v)  # noqa: E731

    @property
    def errors(self) -> list[dict]:
        return [f for f in self.findings if f["level"] == "ERROR"]

    @property
    def warnings(self) -> list[dict]:
        return [f for f in self.findings if f["level"] == "WARN"]

    @property
    def confirmations(self) -> list[dict]:
        return [f for f in self.findings if f["level"] == "CONFIRM"]


_STORE_CACHE: dict[tuple[str, str | None], dict | None] = {}


def store_info(name: str, store_id: str | None = None) -> dict | None:
    """Look a snap up, caching by (name, store). A directory of models reuses
    the same handful of snaps, so without the cache a nine-file run makes the
    same five lookups nine times over."""
    key = (name, store_id)
    if key in _STORE_CACHE:
        return _STORE_CACHE[key]
    url = STORE_INFO.format(name=name) + "?fields=snap-id,name,type,base,architectures,revision,version"
    headers = dict(STORE_HEADERS)
    if store_id:
        # Switches the lookup into a brand store's namespace. Snaps that are
        # published to the brand store but not public in the global store are
        # visible this way; genuinely private snaps still need credentials.
        headers["Snap-Device-Store"] = store_id
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            info = json.load(resp)
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            raise PermissionError(
                f"the store requires authentication for {name!r}"
            ) from exc
        if exc.code == 404:
            _STORE_CACHE[key] = None
            return None
        raise
    except Exception:  # network off, proxy, DNS - treat as "unknown"
        raise
    _STORE_CACHE[key] = info
    return info


def resolution_scope(name: str, store_id: str | None, snap_id: str | None) -> str:
    """Say where a snap actually resolved from.

    Saying "verified in <brand-store>" for every snap overstates the check:
    core26 and snapd resolve identically with or without the store header, and
    only a genuinely brand-scoped snap needs it. The distinction matters because
    a brand store can shadow a public snap of the same name — if the public
    namespace answers with a *different* snap-id, the model's id decides which
    one you actually get, and that is worth saying out loud.
    """
    if not store_id:
        return "global store"
    try:
        public = store_info(name, None)
    except Exception:  # noqa: BLE001 - the brand lookup already succeeded
        # A transient failure here must not read as a finding. Saying "brand
        # store" because the public lookup timed out invents a conclusion the
        # run did not earn, and the same snap then looks different between two
        # runs minutes apart.
        return f"found via {store_id!r} — could not reach the public store to compare"
    if public is None:
        return f"brand store {store_id!r} only — not public"
    if snap_id and public.get("snap-id") and public["snap-id"] != snap_id:
        return (f"brand store {store_id!r} — NOTE: a different snap of the same name "
                f"exists publicly ({public['snap-id']})")
    return "public store (the brand store header made no difference)"


def local_snap_id(name: str) -> str | None:
    """Ask the local snapd. If this machine is attached to the same brand store,
    it can resolve snaps the public API cannot."""
    try:
        proc = subprocess.run(["snap", "info", "--verbose", name],
                              capture_output=True, text=True, timeout=30)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    for line in proc.stdout.splitlines():
        if line.strip().startswith("snap-id:"):
            return line.split(":", 1)[1].strip()
    return None


def detect_variant(model: dict) -> str:
    """UC20+ uses the extended `snaps` header. Anything without it is a UC16/18
    model, which is end-of-life and no longer supported here."""
    if "snaps" in model:
        if model.get("classic") in (True, "true"):
            return "classic-hybrid"
        return "uc20+"
    return "legacy-eol"


def check_scalar_strings(model: dict, rep: Report) -> None:
    """snap sign feeds the JSON straight into assertion headers, and assertion
    headers only hold strings (or lists/maps of strings). A JSON boolean or
    number produces a confusing low-level error, so flag it precisely."""

    def walk(node, path: str) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                walk(value, f"{path}.{key}" if path else key)
        elif isinstance(node, list):
            for idx, value in enumerate(node):
                walk(value, f"{path}[{idx}]")
        elif node is None:
            rep.error(path, "null is not allowed in an assertion header",
                      "remove the field entirely instead of setting it to null")
        elif not isinstance(node, str):
            literal = "true/false" if isinstance(node, bool) else repr(node)
            rep.error(
                path,
                f"header values must be strings; {literal} is a JSON "
                f"{type(node).__name__}",
                f'quote it: "{str(node).lower() if isinstance(node, bool) else node}"',
            )

    walk(model, "")


def check_common(model: dict, rep: Report) -> None:
    if model.get("type") != "model":
        rep.error("type", f'must be "model", got {model.get("type")!r}',
                  'set "type": "model"')

    series = model.get("series")
    if series is None:
        rep.error("series", '"series" header is mandatory', 'set "series": "16"')
    elif isinstance(series, str) and series != "16":
        rep.error("series", f'must be the string "16", got {series!r}',
                  'set "series": "16"')

    brand = model.get("brand-id")
    authority = model.get("authority-id")
    if not brand:
        rep.error("brand-id", '"brand-id" header is mandatory',
                  "use your store account id, e.g. from `snapcraft whoami`")
    elif not ACCOUNT_ID_RE.match(str(brand)):
        rep.error("brand-id", f"{brand!r} is not a valid account id")
    if not authority:
        rep.error("authority-id", '"authority-id" header is mandatory',
                  'set it to the same value as "brand-id"')
    elif brand and authority != brand:
        rep.error(
            "authority-id",
            f"authority-id and brand-id must match ({authority!r} != {brand!r}); "
            "model assertions are expected to be signed by the brand",
            f'set "authority-id": "{brand}"',
        )

    name = model.get("model")
    if not name:
        rep.error("model", '"model" header is mandatory')
    elif not MODEL_RE.match(str(name)):
        rep.error("model", f"{name!r} must be lowercase alphanumerics with single dashes")

    arch = model.get("architecture")
    if not arch:
        rep.error("architecture", '"architecture" header is mandatory')
    elif arch not in ARCHITECTURES:
        rep.error(
            "architecture",
            f"{arch!r} is not a snap architecture — snapd will sign this happily "
            "but every later step will fail to find snaps",
            f"use one of {', '.join(sorted(ARCHITECTURES))} "
            f"({'amd64 if you meant x86_64' if arch in {'x86_64', 'x86-64'} else 'arm64 if you meant aarch64'})",
        )
    else:
        rep.confirm(
            "architecture",
            "is this the architecture of the board you are building for?",
            "nothing downstream can tell you this is wrong: an amd64 model builds a "
            "perfectly valid image that no arm64 board will boot, and vice versa",
            str(arch),
        )

    ts = model.get("timestamp")
    if not ts:
        rep.error("timestamp", '"timestamp" header is mandatory',
                  'use RFC3339 UTC, e.g. "%s"' % dt.datetime.now(dt.timezone.utc)
                  .replace(microsecond=0).isoformat())
    else:
        parsed = parse_rfc3339(str(ts))
        if parsed is None:
            rep.error(
                "timestamp",
                f'{ts!r} is not an RFC3339 date',
                'use e.g. "2026-10-07T00:00:00+00:00" (date alone is rejected)',
            )
        else:
            now = dt.datetime.now(dt.timezone.utc)
            if parsed > now + dt.timedelta(days=1):
                rep.error("timestamp", "timestamp is in the future; devices will reject the assertion")
            elif (now - parsed).days > 365:
                rep.info("timestamp", f"timestamp is {(now - parsed).days} days old — expected for an "
                                      "already-published model, but stale if you are about to sign",
                         "`snap sign --update-timestamp` rewrites it at signing time")

    for header in ("serial-authority", "system-user-authority"):
        val = model.get(header)
        if val is not None and val != "*" and not isinstance(val, list):
            rep.error(header, f'must be a list of account ids (or "*"), got {type(val).__name__}')
    if isinstance(model.get("serial-authority"), list) and "generic" not in model["serial-authority"]:
        rep.info("serial-authority",
                 "does not include \"generic\"; devices can only be serialised by the listed authorities")


def parse_rfc3339(value: str) -> dt.datetime | None:
    """RFC3339 requires both a time and an offset. Python's fromisoformat is
    more permissive than snapd, so reject the extra forms explicitly."""
    if "T" not in value:
        return None
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def check_uc20(model: dict, rep: Report, variant: str) -> list[dict]:
    classic = variant == "classic-hybrid"

    for legacy in ("gadget", "kernel", "required-snaps"):
        if legacy in model:
            rep.error(
                legacy,
                f'cannot specify separate "{legacy}" header once using the extended "snaps" header',
                f'move it into the "snaps" list as an entry with the right "type"',
            )

    grade = model.get("grade")
    if grade is None:
        rep.warn("grade", 'no "grade" header; snapd defaults to "signed"',
                 'set it explicitly: "dangerous" for development, "signed" or "secured" for production')
    elif grade not in GRADES:
        rep.error("grade", f'must be one of {"|".join(sorted(GRADES))}, not {grade!r}')
    elif grade == "dangerous":
        rep.confirm("grade", "development image? dangerous allows unasserted snaps",
                    "dangerous disables secure boot and full-disk encryption and allows "
                    "unasserted snaps; it is the right choice for bring-up and the wrong "
                    "one for anything that ships", "dangerous")
    else:
        if grade == "secured":
            rep.confirm("grade", "recovery modes locked down, every snap must be asserted",
                        "pick secured only if physical access to the device is part of your "
                        "threat model; it also rules out recovery-mode debugging in the field",
                        "secured")
        else:
            rep.confirm("grade", "store-asserted snaps only, every snap needs a snap-id",
                        "right for production. If you are still bringing the board up, dangerous "
                        "lets you sideload; if physical access is in your threat model, secured "
                        "additionally locks down recovery", "signed")

    base = model.get("base")
    if not base:
        rep.error("base", '"base" header is mandatory for UC20+ models',
                  'e.g. "base": "core24"')
    elif base in EOL_BASES:
        rep.error("base", f'{base!r} is an end-of-life base (Ubuntu Core 16/18) and cannot be '
                          'used with the extended "snaps" header',
                  'use core20, core22, core24 or core26')
    elif not base_track(base):
        rep.warn("base", f"{base!r} does not look like an Ubuntu Core base (coreNN)")

    if classic:
        if not model.get("distribution"):
            rep.error("distribution", '"distribution" header is mandatory when classic is true, '
                                      "see distribution ID in os-release spec",
                      'e.g. "distribution": "ubuntu"')
        if isinstance(model.get("classic"), str) and model.get("classic") not in ("true", "false"):
            rep.error("classic", f'must be the string "true" or "false", got {model.get("classic")!r}')
    else:
        if model.get("distribution"):
            rep.error("distribution",
                      "cannot specify distribution for model unless it is classic "
                      "and has an extended snaps header",
                      'either add "classic": "true" or drop "distribution"')

    snaps = model.get("snaps")
    if not isinstance(snaps, list) or not snaps:
        rep.error("snaps", '"snaps" must be a non-empty list')
        return []

    seen: dict[str, int] = {}
    by_type: dict[str, list[str]] = {}
    for idx, snap in enumerate(snaps):
        where = f"snaps[{idx}]"
        if not isinstance(snap, dict):
            rep.error(where, "each entry must be an object")
            continue
        name = snap.get("name")
        if not name:
            rep.error(where, '"name" is mandatory')
            continue
        where = f'snaps[{idx}] "{name}"'
        if not NAME_RE.match(str(name)):
            rep.error(where, f"{name!r} is not a valid snap name")
        if name in seen:
            rep.error(where, f"duplicate entry; also at snaps[{seen[name]}]")
        seen[name] = idx

        stype = snap.get("type")
        if not stype:
            rep.error(where, '"type" is mandatory in the extended snaps header',
                      "one of " + ", ".join(sorted(SNAP_TYPES)))
        elif stype not in SNAP_TYPES:
            rep.error(where, f'type {stype!r} is not valid')
        else:
            by_type.setdefault(stype, []).append(name)

        sid = snap.get("id")
        if sid is None:
            if model.get("grade") == "dangerous":
                rep.warn(where, 'no "id"; only allowed because grade is dangerous',
                         "add the real snap-id before moving to grade signed/secured")
            else:
                rep.error(where, f'"id" of snap "{name}" is mandatory for {model.get("grade", "signed")} grade model',
                          f"look it up: snap info --verbose {name} | grep snap-id")
        elif not SNAP_ID_RE.match(str(sid)):
            rep.error(where, f'"id" {sid!r} is not a 32-character snap-id')

        presence = snap.get("presence")
        if presence is not None:
            if presence not in PRESENCE:
                rep.error(where, f'presence must be required|optional, not {presence!r}')
            elif stype in {"snapd", "kernel", "gadget", "base"}:
                rep.error(where, "essential snaps are always available, cannot specify presence",
                          'remove "presence" from this entry')

        modes = snap.get("modes")
        if modes is not None:
            if not isinstance(modes, list):
                rep.error(where, '"modes" must be a list')
            else:
                bad = set(modes) - MODES
                if bad:
                    rep.error(where, f"unknown modes {sorted(bad)} — snapd signs these without "
                                     "complaint but the snap will never be installed",
                              "valid: " + ", ".join(sorted(MODES)))
            if presence is None:
                rep.info(where, '"modes" without "presence" means required in those modes only')

        channel = snap.get("default-channel")
        if channel is None:
            if stype in {"kernel", "gadget"}:
                rep.warn(where, 'no "default-channel"; defaults to latest/stable, '
                                "which is usually wrong for kernel/gadget snaps",
                         f'set e.g. "{base_track(base) or "24"}/stable"')
        elif "/" in str(channel) and str(channel).count("/") > 2:
            rep.error(where, f"default-channel {channel!r} is malformed")

    # The four essential snaps. snap sign only enforces kernel and gadget, but a
    # model that leaves base or snapd implicit is not reproducible: the image
    # builder picks whatever the store serves that day, so two builds of the
    # "same" model can ship different snapd revisions. Pinning all four is what
    # makes a model describe one specific image rather than a family of them.
    if not classic:
        for required in ("kernel", "gadget"):
            found = by_type.get(required, [])
            if not found:
                rep.error("snaps", f'one "snaps" header entry must specify the model {required}',
                          f'add an entry with "type": "{required}"')
            elif len(found) > 1:
                rep.error("snaps", f"more than one {required} snap: {found}")
    else:
        for optional in ("kernel", "gadget"):
            if len(by_type.get(optional, [])) > 1:
                rep.error("snaps", f"more than one {optional} snap: {by_type[optional]}")
        if not by_type.get("kernel") and not by_type.get("gadget"):
            rep.info("snaps", "classic model with neither kernel nor gadget — snapd allows this, "
                              "so boot and partitioning come from the host install, not the model")

    if "snapd" not in by_type:
        rep.error("snaps", 'no entry with "type": "snapd"',
                  'add {"name": "snapd", "type": "snapd", "id": "'
                  'PMrrV4ml8uWuEUDBT8dSGnKUYbevVhc4", "default-channel": "latest/stable"} — '
                  "snap sign accepts the model without it, but then nothing pins the snapd "
                  "revision and the image stops being reproducible")
    if base and base not in seen:
        others = [n for n in by_type.get("base", []) if n != base]
        hint = (f'found "{others[0]}" instead — a leftover from an older base is a common '
                f"copy-paste error" if others else "")
        rep.error("snaps", f'the base snap "{base}" is not listed in "snaps"' +
                  (f"; {hint}" if hint else ""),
                  f'add {{"name": "{base}", "type": "base", '
                  f'"default-channel": "latest/stable"}} so the base revision is pinned '
                  "like the other three essential snaps")

    # track/base coherence - the single most common silent mistake
    expected = base_track(base)
    if expected:
        for snap in snaps:
            if not isinstance(snap, dict) or snap.get("type") not in {"kernel", "gadget"}:
                continue
            channel = str(snap.get("default-channel", ""))
            track = split_channel(channel)[0] if channel else ""
            if track and not track.startswith(expected):
                rep.confirm(
                    f'snaps "{snap.get("name")}"',
                    f"does not match base {base} (expected {expected}/*) — deliberate?",
                    "hwe, rt and vendor tracks are real reasons to do this; a leftover "
                    "track from the previous release is the more common one",
                    str(track),
                )
    return [s for s in snaps if isinstance(s, dict)]


def reject_legacy(model: dict, rep: Report) -> list[dict]:
    """UC16/18 models are end-of-life. Say so clearly and point at the migration.

    Reporting this as a single error rather than validating the old format is
    deliberate: a UC18 model that passes validation invites someone to keep
    shipping it, and the honest answer is that the base is out of support, the
    format cannot express grade/presence/modes, and nothing downstream will fix
    that. The useful output here is a migration path, not a clean bill of health.
    """
    rep.error(
        "format",
        "this is a UC16/18 model (no extended \"snaps\" header) — Ubuntu Core 16 and 18 "
        "are end-of-life and this format is no longer validated",
        "migrate to a UC20+ model: set \"base\" to a supported core (core20, core22, "
        "core24, core26), replace the \"gadget\"/\"kernel\"/\"required-snaps\" headers "
        "with an extended \"snaps\" list carrying name/id/type/default-channel for "
        "gadget, kernel, base and snapd, and add a \"grade\". See the reference for a "
        "worked example.",
    )
    legacy_present = [h for h in ("gadget", "kernel", "required-snaps") if h in model]
    if legacy_present:
        rep.info("format", "legacy headers found: " + ", ".join(legacy_present),
                 "these carry no snap-id, so the model pins snaps by name only — "
                 "the migrated model should declare ids")
    # Still worth looking the snaps up: knowing which ones still exist and what
    # their ids are is exactly what the migration needs.
    out = []
    for header in ("gadget", "kernel"):
        value = model.get(header)
        if value:
            name = str(value).split("=")[0]  # gadget may be "pc=18"
            out.append({"name": name, "type": header})
    required = model.get("required-snaps")
    if isinstance(required, list):
        out += [{"name": n, "type": "app"} for n in required]
    return out


def check_store(entries: list[dict], model: dict, rep: Report, store_id: str | None = None) -> None:
    arch = model.get("architecture")
    # If the architecture is already wrong, every per-snap arch check would fire
    # and bury the one finding that actually matters.
    check_arch = arch in ARCHITECTURES
    store_id = store_id or model.get("store")
    for snap in entries:
        name = snap.get("name")
        if not name:
            continue
        where = f'snaps "{name}"'
        try:
            info = store_info(str(name), store_id)
        except PermissionError as exc:
            rep.info(where, f"{exc}; falling back to the local snapd")
            info = None
        except Exception as exc:  # noqa: BLE001
            rep.warn(where, f"could not reach the store ({exc}); skipping online checks")
            rep.looked_up(str(name), "unchecked", "store unreachable")
            return
        if info is None:
            # Not in the public store. Before calling it a typo, try the local
            # snapd, which may be attached to the brand store.
            local = local_snap_id(str(name))
            declared_id = snap.get("id")
            if local:
                if declared_id and declared_id != local:
                    rep.build_error(where, f"snap-id mismatch: model says {declared_id}, "
                                     f"locally installed snap is {local}",
                              f'set "id": "{local}"')
                else:
                    rep.info(where, f"not in the public store, but the local snapd "
                                    f"resolves it to {local}")
                rep.looked_up(str(name), "local snapd", f"id {local}")
                continue
            rep.confirm(
                where,
                f"cannot resolve snap {name!r}"
                + (f" in store {store_id!r}" if store_id else " in the public store")
                + (f"; the model declares id {declared_id}" if declared_id else
                   "; the model declares no id")
                + " — please supply the correct snap-id, or confirm the declared one",
                "a brand-store or private snap is invisible from here, so this is "
                f"expected rather than wrong. Get it with `snapcraft status {name}`, "
                f"or `snap info --verbose {name}` on a machine attached to that store, "
                "or re-run with --store <brand-store-id>",
            )
            rep.looked_up(str(name), "NOT FOUND", "snap-id unverified — see CONFIRM")
            continue

        declared_id = snap.get("id")
        real_id = info.get("snap-id")
        if declared_id and real_id and declared_id != real_id:
            rep.build_error(
                where,
                f"snap-id mismatch: model says {declared_id}, store says {real_id}",
                f'set "id": "{real_id}"',
            )
            rep.looked_up(str(name), "MISMATCH", f"store says {real_id}")
        elif not declared_id and real_id:
            rep.info(where, f"store snap-id is {real_id}")
            rep.looked_up(str(name), "no id declared", f"store says {real_id}")
        elif declared_id:
            rep.looked_up(str(name), "snap-id verified",
                          resolution_scope(str(name), store_id, real_id))
        else:
            rep.looked_up(str(name), "found", "no snap-id to check")

        declared_type = snap.get("type")
        # The v2 info endpoint reports type per channel-map entry, not at the
        # top level, so pick it from the releases rather than the snap object.
        types = {c.get("type") for c in (info.get("channel-map") or []) if c.get("type")}
        real_type = next(iter(types)) if len(types) == 1 else None
        if declared_type and real_type and declared_type != real_type:
            if not (declared_type == "core" and real_type == "base"):
                rep.build_error(where, f'type mismatch: model says {declared_type!r}, store says {real_type!r}',
                          f'set "type": "{real_type}"')

        channel = snap.get("default-channel")
        channel_map = info.get("channel-map") or []
        if channel and channel_map:
            track, risk = split_channel(str(channel))
            available = _tracks_by_risk(channel_map, None)
            arch_only = _tracks_by_risk(channel_map, arch)

            def resolve(table: dict[str, set[str]]) -> str | None:
                """Return the channel the store would actually serve, or None.

                A risk with no release of its own falls back to the next more
                stable risk in the same track -- this is why `snap info` prints
                '^' against, say, 26.10/candidate. Only the fallback direction
                is legal: asking for stable never gets you an edge build.
                """
                risks = table.get(track)
                if not risks:
                    return None
                if risk in risks:
                    return f"{track}/{risk}"
                if risk not in RISKS:
                    return None
                for fallback in reversed(RISKS[: RISKS.index(risk)]):
                    if fallback in risks:
                        return f"{track}/{fallback}"
                return None

            served = resolve(available)
            if served is None:
                # Report against the architecture the model actually targets:
                # "no core26 build for amd64" and "no core26 track at all" are
                # different conversations with whoever owns the snap.
                table = arch_only if check_arch else available
                scope = f" for {arch}" if check_arch else ""
                listing = describe_tracks(channel_map, arch if check_arch else None)
                if track not in table:
                    expected = base_track(model.get("base"))
                    is_boot = snap.get("type") in {"kernel", "gadget"}
                    if is_boot and expected and track.startswith(expected):
                        # The track list is a trap here: the obvious reading of
                        # "available: 20, 24" is "use 24", which silently pairs a
                        # previous-generation kernel with this base.
                        fix = (f"no {expected}* track exists{scope}, so there is no valid "
                               f"channel for a {model.get('base')} model yet — this needs a "
                               f"build, not a different channel. Published tracks{scope} "
                               f"are {listing}, and none of them belongs to "
                               f"{model.get('base')}")
                    else:
                        fix = f"published tracks{scope}: {listing}"
                    rep.build_error(where, f"track {track!r} does not exist for this snap{scope}",
                                    fix)
                else:
                    rep.build_error(where,
                              f"channel {channel!r} has no release and nothing more stable "
                              f"to fall back to",
                              f"published risks on track {track!r}{scope}: "
                              f"{', '.join(sorted(table[track]))}")
            elif check_arch and resolve(arch_only) is None:
                rep.build_error(where, f"channel {channel!r} has no {arch} build",
                          f"published tracks for {arch}: "
                          f"{describe_tracks(channel_map, arch)}")
            elif served != f"{track}/{risk}":
                rep.info(where,
                         f"{channel!r} has no release of its own; the store serves "
                         f"{served!r} instead",
                         "that is normal store behaviour, but the image will not contain "
                         "what the channel name suggests")


def ensure_key(name: str = "model-validation-throwaway") -> str | None:
    """Make a passphrase-less key for --sign-check if one is not already there.

    `snap create-key` prompts for a passphrase on a TTY, which blocks forever in
    a non-interactive session. Generating the key directly in snapd's GPG
    keyring avoids that. The key is deliberately throwaway: unregistered, no
    passphrase, trusted by nothing."""
    try:
        listed = subprocess.run(["snap", "keys"], capture_output=True, text=True, timeout=30)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if name in listed.stdout:
        return name
    home = os.path.expanduser("~/.snap/gnupg")
    os.makedirs(home, mode=0o700, exist_ok=True)
    env = dict(os.environ, GNUPGHOME=home)
    try:
        made = subprocess.run(
            ["gpg", "--batch", "--yes", "--passphrase", "", "--quick-generate-key",
             name, "rsa4096", "sign", "never"],
            capture_output=True, text=True, env=env, timeout=300,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    return name if made.returncode == 0 else None


def account_info(account_id: str) -> dict | None:
    """Look up the brand's account assertion. A brand-id is just a string as far
    as signing is concerned, so this is the only way to tell "acme-robotics"
    from "acme-rootics" before the device rejects the assertion."""
    try:
        proc = subprocess.run(
            ["snap", "known", "--remote", "account", f"account-id={account_id}"],
            capture_output=True, text=True, timeout=30,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0 or not proc.stdout.strip():
        return {}  # queried successfully, no such account
    out = {}
    for line in proc.stdout.splitlines():
        if ":" in line and not line.startswith(" "):
            key, _, value = line.partition(":")
            out[key.strip()] = value.strip()
    return out


def check_identity(model: dict, rep: Report, store_id: str | None) -> str | None:
    """The identity headers are the ones nothing downstream can second-guess:
    they are free-form strings that only have to be self-consistent, so a typo
    sails through signing and surfaces as a device refusing its own model."""
    display_name = None
    brand = model.get("brand-id")
    if brand:
        info = account_info(str(brand))
        if info is None:
            rep.confirm("brand-id", "is this your store account id?",
                        "could not query the store to check it; `snapcraft whoami` shows yours",
                        str(brand))
        elif not info:
            rep.confirm(
                "brand-id",
                "no account assertion exists for this id — is it spelled correctly?",
                "the brand-id is the account id from the store, not the company name or "
                "the snapcraft login email; check with `snapcraft whoami`. A brand-store "
                "account that has never published publicly may legitimately not resolve",
                str(brand),
            )
        else:
            display = info.get("display-name", "?")
            display_name = display
            validation = info.get("validation", "unproven")
            rep.confirm(
                "brand-id",
                f"resolves to \"{display}\" ({validation}) — is that you?",
                "assertions signed by a brand-id you do not hold the key for are rejected "
                "by the device, not at signing time",
                str(brand),
            )

    name = model.get("model")
    if name:
        rep.confirm(
            "model",
            "correct for this product and revision?",
            "the model name is part of the device's identity: changing it later means "
            "re-serialising devices, not just rebuilding an image",
            str(name),
        )

    declared_store = model.get("store") or store_id
    if declared_store:
        rep.confirm(
            "store",
            "is this the right store id?",
            "a wrong store id is invisible at signing time and shows up as devices that "
            "cannot refresh; the id is the store's ID from the dashboard, not its name",
            str(declared_store),
        )
    return display_name


def check_sign(path: str, key: str | None, rep: Report) -> None:
    """Round-trip through snapd's own assertion assembler — the authoritative
    structural verdict. Needs a key, and must never block waiting for one."""
    if key is None:
        try:
            listed = subprocess.run(["snap", "keys"], capture_output=True, text=True, timeout=30)
        except (FileNotFoundError, subprocess.TimeoutExpired):
            rep.warn("snap sign", "the `snap` command is not available; skipped the signing check")
            return
        if "No keys registered" in listed.stdout or not listed.stdout.strip():
            rep.info(
                "snap sign",
                "skipped: no signing key is available",
                "re-run with --create-key for a passphrase-less throwaway key, or -k <name> "
                "to use an existing one. Never run `snap create-key` in a non-interactive "
                "session — it blocks waiting for a passphrase on a TTY",
            )
            return
    cmd = ["snap", "sign"]
    if key:
        cmd += ["-k", key]
    try:
        with open(path, "rb") as handle:
            proc = subprocess.run(cmd, stdin=handle, capture_output=True, text=True, timeout=120)
    except FileNotFoundError:
        rep.warn("snap sign", "the `snap` command is not available; skipped authoritative check")
        return
    except subprocess.TimeoutExpired:
        rep.warn("snap sign", "timed out — the key almost certainly has a passphrase and gpg is "
                              "waiting for a TTY that does not exist here",
                 "use --create-key, or run the signing check in a real terminal")
        return
    stderr = proc.stderr.replace(
        "WARNING: could not fetch account-key to cross-check signed assertion with key constraints.", ""
    ).strip()
    if proc.returncode == 0:
        rep.info("snap sign", "snapd assembled and signed the assertion — structure is valid")
    elif "cannot assemble assertion" in stderr:
        rep.error("snap sign", stderr.replace("error: ", ""),
                  "this is snapd's own validator; fix this before anything else")
    else:
        rep.warn("snap sign", f"could not run the signing check: {stderr}",
                 "this is a key/gpg problem, not a problem with the model")


GRADE_MEANING = {
    "dangerous": "unasserted snaps allowed, no secure boot, no disk encryption — development only",
    "signed": "store-asserted snaps only; the model permits secure boot and full-disk "
              "encryption, though whether the device gets them also depends on the "
              "gadget, kernel and platform",
    "secured": "as signed, plus recovery modes are locked down",
}


def summarize(model: dict, variant: str, brand_display: str | None = None) -> str:
    """Say what the model means in prose.

    A model can be perfectly valid and still describe the wrong device. The
    cheapest way to catch that is to state the intent back in a form the user
    can read in ten seconds — they know what they meant, and will spot
    "arm64" or "dangerous" in a sentence faster than in a JSON field."""
    brand = model.get("brand-id", "?")
    who = f'{brand_display} (brand-id "{brand}")' if brand_display else f'brand-id "{brand}"'
    name = model.get("model", "?")
    arch = model.get("architecture", "?")
    base = model.get("base", "")
    classic = model.get("classic") == "true"

    if variant == "legacy-eol":
        system = f"Ubuntu Core 16/18 (base {base or 'core'})"
    elif classic:
        system = f"a classic hybrid {model.get('distribution', '?')} system on {base}"
    else:
        release = base_track(base)
        system = f"Ubuntu Core {release}" if release else f"Ubuntu Core (base {base})"

    lines = ["## What this model actually says", ""]
    lines.append(f'{who} ships a device model called "{name}", running {system} on {arch}.')
    if variant == "legacy-eol":
        lines.append("That release is end-of-life and the format predates grade, presence "
                     "and modes — the model needs migrating, not fixing.")
    lines.append("")

    grade = model.get("grade")
    if grade:
        lines.append(f'Security grade **{grade}** — {GRADE_MEANING.get(grade, "")}.')
        lines.append("")

    snaps = model.get("snaps")
    if isinstance(snaps, list) and snaps:
        by_type: dict[str, tuple] = {}
        extra = []
        for snap in snaps:
            if not isinstance(snap, dict):
                continue
            row = (snap.get("type", "?"), snap.get("name", "?"),
                   snap.get("default-channel", "latest/stable"))
            if row[0] in {"kernel", "gadget", "base", "snapd", "core"}:
                by_type.setdefault("base" if row[0] == "core" else row[0], row)
            else:
                extra.append((row, snap))
        # Fixed boot order, so a missing essential snap is a visible gap rather
        # than a line the reader has to notice is absent.
        order = ["base", "snapd"] if model.get("classic") == "true" else \
                ["gadget", "kernel", "base", "snapd"]
        lines.append("Boot chain:")
        for kind in order:
            row = by_type.get(kind)
            if row:
                lines.append(f"  {kind:<7} {row[1]:<16} {row[2]}")
            else:
                lines.append(f"  {kind:<7} -- not pinned by this model --")
        lines.append("")
        if extra:
            lines.append("Also in the image:")
            for (t, n, c), snap in extra:
                bits = [c, snap.get("presence", "required")]
                if snap.get("modes"):
                    bits.append("modes: " + ", ".join(snap["modes"]))
                lines.append(f"  {n:<16} ({', '.join(bits)})")
            lines.append("")
    else:
        gadget, kernel = model.get("gadget"), model.get("kernel")
        if gadget or kernel:
            lines.append(f"Boot chain: kernel {kernel}, gadget {gadget} (pinned by name, no snap-ids)")
        required = model.get("required-snaps")
        if required:
            lines.append("Required snaps: " + ", ".join(required))
        lines.append("")

    store = model.get("store")
    lines.append(f"Snaps come from {'brand store ' + repr(store) if store else 'the global store'}.")
    serial = model.get("serial-authority")
    if serial:
        lines.append(f"Devices can be serialised by: {', '.join(serial) if isinstance(serial, list) else serial}.")
    sysuser = model.get("system-user-authority")
    if sysuser:
        lines.append(f"system-user assertions accepted from: "
                     f"{', '.join(sysuser) if isinstance(sysuser, list) else sysuser}.")
    lines.append("")
    lines.append("If any line above is not what you meant, the model is wrong regardless of "
                 "what the checks say — they can only tell you it is well-formed, not that "
                 "it describes your product.")
    return "\n".join(lines)


def compute_verdict(rep: Report, variant: str, online: bool) -> str:
    """One sentence saying which stage this model dies at, if any.

    The distinction is the whole point: a structural error stops `snap sign`
    in a second, while a store error signs cleanly and only surfaces much
    later, part-way through a multi-gigabyte image build. Collapsing the two
    into "invalid" throws away the most useful thing the report knows.
    """
    sign_errors = [f for f in rep.errors if f.get("stage", "sign") == "sign"]
    build_errors = [f for f in rep.errors if f.get("stage") == "build"]
    if variant == "legacy-eol":
        return "FAIL — end-of-life model format, migrate it rather than fix it"
    if sign_errors and build_errors:
        return ("FAIL — snap sign will reject this, and there are store problems "
                "waiting behind it")
    if sign_errors:
        return "FAIL — snap sign will reject this"
    if build_errors:
        # Scoped deliberately: this is inferred from what the store publishes,
        # not from an ubuntu-image run, and saying "the build will fail" claims
        # more than the evidence supports.
        return ("FAIL — signs cleanly, but the image build cannot resolve what "
                "this model asks for")
    if not online:
        return "PASS (offline — structure only, nothing checked against the store)"
    if rep.warnings:
        return "PASS with warnings"
    return "PASS"


def render(rep: Report, path: str, variant: str, online: bool = False) -> str:
    verdict = compute_verdict(rep, variant, online)
    lines = [f"# Model assertion validation: {path}", "",
             f"**Verdict: {verdict}** "
             f"({len(rep.errors)} errors, {len(rep.warnings)} warnings, "
             f"{len(rep.confirmations)} to confirm)", "",
             f"Detected format: **{variant}**", ""]
    icon = {"ERROR": "✗", "WARN": "!", "CONFIRM": "?", "INFO": "·"}
    heading = {
        "ERROR": "ERROR — must be fixed",
        "WARN": "WARN — probably wrong",
        "CONFIRM": "CONFIRM — legal, but only you can say if it is correct",
        "INFO": "INFO",
    }
    def emit(levels: tuple[str, ...]) -> None:
        for level in levels:
            group = [f for f in rep.findings if f["level"] == level]
            if not group:
                continue
            lines.append(f"## {heading[level]} ({len(group)})")
            for f in group:
                lines.append(f"{icon[level]} **{f['where']}** — {f['message']}")
                if f["fix"]:
                    lines.append(f"    → {f['fix']}")
            lines.append("")

    # Problems first, then the evidence for what was actually checked, and only
    # then the open questions. Questions are the longest section and the least
    # urgent -- a reader should not have to scroll past five of them to find out
    # whether the snap-ids were verified at all.
    emit(("ERROR", "WARN"))

    # Say what was checked, not just what was wrong.
    if rep.lookups:
        verified = [n for n, s, _ in rep.lookups if s == "snap-id verified"]
        unchecked = [n for n, s, _ in rep.lookups if s in {"NOT FOUND", "unchecked"}]
        no_id = [n for n, s, _ in rep.lookups if s == "no id declared"]
        lines.append(f"## Store lookups ({len(verified)} of {len(rep.lookups)} "
                     f"snap-ids verified against the store)")
        width = max(len(n) for n, _, _ in rep.lookups)
        for name, status, detail in rep.lookups:
            lines.append(f"  {name:<{width}}  {status}" + (f" — {detail}" if detail else ""))
        if unchecked:
            lines.append("")
            lines.append(f"Could not check: {', '.join(unchecked)}. These are the snaps only "
                         "you can vouch for — a wrong snap-id signs cleanly and fails at the "
                         "device, so do not let them pass silently.")
        if no_id:
            lines.append("")
            lines.append(f"No snap-id declared for: {', '.join(no_id)} — pinned by name only, "
                         "so the model does not constrain which publisher's snap is used.")
        lines.append("")
    elif not online:
        lines.append("## Store lookups")
        lines.append("  none — this ran offline, so no snap-id, type, channel or "
                     "architecture claim in this model has been checked against reality.")
        lines.append("  Re-run with --online (and --store <id> for a brand store) "
                     "before trusting a PASS.")
        lines.append("")

    emit(("INFO",))

    # The confirmations are a different reading task from the findings: they are
    # not problems, they are values a human has to recognise as their own. A
    # table makes that a single scan down a column -- which is the point, because
    # the things that land here (architecture, brand-id, store id) are wrong
    # silently and stay wrong all the way to a device that will not boot.
    confirms = rep.confirmations
    if confirms:
        lines.append(f"## Read these values and confirm they are yours ({len(confirms)})")
        lines.append("")
        lines.append("| Field | Current value | Check |")
        lines.append("|---|---|---|")
        for f in confirms:
            value = f.get("value") or "—"
            lines.append(f"| {f['where']} | `{value}` | {f['message']} |")
        lines.append("")
        lines.append("Why each one matters:")
        for f in confirms:
            if f["fix"]:
                lines.append(f"- **{f['where']}** — {f['fix']}")
        lines.append("")

    return "\n".join(lines)


def update_timestamp(path: str, model: dict) -> str:
    """Replace only the timestamp value, leaving the rest of the file byte-identical.

    Re-serialising the parsed model with json.dump would be far simpler, and it
    would also reindent the file, reorder nothing but reformat everything, and
    drop whatever comments-by-convention or spacing the author chose. The user
    said yes to a new timestamp, not to a whole-file reformat, and a diff that
    touches sixty lines when one was agreed is how trust in a tool is lost.
    """
    now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()
    raw = open(path, encoding="utf-8").read()
    pattern = re.compile(r'("timestamp"\s*:\s*)"[^"]*"')
    patched, count = pattern.subn(lambda m: f'{m.group(1)}"{now}"', raw, count=1)
    if count != 1:
        raise ValueError(
            f"could not find a single \"timestamp\" field to replace in {path} "
            f"(found {count}) — refusing to rewrite the file"
        )
    # Prove the result still parses and differs only where intended before it
    # goes anywhere near the user's working tree.
    reparsed = json.loads(patched)
    if {k: v for k, v in reparsed.items() if k != "timestamp"} != \
       {k: v for k, v in model.items() if k != "timestamp"}:
        raise ValueError(f"timestamp rewrite would have changed other fields in {path}")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(patched)
    model["timestamp"] = now
    return now


def validate_one(path: str, args) -> dict:
    """Validate a single file and return everything the caller might report on.

    Split out of main() so a directory sweep can reuse it, share the store
    cache, and then reason about the set as a whole -- which is where the
    interesting problems live.
    """
    out = {"path": path, "rep": Report(), "model": None, "variant": "unknown",
           "brand": None, "fatal": None}
    rep = out["rep"]
    try:
        raw = open(path, encoding="utf-8").read()
    except OSError as exc:
        out["fatal"] = f"cannot read {path}: {exc}"
        return out

    try:
        model = json.loads(raw)
    except json.JSONDecodeError as exc:
        rep.error("json", f"invalid JSON at line {exc.lineno} column {exc.colno}: {exc.msg}",
                  "snap sign reads JSON, not YAML — check for trailing commas and unquoted values")
        return out
    if not isinstance(model, dict):
        rep.error("json", "top level must be a JSON object")
        return out
    if not model:
        rep.error("json", "the file is an empty JSON object — nothing to validate",
                  "check the file was written; `snap known --remote` prints nothing "
                  "and still exits 0 when the model does not exist")
        return out

    out["model"] = model
    out["variant"] = variant = detect_variant(model)
    if args.update_timestamp:
        try:
            now = update_timestamp(path, model)
        except (ValueError, OSError) as exc:
            # The file is untouched in this path. Say so, because "the timestamp
            # update failed" and "the timestamp update half-happened" call for
            # very different next moves from the user.
            rep.warn("timestamp", f"not updated: {exc}",
                     "the file has been left exactly as it was; validation continues")
        else:
            rep.info("timestamp", f"rewritten to {now}")
    check_scalar_strings(model, rep)
    check_common(model, rep)
    if variant in {"uc20+", "classic-hybrid"}:
        entries = check_uc20(model, rep, variant)
    else:
        entries = reject_legacy(model, rep)

    if args.online:
        check_store(entries, model, rep, args.store)
        out["brand"] = check_identity(model, rep, args.store)
    if args.sign_check:
        key = args.key
        if args.create_key and not key:
            key = ensure_key()
            if key is None:
                rep.warn("snap sign", "could not create a throwaway key (is gpg installed?)")
        check_sign(path, key, rep)
    return out


def check_assert_drift(result: dict) -> None:
    """Compare a model against its signed sibling, if one is sitting next to it.

    A `.assert`/`.model` file next to the JSON is the thing that was actually
    signed and shipped. People edit the JSON and forget to re-sign, so the two
    drift apart silently, and the JSON you are validating stops describing the
    artefact in use. Cheap to check, and the answer is interesting either way.
    """
    model = result["model"]
    if not model:
        return
    base = os.path.splitext(result["path"])[0]
    for ext in (".assert", ".model", ".assertion"):
        signed = base + ext
        if not os.path.exists(signed):
            continue
        try:
            proc = subprocess.run([sys.executable,
                                   os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                                "assertion_to_json.py"), signed],
                                  capture_output=True, text=True, timeout=30)
            if proc.returncode != 0:
                return
            other = json.loads(proc.stdout)
        except Exception:  # noqa: BLE001 - drift check is a bonus, never a blocker
            return
        skip = {"sign-key-sha3-384", "timestamp"}
        diffs = [k for k in set(model) | set(other)
                 if k not in skip and model.get(k) != other.get(k)]
        name = os.path.basename(signed)
        if diffs:
            result["rep"].warn(
                "signed sibling",
                f"{name} was signed from different content: {', '.join(sorted(diffs))} differ",
                "the signed assertion is what ships — re-sign after editing the JSON, "
                "or you are validating a file nothing uses")
        else:
            result["rep"].info("signed sibling",
                               f"{name} matches this JSON (ignoring timestamp and sign key)")
        return


def check_identity_collisions(results: list[dict]) -> list[str]:
    """Find models that claim the same device identity.

    A model's primary key is series + brand-id + model, with `revision` as the
    tiebreaker. Filenames mean nothing. Two files that differ only in grade or
    channel are not two variants — they are two revision-0 assertions for one
    identity, and a device can hold exactly one. This is invisible when you
    validate files one at a time, which is exactly why it survives review.
    """
    groups: dict[tuple, list[tuple[str, str]]] = {}
    for r in results:
        m = r["model"]
        if not m:
            continue
        key = (str(m.get("series", "")), str(m.get("brand-id", "")), str(m.get("model", "")))
        if not key[1] or not key[2]:
            continue
        groups.setdefault(key, []).append(
            (os.path.basename(r["path"]), str(m.get("revision", "0"))))

    lines: list[str] = []
    for (series, brand, name), files in sorted(groups.items()):
        if len(files) < 2:
            continue
        revs = [rev for _, rev in files]
        dupes = {r for r in revs if revs.count(r) > 1}
        if not dupes:
            continue
        lines.append(f"**{brand}/{name}** (series {series}) is claimed by "
                     f"{len(files)} files, and these share a revision:")
        for fname, rev in sorted(files):
            mark = "  <-- collision" if rev in dupes else ""
            lines.append(f"  revision {rev:<4} {fname}{mark}")
        lines.append("")
    if lines:
        lines.append("A device accepts the highest revision for a given "
                     "series+brand-id+model and treats it as superseding the rest, so "
                     "files sharing a revision are mutually exclusive rather than "
                     "parallel variants — and remodelling between them is impossible "
                     "because a remodel requires the revision to increase.")
        lines.append("")
        lines.append("Two ways out, and it is a product decision, not a syntax fix: give "
                     "each variant its own `model` name if they are separate products "
                     "that coexist in the field, or keep the name and assign increasing "
                     "`revision` values if they are a hardening progression of one product.")
    return lines


def render_batch(results: list[dict], online: bool) -> str:
    """One report for a set of files: per-file verdicts, the questions merged,
    and the things only visible across the set."""
    lines = [f"# Model assertion validation: {len(results)} files", ""]

    width = max(len(os.path.basename(r["path"])) for r in results)
    lines.append("## Per-file results")
    lines.append("")
    for r in results:
        name = os.path.basename(r["path"])
        if r["fatal"]:
            lines.append(f"  {name:<{width}}  UNREADABLE — {r['fatal']}")
            continue
        rep = r["rep"]
        state = "FAIL" if rep.errors else "pass"
        counts = f"{len(rep.errors)} errors, {len(rep.warnings)} warnings"
        lines.append(f"  {name:<{width}}  {state:<4}  {counts}")
    lines.append("")

    # The same error repeated nine times reads as nine problems. It is one
    # problem with nine instances, and saying so is the difference between a
    # wall of text and a finding someone can act on.
    issues: dict[tuple, list[str]] = {}
    for r in results:
        for f in r["rep"].findings:
            if f["level"] not in {"ERROR", "WARN"}:
                continue
            issues.setdefault((f["level"], f["where"], f["message"], f["fix"]), []).append(
                os.path.basename(r["path"]))
    if issues:
        lines.append(f"## Problems ({len(issues)} distinct)")
        lines.append("")
        for (level, where, message, fix), files in issues.items():
            icon = "✗" if level == "ERROR" else "!"
            scope = ("all files" if len(files) == len(results)
                     else ", ".join(sorted(files)))
            lines.append(f"{icon} **{where}** — {message}")
            if fix:
                lines.append(f"    → {fix}")
            lines.append(f"    ({scope})")
            lines.append("")

    # Say what was checked and came back clean, or a quiet report looks like a
    # report where those checks never ran.
    drift = [f for r in results for f in r["rep"].findings
             if f["where"] == "signed sibling"]
    if drift:
        matched = sum(1 for f in drift if f["level"] == "INFO")
        lines.append("## Signed siblings")
        lines.append("")
        lines.append(f"  {len(drift)} of {len(results)} files have a signed assertion "
                     f"next to them; {matched} match the JSON they sit beside.")
        lines.append("")

    collisions = check_identity_collisions(results)
    if collisions:
        lines.append("## Across the set — shared device identity")
        lines.append("")
        lines.extend(collisions)

    # Identical questions across nine files are one question, not nine.
    merged: dict[tuple[str, str, str, str], list[str]] = {}
    for r in results:
        for f in r["rep"].findings:
            if f["level"] != "CONFIRM":
                continue
            merged.setdefault(
                (f["where"], f.get("value", ""), f["message"], f["fix"]), []
            ).append(os.path.basename(r["path"]))
    if merged:
        lines.append(f"## Read these values and confirm they are yours ({len(merged)})")
        lines.append("")
        lines.append("| Field | Current value | Check | Applies to |")
        lines.append("|---|---|---|---|")
        for (where, value, message, _fix), files in merged.items():
            scope = "all files" if len(files) == len(results) else ", ".join(sorted(files))
            lines.append(f"| {where} | `{value or '—'}` | {message} | {scope} |")
        lines.append("")
        seen: set[str] = set()
        notes = []
        for (where, _v, _m, fix), _files in merged.items():
            if fix and where not in seen:
                seen.add(where)
                notes.append(f"- **{where}** — {fix}")
        if notes:
            lines.append("Why each one matters:")
            lines.extend(notes)
            lines.append("")

    failed = [r for r in results if r["rep"].errors or r["fatal"]]
    if failed:
        lines.append(f"**Verdict: {len(failed)} of {len(results)} files have errors.** "
                     f"See the per-file sections above.")
    elif collisions:
        lines.append("**Verdict: every file is individually valid, but the set is not "
                     "coherent** — see the shared-identity section.")
    else:
        verdict = "PASS" if online else "PASS (offline — structure only)"
        lines.append(f"**Verdict: {verdict}** for all {len(results)} files, "
                     f"{len(merged)} things to confirm.")
    return "\n".join(lines)


def collect_paths(inputs: list[str]) -> list[str]:
    paths: list[str] = []
    for item in inputs:
        if os.path.isdir(item):
            paths.extend(sorted(
                os.path.join(item, f) for f in os.listdir(item) if f.endswith(".json")))
        else:
            paths.append(item)
    return paths


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("model", nargs="+",
                    help="path to the model assertion JSON, or a directory of them "
                         "(several paths are validated as a set, which also surfaces "
                         "problems only visible across files)")
    ap.add_argument("--online", action="store_true", help="verify snap-ids and channels against the snap store")
    ap.add_argument("--store", help="brand store id to look snaps up in (defaults to the model's "
                                    "own \"store\" header if it has one)")
    ap.add_argument("--sign-check", action="store_true", help="round-trip through `snap sign` (needs a key)")
    ap.add_argument("-k", "--key", help="key name for --sign-check")
    ap.add_argument("--create-key", action="store_true",
                    help="with --sign-check, generate a passphrase-less throwaway key if none "
                         "exists (never prompts; `snap create-key` would block on a TTY)")
    ap.add_argument("--json", action="store_true", dest="as_json", help="emit findings as JSON")
    ap.add_argument("--no-summary", action="store_true",
                    help="omit the plain-English summary of what the model describes")
    ap.add_argument("--update-timestamp", action="store_true",
                    help="rewrite the model's timestamp to now (UTC) in place, then validate")
    args = ap.parse_args()

    paths = collect_paths(args.model)
    if not paths:
        print("no .json files found", file=sys.stderr)
        return 2

    if len(paths) > 1 and args.update_timestamp:
        print("--update-timestamp rewrites files in place and is refused for a batch run; "
              "run it per file once you have agreed the changes", file=sys.stderr)
        return 2

    results = [validate_one(p, args) for p in paths]
    for r in results:
        check_assert_drift(r)

    for r in results:
        if r["fatal"] and len(paths) == 1:
            print(r["fatal"], file=sys.stderr)
            return 2

    if args.as_json:
        print(json.dumps({"files": [
            {"path": r["path"], "variant": r["variant"], "findings": r["rep"].findings,
             "summary": {"errors": len(r["rep"].errors), "warnings": len(r["rep"].warnings),
                         "confirmations": len(r["rep"].confirmations)}}
            for r in results],
            "identity_collisions": check_identity_collisions(results)}, indent=2))
        return 1 if any(r["rep"].errors for r in results) else 0

    if len(paths) == 1:
        r = results[0]
        report = render(r["rep"], r["path"], r["variant"], args.online)
        if not args.no_summary and r["model"]:
            report += "\n\n" + summarize(r["model"], r["variant"], r["brand"])
        print(report)
    else:
        print(render_batch(results, args.online))

    if any(r["rep"].errors or r["fatal"] for r in results):
        return 1
    return 1 if check_identity_collisions(results) else 0


if __name__ == "__main__":
    sys.exit(main())
