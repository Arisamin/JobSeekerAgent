"""One-shot script to (re)send existing preview screenshots to Telegram."""
import os, pathlib, urllib.request, uuid

token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

if not token or not chat_id:
    raise SystemExit("TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not set")

shots_dir = pathlib.Path(__file__).parent / "Tests" / "Samples" / "preview_screenshots"
shots = sorted(shots_dir.glob("*.png"))
if not shots:
    raise SystemExit(f"No screenshots found in {shots_dir}")

print(f"Found {len(shots)} screenshot(s): {[s.name for s in shots]}")

for shot in shots:
    data = shot.read_bytes()
    boundary = uuid.uuid4().hex
    CRLF = b"\r\n"

    def pf(name: str, val: str) -> bytes:
        return (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="{name}"\r\n\r\n'
            f"{val}\r\n"
        ).encode("utf-8")

    body = (
        pf("chat_id", chat_id)
        + pf("caption", f"[Preview screenshot] {shot.name}")
        + (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="photo"; filename="{shot.name}"\r\n'
            f"Content-Type: image/png\r\n\r\n"
        ).encode("utf-8")
        + data
        + CRLF
        + f"--{boundary}--\r\n".encode("utf-8")
    )

    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendPhoto",
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            print(f"✅ Sent: {shot.name}  HTTP {resp.status}")
    except Exception as exc:
        print(f"❌ Failed: {shot.name}  {exc}")
