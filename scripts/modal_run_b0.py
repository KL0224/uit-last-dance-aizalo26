#!/usr/bin/env python3
"""Script chạy End-to-End B0 Pipeline trên GPU của nền tảng Modal (Serverless GPU).

Tính năng:
  - Tự động tải và cache model `Qwen/Qwen3.5-9B` trên Modal Volume (`datamate-b0-volume`)
    chỉ trong lần chạy đầu tiên; các lần chạy sau dùng lại ngay lập tức.
  - Chỉ đẩy đúng các thư mục `business_id` cần thiết cho tập câu hỏi được chọn lên Modal
    (tiết kiệm băng thông upload khi test `--limit 10` hoặc `--business-id biz_105`).
  - Tự động tải toàn bộ kết quả & log (`submission.jsonl`, `detailed_logs.jsonl`,
    `gate_trace.jsonl`, `eval_report.json`, `logs/*.json`) về máy local tại `--local-output-dir`.

Ví dụ sử dụng:
  1. Chạy thử 10 mẫu trong tập train (có lưu cả phần suy nghĩ <think> của LLM):
     modal run scripts/modal_run_b0.py --split train --limit 10 --enable-thinking

  2. Chạy thử riêng doanh nghiệp biz_105 trong tập train:
     modal run scripts/modal_run_b0.py --split train --business-id biz_105

  3. Chạy toàn bộ tập public_test để lấy file nộp bài:
     modal run scripts/modal_run_b0.py --split public_test --local-output-dir artifacts/runs/public_test
"""

from __future__ import annotations

import io
import json
import os
from pathlib import Path
import tarfile
from typing import Any

import modal

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Chọn GPU mặc định là "A100" (40GB VRAM) để đảm bảo đủ KV cache cho context dài 8192 tokens.
# Có thể đổi linh hoạt: MODAL_GPU=A100 hoặc MODAL_GPU=A10G
SELECTED_GPU = os.environ.get("MODAL_GPU", "A100")

# 1. Định nghĩa môi trường Container trên Modal (cài đặt đầy đủ từ requirements.txt gồm PyTorch, vLLM, DuckDB...)
image = (
    modal.Image.debian_slim(python_version="3.12")
    .env({"VLLM_USE_FLASHINFER_SAMPLER": "0"})
    .pip_install_from_requirements(str(PROJECT_ROOT / "requirements.txt"))
    .add_local_file(str(PROJECT_ROOT / "requirements.txt"), remote_path="/workspace/requirements.txt")
    .add_local_file(str(PROJECT_ROOT / "pyproject.toml"), remote_path="/workspace/pyproject.toml")
    .add_local_file(str(PROJECT_ROOT / "uv.lock"), remote_path="/workspace/uv.lock")
    .add_local_file(str(PROJECT_ROOT / "requirements-lock.txt"), remote_path="/workspace/requirements-lock.txt")
    .add_local_file(str(PROJECT_ROOT / "README.md"), remote_path="/workspace/README.md")
    .add_local_file(str(PROJECT_ROOT / "main.py"), remote_path="/workspace/main.py")
    .add_local_dir(str(PROJECT_ROOT / "src"), remote_path="/workspace/src")
    .add_local_dir(str(PROJECT_ROOT / "configs"), remote_path="/workspace/configs")
    .add_local_dir(str(PROJECT_ROOT / "scripts"), remote_path="/workspace/scripts")
    .add_local_dir(str(PROJECT_ROOT / "tests"), remote_path="/workspace/tests")
    .add_local_dir(str(PROJECT_ROOT / "docs"), remote_path="/workspace/docs")
    .add_local_dir(str(PROJECT_ROOT / "examples"), remote_path="/workspace/examples")
    .add_local_dir(str(PROJECT_ROOT / "data" / "train"), remote_path="/workspace/data/train")
)

if (PROJECT_ROOT / "data" / "public_test").is_dir():
    image = image.add_local_dir(
        str(PROJECT_ROOT / "data" / "public_test"),
        remote_path="/workspace/data/public_test",
    )

app = modal.App("datamate-b0-pipeline", image=image)

# Volume bền vững trên Modal để lưu weights model (~18GB) và cache DuckDB bundles
volume = modal.Volume.from_name("datamate-b0-volume", create_if_missing=True)
VOL_ROOT = Path("/vol")


