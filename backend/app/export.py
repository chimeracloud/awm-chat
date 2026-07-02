"""Build a single user's data export (conversations, pins, attachments) as a zip.

Used by the admin "Export" button. Runs inside Cloud Run, which already has
Firestore + GCS access, so the admin just downloads the resulting zip — no
credentials or tooling on their side.
"""
import io
import json
import re
import zipfile
from datetime import datetime

from .storage import db, archive_bucket


def _ts(v) -> str:
    if v is None:
        return ""
    iso = getattr(v, "isoformat", None)
    return iso() if callable(iso) else str(v)


def _jsonable(d: dict) -> dict:
    return {k: (_ts(v) if hasattr(v, "isoformat") else v) for k, v in d.items()}


def _safe(name: str, fallback: str) -> str:
    name = (name or "").strip() or fallback
    name = re.sub(r"[^\w\-. ]+", "_", name)
    return name[:80].strip() or fallback


def build_user_export_zip(uid: str) -> tuple[bytes, dict]:
    """Return (zip_bytes, summary) for one user's full data export."""
    d = db()
    bucket = archive_bucket()

    profile = d.collection("users").document(uid).get().to_dict() or {}
    who = profile.get("display_name") or profile.get("email") or uid

    # Conversations + messages (sorted client-side to avoid index needs).
    convs = [{"id": c.id, **c.to_dict()}
             for c in d.collection("conversations").where("owner_uid", "==", uid).stream()]
    convs.sort(key=lambda c: _ts(c.get("created_at")))

    export = []
    conv_files: list[tuple[str, str]] = []
    for i, conv in enumerate(convs, 1):
        msgs = [m.to_dict() for m in
                d.collection("conversations").document(conv["id"])
                 .collection("messages").stream()]
        msgs.sort(key=lambda m: _ts(m.get("created_at")))

        title = conv.get("title") or "Untitled conversation"
        lines = [f"# {title}", "",
                 f"_Conversation {conv['id']} · started {_ts(conv.get('created_at'))}_", ""]
        for m in msgs:
            role = "User" if m.get("role") == "user" else "Assistant"
            lines.append(f"## {role}")
            for a in (m.get("attachments") or []):
                lines.append(f"> [attachment: {a.get('filename')}]")
            lines.append("")
            lines.append((m.get("content") or "").strip())
            lines.append("")
        conv_files.append((f"conversations/{i:04d} - {_safe(title, conv['id'])}.md",
                           "\n".join(lines)))
        export.append({
            "id": conv["id"],
            "title": title,
            "created_at": _ts(conv.get("created_at")),
            "updated_at": _ts(conv.get("updated_at")),
            "archived": conv.get("archived", False),
            "messages": [{
                "role": m.get("role"),
                "content": m.get("content"),
                "created_at": _ts(m.get("created_at")),
                "attachments": m.get("attachments") or [],
            } for m in msgs],
        })

    # Pinned context
    pins = [p.to_dict() for p in
            d.collection("pins").document(uid).collection("items").stream()]
    pins.sort(key=lambda p: _ts(p.get("created_at")))
    pin_md = ["# Pinned context", ""]
    for p in pins:
        pin_md.append(f"## {p.get('label') or 'Context'}")
        pin_md.append((p.get("content") or "").strip())
        pin_md.append("")

    # Attachments (metadata + original bytes + extracted text)
    atts = [{"id": a.id, **a.to_dict()} for a in
            d.collection("attachments").document(uid).collection("items").stream()]

    summary = {
        "user": who,
        "conversations": len(export),
        "messages": sum(len(c["messages"]) for c in export),
        "pins": len(pins),
        "attachments": len(atts),
    }

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for path, text in conv_files:
            z.writestr(path, text)
        z.writestr("data/conversations.json", json.dumps(export, indent=2, ensure_ascii=False))
        z.writestr("data/pinned_context.md", "\n".join(pin_md))
        z.writestr("data/pins.json", json.dumps(
            [{**p, "created_at": _ts(p.get("created_at"))} for p in pins],
            indent=2, ensure_ascii=False))
        z.writestr("data/profile.json", json.dumps(_jsonable(profile), indent=2, ensure_ascii=False))

        att_meta = []
        for a in atts:
            att_meta.append({
                "id": a.get("id"),
                "filename": a.get("filename"),
                "content_type": a.get("content_type"),
                "created_at": _ts(a.get("created_at")),
                "has_extracted_text": bool(a.get("extracted_text")),
                "has_transcript": bool(a.get("transcript")),
            })
            base = f"attachments/{a.get('id')}__{_safe(a.get('filename'), 'file')}"
            gcs_path = a.get("gcs_path")
            if gcs_path:
                blob = bucket.blob(gcs_path)
                if blob.exists():
                    z.writestr(base, blob.download_as_bytes())
            if a.get("extracted_text"):
                z.writestr(base + ".txt", a["extracted_text"])
            if a.get("transcript"):
                z.writestr(f"attachments/{a.get('id')}__transcript.txt", a["transcript"])
        z.writestr("attachments/attachments.json", json.dumps(att_meta, indent=2, ensure_ascii=False))

        z.writestr("README.txt",
            f"""AWM Chat export for {who}
Generated {datetime.now().astimezone().isoformat()}

WHAT'S INSIDE
  conversations/   One readable Markdown file per chat (full transcript).
  data/            The same content as JSON, plus your pinned context.
  attachments/     Every file you uploaded, plus extracted text / transcripts.

HOW TO USE THIS IN CLAUDE
  Claude does not import old chats as chats — there is no "restore history"
  feature. Use these files as reference material instead:

  - Claude Projects (Pro/Team): create a Project and add the files from
    conversations/ and attachments/ to the Project knowledge. Claude then
    draws on them in every chat in that Project.
  - Any Claude account: attach the relevant files directly to a chat when
    you want Claude to use that context.

  Start with data/pinned_context.md and the conversations that matter most.

Summary: {summary['conversations']} conversations, {summary['messages']} messages, {summary['pins']} pinned items, {summary['attachments']} attachments.
""")

    return buf.getvalue(), summary
