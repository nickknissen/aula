"""Stop names, UniLogins and IDs from a live Aula account reaching a commit.

Runs as a pre-commit hook on every staged text file, with two checks:

1. Values listed in ``~/.config/aula/never-commit.txt`` (or ``$AULA_NEVER_COMMIT``),
   one per line, matched as whole words and ignoring case. The file stays outside the
   repo. Fill it from your own profile with::

       uv run aula --output json profile | uv run python scripts/check_fixture_values.py --learn

2. Shapes that account data has and placeholders don't: UniLogins, Aula-sized IDs,
   institution codes, and common Danish names inside strings.

Fixtures use placeholders instead: ``Barn Et``, ``Værge Et``, ``Lærer Et``,
``Skole Et``, ``barn0001``, ``900001``, ``G90001``, ``1000001``. A line that must keep
a flagged value can carry the comment ``value-check: ok``.
"""

import io
import json
import os
import re
import sys
import tokenize
from dataclasses import dataclass
from pathlib import Path

PRAGMA = "value-check: ok"
DEFAULT_LIST = Path.home() / ".config" / "aula" / "never-commit.txt"

_UNILOGIN = re.compile(r"(?<![\w-])[a-zæøå]{4}\d[a-z0-9]{3}(?![\w-])")
_UNILOGIN_PLACEHOLDER = re.compile(r"(?:barn|fake)\d{4}")
_ID = re.compile(r"(?<![\w.])\d{6,9}(?![\w.])")
_ROUND_ID = re.compile(r"[1-9]\d?0{2,}\d{0,2}")
_DATE = re.compile(r"(?:19|20)\d\d(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])")
_INSTITUTION_CODE = re.compile(r"(?<![\w-])[A-Z]\d{5}(?![\w-])")
_CODE_PLACEHOLDER = re.compile(r"[A-Z]9\d{4}")
_WORD = re.compile(r"(?<![\w-])[A-ZÆØÅ][a-zæøåéü]+(?![\w-])")

# Common given names and surnames in Denmark. Names that are also everyday words
# in code or prose (Bo, Line, Mark, Max, Per, Jan, August, Storm, Holm...) are left out.
_NAMES_TEXT = """
    ida clara freja alma ella sofia anna laura karla agnes olivia josefine lily ellen nora
    alberte mathilde isabella maja liva frida asta signe lærke victoria caroline emilie
    sofie cecilie julie mille marie sara amalie ronja luna silje esther vigga ingrid lea
    andrea naja nanna hannah johanne alba aya selma thea emily celina molly carla filippa
    iben lina malou mynte rosa sigrid silke smilla vilma ellie elvira merle mia tilde
    emma mette hanne susanne anne lene kirsten pia charlotte tina louise maria helle
    camilla karen inge birgitte bente marianne gitte lise jette rikke dorthe
    tanja heidi trine malene pernille katrine christina stine nina linda annette lisbeth
    vibeke lotte lærke ulla winnie sanne tove grethe ruth else birthe kristine josephine
    william noah oscar lucas carl victor alfred malthe emil valdemar aksel oliver elias
    arthur frederik magnus felix viggo theo otto anton johan liam albert konrad
    mikkel hugo walter ludvig bertram benjamin sebastian alexander mathias marius
    kasper jonas laurits lauge asger bjørn christian tobias villads vincent adam
    alvin aske bastian erik ebbe finn gustav harald halfdan ivan jakob jacob jens
    kristian lasse loui louis mads marcus milas nikolaj niels olaf ole peter philip
    rasmus silas sigurd tristan wilfred lars søren henrik thomas michael jesper martin
    anders morten hans poul brian jørgen steen torben claus kenneth allan rene ulrik
    kristoffer daniel nicolai simon jonathan rune troels mogens preben leif bent
    flemming kurt svend carsten karsten dennis bjarne palle jimmi johnny
    mohammad mohammed muhammad ahmed ahmad omar yusuf ibrahim hassan hussein mustafa
    emre fatima aisha zeynep elif esra yasmin amina nour maryam leyla hiba alina
    anja natalia oliwia zofia agnete astrid bodil dagmar jonna karoline katja kirstine
    nicoline rebecca sille stella vera christoffer esben jeppe nicklas patrick sander sune
    aron bertil eigil elliot gunnar holger johannes julius knud oskar pelle vagn
    jensen nielsen hansen pedersen andersen christensen larsen sørensen rasmussen
    jørgensen petersen madsen kristensen olsen thomsen christiansen poulsen johansen
    møller mortensen knudsen jakobsen jacobsen mikkelsen olesen frederiksen laursen
    henriksen schmidt eriksen kristiansen clausen simonsen svendsen andreasen
    iversen jeppesen mogensen jespersen lauridsen kjær carlsen østergaard
    vestergaard nørgaard lassen bertelsen kjeldsen bruun friis juhl krogh thygesen
    gregersen jessen mathiesen michelsen paulsen steffensen villadsen dalgaard damgaard
    kjærgaard nygaard overgaard brandt lindberg ebbesen nissen
"""
_NAMES = frozenset(_NAMES_TEXT.split())

# Words that are never names, kept for the parts of a learned name to skip.
_GENERIC_TEXT = """
    skole børnehus børnehave vuggestue sfo fritidshjem klub dagtilbud institution
    afdeling friskole privatskole efterskole gymnasium school den det og på af til the
"""
_GENERIC_NAME_PARTS = frozenset(_GENERIC_TEXT.split())


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    kind: str
    value: str

    def __str__(self) -> str:
        return f"{self.path}:{self.line}: {self.kind}: {self.value}"


