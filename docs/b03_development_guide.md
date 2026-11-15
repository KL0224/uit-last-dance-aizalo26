# HƯỚNG DẪN PHÁT TRIỂN TIẾP CHO LỚP B03 (TEXT-TO-SQL PLANNER) TRÊN NỀN TẢNG B01 & B02 ĐÃ HOÀN THIỆN

> **Dành cho**: Nhóm phát triển (Teammates) phụ trách B03 (Planner / Text-to-SQL / Prompt Engineering)  
> **Trạng thái nền tảng**: B01 (Schema & Joins) đạt 100% Recall, B02 (Unit Conversions) đạt 100% Recall.

---

## 1. NỀN TẢNG ĐÃ ĐƯỢC CHUẨN HÓA SẴN CHO B03

Khi pull code về, lớp B03 sẽ được hưởng lợi trực tiếp từ các dữ liệu chuẩn sau:

### 1.1. Quan hệ JOIN sạch 100% (Không còn nhiễu Cartesian)
- B01 đã triệt tiêu hơn 350 quan hệ rác `many_to_many` giữa các bảng Fact.
- Prompt của Planner trong `src/datamate/planner/prompt.py` sẽ chỉ nhận các quan hệ Foreign Key thực sự (Header $\to$ Detail, Fact $\to$ Dimension).
- Các bảng quy đổi (`quy_doi`) đã có sẵn **Composite Key** ghép chuẩn cả `ten_san_pham` và `don_vi_tinh`.

### 1.2. Bảng quy đổi đơn vị `main.unit_conversions` trong DuckDB
- Mọi database `data.duckdb` trong bundle đã được tạo sẵn bảng:
  ```sql
  CREATE TABLE main.unit_conversions (
      item_name VARCHAR,
      from_unit VARCHAR,
      to_unit VARCHAR,
      factor DECIMAL(38,12)
  );
  ```
- Prompt generator đã tự động thêm phần:
  ```markdown
  ### BẢNG QUY ĐỔI ĐƠN VỊ TÍNH (UNIT CONVERSIONS):
  Có sẵn bảng `unit_conversions` (item_name, from_unit, to_unit, factor). Áp dụng khi câu hỏi yêu cầu đơn vị khác với bảng bán hàng:
  - Bánh croissant: 1 hộp = 6 cái
  - Pepsi 330ml: 1 thùng = 24 lon
  ```

---

## 2. QUY TẮC VIẾT SQL CHO B03 KHI GẶP CÂU HỎI ĐƠN VỊ (UNIT CONVERSION)

Khi người dùng hỏi về số lượng theo đơn vị cơ bản (ví dụ hỏi "bán được bao nhiêu *lon*" trong khi bảng bán hàng ghi đơn vị là "*thùng*"):
```sql
SELECT 
    SUM(bh.so_luong * COALESCE(uc.factor, 1)) AS tong_so_luong
FROM ban_hang bh
LEFT JOIN unit_conversions uc 
    ON LOWER(TRIM(bh.ten_san_pham)) = LOWER(TRIM(uc.item_name))
    AND LOWER(TRIM(bh.don_vi_tinh)) = LOWER(TRIM(uc.from_unit))
WHERE bh.ten_san_pham = 'Pepsi 330ml';
```

---

## 3. CÁC LỆNH CHẠY & KIỂM THỬ DÀNH CHO TEAMMATE

### 3.1. Chạy unit tests cho riêng B03
```bash
# Kích hoạt môi trường ảo
source .venv/bin/activate

# Chạy test suite của B03 Text2SQL và Grounded Planner Bridge
pytest tests/test_b03_text2sql.py tests/test_grounded_planner_bridge.py
```

### 3.2. Chạy test toàn bộ hệ thống
```bash
pytest tests/
```
*(Kỳ vọng: 484 passed, 3 skipped)*

### 3.3. Chạy thử nghiệm Full Pipeline End-to-End
1. **Chạy thử local với số lượng câu hỏi nhỏ (Smoke test)**:
   ```bash
   python scripts/run_pipeline.py \
       --split train \
       --bundles-dir artifacts/b01_b02_full/enriched_bundles \
       --output-dir artifacts/runs/local_test \
       --limit 5
   ```
2. **Chạy thử trên Modal GPU (A100)**:
   ```bash
   modal run scripts/modal_run_pipeline.py \
       --split train \
       --limit 10 \
       --enable-thinking
   ```
