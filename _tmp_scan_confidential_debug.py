import logging
import tempfile
from pathlib import Path

import agent_engine


def main() -> None:
    temp_dir = tempfile.TemporaryDirectory()
    db_path = Path(temp_dir.name) / "tmp_scan_debug.db"
    db = agent_engine.ProcessedJobsDB(db_path)

    logger = logging.getLogger("tmp.scan.confidential")
    logger.handlers = []
    logger.setLevel(logging.INFO)
    stream = logging.StreamHandler()
    stream.setLevel(logging.INFO)
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    stream.setFormatter(formatter)
    logger.addHandler(stream)

    session = agent_engine.TelegramJobSession(
        bot_token="dummy",
        chat_id=1,
        db=db,
        new_jobs=[],
        query="q",
        logger=logger,
        easy_apply_run_mode="search",
    )

    job_url = "https://www.linkedin.com/jobs/view/4400959935/"
    scanned = session._scan_easy_apply_fields(job_url)
    print("\n=== DISCOVERED ===")
    for idx, item in enumerate(scanned, 1):
        print(f"{idx}. {item}")

    print("\n=== OPTIONS ===")
    for k, v in session._apply_field_options.items():
        print(f"{k}: {v[:10]}")

    db.close()
    temp_dir.cleanup()


if __name__ == "__main__":
    main()
