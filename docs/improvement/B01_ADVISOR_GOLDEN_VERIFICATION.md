# Kiểm chứng B01 Schema Advisor với golden train

Ngày 14/11/2026. Baseline: bundle release parser 1.1.2; bản nâng cấp: code Schema Advisor tại commit `a8e3701`. Lượt này chỉ kiểm B01/B02, không chạy Grounding, planner, pipeline trả lời hoặc sinh SQL bằng LLM. Không có GPU call mới, không tăng reservation Modal.

## Kết luận

**Chưa đo được cải thiện độ chính xác golden từ Schema Advisor.** Trên 61 SQL đã review, baseline và bản có Advisor đều đúng 61/61, chênh lệch 0 câu / 0 điểm phần trăm. Đây là kết quả trên tập con có reference SQL, không phải PA trên 3.000 câu.

Advisor là tính năng tùy chọn, chỉ xuất đề xuất chờ review; chưa thay đổi database, catalog hoặc rule dùng bởi downstream. Vì vậy hai nhánh cố ý chạy cùng published bundle, trước và sau replay validator với output Modal đã lưu. Đây là phép đo bảo toàn kết quả, **không phải A/B hai hệ thống trả lời khác nhau**. Không dùng câu trả lời golden làm prompt.

## Đã chạy lại những gì?

| Hạng mục | Kết quả |
|---|---:|
| Business audit integrity | 30/30 |
| File dữ liệu đọc được trong manifest | 128: 20 CSV, 107 XLSX, 1 SQLite |
| Integrity findings / khác biệt database so release | 0 / 0 |
| Bundle giữ nguyên artifact hashes trước/sau | 30/30 |
| Golden inventory: ID duy nhất, question/answer đầy đủ | 3.000/3.000 |
| Golden có SQL đã review được thực thi hai nhánh | 61, thuộc 14 business |
| Baseline đúng / bản có Advisor đúng | 61/61 / 61/61 |
| Câu thay đổi kết quả | 0 |
| Chưa có reference SQL trong evaluator B01/B02 | 2.939 (97,97%) |

Integrity audit chạy lại SQL kiểm row counts, profile, raw/main/lineage, candidate keys và JOIN tuple statistics theo công cụ audit hiện có; kiểm hashes và control totals. Không parse lại nguồn hoặc đo cold preparation. Baseline cho lượt audit này là chính release, không so với bản parser cũ để gán nhầm lợi ích cho LLM.

Đã đối chiếu lại **160 file dependency nguồn/tài liệu** với hash trong manifest, trước và sau chạy; giữ nguyên: **True**. Bao gồm README, rulebook, calendar, cấu hình nguồn đã được bundle ghi nhận.

## Pilot LLM được xác minh lại

Replay response thật từ Qwen2.5-3B-Instruct trên Modal cho hai bảng đơn/chi tiết của `biz_123`, kiểm lại binding database/context, hash README, quote/line và SQL JOIN statistics:

- 1 vai trò `ma_hoa_don → order_id` được giữ ở trạng thái cần review.
- 1 JOIN đơn–chi tiết: coverage hai phía 100%, cardinality một–nhiều; đã có trong catalog, nên số JOIN mới là **0**.
- 3 role bị loại do trích dẫn không khớp. Đây không phải bộ nhãn role để tính precision/recall; câu trích dẫn đúng cũng chưa đảm bảo diễn giải đúng.
- Số proposal áp dụng vào baseline: **0**. Không có cạnh được tự nâng `validated`.
- Không mở rộng LLM cho cả 30 business trong lượt này. Gọi thêm model khi chưa có nhãn đánh giá/review không thể chứng minh tăng golden accuracy.

B02 không được bổ sung binding hay rule mới trong lần nâng cấp Advisor này. Lượt audit chỉ kiểm lại binding hiện có và golden SQL liên quan, không suy rộng kết quả pilot unit-conversion cũ thành chất lượng B02 trên toàn train.

## Toàn bộ golden và khoảng trống

`number`: 1884, `percent`: 578, `string`: 88, `list`: 193, `unanswerable`: 70, `date`: 145, `table`: 19, `boolean`: 23.

Mỗi câu trong report JSON có trạng thái `evaluated_reviewed_sql` hoặc `not_evaluated_no_reviewed_sql`. Các câu chưa đánh giá không bị chấm sai hay coi là đúng. Nhóm unanswerable cũng chưa được evaluator quyết định: không suy từ thiếu nguồn SQL thành unanswerable nghiệp vụ.