def load_listed_values(path: Path) -> list[str]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return []
    return [line.strip() for line in lines if line.strip() and not line.startswith("#")]


def _listed_pattern(values: list[str]) -> re.Pattern[str] | None:
    if not values:
        return None
    alternatives = "|".join(re.escape(v) for v in sorted(values, key=len, reverse=True))
    return re.compile(rf"(?<!\w)(?:{alternatives})(?!\w)", re.IGNORECASE)


def _masked(value: str) -> str:
    return value[:2] + "…" if len(value) > 2 else "…"


def _string_lines(path: str, text: str) -> dict[int, str]:
    """The text inside Python string literals, by line. Other files count whole."""
    if not path.endswith(".py"):
        return dict(enumerate(text.splitlines(), 1))

    found: dict[int, str] = {}
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(text).readline))
    except tokenize.TokenError, SyntaxError:
        return dict(enumerate(text.splitlines(), 1))
    for token in tokens:
        if token.type not in (tokenize.STRING, tokenize.FSTRING_MIDDLE):
            continue
        for offset, part in enumerate(token.string.splitlines()):
            line = token.start[0] + offset
            found[line] = f"{found.get(line, '')} {part}"
    return found


def _shape_findings(path: str, line: int, text: str) -> list[Finding]:
    findings = []
    for match in _UNILOGIN.finditer(text):
        if not _UNILOGIN_PLACEHOLDER.fullmatch(match.group()):
            findings.append(Finding(path, line, "UniLogin-shaped value", match.group()))
    for match in _ID.finditer(text):
        value = match.group()
        placeholder = (
            len(set(value)) == 1
            or value in "1234567890"
            or value in "9876543210"
            or _ROUND_ID.fullmatch(value)
            or _DATE.fullmatch(value)
        )
        if not placeholder:
            findings.append(Finding(path, line, "ID-shaped number", value))
    for match in _INSTITUTION_CODE.finditer(text):
        if not _CODE_PLACEHOLDER.fullmatch(match.group()):
            findings.append(Finding(path, line, "institution code", match.group()))
    return findings


def check_text(path: str, text: str, listed: re.Pattern[str] | None) -> list[Finding]:
    lines = text.splitlines()
    skipped = {number for number, line in enumerate(lines, 1) if PRAGMA in line}
    findings = []

    if listed is not None:
        for number, line in enumerate(lines, 1):
            if number not in skipped:
                findings += [
                    Finding(path, number, "listed value", _masked(m.group()))
                    for m in listed.finditer(line)
                ]

    for number, line in enumerate(lines, 1):
        if number not in skipped:
            findings += _shape_findings(path, number, line)

    for number, strings in _string_lines(path, text).items():
        if number in skipped:
            continue
        for match in _WORD.finditer(strings):
            if match.group().casefold() in _NAMES:
                findings.append(Finding(path, number, "common name", match.group()))

    # A listed value is already reported, masked; never print it again in full.
    if listed is not None:
        findings = [
            f for f in findings if f.kind == "listed value" or not listed.fullmatch(f.value)
        ]
    return findings


def learn(payload: object) -> set[str]:
    """Pick the names, IDs, UniLogins and codes out of ``aula --output json profile``."""
    found: set[str] = set()

    def walk(value: object, key: str) -> None:
        key = key.casefold()
        if isinstance(value, dict):
            for child_key, child in value.items():
                walk(child, str(child_key))
        elif isinstance(value, list):
            for child in value:
                walk(child, key)
        elif "picture" in key or "url" in key or isinstance(value, bool):
            return
        elif isinstance(value, int):
            if key.endswith(("id", "ids", "code")) and value >= 1000:
                found.add(str(value))
        elif isinstance(value, str) and value.strip():
            if "name" in key:
                found.add(value.strip())
                for word in re.findall(r"[^\W\d_]+", value):
                    if len(word) >= 3 and word.casefold() not in _GENERIC_NAME_PARTS:
                        found.add(word)
            elif key.endswith(("id", "code", "login", "email", "phone")) or "address" in key:
                found.add(value.strip())

    walk(payload, "")
    return found


def _learn_into(path: Path) -> int:
    values = learn(json.load(sys.stdin))
    known = set(load_listed_values(path))
    new = values - known
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(f"{v}\n" for v in sorted(known | values)), encoding="utf-8")
    path.chmod(0o600)
    print(f"Added {len(new)} value(s) to {path} ({len(known | values)} in total).")
    return 0


def main(argv: list[str]) -> int:
    list_path = Path(os.environ.get("AULA_NEVER_COMMIT", DEFAULT_LIST))
    if argv[:1] == ["--learn"]:
        return _learn_into(list_path)

    listed = _listed_pattern(load_listed_values(list_path))
    findings = []
    for name in argv:
        try:
            text = Path(name).read_text(encoding="utf-8")
        except UnicodeDecodeError, FileNotFoundError, IsADirectoryError:
            continue
        findings += check_text(name, text, listed)

    for finding in findings:
        print(finding)
    if findings:
        print(
            f"\n{len(findings)} value(s) look like they come from a live Aula account. "
            "Use placeholders (Barn Et, barn0001, 900001), or add the comment "
            f"'{PRAGMA}' to a line that must keep its value."
        )
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
