#!/usr/bin/env python3
"""CLI entry points backing the /worklog-* slash commands.

Kept as a single script (rather than one per command) so there is one
place that knows how to find the data directory, read the debug log,
etc. -- the slash commands are thin wrappers that just run this and
show the result.
"""

import argparse
import datetime
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))
import archive as archive_module  # noqa: E402
import check_and_summarize  # noqa: E402
import debug_log  # noqa: E402
import search_index  # noqa: E402
from paths import data_dir, lock_path, note_path  # noqa: E402


def cmd_show(args):
    date = args.date or datetime.date.today().isoformat()
    path = note_path(date)
    if not os.path.exists(path):
        print("No worklog for %s yet (not summarized, or nothing was captured that day)." % date)
        return
    with open(path, encoding="utf-8") as fh:
        print(fh.read())


def cmd_search(args):
    query = " ".join(args.query)
    if not query.strip():
        print("Usage: /worklog:search <keyword>")
        return
    results = search_index.search(query, limit=args.limit)
    if not results:
        print('No matches for "%s".' % query)
        return
    print('%d match(es) for "%s":\n' % (len(results), query))
    for r in results:
        print("- %s · %s · %s" % (r["date"], r["project"], r["title"]))
        if r["snippet"]:
            print("  %s" % r["snippet"])


def cmd_archive(args):
    archived = archive_module.archive_older_than(args.days)
    if not archived:
        print("Nothing to archive (nothing older than the cutoff, or already archived). Originals are untouched.")
        return
    print("Compressed %d date folder(s) into archive/. Originals under data/ were not modified or deleted:" % len(archived))
    for name in archived:
        print("  - %s" % name)


def cmd_debug(args):
    lines = debug_log.tail(args.lines)
    if not lines:
        print("No errors logged.")
        return
    print("Last %d debug log line(s):\n" % len(lines))
    sys.stdout.write("".join(lines))


def cmd_doctor(args):
    lines = []

    for var in ("CLAUDE_PLUGIN_DATA", "CLAUDE_PLUGIN_ROOT"):
        value = os.environ.get(var)
        lines.append("%s: %s" % (var, value if value else "not set for this process"))

    d = data_dir()
    lines.append("Data directory: %s" % d)
    try:
        os.makedirs(d, exist_ok=True)
        probe = os.path.join(d, ".doctor-write-test")
        with open(probe, "w", encoding="utf-8") as fh:
            fh.write("ok")
        os.remove(probe)
        lines.append("  writable: yes")
    except OSError as exc:
        lines.append("  writable: NO (%r)" % (exc,))

    data_root = os.path.join(d, "data")
    date_count = len([n for n in os.listdir(data_root) if os.path.isdir(os.path.join(data_root, n))]) if os.path.isdir(data_root) else 0
    lines.append("Captured date folders: %d" % date_count)
    if date_count == 0:
        lines.append("  no data captured yet -- if you expect activity, check that the Stop hook is registered (claude --debug)")

    pending = check_and_summarize.find_unsummarized_dates()
    if pending:
        lines.append("Pending (not yet summarized): %s" % ", ".join(pending))
    else:
        lines.append("Pending: none")

    lock = lock_path()
    if os.path.exists(lock):
        try:
            with open(lock, encoding="utf-8") as fh:
                info = json.load(fh)
            lines.append("Lock file present (pid %s) -- a summarization may be in progress, or it's stale." % info.get("pid"))
        except (ValueError, OSError):
            lines.append("Lock file present but unreadable.")
    else:
        lines.append("Lock: none held")

    recent_errors = debug_log.tail(5)
    if recent_errors:
        lines.append("\nMost recent debug log entries (see /worklog:debug for more):")
        lines.extend("  " + line.rstrip("\n") for line in recent_errors)
    else:
        lines.append("Recent errors: none")

    print("\n".join(lines))


def main():
    parser = argparse.ArgumentParser(prog="worklog-cli")
    sub = parser.add_subparsers(dest="command", required=True)

    p_show = sub.add_parser("show")
    p_show.add_argument("date", nargs="?", default=None)
    p_show.set_defaults(func=cmd_show)

    p_search = sub.add_parser("search")
    p_search.add_argument("query", nargs="*")
    p_search.add_argument("--limit", type=int, default=10)
    p_search.set_defaults(func=cmd_search)

    p_archive = sub.add_parser("archive")
    p_archive.add_argument("days", nargs="?", type=int, default=None)
    p_archive.set_defaults(func=cmd_archive)

    p_debug = sub.add_parser("debug")
    p_debug.add_argument("--lines", type=int, default=50)
    p_debug.set_defaults(func=cmd_debug)

    p_doctor = sub.add_parser("doctor")
    p_doctor.set_defaults(func=cmd_doctor)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
