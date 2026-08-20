#!/usr/bin/env python3
"""Export one user's AWM Chat data into a ready-to-send zip.

Pulls a single user's conversations + messages, pinned context, profile, and
uploaded attachments from Firestore + GCS, and packages them as:

    <out>/<label>_export/
        README.txt                     how to use the files in Claude
        conversations/                 one readable Markdown transcript per chat
            0001 - <title>.md
        data/
            conversations.json         structured dump of every chat + message
            pinned_context.md          the user's pinned context, readable
            pins.json
            profile.json
        attachments/
            <attId>__<filename>        the original uploaded files
            attachments.json           attachment metadata (+ extracted text)

...then zips that folder to <out>/<label>_export.zip.

Run it from a machine with read access to the project (a human `gcloud auth
application-default login`, or a service account key). Read-only — it never
writes to Firestore or GCS.

    pip install google-cloud-firestore google-cloud-storage
    gcloud auth application-default login          # or set GOOGLE_APPLICATION_CREDENTIALS

    python export_user_data.py \
        --uid <BELINDA_UID> \
        --project chiops \
        --database awm-chat \
        --bucket awm-chat-archive \
        --label belinda

Find the UID in the app: Admin -> Users -> Belinda's row (the `uid` field).
`--project`, `--database`, and `--bucket` default to the GCP_PROJECT /
FIRESTORE_DATABASE / GCS_ARCHIVE_BUCKET env vars if set; override to match your
Cloud Run config (the live values are project `chiops`, database `awm-chat`).
"""
import argparse
import json
import os
import re
import shutil
from datetime import datetime
from pathlib import Path

from google.cloud import firestore, storage


def _ts(v):
    """ISO-8601 string for a Firestore timestamp, or '' if missing."""
    if v is None:
        return ""
    if isinstance(v, datetime):
        return v.isoformat()
    iso = getattr(v, "isoformat", None)
    return iso() if callable(iso) else str(v)


def _sort_key(d, field):
    return _ts(d.get(field)) or ""


def _safe(name: str, fallback: str) -> str:
    name = (name or "").strip() or fallback
    name = re.sub(r"[^\w\-. ]+", "_", name)   # keep it filesystem-friendly
    return name[:80].strip() or fallback


