#!/usr/bin/env python3
"""Script chạy End-to-End DataMate Pipeline trên GPU của nền tảng Modal (Serverless GPU).

Tính năng:
  - Tự động tải và cache model `Qwen/Qwen3.5-9B` trên Modal Volume (`datamate-b0-volume`)
    chỉ trong lần chạy đầu tiên; các lần chạy sau dùng lại ngay lập tức.
  - Tự động tải toàn bộ kết quả & log (`submission.jsonl`, `detailed_logs.jsonl`,
    `gate_trace.jsonl`, `grounding_trace.jsonl`, `eval_report.json`, `logs/*.json`) về máy local tại `--local-output-dir`.

Ví dụ sử dụng:
  1. Chạy thử 10 mẫu trong tập train:
     modal run scripts/modal_run_pipeline.py --split train --limit 10 --enable-thinking

  2. Chạy thử riêng doanh nghiệp biz_105 trong tập train:
     modal run scripts/modal_run_pipeline.py --split train --business-id biz_105

  3. Chạy toàn bộ tập public_test để lấy file nộp bài:
     modal run scripts/modal_run_pipeline.py --split public_test --local-output-dir artifacts/runs/public_test

  4. Chạy và tải về kèm cả thư mục data xử lý Phần A & B (bundles):
     modal run scripts/modal_run_pipeline.py --split public_test --local-output-dir artifacts/runs/public_test --include-bundles
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

# Chọn GPU mặc định là "A100" (40GB VRAM)
SELECTED_GPU = os.environ.get("MODAL_GPU", "A100")

# 1. Định nghĩa môi trường Container trên Modal
image = (
    modal.Image.debian_slim(python_version="3.12")
    .env({"VLLM_USE_FLASHINFER_SAMPLER": "0"})
    .pip_install_from_requirements(str(PROJECT_ROOT / "requirements-lock.txt"))
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

if (PROJECT_ROOT / "artifacts" / "b01_b02_full" / "enriched_bundles").is_dir():
    image = image.add_local_dir(
        str(PROJECT_ROOT / "artifacts" / "b01_b02_full" / "enriched_bundles"),
        remote_path="/workspace/enriched_bundles",
    )

app = modal.App("datamate-pipeline", image=image)

# Giữ nguyên volume name hiện có để tái sử dụng model weights (~18GB) đã cache
volume = modal.Volume.from_name("datamate-b0-volume", create_if_missing=True)
VOL_ROOT = Path("/vol")


@app.function(
    gpu=SELECTED_GPU,
    volumes={str(VOL_ROOT): volume},
    timeout=36000,  # 10 giờ (36000 giây). Container tự động tắt ngay khi chạy xong.
)
def run_pipeline_on_modal_gpu(
    split: str,
    run_name: str,
    limit: int = 0,
    batch_size: int = 16,
    business_ids: list[str] | None = None,
    question_ids: list[str] | None = None,
    model_id: str = "Qwen/Qwen3.5-9B",
    grounding_model_id: str = "Qwen/Qwen2.5-3B-Instruct",
    enable_thinking: bool = True,
    enable_grounding: bool = True,
    enable_grounding_llm: bool = True,
    include_bundles: bool = False,
    timeout_sec: float = 10.0,
    max_rows: int = 10000,
) -> bytes:
    """Hàm thực thi trên GPU của Modal: tải model (nếu chưa có), chạy pipeline và nén kết quả trả về."""
    import os
    import sys
    os.environ["VLLM_USE_FLASHINFER_SAMPLER"] = "0"
    from huggingface_hub import snapshot_download

    if "/workspace/src" not in sys.path:
        sys.path.insert(0, "/workspace/src")
    if "/workspace" not in sys.path:
        sys.path.insert(0, "/workspace")

    from scripts.run_pipeline import run_pipeline_cli

    def _ensure_model(m_id: str) -> Path:
        safe_dir = m_id.replace("/", "--")
        m_dir = VOL_ROOT / "models" / safe_dir
        marker = m_dir / ".download_complete"
        if not (marker.is_file() and (m_dir / "config.json").is_file()):
            print(f"[Modal GPU] Đang tải model {m_id} vào Volume {m_dir} (chỉ tải lần đầu)...", flush=True)
            m_dir.mkdir(parents=True, exist_ok=True)
            snapshot_download(repo_id=m_id, local_dir=str(m_dir))
            marker.write_text("complete", encoding="utf-8")
            (m_dir / ".model-download.json").write_text(json.dumps({"status": "complete"}), encoding="utf-8")
            volume.commit()
        else:
            print(f"[Modal GPU] Đã tìm thấy model cache tại {m_dir}", flush=True)
        return m_dir

    # 1. Đảm bảo cả hai mô hình (9B Planner và 3B Grounding) đã có trong Volume
    planner_model_dir = _ensure_model(model_id)
    grounding_model_dir = _ensure_model(grounding_model_id) if (enable_grounding and enable_grounding_llm) else None

    # 2. Sử dụng trực tiếp dữ liệu tại /workspace/data/<split> đã được mount sẵn trong Image
    remote_split_dir = Path("/workspace/data") / split
    enriched_local = Path("/workspace/enriched_bundles")
    if enriched_local.is_dir() and split == "train":
        bundles_dir = enriched_local
        print(f"[Modal GPU] Tự động nạp 30 enriched bundles chuẩn B01 & B02 từ {bundles_dir}", flush=True)
    else:
        bundles_dir = VOL_ROOT / "bundles" / split
    remote_out_dir = VOL_ROOT / "runs" / run_name
    remote_out_dir.mkdir(parents=True, exist_ok=True)

    # 3. Chạy trọn vẹn DataMatePipeline với cấu hình 2 model vLLM trên 1 GPU A100 (40GB)
    run_pipeline_cli(
        split_dir=remote_split_dir,
        bundles_dir=bundles_dir,
        output_dir=remote_out_dir,
        config_path=Path("/workspace/configs/qwen3_5_9b.toml"),
        model_path=planner_model_dir,
        grounding_config_path=Path("/workspace/configs/qwen2_5_3b_grounding.toml") if enable_grounding_llm else None,
        grounding_model_path=grounding_model_dir,
        enable_thinking=enable_thinking,
        enable_grounding=enable_grounding,
        enable_grounding_llm=enable_grounding_llm,
        business_ids=business_ids,
        question_ids=question_ids,
        limit=limit if limit > 0 else None,
        batch_size=batch_size,
        timeout_sec=timeout_sec,
        max_rows=max_rows,
    )
    volume.commit()

    # 4. Đóng gói toàn bộ thư mục kết quả & log để gửi thẳng về máy local
    out_buf = io.BytesIO()
    with tarfile.open(fileobj=out_buf, mode="w:gz") as tar:
        for item in remote_out_dir.rglob("*"):
            if item.is_file():
                tar.add(str(item), arcname=str(item.relative_to(remote_out_dir)))
        if include_bundles and bundles_dir.is_dir():
            print(f"[Modal GPU] Đang đóng gói thư mục bundles ({bundles_dir}) gửi về local...", flush=True)
            for item in bundles_dir.rglob("*"):
                if item.is_file():
                    if business_ids:
                        rel = item.relative_to(bundles_dir)
                        top_biz = rel.parts[0] if rel.parts else ""
                        if top_biz not in business_ids:
                            continue
                    arc = Path("bundles") / item.relative_to(bundles_dir)
                    tar.add(str(item), arcname=str(arc))
    return out_buf.getvalue()


@app.local_entrypoint()
def main(
    split: str = "train",
    limit: int = 0,
    batch_size: int = 16,
    business_id: str = "",
    question_id: str = "",
    model_id: str = "Qwen/Qwen3.5-9B",
    grounding_model_id: str = "Qwen/Qwen2.5-3B-Instruct",
    enable_thinking: bool = True,
    enable_grounding: bool = True,
    enable_grounding_llm: bool = True,
    include_bundles: bool = False,
    answers_file: str = "",
    local_output_dir: str = "",
) -> None:
    """Entrypoint chạy trên máy local khi gõ `modal run scripts/modal_run_pipeline.py ...`."""
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
        f"(limit={limit or 'ALL'}, batch_size={batch_size}, business_id={biz_list or 'ALL'}, "
        f"grounding={enable_grounding}, grounding_llm={enable_grounding_llm})...",
        flush=True,
    )

    tar_bytes = run_pipeline_on_modal_gpu.remote(
        split=split,
        run_name=run_name,
        limit=limit,
        batch_size=batch_size,
        business_ids=biz_list,
        question_ids=q_list,
        model_id=model_id,
        grounding_model_id=grounding_model_id,
        enable_thinking=enable_thinking,
        enable_grounding=enable_grounding,
        enable_grounding_llm=enable_grounding_llm,
        include_bundles=include_bundles,
    )

    print(f"[Local] Đang nhận và giải nén kết quả vào {out_dir}...")
    with tarfile.open(fileobj=io.BytesIO(tar_bytes), mode="r:gz") as tar:
        try:
            tar.extractall(path=out_dir, filter="data")
        except TypeError:
            tar.extractall(path=out_dir)

    print(f"\n[Local] HOÀN TẤT! Kết quả đã được tải về đầy đủ tại: {out_dir}")
    print(f"  - File nộp bài        : {out_dir / 'submission.jsonl'}")
    print(f"  - Log suy nghĩ & SQL  : {out_dir / 'detailed_logs.jsonl'}")
    print(f"  - Log Grounding trace : {out_dir / 'grounding_trace.jsonl'}")
    if include_bundles:
        print(f"  - Dữ liệu Phần A & B  : {out_dir / 'bundles'}")

    # Tự động đánh giá điểm PA nếu có file Ground Truth
    effective_answers: Path | None = None
    if answers_file:
        effective_answers = Path(answers_file).resolve()
    else:
        candidate_gt = PROJECT_ROOT / "data" / "gt" / f"{split}_GT.jsonl"
        candidate_answers = split_dir / "answers.jsonl"
        if candidate_gt.is_file():
            effective_answers = candidate_gt
        elif candidate_answers.is_file():
            effective_answers = candidate_answers

    if effective_answers and effective_answers.is_file():
        from scripts.run_pipeline import evaluate_predictions

        print(f"\n[Local] Đang tính toán điểm PA với Ground Truth: {effective_answers}...")
        questions_path = split_dir / "questions.jsonl"
        all_q: list[dict[str, Any]] = []
        with questions_path.open("r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    all_q.append(json.loads(line))
        if biz_list:
            b_set = set(biz_list)
            all_q = [q for q in all_q if q.get("business_id") in b_set]
        if q_list:
            q_set = set(q_list)
            all_q = [q for q in all_q if str(q.get("id")) in q_set]
        if limit and limit > 0:
            all_q = all_q[:limit]

        eval_report = evaluate_predictions(
            submission_path=out_dir / "submission.jsonl",
            answers_path=effective_answers,
            questions=all_q,
        )
        eval_path = out_dir / "eval_report.json"
        eval_path.write_text(json.dumps(eval_report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(
            f"  => KẾT QUẢ ĐÁNH GIÁ (N={eval_report['total_evaluated']}):\n"
            f"     - Đúng (+1)   : {eval_report['correct']} ({eval_report['accuracy_percent']}%)\n"
            f"     - Sai (-1)    : {eval_report['wrong']}\n"
            f"     - Abstain (0) : {eval_report['abstained']}\n"
            f"     - ĐIỂM PA     : {eval_report['pa_score']} ({eval_report['pa_percent']}%) [PA Points = {eval_report['pa_points']}/{eval_report['total_evaluated']}]",
            flush=True,
        )
    elif (out_dir / "eval_report.json").is_file():
        eval_data = json.loads((out_dir / "eval_report.json").read_text(encoding="utf-8"))
        print(
            f"  - Điểm PA đánh giá    : {eval_data.get('pa_score')} "
            f"({eval_data.get('pa_percent')}%) [Đúng: {eval_data.get('correct')}, Sai: {eval_data.get('wrong')}, Abstain: {eval_data.get('abstained')}]"
        )
