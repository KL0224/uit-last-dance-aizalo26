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

Nếu không có dataset, bỏ biến `DATAMATE_TRAIN_DIR` để chạy unit tests; các tests dữ liệu thật sẽ được skip. Tests ingestion tạo file thật trong thư mục tạm; benchmark 30 business chạy bằng `scripts/benchmark_preparation.py`. Chưa có pipeline Text-to-SQL end-to-end hoặc benchmark PA.

Tài liệu bàn giao ngắn cho teammate: [B01/B02 input/output](docs/B01_B02_HANDOFF.md).
