# Quy Chuẩn Lập Trình (Coding Conventions & Rules) - Team UIT Last Dance

Tài liệu này định nghĩa các nguyên tắc kiến trúc, quy chuẩn viết mã (coding style), cấu trúc thư mục và quy định an toàn bảo mật cho dự án **Zalo AI Challenge 2026 - Track 2 (DataMate)**, bám sát kiến trúc hệ thống từ **Baseline B0 (Direct Text-to-SQL)** và sẵn sàng mở rộng cho các phiên bản Agentic nâng cao sau này.

---

## 1. Nguyên Tắc Cốt Lõi (Core Principles)

1. **Ngôn ngữ chuẩn**: **Python 3.12+**.
2. **Kiến trúc hướng đối tượng (OOP & Clean Architecture)**:
   * Toàn bộ các thành phần tính toán cốt lõi đều được thiết kế dưới dạng **Class**.
   * Sử dụng **Abstract Base Class (`abc.ABC`)** để định nghĩa hợp đồng giao tiếp (Interface/Base Contract). Các module cụ thể kế thừa và hiện thực các phương thức trừu tượng (`@abstractmethod`).
   * **Single Responsibility Principle (SRP)**: Mỗi class chỉ đảm nhận một trách nhiệm duy nhất (Loader chỉ đọc dữ liệu, Executor chỉ thực thi truy vấn, Formatter chỉ định dạng kết quả).
   * **Dependency Injection**: Các pipeline không khởi tạo cứng (hardcode) các module phụ thuộc bên trong mà nhận thông qua hàm khởi tạo `__init__`.
3. **Kiểu dữ liệu tường minh (Strict Type Hints)**:
   * **100% hàm, phương thức (methods)** bắt buộc phải có Type Annotations cho toàn bộ tham số đầu vào và kiểu dữ liệu trả về (kể cả `-> None`).
   * Sử dụng thư viện `typing` (`Optional`, `Union`, `List`, `Dict`, `Any`, `Callable`, `Tuple`) hoặc cú pháp Python 3.10+ (`int | None`, `list[str]`).
4. **Data Transfer Objects (DTO) chuẩn hóa**:
   * Sử dụng **`pydantic.BaseModel`** hoặc `@dataclass` để truyền dữ liệu có cấu trúc giữa các tầng (Context, LLM Response, Execution Result, Submission Record). Tuyệt đối hạn chế truyền dictionary tự do không kiểm soát key.

---

## 2. Quy Tắc Đặt Tên (Naming Conventions)

Tuân thủ nghiêm ngặt chuẩn **PEP 8**:

| Thành phần | Quy tắc đặt tên | Ví dụ thực tế trong dự án | Ghi chú |
| :--- | :--- | :--- | :--- |
| **Class** | `PascalCase` | `BaseLoader`, `DuckDBExecutor`, `DirectSQLPipeline` | Danh từ, mô tả rõ đối tượng |
| **Exception Class** | `PascalCase` + đuôi `Error` | `SQLExecutionError`, `ValidationError` | Kế thừa từ `Exception` |
| **Function / Method** | `snake_case` | `execute_query()`, `extract_schema()`, `format_answer()` | Động từ hoặc cụm động từ, **bắt buộc type hints** |
| **Variable / Parameter** | `snake_case` | `query_context`, `table_name`, `error_msg` | Rõ nghĩa, tránh viết tắt khó hiểu |
| **Private Attribute / Method** | `_snake_case` | `_init_duckdb()`, `_parse_json()` | Có tiền tố gạch dưới `_` |
| **Constant (Hằng số)** | `UPPER_SNAKE_CASE` | `MAX_RETRY_COUNT`, `DEFAULT_TIMEOUT_SEC`, `NUM_ANSWER_TYPES` | Định nghĩa đầu file hoặc trong file config |
| **Enum / Enum Members** | `PascalCase` / `UPPER_SNAKE` | `AnswerType.NUMERIC`, `ExecutionStatus.SUCCESS` | Dùng `enum.Enum` |

### Ví dụ chuẩn về Class & Type Hints:

