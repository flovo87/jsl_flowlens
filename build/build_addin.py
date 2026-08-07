#!/usr/bin/env python3
"""Build JSL_FlowLens_vX.Y.Z.jmpaddin from src/ and demo/.

The version in VERSION is the single source of truth: this script stamps it
into FlowLens.jsl and flowlens_parser.py before packaging, so those files can
never drift apart again.

JMP's own Add-In Builder writes uncompressed archives with Addin.def first;
this reproduces that exactly, because JMP is picky about it.

    python build/build_addin.py            # build dist/JSL_FlowLens_v<VERSION>.jmpaddin
    python build/build_addin.py --check    # verify only, write nothing
"""

import argparse
import datetime
import os
import re
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src")
DIST = os.path.join(ROOT, "dist")

# Addin.def must come first in the archive
PACKAGE = [
    ("src/Addin.def", "Addin.def"),
    ("src/addin.jmpcust", "addin.jmpcust"),
    ("src/FlowLens.jsl", "FlowLens.jsl"),
    ("src/flowlens_parser.py", "flowlens_parser.py"),
    ("src/flowlens_template.html", "flowlens_template.html"),
    ("src/icon.png", "icon.png"),
    ("README.md", "README.md"),
    ("CHANGELOG.md", "CHANGELOG.md"),
    ("LICENSE.txt", "LICENSE.txt"),
    ("demo/quality_snapshot/Main.jsl", "demo/Main.jsl"),
    ("demo/quality_snapshot/Utils.jsl", "demo/Utils.jsl"),
    ("demo/quality_snapshot/Report.jsl", "demo/Report.jsl"),
    ("demo/architecture/LaunchPad.jsl", "demo/LaunchPad.jsl"),
    ("demo/architecture/Tool_Report.jsl", "demo/Tool_Report.jsl"),
    ("demo/architecture/Tool_Cleanup.jsl", "demo/Tool_Cleanup.jsl"),
]


def read_version():
    with open(os.path.join(ROOT, "VERSION"), encoding="utf-8") as fh:
        v = fh.read().strip()
    if not re.match(r"^\d+\.\d+\.\d+$", v):
        sys.exit("VERSION must look like 1.2.3, got %r" % v)
    return v


def stamp(version, build_date, check=False):
    """Write version and build date into the sources. Returns list of edits."""
    edits = []

    jsl = os.path.join(SRC, "FlowLens.jsl")
    txt = open(jsl, encoding="utf-8").read()
    new = re.sub(r'(sl_version = ")[^"]*(")', r"\g<1>%s\g<2>" % version, txt)
    new = re.sub(r'(sl_build = ")[^"]*(")', r"\g<1>%s\g<2>" % build_date, new)
    new = re.sub(r"(// JSL FlowLens v)\d+\.\d+\.\d+", r"\g<1>%s" % version, new)
    if new != txt:
        edits.append("FlowLens.jsl")
        if not check:
            open(jsl, "w", encoding="utf-8").write(new)

    py = os.path.join(SRC, "flowlens_parser.py")
    txt = open(py, encoding="utf-8").read()
    new = re.sub(r'(VERSION = ")[^"]*(")', r"\g<1>%s\g<2>" % version, txt)
    if new != txt:
        edits.append("flowlens_parser.py")
        if not check:
            open(py, "w", encoding="utf-8").write(new)

    rd = os.path.join(ROOT, "README.md")
    txt = open(rd, encoding="utf-8").read()
    new = re.sub(r"^Version \d+\.\d+\.\d+", "Version %s" % version, txt,
                 count=1, flags=re.M)
    if new != txt:
        edits.append("README.md")
        if not check:
            open(rd, "w", encoding="utf-8").write(new)
    return edits


def smoke_test():
    """Parse the demo with the packaged parser, so a broken build fails here
    rather than in front of a user."""
    import importlib.util
    import tempfile
    spec = importlib.util.spec_from_file_location(
        "flp", os.path.join(SRC, "flowlens_parser.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    out = os.path.join(tempfile.mkdtemp(), "smoke.html")
    files = "\n".join(
        os.path.join(ROOT, "demo", "quality_snapshot", n)
        for n in ("Main.jsl", "Utils.jsl", "Report.jsl"))
    mod.run_simple(files_str=files, entry="Main.jsl",
                   template=os.path.join(SRC, "flowlens_template.html"),
                   out=out)
    size = os.path.getsize(out)
    if size < 20000:
        sys.exit("smoke test produced a suspiciously small page (%d bytes)" % size)
    return mod.VERSION, size


def build(version):
    os.makedirs(DIST, exist_ok=True)
    target = os.path.join(DIST, "JSL_FlowLens_v%s.jmpaddin" % version)
    missing = [s for s, _ in PACKAGE if not os.path.exists(os.path.join(ROOT, s))]
    if missing:
        sys.exit("missing source files:\n  " + "\n  ".join(missing))
    if os.path.exists(target):
        os.remove(target)
    # ZIP_STORED throughout: JMP's Add-In Builder does the same
    with zipfile.ZipFile(target, "w", zipfile.ZIP_STORED) as z:
        for src, arc in PACKAGE:
            z.write(os.path.join(ROOT, src), arc)
    with zipfile.ZipFile(target) as z:
        bad = z.testzip()
        if bad:
            sys.exit("archive is corrupt at %s" % bad)
        names = z.namelist()
    if names[0] != "Addin.def":
        sys.exit("Addin.def must be the first entry, found %s" % names[0])
    return target, len(names), os.path.getsize(target)


def main():
    ap = argparse.ArgumentParser(description="Build the JSL FlowLens add-in")
    ap.add_argument("--check", action="store_true",
                    help="verify sources and version stamping, build nothing")
    args = ap.parse_args()

    version = read_version()
    today = datetime.date.today().isoformat()
    edits = stamp(version, today, check=args.check)
    print("version %s (build %s)" % (version, today))
    print("stamped: %s" % (", ".join(edits) if edits else "already current"))

    pv, size = smoke_test()
    print("smoke test: parser %s produced %d bytes" % (pv, size))
    if pv != version:
        sys.exit("parser reports %s but VERSION says %s" % (pv, version))

    if args.check:
        print("check only - nothing written")
        return
    target, n, size = build(version)
    print("built %s (%d entries, %d bytes)" % (target, n, size))


if __name__ == "__main__":
    main()
