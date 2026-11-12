# Giải Thích Mã Nguồn: `__init__.py`

**Đường dẫn file:** [`src/datamate/grounding/__init__.py`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/grounding/__init__.py)  
**Thuộc module:** Component C — Question Grounding (Public API Facade)  
**Dự án:** DataMate — Zalo AI Challenge 2026 (Track 2: Vietnamese Tabular QA)

---

## 1. Tổng Quan & Vai Trò

File `__init__.py` là **Cửa sổ giao tiếp công khai (Public API Facade)** của toàn bộ package `datamate.grounding`.

Trong thiết kế kiến trúc phần mềm hướng mô-đun (Modular Software Architecture), cấu trúc thư mục và việc phân chia file bên trong một package (`parser.py`, `temporal.py`, `rules_matcher.py`, ...) là chi tiết triển khai nội bộ (Internal Implementation Details). Các module bên ngoài (như pipeline điều phối toàn hệ thống, tầng kiểm thử, hoặc các module khác B0.1–B0.5) không nên import trực tiếp từ từng file con nằm sâu bên trong.

File `__init__.py` đóng vai trò là "mặt tiền" duy nhất:
1. Thu gom và tái xuất khẩu (Re-export) tất cả các lớp, kiểu dữ liệu, giao diện và hàm thiết yếu.
2. Thiết lập danh sách `__all__` rõ ràng, ngăn ngừa việc rò rỉ các biến nội bộ hoặc các thư viện bên thứ ba ra ngoài không gian tên công khai.

---

## 2. Chi Tiết Danh Sách Xuất Khẩu (`__all__`)

Danh sách `__all__` được phân nhóm theo 6 phân tầng logic:

### 2.1. Nhóm Hợp Đồng Dữ Liệu & Enum Cốt Lõi (Contracts & Enums)
* `OperationKind`: Enum 13 phép toán giải tích (`SUM`, `COUNT`, `TOP_K`, ...).
* `AnswerTypeHint`: Enum 9 kiểu dữ liệu đầu ra của cuộc thi.
* `CoverageStatus`: Enum trạng thái độ phủ dữ liệu (`SUPPORTED`, `UNSUPPORTED`, `UNKNOWN`).
* `DateRole`: Enum vai trò ngữ nghĩa của cột ngày (`ORDER_DATE`, `PAYMENT_DATE`, ...).
* `QuestionRequest`: Dataclass câu hỏi đầu vào chuẩn hóa.
* `FilterCondition`: Dataclass điều kiện lọc câu hỏi.
* `QuestionIntent`: Dataclass ý định phân tích từ C1.
* `ResolvedTimeRange`: Dataclass khoảng thời gian đã phân giải từ C2.
* `SchemaCandidate`, `CandidateJoinPath`, `SelectedSchema`: Các dataclass lược đồ từ C3.
* `MatchedValue`: Dataclass liên kết thực thể từ C4.
* `EvidenceRequirement`, `MissingEvidenceProof`: Các dataclass bằng chứng từ C5.
* `GroundedQuestion`: Dataclass đầu ra bàn giao tối cao của Component C.

### 2.2. Nhóm Giao Diện & Đặc Tả Siêu Dữ Liệu (Protocols & Specs)
* `ColumnSpec`, `TableSpec`, `JoinSpec`, `MetricSpec`, `CalendarEventSpec`: Các descriptor gọn nhẹ.
* `BusinessContextProtocol`: Giao diện trừu tượng cho ngữ cảnh doanh nghiệp.
* `LLMParserProtocol`: Giao diện trừu tượng cho mô hình 3B LLM.

### 2.3. Nhóm Nhà Máy Dữ Liệu Giả Lập (Mock Provider)
* `InMemoryBusinessContext`: Lớp ngữ cảnh trong bộ nhớ RAM.
* `MockBusinessContextProvider`: Nhà máy sinh dữ liệu giả lập chuẩn (F&B và bán lẻ ẩn danh).