```python
from abc import ABC, abstractmethod
from typing import Optional
from pydantic import BaseModel

# 1. DTO Định nghĩa dữ liệu truyền qua lại
class ExecutionResult(BaseModel):
    is_success: bool
    data: list[dict] | None = None
    error_message: str | None = None
    executed_sql: str

# 2. Abstract Base Class
class BaseExecutor(ABC):
    """Lớp cơ sở cho các công cụ thực thi mã truy vấn."""

    def __init__(self, is_read_only: bool = True) -> None:
        self.is_read_only: bool = is_read_only

    @abstractmethod
    def execute(self, query: str, timeout_seconds: int = 30) -> ExecutionResult:
        """Thực thi câu truy vấn và trả về kết quả chuẩn hóa."""
        pass

# 3. Lớp kế thừa cụ thể (B0.4 DuckDB Executor)
class DuckDBExecutor(BaseExecutor):
    """Thực thi truy vấn SQL an toàn trên DuckDB (In-memory / Read-only)."""

    def __init__(self, db_path: str = ":memory:") -> None:
        super().__init__(is_read_only=True)
        self.db_path: str = db_path
        self._connection = self._init_connection()

    def _init_connection(self):
        # Thiết lập kết nối DuckDB
        pass

    def execute(self, query: str, timeout_seconds: int = 30) -> ExecutionResult:
        try:
            # Logic thực thi truy vấn
            return ExecutionResult(
                is_success=True,
                data=[],
                executed_sql=query
            )
        except Exception as exc:
            return ExecutionResult(
                is_success=False,
                error_message=str(exc),
                executed_sql=query
            )
```

---

## 3. Cấu Trúc Thư Mục Đề Xuất (Project Directory Structure)

Cấu trúc được thiết kế theo hướng **Module hóa cao (Modular Architecture)**, vừa tối ưu cho **Baseline B0** (bám sát sơ đồ HÌNH 10), vừa sẵn sàng mở rộng cho các baseline sau (B1 Multi-turn Agent, Text-to-Pandas, RAG, Ensemble) mà không cần đập đi xây lại:

