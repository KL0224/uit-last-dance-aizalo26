# Giải Thích Mã Nguồn: `config.py` (B0.3)

**Đường dẫn file:** [`src/datamate/b0/b03/config.py`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b03/config.py)  
**Thuộc module:** B0.3 Text-to-SQL LLM Layer  
**Dự án:** DataMate — Zalo AI Challenge 2026 (Track 2)

---

## 1. Tổng Quan & Vai Trò

Tệp `config.py` chịu trách nhiệm đọc, phân tích cú pháp và xác thực các tệp cấu hình TOML (ví dụ: `configs/qwen3_5_9b.toml`) bằng thư viện chuẩn `tomllib` của Python 3.12. File này đảm bảo các tham số mô hình và tùy chọn sampling được cấu hình một cách có kỷ luật, tự động chuẩn hóa đường dẫn tương đối và từ chối các khóa lạ để tránh lỗi cấu hình ngầm.

---

## 2. Chi Tiết Hàm `load_config`

```python
def load_config(path: str | Path) -> tuple[ModelConfig, GenerationOptions]:
```

### Các bước xử lý trong hàm:
1. **Phân giải đường dẫn file TOML:**
   * Sử dụng `Path(path).expanduser().resolve()` để đảm bảo đường dẫn tuyệt đối chuẩn xác bất kể vị trí gọi lệnh.
2. **Đọc nội dung bằng `tomllib`:**
   * Đọc ở chế độ nhị phân (`"rb"`) theo đúng chuẩn của thư viện `tomllib`.
3. **Kiểm tra tính hợp lệ của các phân vùng (Sections):**
   * Chỉ cho phép 2 section: `[model]` và `[generation]`.
   * Nếu có bất kỳ section nào khác (`unknown = document.keys() - {"model", "generation"}`), hàm sẽ ném `ValueError` ngay lập tức.
4. **Chuẩn hóa đường dẫn snapshot (`model_path`):**
   * Nếu `model_path` trong TOML là đường dẫn tương đối (ví dụ: `../.models/Qwen3.5-9B`), nó sẽ được tính tương đối từ **thư mục chứa file TOML**, chứ không phải từ thư mục làm việc hiện tại (`current working directory`).
5. **Khởi tạo Data Transfer Objects (DTO):**
   * Trả về bộ đôi `(ModelConfig, GenerationOptions)` với các giá trị mặc định an toàn.

---

## 3. Tại Sao Lại Code Như Vậy?

1. **Chuẩn hóa đường dẫn tương đối theo vị trí file cấu hình:**
   * Trong thực tế, khi chạy script từ các thư mục khác nhau (root dự án, thư mục con `scripts/`, hoặc runner test), việc tính đường dẫn tương đối từ `cwd` sẽ rất dễ dẫn tới lỗi `FileNotFoundError: weights not found`. Việc tính tương đối từ `config_path.parent` triệt tiêu hoàn toàn rủi ro này.
2. **Sử dụng `tomllib` chuẩn Python 3.12:**
   * Không phụ thuộc vào các thư viện bên thứ ba như `pytoml`, `toml`, `tomli`, giảm thiểu phụ thuộc và tăng tốc độ nạp cấu hình.
3. **Từ chối cấu hình thừa (Fail-fast on unknown keys):**
   * Ngăn chặn tình trạng người dùng gõ sai chính tả một tham số quan trọng (ví dụ: gõ `max_tokens` thay vì `max_new_tokens`) mà hệ thống vẫn âm thầm bỏ qua và dùng giá trị mặc định sai lệch.

---

## 4. Tương Thích & Mối Liên Hệ

* File cấu hình mẫu tương thích: [`configs/qwen3_5_9b.toml`](file:///home/kiet97/uit-last-dance-aizalo26/configs/qwen3_5_9b.toml).
* Đầu ra của hàm được truyền trực tiếp vào hàm khởi tạo của [`VLLMModel`](file:///home/kiet97/uit-last-dance-aizalo26/docs/code/b0/b03/vllm_model.md) và kịch bản thực thi [`inference.py`](file:///home/kiet97/uit-last-dance-aizalo26/docs/code/b0/b03/inference.md).

---

## 5. Nếu Không Có File Này Thì Sao?

* Toàn bộ các thông số kỹ thuật (độ dài ngữ cảnh, GPU memory utilization, tensor parallelism, temperature, max tokens) sẽ phải hardcode cứng trong mã nguồn Python.
* Việc thay đổi mô hình thử nghiệm hoặc tinh chỉnh siêu tham số khi triển khai trên các server GPU khác nhau sẽ đòi hỏi phải chỉnh sửa trực tiếp vào mã nguồn, vi phạm nguyên tắc Twelve-Factor App.