@app.function(
    gpu=SELECTED_GPU,
    volumes={str(VOL_ROOT): volume},
    timeout=21600,  # 6 giờ (21600 giây). Container tự động tắt ngay khi chạy xong, không tính phí thời gian dư thừa.
)
def run_b0_on_modal_gpu(
    split: str,
    run_name: str,
    limit: int = 0,
    batch_size: int = 32,
    business_ids: list[str] | None = None,
    question_ids: list[str] | None = None,
    model_id: str = "Qwen/Qwen3.5-9B",
    enable_thinking: bool = True,
    timeout_sec: float = 10.0,
    max_rows: int = 10000,
) -> bytes:
    """Hàm thực thi trên GPU của Modal: tải model (nếu chưa có), chạy B0.1->B0.5 trên /workspace/data và nén kết quả trả về."""
    import os
    import sys
    os.environ["VLLM_USE_FLASHINFER_SAMPLER"] = "0"
    from huggingface_hub import snapshot_download

    if "/workspace/src" not in sys.path:
        sys.path.insert(0, "/workspace/src")
    if "/workspace" not in sys.path:
        sys.path.insert(0, "/workspace")

    from scripts.run_b0_pipeline import run_pipeline_cli

    # 1. Đảm bảo model đã có trong Modal Volume (/vol/models/...)
    safe_model_dir = model_id.replace("/", "--")
    model_dir = VOL_ROOT / "models" / safe_model_dir
    complete_marker = model_dir / ".download_complete"
    if not (complete_marker.is_file() and (model_dir / "config.json").is_file()):
        print(f"[Modal GPU] Đang tải model {model_id} vào Volume {model_dir} (chỉ tải lần đầu)...", flush=True)
        model_dir.mkdir(parents=True, exist_ok=True)
        snapshot_download(repo_id=model_id, local_dir=str(model_dir))
        complete_marker.write_text("complete", encoding="utf-8")
        (model_dir / ".model-download.json").write_text(json.dumps({"status": "complete"}), encoding="utf-8")
        volume.commit()
    else:
        print(f"[Modal GPU] Đã tìm thấy model cache tại {model_dir}", flush=True)

    # 2. Sử dụng trực tiếp dữ liệu tại /workspace/data/<split> đã được mount sẵn trong Image
    remote_split_dir = Path("/workspace/data") / split
    bundles_dir = VOL_ROOT / "bundles" / split
    remote_out_dir = VOL_ROOT / "runs" / run_name
    remote_out_dir.mkdir(parents=True, exist_ok=True)

    # 3. Chạy trọn vẹn B0Pipeline
    run_pipeline_cli(
        split_dir=remote_split_dir,
        bundles_dir=bundles_dir,
        output_dir=remote_out_dir,
        config_path=Path("/workspace/configs/qwen3_5_9b.toml"),
        model_path=model_dir,
        enable_thinking=enable_thinking,
        business_ids=business_ids,
        question_ids=question_ids,
        limit=limit if limit > 0 else None,
        batch_size=batch_size,
        timeout_sec=timeout_sec,
        max_rows=max_rows,
        on_bundle_ready=lambda _b, _p: volume.commit(),
    )
    volume.commit()

    # 4. Đóng gói toàn bộ thư mục kết quả & log để gửi thẳng về máy local
    out_buf = io.BytesIO()
    with tarfile.open(fileobj=out_buf, mode="w:gz") as tar:
        for item in remote_out_dir.rglob("*"):
            if item.is_file():
                tar.add(str(item), arcname=str(item.relative_to(remote_out_dir)))
    return out_buf.getvalue()


@app.local_entrypoint()
def main(
    split: str = "train",
    limit: int = 0,
    batch_size: int = 32,
    business_id: str = "",
    question_id: str = "",
    model_id: str = "Qwen/Qwen3.5-9B",
    enable_thinking: bool = True,
    local_output_dir: str = "",
) -> None:
    """Entrypoint chạy trên máy local khi gõ `modal run scripts/modal_run_b0.py ...`."""
    split_dir = PROJECT_ROOT / "data" / split
    if not split_dir.is_dir():
        raise SystemExit(f"Không tìm thấy thư mục dữ liệu: {split_dir}")

    biz_list = [b.strip() for b in business_id.split(",") if b.strip()] or None
    q_list = [qid.strip() for qid in question_id.split(",") if qid.strip()] or None

    tag = f"n{limit}" if limit > 0 else "all"
    if biz_list:
        tag = "_".join(biz_list) + f"_{tag}"
    run_name = f"{split}_{tag}"
    out_dir = Path(local_output_dir) if local_output_dir else (PROJECT_ROOT / "artifacts" / "runs" / run_name)
    out_dir.mkdir(parents=True, exist_ok=True)

    print(
        f"[Local] Đang khởi chạy Modal GPU ({SELECTED_GPU}) cho split='{split}' "
        f"(limit={limit or 'ALL'}, batch_size={batch_size}, business_id={biz_list or 'ALL'})...",
        flush=True,
    )

    result_tar_bytes = run_b0_on_modal_gpu.remote(
        split=split,
        run_name=run_name,
        limit=limit,
        batch_size=batch_size,
        business_ids=biz_list,
        question_ids=q_list,
        model_id=model_id,
        enable_thinking=enable_thinking,
    )

    with tarfile.open(fileobj=io.BytesIO(result_tar_bytes), mode="r:gz") as tar:
        tar.extractall(path=out_dir)

    print("\n======================================================================")
    print(f"[HOÀN TẤT] Đã tải toàn bộ kết quả và log từ Modal GPU về máy local tại:")
    print(f"  Thư mục gốc          : {out_dir}")
    print(f"  1. File nộp bài      : {out_dir / 'submission.jsonl'}")
    print(f"  2. Log suy nghĩ LLM  : {out_dir / 'detailed_logs.jsonl'}")
    print(f"  3. Log cổng B0.5     : {out_dir / 'gate_trace.jsonl'}")
    print(f"  4. Log từng câu hỏi  : {out_dir / 'logs/'}")
    if (out_dir / "eval_report.json").is_file():
        report = json.loads((out_dir / "eval_report.json").read_text(encoding="utf-8"))
        print(f"  5. Báo cáo chấm điểm : {out_dir / 'eval_report.json'}")
        print(
            f"     - Đúng (+1)       : {report['correct']}/{report['total_evaluated']} ({report['accuracy_percent']}%)\n"
            f"     - Sai (-1)        : {report['wrong']}\n"
            f"     - Abstain (0)     : {report['abstained']}\n"
            f"     => ĐIỂM PA        : {report['pa_score']} ({report['pa_percent']}%) [PA Points = {report['pa_points']}/{report['total_evaluated']}]"
        )
    print("======================================================================")