```text
uit-last-dance-aizalo26/
├── configs/                            # Cấu hình hệ thống (YAML / JSON)
│   ├── b0_direct_sql.yaml              # Config tham số cho Baseline B0
│   └── prompts/                        # Quản lý Prompt templates tách biệt
│       ├── b0_text2sql.jinja2          # Prompt sinh SQL cho B0
│       └── b0_retry_correction.jinja2  # Prompt sửa lỗi khi retry
├── data/                               # Dữ liệu cuộc thi (ĐÃ ĐƯA VÀO .gitignore)
│   ├── raw/                            # Dữ liệu gốc: file excel, csv, rulebook, readme
│   ├── cache/                          # Dữ liệu cache parquet, duckdb snapshot
│   └── submissions/                    # File kết quả đầu ra jsonl / csv
├── docs/                               # Tài liệu hướng dẫn & quy chuẩn
│   ├── GIT_WORKFLOW.md                 # Quy chuẩn nhánh Git & CI/CD
│   └── CODING_CONVENTIONS.md          # Tài liệu quy chuẩn code (file này)
├── src/                                # Toàn bộ mã nguồn chính của dự án
│   ├── __init__.py
│   ├── utils/                          # Các hàm tiện ích dùng chung (Utilities)
│   │   ├── __init__.py
│   │   ├── config.py                   # Quản lý biến môi trường (.env) & config qua Pydantic
│   │   ├── logger.py                   # Cấu hình log chuẩn (Loguru / Logging)
│   │   ├── file_utils.py               # Tiện ích đọc/ghi file json, jsonl, parquet, cache
│   │   ├── text_utils.py               # Xử lý chuỗi, regex, chuẩn hóa tiếng Việt
│   │   ├── sql_utils.py                # Tiện ích bóc tách SQL từ markdown LLM, format query
│   │   ├── types.py                    # Định nghĩa Enums (9 Answer Types, Status, ...)
│   │   └── exceptions.py               # Custom Exceptions của dự án
│   │
│   ├── core/                           # Các Interface / Abstract Base Classes
│   │   ├── __init__.py
│   │   ├── base_loader.py              # BaseLoader (cho các bộ đọc dữ liệu)
│   │   ├── base_context.py             # BaseContextBuilder (cho trích xuất context/schema)
│   │   ├── base_llm.py                 # BaseLLMClient (cho các nhà cung cấp LLM)
│   │   ├── base_executor.py            # BaseExecutor (DuckDB, Pandas, SQLite)
│   │   ├── base_validator.py           # BaseValidator (kiểm tra tính hợp lệ của SQL/kết quả)
│   │   ├── base_formatter.py           # BaseFormatter (format kết quả theo 9 types)
│   │   └── base_pipeline.py            # BasePipeline (khung sườn điều phối)
│   │
│   ├── modules/                        # Hiện thực cụ thể các module chức năng
│   │   ├── loaders/                    # B0.1: Loader (Read / type inference / cache)
│   │   │   ├── __init__.py
│   │   │   └── tabular_loader.py       # Đọc CSV/Excel, suy luận kiểu, nạp vào DuckDB/Parquet
│   │   ├── context/                    # B0.2: Context Builder
│   │   │   ├── __init__.py
│   │   │   └── schema_context.py       # Trích xuất Schema, metadata cột, rulebook excerpts
│   │   ├── llm/                        # B0.3: LLM Providers
│   │   │   ├── __init__.py
│   │   │   ├── openai_client.py        # Tích hợp OpenAI API
│   │   │   ├── gemini_client.py        # Tích hợp Gemini API
│   │   │   └── vllm_client.py          # Tích hợp Local GPU LLM (vLLM / HuggingFace)
│   │   ├── executors/                  # B0.4: SQL / Code Executors
│   │   │   ├── __init__.py
│   │   │   └── duckdb_executor.py      # Thực thi SQL read-only trên DuckDB
│   │   ├── validators/                 # Validator & Decision Gating
│   │   │   ├── __init__.py
│   │   │   └── sql_validator.py        # Phân loại lỗi: recoverable vs unresolvable
│   │   └── formatters/                 # B0.5: Format / Gate (9 types + fallback)
│   │       ├── __init__.py
│   │       └── result_formatter.py     # Chuẩn hóa 9 dạng đầu ra hoặc Abstain nếu lỗi
│   │
│   └── pipelines/                      # Ghép nối các module thành luồng hoàn chỉnh
│       ├── __init__.py
│       ├── b0_direct_sql_pipeline.py   # Hiện thực luồng B0 (HÌNH 10)
│       └── (tương lai: b1_agentic_pipeline.py, b2_hybrid_pipeline.py)
│
├── tests/                              # Bộ unit test & sanity test cho CI
│   ├── __init__.py
│   ├── test_loaders.py
│   ├── test_duckdb_executor.py
│   └── test_formatters.py
├── scripts/                            # Script tiện ích chạy server GPU / môi trường
│   ├── setup_env.sh
│   └── run_b0_benchmark.sh
├── .env.example                        # Mẫu cấu hình môi trường (KHÔNG CHỨA KHÓA THẬT)
├── pyproject.toml                      # Quản lý dependencies với uv
└── README.md
```

---

## 4. Ánh Xạ Baseline B0 Vào Kiến Trúc Mã Nguồn

Theo sơ đồ **HÌNH 10 · BASELINE B0 (DIRECT TEXT-TO-SQL)**, các thành phần tương ứng với các class như sau:

| Thành phần trong sơ đồ B0 | Class đảm nhận | File vị trí | Chức năng cụ thể |
| :--- | :--- | :--- | :--- |
| **B0.1 · Loader** | `TabularLoader` | `src/modules/loaders/tabular_loader.py` | Đọc files + rulebook + README, suy luận kiểu dữ liệu, cache vào DuckDB/Parquet |
| **B0.2 · Context** | `SchemaContextBuilder` | `src/modules/context/schema_context.py` | Tạo chuỗi schema, mẫu dòng, trích đoạn luật nghiệp vụ từ rulebook |
| **B0.3 · One LLM** | `LLMClient` | `src/modules/llm/` | Nhận (Context + Question + as_of_date) -> Sinh ra SQL query + dự đoán 1 trong 9 answer types |
| **B0.4 · Execute** | `DuckDBExecutor` | `src/modules/executors/duckdb_executor.py` | Chạy câu lệnh SQL ở chế độ Read-only an toàn |
| **Decision: SQL / result valid?** | `SQLResultValidator` | `src/modules/validators/sql_validator.py` | Kiểm tra kết quả truy vấn. Nếu có lỗi, xác định có thể tự sửa (recoverable) hay không |
| **One bounded retry** | `B0DirectSQLPipeline` | `src/pipelines/b0_direct_sql_pipeline.py` | Gửi lỗi lại cho LLM sửa SQL (chỉ retry **tối đa 1 lần** theo sơ đồ) |
| **Abstain if unresolved** | `ResultFormatter` | `src/modules/formatters/result_formatter.py` | Nếu retry vẫn thất bại -> trả kết quả Abstain/Fallback an toàn |
| **B0.5 · Format / Gate** | `ResultFormatter` | `src/modules/formatters/result_formatter.py` | Ép kiểu kết quả vào đúng 1 trong 9 types chuẩn của đề bài |
| **Output** | `JSONLWriter` | `src/utils/file_utils.py` | Ghi kết quả ra tệp `.jsonl` và lưu vết vào `error.log` |

