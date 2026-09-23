from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import bpy


def parse_args() -> argparse.Namespace:
    argv = sys.argv
    argv = argv[argv.index("--") + 1 :] if "--" in argv else []
    parser = argparse.ArgumentParser(description="Keep one Blender window alive and load BatiForge blends on command")
    parser.add_argument("--command-file", type=Path, required=True)
    parser.add_argument("--ack-file", type=Path, required=True)
    parser.add_argument("--initial-blend", type=Path)
    return parser.parse_args(argv)


def main() -> None:
    args = parse_args()
    command_file = args.command_file.resolve()
    ack_file = args.ack_file.resolve()
    command_file.parent.mkdir(parents=True, exist_ok=True)
    ack_file.parent.mkdir(parents=True, exist_ok=True)

    state = {"request_id": None}

    def write_ack(request_id: str, blend_path: str, status: str, error: str | None = None) -> None:
        payload = {
            "request_id": request_id,
            "blend_path": blend_path,
            "status": status,
            "pid": os.getpid(),
        }
        if error:
            payload["error"] = error
        ack_file.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    def poll() -> float:
        try:
            if not command_file.is_file():
                return 0.5
            payload = json.loads(command_file.read_text(encoding="utf-8"))
            request_id = str(payload.get("request_id", "")).strip()
            blend_path = str(payload.get("blend_path", "")).strip()
            if not request_id or request_id == state["request_id"]:
                return 0.5
            state["request_id"] = request_id
            target = Path(blend_path)
            if not target.is_file():
                write_ack(request_id, blend_path, "error", "blend path missing")
                return 0.5
            try:
                bpy.ops.wm.open_mainfile(filepath=str(target.resolve()))
                bpy.context.window.workspace = bpy.data.workspaces.get("Layout") or bpy.context.window.workspace
                write_ack(request_id, str(target.resolve()), "loaded")
            except Exception as exc:
                write_ack(request_id, blend_path, "error", repr(exc))
        except Exception:
            pass
        return 0.5

    bpy.app.timers.register(poll, first_interval=0.5, persistent=True)

    if args.initial_blend and args.initial_blend.is_file():
        initial = args.initial_blend.resolve()
        request_id = "initial"
        state["request_id"] = request_id
        try:
            bpy.ops.wm.open_mainfile(filepath=str(initial))
            write_ack(request_id, str(initial), "loaded")
        except Exception as exc:
            write_ack(request_id, str(initial), "error", repr(exc))


if __name__ == "__main__":
    main()