### 2.4. Nhóm Module Trích Xuất Ngữ Nghĩa (C1 Intent Parser)
* `VietnameseQuestionNormalizer`: Chuẩn hóa câu hỏi và mở rộng allowlist viết tắt trước khi vào C1–C5.
* `VietnameseRuleMatcher`: Bộ bóc tách nhanh bằng Regex xác định.
* `EXTRACTOR_SYSTEM_PROMPT`: Prompt hệ thống chuẩn cho mô hình 3B.
* `StructuredLLMParser`: Bộ điều phối mô hình 3B LLM Fallback.
* `QuestionIntentParser`: Bộ phân tích ý định tổng hợp (Hybrid C1 Coordinator).

### 2.5. Nhóm Phân Giải Thời Gian & Lược Đồ (C2, C3, C4, C5)
* `QuestionTemporalResolver`: Bộ phân giải mốc thời gian và sự kiện Tết (C2).
* `SchemaGrounder`: Bộ chọn lọc Fact Table và đường nối BFS trên Join Graph (C3).
* `ValueGrounder`: Bộ đối chiếu từ vựng thực tế và khử dấu tiếng Việt (C4).
* `AnswerabilityPrechecker`: Bộ thẩm định năng lực và bắt `unanswerable` sớm (C5).

### 2.6. Nhóm Điều Phối Tuyến & Cầu Nối Tích Hợp (Engine & Adapters)
* `QuestionGroundingEngine`: Nhạc trưởng điều phối toàn bộ quy trình C1 $\rightarrow$ C5.
* `B02ContextAdapter`: Adapter tiếp nhận ngữ cảnh thực tế từ B0.2.
* `GroundingToPlannerAdapter`: Adapter xuất prompt hint cho B0.3 và `EvidenceProof` cho B0.5.

---

## 3. Tại Sao Lại Thiết Kế & Code Như Vậy?

1. **Chuẩn hóa điểm vào (Clean Single Import Point)**:
   * Người sử dụng package chỉ cần viết một câu lệnh import duy nhất:
     ```python
     from datamate.grounding import (
         B02ContextAdapter,
         GroundingToPlannerAdapter,
         QuestionGroundingEngine,
         QuestionRequest,
     )
     ```
   * Cực kỳ gọn gàng, tăng tính trực quan và giảm thiểu lỗi sai đường dẫn file.
2. **Nguyên tắc đóng gói thông tin (Information Hiding)**:
   * Giúp che giấu các hàm hỗ trợ nội bộ như `_extract_json_dict()`, `_find_shortest_join_path()`, `_strip_accents()`. Những hàm này chỉ phục vụ nội bộ và không được phép gọi tự do từ bên ngoài, ngăn ngừa các lỗi phụ thuộc ngầm (tight coupling).

---

## 4. Ý Nghĩa & Ảnh Hưởng Đến Các Module Khác

* **Điểm tiếp xúc duy nhất cho `pipeline.py`**: Pipeline điều phối chính của dự án chỉ giao tiếp với package `grounding` qua các lớp được xuất khẩu trong file này.
* **Hỗ trợ IDE Auto-completion**: Việc khai báo tường minh trong `__all__` giúp các trình biên dịch và IDE (VS Code, Cursor, Antigravity) tự động gợi ý đúng các lớp công khai, tránh việc import nhầm các biến tạm.

---

## 5. Nếu Không Có File Này Thì Sao?

* Nếu không có `__init__.py` với danh sách `__all__` chuẩn, người phát triển các module khác sẽ phải viết những câu lệnh import dài dòng và phân tán:
  ```python
  from datamate.grounding.engine import QuestionGroundingEngine
  from datamate.grounding.contracts import QuestionRequest, GroundedQuestion
  from datamate.grounding.adapters import B02ContextAdapter, GroundingToPlannerAdapter
  ```
* Sau này, nếu bạn muốn đổi tên file `engine.py` thành `coordinator.py` hoặc gộp `rules_matcher.py` vào `parser.py`, toàn bộ code ở các module khác sẽ bị vỡ vụn do import sai đường dẫn. Nhờ có `__init__.py`, việc tái cấu trúc bên trong package diễn ra hoàn toàn êm đẹp mà không ảnh hưởng đến bất kỳ ai.