---

## 5. Quy Định Về Biến Môi Trường (.env) & Bảo Mật

1. **Tuyệt đối không commit file `.env` chứa bí mật**:
   * File `.env` chứa API keys (OpenAI, Gemini, Anthropic, Hugging Face Token, WandB Token...) là tài nguyên nhạy cảm.
   * **Bắt buộc** file `.gitignore` phải chặn: `.env`, `*.env`, `.env.*`.
2. **Luôn duy trì file `.env.example`**:
   * Khi thêm biến môi trường mới vào code, dev **bắt buộc** phải cập nhật tên biến và mô tả vào `.env.example` với giá trị rỗng để đồng đội biết cấu hình theo.
3. **Quản lý biến môi trường tập trung bằng Pydantic Settings**:
   * **Nghiêm cấm** việc gọi `os.getenv("API_KEY")` rải rác trong các hàm/class nghiệp vụ.
   * Tất cả phải thông qua class `Settings` tại `src/utils/config.py`:

```python
# src/utils/config.py
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # API Keys
    OPENAI_API_KEY: str = Field(default="", description="OpenAI API Key")
    GEMINI_API_KEY: str = Field(default="", description="Google Gemini API Key")
    
    # Model configs
    DEFAULT_LLM_MODEL: str = Field(default="gpt-4o-mini")
    MAX_RETRY_COUNT: int = Field(default=1, description="Giới hạn số lần retry cho Baseline B0")
    
    # Storage configs
    DUCKDB_PATH: str = Field(default=":memory:")
    DATA_DIR: str = Field(default="./data")
    LOG_LEVEL: str = Field(default="INFO")

settings = Settings()
```

---

## 6. Xử Lý Lỗi, Giới Hạn Retry & Logging

1. **Chính sách Bounded Retry (Tối đa 1 lần theo Baseline B0)**:
   * Sơ đồ B0 quy định rõ: **"One bounded retry"**. Không tạo vòng lặp vô hạn `while True`. Nếu lần retry thứ nhất vẫn lỗi -> Lập tức chuyển sang trạng thái **Abstain** (bỏ phiếu trắng/trả fallback an toàn).
2. **Quy định Logging thay thế `print()`**:
   * **Nghiêm cấm** sử dụng lệnh `print()` trong mã nguồn của `src/`.
   * Sử dụng module `logger`:
     * `logger.debug()`: Dùng khi cần soi câu SQL thô hoặc dump context schema trong lúc phát triển.
     * `logger.info()`: Thông báo tiến trình (Bắt đầu đọc file, Hoàn tất pipeline question_id=X).
     * `logger.warning()`: Cảnh báo khi SQL lỗi lần đầu và kích hoạt bounded retry.
     * `logger.error()`: Báo lỗi khi truy vấn thất bại hoàn toàn, ghi nguyên nhân ra `error.log`.
3. **Safe Execution trên DuckDB**:
   * DuckDB executor bắt buộc phải chạy ở chế độ **Read-only** để tránh các rủi ro câu SQL do LLM sinh ra vô tình chỉnh sửa, xóa bảng (`DROP TABLE`, `DELETE`, `UPDATE`) hoặc làm tràn bộ nhớ server.

---

## 7. Quy Chuẩn Kiểm Thử & CI Sanity Check Trước Khi Merge

Trước khi tạo Pull Request vào nhánh `dev`, lập trình viên phải đảm bảo:
1. Chạy linter kiểm tra cú pháp và định dạng:
   ```bash
   uv run ruff check .
   uv run ruff format --check .
   ```
2. Chạy unit tests cục bộ:
   ```bash
   uv run pytest tests/
   ```
3. Đảm bảo toàn bộ phương thức mới viết có đầy đủ **Type Hints** và docstring ngắn gọn mô tả đầu vào/đầu ra.

