from __future__ import annotations

from datetime import datetime
from pathlib import Path
import sys
from typing import Any

import streamlit as st

# The Streamlit entry point lives in starter_v0 alongside the runtime modules.
# Add its own directory to sys.path first because the runtime uses absolute
# imports (chat, providers, tools).
STARTER_ROOT = Path(__file__).resolve().parent
if str(STARTER_ROOT) not in sys.path:
    sys.path.insert(0, str(STARTER_ROOT))

from chat import ROOT, now_iso, run_model_tool_loop, safe_slug, trim_history, write_transcript
from providers import make_provider
from tools import load_tool_declarations, to_openai_tools
from versioning import artifact_version_dict, build_artifact_version


ARTIFACTS_DIR = ROOT / "artifacts"
SYSTEM_PROMPT_PATH = ARTIFACTS_DIR / "system_prompt.md"
TOOLS_PATH = ARTIFACTS_DIR / "tools.yaml"
TRANSCRIPTS_DIR = ROOT / "transcripts"


def new_transcript(provider_name: str, model: str | None, version: str, history_window: int, max_tool_rounds: int) -> dict[str, Any]:
    artifact_version = build_artifact_version(version, SYSTEM_PROMPT_PATH, TOOLS_PATH)
    timestamp = datetime.now().strftime("%Y%m%dT%H%M%S%f")
    transcript_id = "_".join([safe_slug(version), safe_slug(provider_name), timestamp])
    return {
        "transcript_id": transcript_id,
        **artifact_version_dict(artifact_version),
        "provider": provider_name,
        "model": model,
        "system_prompt": str(SYSTEM_PROMPT_PATH),
        "tools": str(TOOLS_PATH),
        "history_window": history_window,
        "max_tool_rounds": max_tool_rounds,
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "turns": [],
    }


def initialise_state(provider_name: str, model: str | None, version: str, history_window: int, max_tool_rounds: int) -> None:
    if "messages" not in st.session_state:
        st.session_state.messages = []
    if "transcript" not in st.session_state:
        st.session_state.transcript = new_transcript(provider_name, model, version, history_window, max_tool_rounds)


def render_trace(result: dict[str, Any]) -> None:
    with st.expander(f"Tool trace — status: {result['status']}", expanded=bool(result["tool_events"])):
        st.caption(f"Tool rounds: {len(result['rounds'])}")
        for round_record in result["rounds"]:
            st.markdown(f"**Round {round_record['round']}**")
            if round_record["assistant_text"]:
                st.caption(f"Model: {round_record['assistant_text']}")
            for event in round_record["tool_results"]:
                st.code(event["tool"], language=None)
                st.json({"args": event["args"], "result": event["result"]})


def main() -> None:
    st.set_page_config(page_title="IT Helpdesk Agent", page_icon="🛠️", layout="wide")
    st.title("🛠️ IT Helpdesk Agent")
    st.caption("Chat UI dùng chung `run_model_tool_loop` với CLI và evaluation runtime.")

    with st.sidebar:
        st.header("Runtime")
        provider_name = st.selectbox("Provider", options=["openrouter", "openai", "anthropic", "gemini"])
        model = st.text_input("Model override (optional)").strip() or None
        version = st.text_input("Artifact version", value="v0").strip() or "v0"
        history_window = st.number_input("History window (turn pairs)", min_value=0, max_value=50, value=5, step=1)
        max_tool_rounds = st.number_input("Maximum tool rounds", min_value=1, max_value=10, value=4, step=1)

        if st.button("Clear conversation", use_container_width=True):
            st.session_state.clear()
            st.rerun()

    initialise_state(provider_name, model, version, int(history_window), int(max_tool_rounds))

    artifact = build_artifact_version(version, SYSTEM_PROMPT_PATH, TOOLS_PATH)
    with st.sidebar:
        st.divider()
        st.subheader("Artifact")
        st.code(artifact.artifact_version, language=None)
        st.caption(f"Prompt hash: {artifact.prompt_hash}")
        st.caption(f"Tools hash: {artifact.tools_hash}")
        transcript_path = TRANSCRIPTS_DIR / f"{st.session_state.transcript['transcript_id']}.transcript.json"
        st.caption(f"Transcript: {transcript_path.relative_to(ROOT)}")

    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])
            if message["role"] == "assistant" and message.get("result"):
                render_trace(message["result"])

    user_text = st.chat_input("Describe your IT issue…")
    if not user_text:
        return

    with st.chat_message("user"):
        st.markdown(user_text)
    st.session_state.messages.append({"role": "user", "content": user_text})

    turn_record: dict[str, Any] = {
        "turn_index": len(st.session_state.transcript["turns"]) + 1,
        "started_at": now_iso(),
        "user": user_text,
        "status": "started",
        "assistant_text": None,
        "rounds": [],
        "tool_events": [],
    }

    with st.chat_message("assistant"):
        try:
            system_prompt = SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")
            declarations = load_tool_declarations(TOOLS_PATH)
            provider = make_provider(provider_name)
            result = run_model_tool_loop(
                provider=provider,
                messages=[
                    {"role": "system", "content": system_prompt},
                    *trim_history(st.session_state.messages[:-1], int(history_window)),
                    {"role": "user", "content": user_text},
                ],
                tools=to_openai_tools(declarations),
                model=model,
                max_tool_rounds=int(max_tool_rounds),
            )
            turn_record.update(result)
            st.markdown(result["assistant_text"])
            render_trace(result)
            st.session_state.messages.append({"role": "assistant", "content": result["assistant_text"], "result": result})
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            turn_record.update({"status": "provider_error", "error": error})
            st.error(error)
            st.session_state.messages.append({"role": "assistant", "content": f"Error: {error}"})
        finally:
            turn_record["ended_at"] = now_iso()
            st.session_state.transcript["turns"].append(turn_record)
            write_transcript(transcript_path, st.session_state.transcript)


if __name__ == "__main__":
    main()