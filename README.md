# Zalo AI Challenge 2026 - Track 2
### Team: UIT Last Dance

[![Python Version](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Package Manager](https://img.shields.io/badge/Package_Manager-uv-DE5FE9?logo=astral&logoColor=white)](https://docs.astral.sh/uv/)
[![Organization](https://img.shields.io/badge/University-UIT-005BAA?logo=vnu-uit&logoColor=white)](https://www.uit.edu.vn/)
[![Version](https://img.shields.io/badge/Doc_Version-v1.0-brightgreen)](#ghi-chú-phiên-bản)

---

## 1. Giới Thiệu Cuộc Thi & Đề Bài Track 2

* **Cuộc thi:** **Zalo AI Challenge 2026**
* **Chủ đề mùa giải:** *"Advancing AI Agents for Real Life"*
* **Đề bài Track 2:** **DataMate – Talking To Your Data Through Agentic AI**
* **Trọng tâm (Core Focus):** Data Agents / Tương tác & Lập luận trên Dữ liệu Bảng (Tabular Data Interaction & Reasoning)

### 📌 Tóm Tắt Nội Dung Bài Toán Track 2 (DataMate)

Trong thực tế, các chủ hộ kinh doanh, tiểu thương, giáo viên hay nhân viên văn phòng thường xuyên phải quản lý và đưa ra quyết định dựa trên các tệp dữ liệu bảng (Excel, CSV) rất phức tạp và "hỗn tạp" (messy data: nhiều trang tính, tên cột không đồng nhất, định dạng ngày tháng đa dạng, viết tắt theo thói quen). Khi cần trích xuất thông tin hoặc thống kê số liệu, việc viết hàm Excel hay truy vấn thủ công tốn rất nhiều thời gian và dễ nhầm lẫn.

**Mục tiêu chính:** 
Xây dựng một **AI Data Agent** thông minh có khả năng **lắng nghe và thấu hiểu câu hỏi bằng tiếng Việt tự nhiên** (kể cả cách diễn đạt thông tục, từ ngữ đời thường của người dùng Việt), sau đó tự động truy xuất, tính toán và suy luận trực tiếp trên các bảng dữ liệu để phản hồi câu trả lời chính xác, đáng tin cậy.

### 🎯 Các Thách Thức Kỹ Thuật Trọng Tâm:
1. **Xử lý dữ liệu bảng thực tế (Messy Tabular Data):** Xử lý các bảng tính có cấu trúc phức tạp (multi-sheet, cột lồng nhau, dữ liệu rải rác hoặc khuyết thiếu).
2. **Hiểu ngôn ngữ tự nhiên tiếng Việt (Vietnamese NLP & Ambiguity):** Phân tích và làm rõ các câu hỏi truy vấn mang tính khẩu ngữ, từ viết tắt ngành nghề kinh doanh, tên sản phẩm không đồng nhất.
3. **Lập luận đa bước (Multi-step Reasoning & Planning):** Khả năng phân rã câu hỏi phức tạp thành chuỗi các thao tác: Lọc (Filter) → Nhóm (Group by) → Kết nối dữ liệu nhiều bảng (Table Join) → Tính toán tổng hợp.
4. **Agentic Code Execution (Text-to-SQL / Text-to-Pandas):** Agent tự động sinh mã code truy vấn, thực thi trong sandbox và có cơ chế tự sửa sai (Self-reflection / Self-debugging) nếu code gặp lỗi.
5. **Độ chính xác & Chống ảo giác (Faithfulness & Hallucination Prevention):** Đảm bảo câu trả lời số liệu phản ánh đúng 100% thực tế của bảng dữ liệu, không tự bịa đặt thông tin.

---

## 2. Thông Tin Đội Thi

* **Tên đội:** **UIT Last Dance**
* **Đơn vị:** **Trường Đại học Công nghệ Thông tin – Đại học Quốc gia TP.HCM (UIT - VNUHCM)**
* **Danh sách thành viên (04 thành viên):**

| STT | Họ và Tên | Vai trò | Trường |
| :---: | :--- | :--- | :---: |
| 1 | **Phạm Anh Kiệt** |  Trưởng nhóm | UIT |
| 2 | **Lê Thiên Bảo** | Thành viên | UIT |
| 3 | **Nguyễn Hoài Minh** | Thành viên | UIT |
| 4 | **Nguyễn Trọng Khôi** | Thành viên | UIT |

---

## 3. Cấu Trúc Dự Án hiện tại (Cấu trúc hoàn chỉnh sẽ được cập nhật sau)

```text
uit-last-dance-aizalo26/
├── .github/              # Cấu hình GitHub Actions CI & tự động hóa
├── data/                 # Thư mục chứa dữ liệu bài thi (không commit file nặng)
├── docs/                 # Tài liệu quy trình & kiến trúc
│   └── GIT_WORKFLOW.md   # Quy chuẩn Git Workflow & chiến lược CI/CD
├── tasks/                # Kế hoạch và danh sách công việc của team
├── pyproject.toml        # Cấu hình dự án & danh sách dependencies
├── .python-version       # Khai báo phiên bản Python chuẩn (3.12)
├── main.py               # Entrypoint khởi tạo ban đầu
└── README.md             # Tài liệu tổng quan dự án
```
 
 Cấu trúc hoàn chỉnh sẽ được cập nhật sau.
---

## 4. Môi Trường & Hướng Dẫn Cài Đặt (Setup & Environment)

Dự án sử dụng ngôn ngữ **Python 3.12** và trình quản lý gói thế hệ mới **[uv](https://docs.astral.sh/uv/)** của Astral nhằm tối ưu tốc độ phân giải thư viện, đồng bộ môi trường nhất quán và loại bỏ xung đột package giữa các thành viên.

### 4.1. Cài đặt `uv`

Nếu máy cá nhân hoặc server GPU chưa có `uv`, cài đặt nhanh bằng lệnh sau:

* **Trên Linux / macOS / WSL:**
  ```bash
  curl -LsSf https://astral.sh/uv/install.sh | sh
  ```
* **Trên Windows (PowerShell):**
  ```powershell
  powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
  ```

---

### 4.2. Khởi tạo môi trường ảo & Cài đặt thư viện

1. **Clone mã nguồn về máy:**
   ```bash
   git clone -b dev https://github.com/<your-org-or-user>/uit-last-dance-aizalo26.git
   cd uit-last-dance-aizalo26
   ```

2. **Tạo môi trường ảo với Python 3.12:**
   ```bash
   uv venv --python 3.12
   ```

3. **Kích hoạt môi trường ảo:**
   * **Linux / macOS / WSL:**
     ```bash
     source .venv/bin/activate
     ```
   * **Windows:**
     ```powershell
     .venv\Scripts\activate
     ```

4. **Đồng bộ hóa các package của dự án:**
   ```bash
   uv sync
   ```

---

### 4.3. Các thao tác thông dụng với `uv`

* **Chạy một script Python trong môi trường `uv` mà không cần kích hoạt thủ công:**
  ```bash
  uv run main.py
  ```
* **Thêm thư viện mới vào dự án (tự động cập nhật `pyproject.toml`):**
  ```bash
  uv add torch torchvision --index-url https://download.pytorch.org/whl/cu128
  uv add pandas scikit-learn albumentations tqdm
  ```
* **Thêm thư viện chỉ dùng cho quá trình kiểm thử / dev:**
  ```bash
  uv add --dev pytest ruff
  ```

---

## 5. Quy Chuẩn Đóng Góp & Làm Việc Nhóm

Toàn bộ quy trình cộng tác, kiến trúc mã nguồn và kiểm thử đều được quy định chặt chẽ tại:
* 👉 **[Quy trình Quản lý Nhánh (Git Workflow) & CI/CD](docs/GIT_WORKFLOW.md)**: Chiến lược phân nhánh, CI/CD trên GitHub Actions và hướng dẫn kéo code lên server GPU thuê.
* 👉 **[Quy Chuẩn Lập Trình (Coding Conventions & Rules)](docs/CODING_CONVENTIONS.md)**: Chuẩn OOP, kế thừa Abstract Base Class, quy tắc đặt tên, type hints, cấu trúc thư mục mở rộng và ánh xạ theo Baseline B0 (Text-to-SQL).

---

## 6. Ghi Chú Phiên Bản (Version Note)

* **Phiên bản hiện tại:** `README v1.0` (Khởi tạo tài liệu cơ bản, thiết lập thông tin đội thi và cấu hình môi trường chuẩn).
* Tài liệu sẽ liên tục được cập nhật theo từng giai đoạn của cuộc thi (EDA, xây dựng baseline, thiết kế mô hình ensemble, tối ưu hóa điểm số và nộp bài).

## 7. B01/B02 — Semantic Knowledge

Các module tại `src/datamate/`: B01 đọc CSV/XLSX/SQLite, chuẩn hóa, tạo DuckDB và Schema Catalog/Join Graph; B02 đọc luật nghiệp vụ; service xuất Business Context JSON contract 1.1. Adapter metadata 1.0 vẫn tương thích. Xem [Data Contract và hướng dẫn tích hợp](docs/DATA_CONTRACT.md) để biết interface, điều kiện validation và các giới hạn hiện tại.

Bản tổng kết tiếng Việt: [B01/B02 — Những gì đã làm, input và output](docs/B01_B02_IMPLEMENTATION.md).

Chuẩn bị trực tiếp từ dataset (cài dependency bằng `uv sync --frozen`):

```bash
PYTHONPATH=src uv run --frozen python -m datamate prepare \
  --business-dir data/train/data/biz_123 \
  --rulebook data/train/rulebook.md --calendar data/train/calendar.csv \
  --output-dir data/cache
```

Output: bundle gồm `data.duckdb`, manifest, foundation metadata, Business Context và normalization report. Xem [input/output và Docker offline](docs/B01_B02_IMPLEMENTATION.md).

Chạy ví dụ metadata 1.0 độc lập với dữ liệu cuộc thi:

```bash
PYTHONPATH=src uv run --frozen python -m datamate \
  --metadata examples/foundation_metadata.json \
  --business-id example_shop \
  --document examples/README.md
```

Chạy tests, bao gồm kiểm tra metadata trên CSV/SQLite train khi dữ liệu có sẵn:

```bash
DATAMATE_TRAIN_DIR=data/train PYTHONPATH=src uv run --frozen python -m unittest discover -s tests -v
```

Nếu không có dataset, bỏ biến `DATAMATE_TRAIN_DIR` để chạy unit tests; các tests dữ liệu thật sẽ được skip. Các reader trong tests chỉ tạo metadata fixture, không thay thế ingestion production của team. Chưa có pipeline Text-to-SQL end-to-end hoặc benchmark PA.

# ZAIC 2026 — Local LLM layer
Interface Python dùng chung cho model local, backend đầu tiên là offline vLLM.
Checkpoint mẫu: `Qwen/Qwen3.5-9B`. Model chỉ được load vào GPU khi gọi `load()`.
Backend offline mặc định dùng `language_model_only = true` để bỏ vision encoder
và multimodal profiling. Có thể đặt `language_model_only = false` trong phần
`[model]` của file TOML để tắt chế độ này.

- Cấu hình: [configs/qwen3_5_9b.toml](configs/qwen3_5_9b.toml)
- Tải weights: [scripts/download_model.py](scripts/download_model.py)
- Ví dụ generate/chat/batch: [examples/basic_usage.py](examples/basic_usage.py)
- Hướng dẫn và báo cáo kỹ thuật: [docs/model_layer_report.md](docs/model_layer_report.md)

Chưa chạy cài đặt, tải weights, inference hoặc test. Xem báo cáo trước khi
chủ động chạy các lệnh trên server GPU.


## Setup Virtual Env
chmod +x setup_env.sh
./setup_env.sh
source .venv/bin/activate

## Test Inference
vllm serve Qwen/Qwen3.5-9B \
  --dtype bfloat16 \
  --max-model-len 8192 \
  --max-num-seqs 4 \
  --gpu-memory-utilization 0.90 \
  --language-model-only \
  --reasoning-parser qwen3


## On 5090 Server
uv python install 3.12
uv venv --python 3.12 .venv

source .venv/bin/activate

uv pip install -r requirements-lock.txt \
  --torch-backend=auto

---

## 8. Quy Cách Đóng Gói Docker & Khai Báo Theo Quy Định BTC

> Tuân thủ 100% tài liệu **Docker Submission Guide - Zalo AI Challenge 2026 (DataMate)**.

### 8.1. Phương Pháp Tiếp Cận (Approach)
Giải pháp **DataMate** của đội **UIT Last Dance** là một luồng Agentic AI tích hợp đa tầng, hoạt động hoàn toàn offline:
1. **Data Ingestion & Normalization (`src/datamate/ingestion/`)**: Đọc các tệp bảng biểu đa định dạng (CSV, XLSX, SQLite) của từng doanh nghiệp trong `/data/data/<business_id>`, chuẩn hóa kiểu dữ liệu, giải quyết xung đột mã hóa và tự động phát hiện liên kết khóa nối (Join Graph).
2. **Business Context & Rule Compiler (`src/datamate/context/`)**: Phân tích luật kinh doanh từ `README.md` của từng shop và `rulebook.md`, trích xuất các điều kiện nghiệp vụ cốt lõi (doanh thu thực, điều kiện loại trừ đơn hủy, hoàn trả, quà tặng 0đ).
3. **Question Grounding (`src/datamate/grounding/`)**: Phân tích câu hỏi tiếng Việt, nhận diện ý định (Intent C1), thời gian (Temporal C2), liên kết cột/bảng (Schema C3), nhận diện giá trị (Value C4) và phân loại tính khả thi (Answerability C5).
4. **Agent Planner Text-to-SQL (`src/datamate/planner/`)**: Sử dụng LLM cục bộ (vLLM offline) sinh truy vấn DuckDB SQL có cấu trúc, tích hợp ngữ cảnh grounding và cơ chế sinh suy nghĩ (`thinking`).
5. **Safe Sandbox Execution (`src/datamate/execution/`)**: Thực thi truy vấn trong môi trường DuckDB tối ưu bộ nhớ, tự động gỡ lỗi cú pháp qua AST parser, bổ sung schema hints khi retry và bẫy lỗi tràn bộ nhớ/spill disk vào `/tmp/duckdb_spill`.
6. **Risk-Policy Gate (`src/datamate/gate/`)**: Thẩm định kết quả theo chính sách rủi ro chặt chẽ. Áp dụng chiến lược **Aggressive Abstain** (không chắc chắn thì bỏ qua để nhận 0 điểm, tránh bị trừ -1 điểm theo luật BTC). Ghi kết quả lập tức vào `/result/submission.jsonl` và log chi tiết vào `/result/logs/`.

### 8.2. Khai Báo Mô Hình (Model Declarations)
* **Mô hình chính (Primary Planner LLM):**
  - **Tên:** `Qwen/Qwen3.5-9B`
  - **Nguồn công khai:** [https://huggingface.co/Qwen/Qwen3.5-9B](https://huggingface.co/Qwen/Qwen3.5-9B)
  - **Revision:** `main` (cố định)
  - **Ngày phát hành gốc:** Tháng 10/2024 (trước mốc quy định 26/10/2026)
  - **Giấy phép:** Apache 2.0 (cho phép sử dụng thương mại và nghiên cứu)
  - **Số lượng tham số:** 9.0B tham số (thỏa mãn tổng số tham số suy luận $\le$ 15B)
* **Mô hình phụ trợ Grounding Fallback (Tùy chọn):**
  - **Tên:** `Qwen/Qwen2.5-3B-Instruct`
  - **Nguồn công khai:** [https://huggingface.co/Qwen/Qwen2.5-3B-Instruct](https://huggingface.co/Qwen/Qwen2.5-3B-Instruct)
  - **Ngày phát hành gốc:** 19/09/2024 (trước 26/10/2026)
  - **Giấy phép:** Apache 2.0
  - **Số lượng tham số:** 3.0B tham số
* **Tổng tham số toàn bộ hệ thống suy luận:** 9.0B + 3.0B = 12.0B $\le$ 15B (Hợp lệ Rule 2).

### 8.3. Dữ Liệu & Huấn Luyện (Data & Training Declaration)
* **Dữ liệu sử dụng:** Bộ dữ liệu `train` chính thức do BTC Zalo AI Challenge 2026 cung cấp. Không sử dụng dữ liệu public test hay private test để huấn luyện (Tuân thủ Rule 6).
* **Khai báo huấn luyện (Training Declaration):** Giải pháp vận hành theo kiến trúc zero-shot / few-shot text-to-SQL và suy luận agentic cục bộ dựa trên trọng số gốc nguồn mở đã công bố. Không thực hiện fine-tuning can thiệp trực tiếp lên bộ trọng số gốc trên dữ liệu bài thi.
* **Mã nguồn huấn luyện:** Toàn bộ cấu trúc thư mục `/code/training_code/`, cấu hình, kịch bản kiểm chứng và tệp kê khai `data_manifest.json` được đóng gói đầy đủ trong Docker image theo Mục 4 & Mục 8 của hướng dẫn BTC.

### 8.4. Hướng Dẫn Chạy & Kiểm Thử Docker Image
* **Tên Image chuẩn hóa:** `zaic2026_datamate_uit_last_dance:final`
* **Lệnh chạy chấm điểm của BTC (Scoring Command):**
  ```bash
  docker run --rm --gpus '"device=0,1"' --network none --shm-size=16g \
    --entrypoint bash \
    -v /path/to/public_test:/data:ro \
    -v /path/to/output:/result \
    zaic2026_datamate_uit_last_dance:final /code/predict.sh
  ```
* **Lệnh đóng gói & xuất bản nộp bài:**
  ```bash
  set -o pipefail
  docker save zaic2026_datamate_uit_last_dance:final | gzip > zaic2026_datamate_uit_last_dance.tar.gz
  gzip -dc zaic2026_datamate_uit_last_dance.tar.gz | wc -c
  md5sum zaic2026_datamate_uit_last_dance.tar.gz > zaic2026_datamate_uit_last_dance.tar.gz.md5
  ```
