"""Tải snapshot Hugging Face về đĩa; không import torch hoặc load weights.

Chỉ thực hiện download khi gọi script. Token riêng tư được huggingface_hub
đọc qua HF_TOKEN hoặc login sẵn có; không ghi token vào source/manifest.
"""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-id", default="Qwen/Qwen3.5-9B")
    parser.add_argument("--revision", default="main", help="Branch, tag or exact commit SHA")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("models/Qwen3.5-9B"),
        help="Thư mục đích dưới models/ (ví dụ: models/Qwen3.5-9B hoặc models/Qwen2.5-3B-Instruct)",
    )
    args = parser.parse_args()

    # Dependency download là optional; import tại đây giúp thông báo lỗi rõ.
    try:
        from huggingface_hub import HfApi, snapshot_download
    except ImportError as exc:
        raise SystemExit("Install download dependencies first: uv sync --extra download") from exc

    destination = args.output_dir.expanduser().resolve()
    # Resolve branch/tag một lần rồi tải đúng SHA, tránh main đổi giữa chừng.
    revision = HfApi().model_info(args.model_id, revision=args.revision).sha
    if not revision:
        raise SystemExit("Hugging Face did not return a commit SHA")
    manifest_path = destination / ".model-download.json"
    if manifest_path.exists():
        previous = json.loads(manifest_path.read_text(encoding="utf-8"))
        if previous.get("model_id") != args.model_id or previous.get("resolved_revision") != revision:
            raise SystemExit("Destination contains a different model/revision; choose a new directory")
    elif destination.exists() and any(destination.iterdir()):
        raise SystemExit("Destination is nonempty without a download manifest; choose a new directory")
    destination.mkdir(parents=True, exist_ok=True)
    manifest = {
        "model_id": args.model_id,
        "requested_revision": args.revision,
        "resolved_revision": revision,
        "status": "downloading",
    }

    def write_manifest() -> None:
        # Atomic replacement tránh để lại JSON dở dang khi process bị ngắt.
        temporary = manifest_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        temporary.replace(manifest_path)

    write_manifest()
    print(f"Downloading {args.model_id}@{revision} to {destination}")
    # Tải toàn bộ snapshot để không bỏ thiếu tokenizer/template/config/shards.
    # Chạy lại cùng SHA và cùng thư mục sẽ tận dụng cache download của Hub.
    snapshot_download(repo_id=args.model_id, revision=revision, local_dir=str(destination))
    manifest["status"] = "complete"
    manifest["completed_at_utc"] = datetime.now(timezone.utc).isoformat()
    write_manifest()
    print(f"Downloaded snapshot. Provenance: {manifest_path}")


if __name__ == "__main__":
    main()
