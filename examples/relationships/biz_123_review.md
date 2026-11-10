# Review quan hệ biz_123 — ví dụ có phạm vi rõ ràng

Người review: Codex, kiểm tra source schema và README ngày 07/11/2026.
Đây là review kỹ thuật của agent cho ví dụ tích hợp, không phải xác nhận của teammate.
Chỉ áp dụng cho `biz_123`, các bảng nguồn trong `pos.sqlite`.
Không có Foreign Key khai báo trong SQLite này. Các quan hệ dưới đây là khai báo
được review riêng; runtime không tự trích chúng từ tên cột hay nâng cạnh inferred.

Căn cứ: `data/train/data/biz_123/README.md` mô tả bảng POS, mã đơn nối đơn–dòng
(dòng 11), mỗi lần trả tiền thuộc một đơn (dòng 17), một dòng bán có thể lấy nhiều
lô (dòng 20). Kiểm tra schema nguồn cho thấy mã khách nằm trên đơn và bảng khách,
mã hàng nằm trên dòng bán và danh mục sản phẩm, SoThuTu định danh dòng trong đơn.
Mapping khách/sản phẩm là kết luận review schema nghiệp vụ POS, không phải câu FK
được trích nguyên văn từ README. SQL kiểm tra uniqueness/coverage riêng khi build.

- `don_hang.MaKhachHang -> khach_hang.MaKhachHang`: many_to_one; khách là tùy chọn, NULL không phải orphan.
- `chi_tiet_don.MaHoaDon -> don_hang.MaHoaDon`: many_to_one; dòng bán thuộc một đơn.
- `chi_tiet_don.MaHangHoa -> san_pham.MaHangHoa`: many_to_one; dòng bán tham chiếu danh mục sản phẩm.
- `thanh_toan.MaHoaDon -> don_hang.MaHoaDon`: many_to_one; một đơn có thể có nhiều lần thu tiền.
- `chi_tiet_don_lo.(MaHoaDon,SoThuTu) -> chi_tiet_don.(MaHoaDon,SoThuTu)`: many_to_one; phân bổ lô thuộc đúng dòng bán, không chỉ thuộc đơn.
- `chi_tiet_don_lo.MaLo -> lo_hang.MaLo`: many_to_one; phân bổ tham chiếu một lô, không yêu cầu mọi lô đã được bán.

Không review JOIN dòng bán–phân bổ chỉ bằng MaHoaDon: cách đó gộp nhầm các dòng
của cùng đơn. Không review JOIN trực tiếp dòng bán–lô bằng MaHangHoa để phân bổ
giá trị: một sản phẩm có nhiều lô. Những cạnh tương tự nếu được suy luận vẫn chỉ
là uncertain. Validated không có nghĩa SUM sau JOIN luôn an toàn: phải giữ grain,
chọn INNER/LEFT JOIN và xử lý hai nhánh con độc lập ở downstream.
