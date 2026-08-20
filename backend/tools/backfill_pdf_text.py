#!/usr/bin/env python3
"""Extract and store the text layer for PDFs uploaded before extraction existed.

Chat sends a PDF natively only on the newest turn; earlier turns fall back to
the stored text layer, which is far cheaper. PDFs uploaded before that change
have no `extracted_text`, so they keep being sent natively on every turn — the
exact cost this was meant to remove. This backfills them in place.

Read-mostly and idempotent: it only writes `extracted_text` on PDF attachments
that don't already have one, and re-running it is a no-op. Nothing else on the
document is touched, and no file in GCS is modified.

    gcloud auth application-default login
    python tools/backfill_pdf_text.py                 # dry run, changes nothing
    python tools/backfill_pdf_text.py --apply         # write the extracted text

Scanned PDFs have no text layer and yield nothing. Those are recorded with
`extracted_text_attempted` so the backfill doesn't retry them forever, and they
continue to be sent natively — which for a scan is the only useful option.
"""
import argparse
import io
import os
import sys

from google.cloud import firestore, storage

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app.attachments import MAX_EXTRACTED_CHARS, _truncate  # noqa: E402


def extract(raw: bytes) -> str:
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(raw))
    pages = []
    for page in reader.pages:
        try:
            text = page.extract_text() or ""
        except Exception:
            continue
        if text.strip():
            pages.append(text.strip())
    return _truncate("\n\n".join(pages))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--project", default=os.getenv("GCP_PROJECT", "chiops"))
    ap.add_argument("--database", default=os.getenv("FIRESTORE_DATABASE", "awm-chat"))
    ap.add_argument("--bucket", default=os.getenv("GCS_ARCHIVE_BUCKET", "awm-chat-archive"))
    ap.add_argument("--apply", action="store_true", help="Write changes (default is a dry run)")
    ap.add_argument("--uid", help="Limit to one user")
    args = ap.parse_args()

    db = firestore.Client(project=args.project, database=args.database)
    bucket = storage.Client(project=args.project).bucket(args.bucket)

    # attachments/{uid}/items/{attId} — collection_group reaches every user at
    # once, which is why this needs no list of uids.
    if args.uid:
        docs = list(db.collection("attachments").document(args.uid).collection("items").stream())
    else:
        docs = list(db.collection_group("items").stream())

    pdfs = [d for d in docs if (d.to_dict() or {}).get("content_type") == "application/pdf"]
    todo, skipped, missing = [], 0, 0
    for d in pdfs:
        data = d.to_dict() or {}
        if (data.get("extracted_text") or "").strip():
            skipped += 1
        elif data.get("extracted_text_attempted"):
            skipped += 1
        elif not data.get("gcs_path"):
            missing += 1
        else:
            todo.append(d)

    print(f"PDF attachments found : {len(pdfs)}")
    print(f"  already have text   : {skipped}")
    print(f"  no gcs_path         : {missing}")
    print(f"  to process          : {len(todo)}")
    if not todo:
        print("\nNothing to do.")
        return
    if not args.apply:
        print("\nDry run — re-run with --apply to write. Would process:")
        for d in todo:
            print(f"  {(d.to_dict() or {}).get('filename')}")
        return

    print()
    ok = empty = failed = 0
    for d in todo:
        data = d.to_dict() or {}
        name = data.get("filename") or d.id
        try:
            blob = bucket.blob(data["gcs_path"])
            if not blob.exists():
                print(f"  SKIP  {name} — file missing from storage")
                failed += 1
                continue
            text = extract(blob.download_as_bytes())
        except Exception as e:
            print(f"  FAIL  {name} — {type(e).__name__}: {str(e)[:90]}")
            failed += 1
            continue

        patch = {"extracted_text_attempted": True}
        if text.strip():
            patch["extracted_text"] = text
            ok += 1
            print(f"  OK    {name} — {len(text):,} chars")
        else:
            empty += 1
            print(f"  SCAN  {name} — no text layer, stays native")
        d.reference.update(patch)

    print(f"\nExtracted {ok}, no text layer {empty}, failed {failed}.")


if __name__ == "__main__":
    main()
