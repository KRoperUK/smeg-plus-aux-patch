#!/usr/bin/env python3
"""Validate a Conventional Commits message, or a PR title.

Conventional commits are not a style preference here — the repository squash-merges, so the
PR title becomes the commit on `main`, and Release Please reads it to pick the next version
and write `CHANGELOG.md`. A title that does not parse means the release is silently wrong
(or does not happen), which is why this is enforced in two places:

  * as a `commit-msg` hook, so a local commit cannot be made with a bad message;
  * in CI against the PR title, because that is the message that actually lands.

usage:
    check_commit_msg.py .git/COMMIT_EDITMSG     # hook form
    check_commit_msg.py --title "feat: a thing"  # CI form
"""
import argparse
import re
import sys

TYPES = ("feat", "fix", "docs", "style", "refactor", "perf", "test",
         "build", "ci", "chore", "revert")

# type[(scope)][!]: description
HEADER = re.compile(
    r"^(?P<type>[a-z]+)"
    r"(?:\((?P<scope>[^()\s]+)\))?"
    r"(?P<breaking>!)?"
    r": (?P<desc>\S.*)$"
)

MAX_HEADER = 100
# git generates these; they are not ours to police
SKIP = re.compile(
    r"^(Merge |Revert \"|fixup! |squash! |amend! |"
    r"Apply .* patch|Auto-merged |Reapply )")

HELP = """\
Conventional Commits are required on this repository.

    <type>[(scope)][!]: <description>

  types      : %s
  breaking   : add ! before the colon, e.g. `feat!: ...`, or a `BREAKING CHANGE:` footer
  examples   : feat: always offer AUX first in the SRC cycle
               fix(media): keep SIZE_1/2/4 deltas when replacing a tone
               docs!: rename the project to smeg-plus-patches

The PR title becomes the commit on main (we squash-merge), and drives the version:

  feat  -> minor      fix -> patch      ! -> major      docs/chore/... -> no release
""" % ", ".join(TYPES)


def check(text):
    """Return a list of problems with a commit message."""
    lines = text.splitlines()
    # ignore comments and trailing blank lines
    while lines and lines[0].lstrip().startswith("#"):
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    if not lines:
        return ["the message is empty"]

    header = lines[0].strip()
    if SKIP.match(header):
        return []

    m = HEADER.match(header)
    if not m:
        return ["%r does not look like `<type>[(scope)][!]: <description>`" % header]

    problems = []
    if m.group("type") not in TYPES:
        problems.append("unknown type %r — expected one of: %s"
                        % (m.group("type"), ", ".join(TYPES)))
    if len(header) > MAX_HEADER:
        problems.append("the first line is %d characters; keep it under %d"
                        % (len(header), MAX_HEADER))
    if m.group("desc")[0].isupper():
        problems.append("the description starts with a capital; use lower case after ': '")
    if m.group("desc").endswith("."):
        problems.append("the description ends with a full stop; drop it")

    body = "\n".join(lines[1:])
    if m.group("breaking") and "BREAKING CHANGE" in body:
        pass  # both is fine
    return problems


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("msgfile", nargs="?",
                    help="a commit message file (what the commit-msg hook passes)")
    ap.add_argument("--title", help="validate a string instead, e.g. a PR title")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    if args.title is not None:
        text, what = args.title, "PR title"
    elif args.msgfile:
        try:
            with open(args.msgfile, encoding="utf-8", errors="replace") as fh:
                text = fh.read()
        except OSError as e:
            sys.exit("cannot read %s: %s" % (args.msgfile, e))
        what = "commit message"
    else:
        # sys.exit rather than ap.error so this plainly cannot fall through
        ap.print_usage(sys.stderr)
        sys.exit("give a message file or --title")

    problems = check(text)
    if not problems:
        return 0
    print("this %s does not follow Conventional Commits:\n" % what, file=sys.stderr)
    for p in problems:
        print("  - %s" % p, file=sys.stderr)
    if not args.quiet:
        print("\n" + HELP, file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
