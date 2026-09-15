from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from chat import now_iso, run_model_tool_loop, write_transcript
from providers import make_provider
from tools import load_tool_declarations, to_openai_tools
from versioning import artifact_version_dict, build_artifact_version


ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT / "artifacts"
TRANSCRIPTS = ROOT / "transcripts"
VERSION = "v3"
PROMPT_PATH = ARTIFACTS / "system_prompt.md"
TOOLS_PATH = ARTIFACTS / "tools.yaml"
PROMPT = PROMPT_PATH.read_text(encoding="utf-8")
TOOLS = to_openai_tools(load_tool_declarations(TOOLS_PATH))
PROVIDER_NAME = "openrouter"
PROVIDER = make_provider(PROVIDER_NAME)
ARTIFACT_VERSION = build_artifact_version(VERSION, PROMPT_PATH, TOOLS_PATH)

SCENARIOS = [
    ("S01_service_status", ["Dịch vụ VPN production hiện có đang gặp sự cố không?"]),
    ("S02_device_vpn", ["Kiểm tra riêng kết nối VPN trên LT-204."]),
    ("S03_missing_environment", ["Kiểm tra email ở môi trường demo của team QA."]),
    ("S04_multiturn_correction", [
        "VPN trên LT-204 đang lỗi.",
        "À mã đúng là LT-318, máy macOS.",
        "Kiểm tra cả VPN trên máy đó và VPN production.",
    ]),
    ("S05_action_confirmation", ["Tạo ticket lỗi VPN trên LT-204 mức high."]),
]


def main() -> None:
    for scenario_id, user_turns in SCENARIOS:
        stamp = datetime.now().strftime("%Y%m%dT%H%M%S%f")
        transcript = {
            "transcript_id": f"demo_{VERSION}_{scenario_id}_{stamp}",
            **artifact_version_dict(ARTIFACT_VERSION),
            "provider": PROVIDER_NAME,
            "model": None,
            "system_prompt": str(PROMPT_PATH),
            "tools": str(TOOLS_PATH),
            "history_window": 5,
            "max_tool_rounds": 4,
            "created_at": now_iso(),
            "updated_at": now_iso(),
            "demo_scenario": scenario_id,
            "turns": [],
        }
        history: list[dict[str, str]] = []
        for index, user_text in enumerate(user_turns, 1):
            record = {
                "turn_index": index,
                "started_at": now_iso(),
                "user": user_text,
                "status": "started",
                "assistant_text": None,
                "rounds": [],
                "tool_events": [],
            }
            try:
                result = run_model_tool_loop(
                    provider=PROVIDER,
                    messages=[
                        {"role": "system", "content": PROMPT},
                        *history,
                        {"role": "user", "content": user_text},
                    ],
                    tools=TOOLS,
                    model=None,
                    max_tool_rounds=4,
                )
                record.update(result)
                history.extend([
                    {"role": "user", "content": user_text},
                    {"role": "assistant", "content": result["assistant_text"]},
                ])
                print(json.dumps({
                    "scenario": scenario_id,
                    "turn": index,
                    "status": result["status"],
                    "tool_events": result["tool_events"],
                }, ensure_ascii=False, default=str), flush=True)
            except Exception as exc:
                record.update({"status": "provider_error", "error": f"{type(exc).__name__}: {exc}"})
                print(json.dumps({
                    "scenario": scenario_id,
                    "turn": index,
                    "status": "provider_error",
                    "error": str(exc),
                }, ensure_ascii=False), flush=True)
            record["ended_at"] = now_iso()
            transcript["turns"].append(record)
        path = TRANSCRIPTS / f"{transcript['transcript_id']}.transcript.json"
        write_transcript(path, transcript)
        print(f"SAVED {path}", flush=True)


if __name__ == "__main__":
    main()