| Business | Tổng golden | Có SQL kiểm | Baseline đúng | Có Advisor đúng | Chưa đánh giá |
|---|---:|---:|---:|---:|---:|
| biz_101 | 40 | 6 | 6 | 6 | 34 |
| biz_102 | 119 | 0 | 0 | 0 | 119 |
| biz_103 | 119 | 0 | 0 | 0 | 119 |
| biz_104 | 119 | 12 | 12 | 12 | 107 |
| biz_105 | 119 | 3 | 3 | 3 | 116 |
| biz_106 | 119 | 2 | 2 | 2 | 117 |
| biz_107 | 40 | 0 | 0 | 0 | 40 |
| biz_108 | 119 | 5 | 5 | 5 | 114 |
| biz_109 | 118 | 0 | 0 | 0 | 118 |
| biz_110 | 40 | 8 | 8 | 8 | 32 |
| biz_111 | 118 | 1 | 1 | 1 | 117 |
| biz_112 | 118 | 0 | 0 | 0 | 118 |
| biz_113 | 40 | 3 | 3 | 3 | 37 |
| biz_114 | 40 | 0 | 0 | 0 | 40 |
| biz_115 | 118 | 0 | 0 | 0 | 118 |
| biz_116 | 118 | 0 | 0 | 0 | 118 |
| biz_117 | 118 | 2 | 2 | 2 | 116 |
| biz_118 | 118 | 0 | 0 | 0 | 118 |
| biz_119 | 118 | 2 | 2 | 2 | 116 |
| biz_120 | 118 | 4 | 4 | 4 | 114 |
| biz_121 | 118 | 0 | 0 | 0 | 118 |
| biz_122 | 118 | 0 | 0 | 0 | 118 |
| biz_123 | 118 | 2 | 2 | 2 | 116 |
| biz_124 | 118 | 2 | 2 | 2 | 116 |
| biz_125 | 40 | 0 | 0 | 0 | 40 |
| biz_126 | 40 | 0 | 0 | 0 | 40 |
| biz_127 | 118 | 0 | 0 | 0 | 118 |
| biz_128 | 118 | 9 | 9 | 9 | 109 |
| biz_129 | 118 | 0 | 0 | 0 | 118 |
| biz_130 | 118 | 0 | 0 | 0 | 118 |

## Muốn đo cải thiện thực sự cần gì?

1. Tạo bộ nhãn B01 độc lập từ tài liệu/constraint: role đúng, JOIN đúng, composite key, cardinality và quan hệ âm. Chốt trước khi xem output model; tách tập phát triển và holdout.
2. Review proposal, áp dụng vào một bundle thử nghiệm riêng bằng luồng relationship/semantic binding hiện có. Giữ nguyên baseline và không tự approved theo overlap.
3. Bổ sung reference SQL có prechecks cho các business/nhóm nghiệp vụ còn thiếu. Ưu tiên các câu thực sự cần JOIN/role đang cải tiến, gồm công nợ, temporal, lô/hạn dùng và lợi nhuận; không suy công thức từ đáp án.
4. So sánh hai bundle trên cùng SQL/reference và đo precision/recall JOIN/role. Nếu chỉ thêm metadata mà không thay đổi dữ liệu hay SQL, golden numeric vẫn có thể không đổi dù metadata hữu ích hơn.
5. Đo PA cả 3.000 câu cần tích hợp sinh truy vấn/answerability/formatter hoặc có reference procedure đầy đủ; nằm ngoài phạm vi B01/B02 của lượt này. Hiện **chưa hoàn tất chấm full 3.000 câu**.

Không lấy mức tăng 58/61 → 61/61 của bản sửa parser trước đây làm kết quả của Schema Advisor mới.

## Tái lập

```bash
PYTHONPATH=src .venv/bin/python scripts/audit_b01_b02_full.py \
  --report artifacts/b01_b02_full/preparation_release.json \
  --baseline artifacts/b01_b02_full/preparation_release.json \
  --output artifacts/b01_advisor/full_verification/integrity \
  --cases examples/b01_b02/expanded_golden_checks.json

PYTHONPATH=src .venv/bin/python scripts/compare_b01_advisor_golden.py \
  --report artifacts/b01_b02_full/preparation_release.json \
  --response artifacts/b01_advisor/modal_constrained.json \
  --output artifacts/b01_advisor/full_verification/golden_comparison.json
```

Các artifact local không commit: `artifacts/b01_advisor/full_verification/integrity/audit.json` và `golden_comparison.json`. File comparison lưu SHA256 evaluation inputs, hashes artifact trước chạy, kết quả hai nhánh từng câu, coverage theo business và replay summary. Cần có release bundles cùng saved Modal response để tái lập; script không gọi GPU khi thiếu chúng.

Kiểm thử: **484 passed, 3 skipped, 15 subtests passed**. Hai tests mới kiểm việc giữ câu chưa có reference ở trạng thái chưa đánh giá, không tính thành accuracy; phát hiện question/answer trùng; precondition thất bại và NULL không được tính thành đáp án đúng.
