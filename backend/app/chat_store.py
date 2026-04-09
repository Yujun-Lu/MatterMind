from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List

from .config import CHAT_FILENAME
from .storage import now_iso


def chat_path(job_dir: Path) -> Path:
    return job_dir / CHAT_FILENAME


def load_chat(job_dir: Path) -> Dict[str, Any]:
    path = chat_path(job_dir)
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_chat(job_dir: Path, data: Dict[str, Any]) -> None:
    path = chat_path(job_dir)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _analysis_system_message(analysis_text: str) -> Dict[str, str]:
    return {"role": "system", "content": f"Analysis report:\n{analysis_text}"}


def _analysis_fingerprint(analysis_text: str, analysis_model: str | None) -> str:
    payload = f"{analysis_model or ''}\n{analysis_text}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def init_chat(
    job_id: str, system_prompt: str, analysis_text: str, analysis_model: str | None
) -> Dict[str, Any]:
    fingerprint = _analysis_fingerprint(analysis_text, analysis_model)
    return {
        "version": "0.3",
        "job_id": job_id,
        "created_at": now_iso(),
        "analysis_model": analysis_model,
        "analysis_fingerprint": fingerprint,
        "messages": [
            {"role": "system", "content": system_prompt},
            _analysis_system_message(analysis_text),
        ],
    }


def ensure_chat(
    job_id: str,
    job_dir: Path,
    system_prompt: str,
    analysis_text: str,
    analysis_model: str | None,
) -> Dict[str, Any]:
    data = load_chat(job_dir)
    fingerprint = _analysis_fingerprint(analysis_text, analysis_model)
    if not data or data.get("analysis_fingerprint") != fingerprint:
        data = init_chat(job_id, system_prompt, analysis_text, analysis_model)
        save_chat(job_dir, data)
        return data

    messages = data.get("messages", [])
    updated = False

    if not any(m.get("role") == "system" and m.get("content") == system_prompt for m in messages):
        messages.insert(0, {"role": "system", "content": system_prompt})
        updated = True

    analysis_system = _analysis_system_message(analysis_text)
    if not any(
        m.get("role") == "system"
        and m.get("content") == analysis_system["content"]
        for m in messages
    ):
        messages.insert(1, analysis_system)
        updated = True

    target_text = analysis_text.strip()
    for idx, message in enumerate(list(messages)):
        if (
            message.get("role") == "assistant"
            and message.get("content", "").strip() == target_text
        ):
            messages.pop(idx)
            updated = True
            break

    if updated:
        data["messages"] = messages
        save_chat(job_dir, data)

    return data


def public_messages(data: Dict[str, Any]) -> List[Dict[str, str]]:
    messages = data.get("messages", [])
    return [m for m in messages if m.get("role") != "system"]