def main() -> None:
    ap = argparse.ArgumentParser(description="Export one user's AWM Chat data.")
    ap.add_argument("--uid", help="Firestore user id (Admin -> Users)")
    ap.add_argument("--email", help="Look the user up by email instead of uid")
    ap.add_argument("--project", default=os.getenv("GCP_PROJECT", "chiops"))
    ap.add_argument("--database", default=os.getenv("FIRESTORE_DATABASE", "awm-chat"))
    ap.add_argument("--bucket", default=os.getenv("GCS_ARCHIVE_BUCKET", "awm-chat-archive"))
    ap.add_argument("--label", default="user", help="Name used for the output folder/zip")
    ap.add_argument("--out", default=".", help="Directory to write the export into")
    ap.add_argument(
        "--markdown-only", action="store_true",
        help="Skip downloading original attachment binaries. Extracted text and "
             "transcripts are still written, so nothing readable is lost. Use this "
             "for Claude Project knowledge, which takes text and would be blown "
             "past its size limit by raw PDFs and video files.",
    )
    args = ap.parse_args()

    db = firestore.Client(project=args.project, database=args.database)
    bucket = storage.Client(project=args.project).bucket(args.bucket)

    root = Path(args.out) / f"{args.label}_export"
    conv_dir = root / "conversations"
    data_dir = root / "data"
    if not args.uid:
        if not args.email:
            ap.error("give either --uid or --email")
        match = next(
            iter(db.collection("users").where("email", "==", args.email.lower()).limit(1).stream()),
            None,
        )
        if match is None:
            ap.error(f"no user found with email {args.email}")
        args.uid = match.id
        print(f"Resolved {args.email} -> {args.uid}")

    att_dir = root / "attachments"
    for d in (conv_dir, data_dir, att_dir):
        d.mkdir(parents=True, exist_ok=True)

    # --- Profile ---------------------------------------------------------
    profile = (db.collection("users").document(args.uid).get().to_dict()) or {}
    (data_dir / "profile.json").write_text(
        json.dumps({k: _ts(v) if hasattr(v, "isoformat") else v
                    for k, v in profile.items()}, indent=2, ensure_ascii=False)
    )
    who = profile.get("display_name") or profile.get("email") or args.uid

    # --- Conversations + messages ---------------------------------------
    convs = [
        {"id": c.id, **c.to_dict()}
        for c in db.collection("conversations").where("owner_uid", "==", args.uid).stream()
    ]
    convs.sort(key=lambda c: _sort_key(c, "created_at"))

    export = []
    for i, conv in enumerate(convs, 1):
        msgs = [
            m.to_dict()
            for m in db.collection("conversations").document(conv["id"])
                       .collection("messages").stream()
        ]
        msgs.sort(key=lambda m: _sort_key(m, "created_at"))

        title = conv.get("title") or "Untitled conversation"
        # Readable transcript
        lines = [f"# {title}", "",
                 f"_Conversation {conv['id']} · started {_ts(conv.get('created_at'))}_", ""]
        for m in msgs:
            role = "Belinda" if m.get("role") == "user" else "Assistant"
            lines.append(f"## {role}")
            for a in (m.get("attachments") or []):
                lines.append(f"> [attachment: {a.get('filename')}]")
            lines.append("")
            lines.append((m.get("content") or "").strip())
            lines.append("")
        fname = f"{i:04d} - {_safe(title, conv['id'])}.md"
        (conv_dir / fname).write_text("\n".join(lines), encoding="utf-8")

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

    (data_dir / "conversations.json").write_text(
        json.dumps(export, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # --- Pinned context --------------------------------------------------
    pins = [p.to_dict() for p in
            db.collection("pins").document(args.uid).collection("items").stream()]
    pins.sort(key=lambda p: _sort_key(p, "created_at"))
    (data_dir / "pins.json").write_text(
        json.dumps([{**p, "created_at": _ts(p.get("created_at"))} for p in pins],
                   indent=2, ensure_ascii=False), encoding="utf-8")
    pin_md = ["# Pinned context", ""]
    for p in pins:
        pin_md.append(f"## {p.get('label') or 'Context'}")
        pin_md.append((p.get("content") or "").strip())
        pin_md.append("")
    (data_dir / "pinned_context.md").write_text("\n".join(pin_md), encoding="utf-8")

    # --- Attachments (metadata + original files) ------------------------
    atts = [{"id": a.id, **a.to_dict()} for a in
            db.collection("attachments").document(args.uid).collection("items").stream()]
    meta = []
    for a in atts:
        meta.append({
            "id": a.get("id"),
            "filename": a.get("filename"),
            "content_type": a.get("content_type"),
            "created_at": _ts(a.get("created_at")),
            "has_extracted_text": bool(a.get("extracted_text")),
            "has_transcript": bool(a.get("transcript")),
        })
        gcs_path = a.get("gcs_path")
        if gcs_path and not args.markdown_only:
            blob = bucket.blob(gcs_path)
            if blob.exists():
                out_name = f"{a.get('id')}__{_safe(a.get('filename'), 'file')}"
                blob.download_to_filename(str(att_dir / out_name))
        # Preserve extracted text / transcripts as readable sidecars.
        if a.get("extracted_text"):
            (att_dir / f"{a.get('id')}__{_safe(a.get('filename'), 'file')}.txt").write_text(
                a["extracted_text"], encoding="utf-8")
        if a.get("transcript"):
            (att_dir / f"{a.get('id')}__transcript.txt").write_text(
                a["transcript"], encoding="utf-8")
    (att_dir / "attachments.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")

    # --- README for the recipient ---------------------------------------
    (root / "README.txt").write_text(
        f"""AWM Chat export for {who}
Generated {datetime.now().astimezone().isoformat()}

WHAT'S INSIDE
  conversations/   One readable Markdown file per chat (full transcript).
  data/            The same content as structured JSON, plus your pinned context.
  attachments/     Every file you uploaded, plus extracted text / transcripts.

HOW TO USE THIS IN CLAUDE
  Claude does not import old chats as chats — there is no "restore history"
  feature. Instead, use these files as reference material:

  - Claude Projects (Pro/Team): create a Project and add the files in
    conversations/ and attachments/ to the Project's knowledge. Claude can
    then draw on them in every chat in that Project.
  - Any Claude account: attach the relevant .md / files directly to a chat
    when you want Claude to use that context.

  Start with data/pinned_context.md and the conversations that matter most.

Summary: {len(export)} conversations, {sum(len(c['messages']) for c in export)} messages, {len(pins)} pinned items, {len(atts)} attachments.
""", encoding="utf-8")

    zip_path = shutil.make_archive(str(Path(args.out) / f"{args.label}_export"), "zip", root_dir=root)
    print(f"Done: {zip_path}")
    print(f"  {len(export)} conversations, {sum(len(c['messages']) for c in export)} messages, "
          f"{len(pins)} pins, {len(atts)} attachments")


if __name__ == "__main__":
    main()
