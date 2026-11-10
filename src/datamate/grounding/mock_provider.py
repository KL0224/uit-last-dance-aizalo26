"""Mock BusinessContext provider for independent development and testing of Component C."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Sequence

from .protocols import (
    BusinessContextProtocol,
    CalendarEventSpec,
    ColumnSpec,
    JoinSpec,
    MetricSpec,
    TableSpec,
)


@dataclass
class InMemoryBusinessContext(BusinessContextProtocol):
    """Concrete in-memory implementation of BusinessContextProtocol."""

    business_id: str
    tables: tuple[TableSpec, ...] = ()
    join_edges: tuple[JoinSpec, ...] = ()
    metrics: tuple[MetricSpec, ...] = ()
    capabilities: dict[str, str] = field(default_factory=dict)
    calendar_events: tuple[CalendarEventSpec, ...] = ()
    rules: tuple[str, ...] = ()
    value_aliases: dict[str, tuple[str, str, Any]] = field(default_factory=dict)

    def get_tables(self) -> Sequence[TableSpec]:
        return self.tables

    def get_join_edges(self) -> Sequence[JoinSpec]:
        return self.join_edges

    def get_metrics(self) -> Sequence[MetricSpec]:
        return self.metrics

    def get_capability_status(self, capability_key: str) -> str:
        return self.capabilities.get(capability_key, "unknown")

    def get_calendar_events(self) -> Sequence[CalendarEventSpec]:
        return self.calendar_events

    def get_active_rules(self, topic: str | None = None) -> Sequence[str]:
        return self.rules

    def get_value_aliases(self) -> dict[str, tuple[str, str, Any]]:
        return self.value_aliases


class MockBusinessContextProvider:
    """Factory producing realistic mock BusinessContext objects for testing Component C."""

    @staticmethod
    def create_fnb_context(business_id: str = "mock_fnb_003") -> InMemoryBusinessContext:
        """Create an F&B business context (orders, order_items, shift_payments, customers)."""
        tables = (
            TableSpec(
                name="orders",
                grain="order",
                description="Bảng hóa đơn bán hàng theo từng đơn",
                aliases=("hóa đơn", "đơn hàng", "bill"),
                row_count=1250,
                date_coverage_start="2025-01-01",
                date_coverage_end="2026-12-31",
                columns=(
                    ColumnSpec("order_id", "VARCHAR", "Mã đơn hàng", ("mã đơn", "mã bill"), role="id"),
                    ColumnSpec("order_date", "DATE", "Ngày đặt đơn", ("ngày tạo", "ngày bán"), role="date"),
                    ColumnSpec(
                        "customer_id",
                        "VARCHAR",
                        "Mã khách hàng",
                        ("khách hàng", "người mua"),
                        role="id",
                        null_ratio=0.1,
                    ),
                    ColumnSpec(
                        "status",
                        "VARCHAR",
                        "Trạng thái đơn hàng",
                        ("trạng thái", "tình trạng"),
                        sample_values=("Hoàn thành", "Đã hủy", "Đang xử lý"),
                        role="category",
                    ),
                    ColumnSpec(
                        "total_amount",
                        "DOUBLE",
                        "Tổng tiền thanh toán trên bill",
                        ("tổng bill", "phải thu"),
                        role="money",
                    ),
                ),
            ),
            TableSpec(
                name="order_items",
                grain="order_item",
                description="Bảng chi tiết dòng hàng trong mỗi đơn (line items)",
                aliases=("chi tiết đơn", "dòng hàng", "món bán"),
                row_count=3800,
                date_coverage_start="2025-01-01",
                date_coverage_end="2026-12-31",
                columns=(
                    ColumnSpec("order_id", "VARCHAR", "Mã đơn hàng", ("mã bill",), role="id"),
                    ColumnSpec("product_id", "VARCHAR", "Mã sản phẩm", ("mã món", "sku"), role="id"),
                    ColumnSpec(
                        "product_name",
                        "VARCHAR",
                        "Tên sản phẩm kèm size/topping",
                        ("tên món", "sản phẩm", "mặt hàng"),
                        sample_values=(
                            "Cà phê sữa (L)",
                            "Cà phê sữa (M)",
                            "Trà sữa trân châu (L) + Kem cheese",
                            "Hồng trà đào (M)",
                        ),
                        role="name",
                    ),
                    ColumnSpec("quantity", "BIGINT", "Số lượng bán", ("số lượng", "sl"), role="quantity"),
                    ColumnSpec(
                        "line_revenue",
                        "DOUBLE",
                        "Thành tiền dòng hàng sau chiết khấu",
                        ("doanh thu", "thành tiền"),
                        role="money",
                    ),
                    ColumnSpec("order_date", "DATE", "Ngày đơn hàng", ("ngày bán",), role="date"),
                ),
            ),
            TableSpec(
                name="shift_payments",
                grain="payment_event",
                description="Báo cáo thu tiền thực tế theo ca làm việc và phương thức thanh toán",
                aliases=("thu tiền theo ca", "báo cáo ca", "thanh toán"),
                row_count=1400,
                date_coverage_start="2025-01-01",
                date_coverage_end="2026-12-31",
                columns=(
                    ColumnSpec("payment_id", "VARCHAR", "Mã giao dịch thu", role="id"),
                    ColumnSpec("order_id", "VARCHAR", "Mã đơn liên kết", role="id"),
                    ColumnSpec(
                        "payment_date",
                        "DATE",
                        "Ngày thu tiền thực tế",
                        ("ngày thu", "ngày thanh toán"),
                        role="date",
                    ),
                    ColumnSpec(
                        "shift_name",
                        "VARCHAR",
                        "Ca làm việc",
                        ("ca", "ca trực"),
                        sample_values=("Ca sáng", "Ca chiều", "Ca tối"),
                        role="category",
                    ),
                    ColumnSpec(
                        "payment_method",
                        "VARCHAR",
                        "Phương thức thanh toán",
                        ("hình thức thanh toán", "loại tiền"),
                        sample_values=("Tiền mặt", "Chuyển khoản", "Ví MoMo"),
                        role="category",
                    ),
                    ColumnSpec(
                        "collected_amount",
                        "DOUBLE",
                        "Số tiền thực thu trong ca",
                        ("tiền thực thu", "số tiền thu"),
                        role="money",
                    ),
                ),
            ),
            TableSpec(
                name="customers",
                grain="customer",
                description="Danh sách khách hàng thành viên",
                aliases=("khách hàng", "hội viên"),
                row_count=450,
                columns=(
                    ColumnSpec("customer_id", "VARCHAR", "Mã khách hàng", role="id"),
                    ColumnSpec(
                        "customer_name",
                        "VARCHAR",
                        "Tên khách hàng",
                        ("họ tên", "tên khách"),
                        sample_values=("Nguyễn Văn An", "Trần Thị Bình", "Lê Hoàng Nam"),
                        role="name",
                    ),
                ),
            ),
        )

        join_edges = (
            JoinSpec(
                left_table="order_items",
                left_column="order_id",
                right_table="orders",
                right_column="order_id",
                cardinality="many_to_one",
                fanout_warning=False,
                confidence=0.98,
            ),
            JoinSpec(
                left_table="orders",
                left_column="order_id",
                right_table="order_items",
                right_column="order_id",
                cardinality="one_to_many",
                fanout_warning=True,
                confidence=0.98,
            ),
            JoinSpec(
                left_table="orders",
                left_column="customer_id",
                right_table="customers",
                right_column="customer_id",
                cardinality="many_to_one",
                fanout_warning=False,
                confidence=0.95,
            ),
            JoinSpec(
                left_table="shift_payments",
                left_column="order_id",
                right_table="orders",
                right_column="order_id",
                cardinality="many_to_one",
                fanout_warning=False,
                confidence=0.92,
            ),
        )

        metrics = (
            MetricSpec(
                metric_id="revenue",
                aliases=("doanh thu", "doanh số", "tổng thành tiền"),
                preferred_table="order_items",
                required_columns=("line_revenue", "order_date"),
                date_role="order_date",
                formula_hint="SUM(order_items.line_revenue) cho các đơn Hoàn thành",
                unit="money_vnd",
            ),
            MetricSpec(
                metric_id="cash_collected",
                aliases=("tiền thực thu", "tiền mặt thu được", "thu được bao nhiêu tiền", "thực thu"),
                preferred_table="shift_payments",
                required_columns=("collected_amount", "payment_date", "payment_method"),
                date_role="payment_date",
                formula_hint="SUM(shift_payments.collected_amount) theo ngày thu thực tế",
                unit="money_vnd",
            ),
            MetricSpec(
                metric_id="order_count",
                aliases=("số đơn hàng", "bao nhiêu đơn", "tổng số đơn", "số lượng hóa đơn"),
                preferred_table="orders",
                required_columns=("order_id", "order_date"),
                date_role="order_date",
                formula_hint="COUNT(DISTINCT orders.order_id)",
                unit="count",
            ),
            MetricSpec(
                metric_id="distinct_product_orders",
                aliases=("được ưa chuộng", "nhiều đơn mua nhất", "xuất hiện trong nhiều đơn"),
                preferred_table="order_items",
                required_columns=("product_name", "order_id"),
                date_role="order_date",
                formula_hint="COUNT(DISTINCT order_items.order_id) GROUP BY product_name",
                unit="count",
            ),
            MetricSpec(
                metric_id="sold_qty",
                aliases=("bán chạy nhất", "số lượng bán", "tổng số ly", "số món bán ra"),
                preferred_table="order_items",
                required_columns=("quantity", "product_name"),
                date_role="order_date",
                formula_hint="SUM(order_items.quantity)",
                unit="quantity",
            ),
        )

        capabilities = {
            "sales_by_product": "supported",
            "customers": "supported",
            "payments": "supported",
            "shifts": "supported",
            "cost": "unsupported",
            "historical_stock": "unsupported",
            "expiry": "unsupported",
            "warranties": "unsupported",
        }

        calendar_events = (
            CalendarEventSpec(
                event_key="tet_2026",
                aliases=("tết", "tết âm lịch", "tết nguyên đán", "tết 2026", "dịp tết"),
                year=2026,
                start_date="2026-02-14",
                end_date="2026-02-22",
            ),
            CalendarEventSpec(
                event_key="tet_2025",
                aliases=("tết 2025", "tết năm ngoái"),
                year=2025,
                start_date="2025-01-25",
                end_date="2025-02-02",
            ),
        )

        rules = (
            "Doanh thu chuẩn được tính trên tổng thành tiền dòng hàng (line_revenue) của các đơn có trạng thái 'Hoàn thành'.",
            "Tiền thu theo ca (cash_collected) phải lấy từ bảng shift_payments theo ngày thu (payment_date), không lấy từ ngày đặt đơn.",
            "Sản phẩm 'được ưa chuộng nhất' tính theo số đơn hàng khác nhau (COUNT DISTINCT order_id), còn 'bán chạy nhất' tính theo tổng số lượng (SUM quantity).",
        )

        value_aliases = {
            "ca tối": ("shift_payments", "shift_name", "Ca tối"),
            "ca sáng": ("shift_payments", "shift_name", "Ca sáng"),
            "ca chiều": ("shift_payments", "shift_name", "Ca chiều"),
            "tiền mặt": ("shift_payments", "payment_method", "Tiền mặt"),
            "chuyển khoản": ("shift_payments", "payment_method", "Chuyển khoản"),
            "ck": ("shift_payments", "payment_method", "Chuyển khoản"),
            "momo": ("shift_payments", "payment_method", "Ví MoMo"),
            "hoàn thành": ("orders", "status", "Hoàn thành"),
            "thành công": ("orders", "status", "Hoàn thành"),
            "đã giao": ("orders", "status", "Hoàn thành"),
            "đã hủy": ("orders", "status", "Đã hủy"),
            "hủy": ("orders", "status", "Đã hủy"),
        }

        return InMemoryBusinessContext(
            business_id=business_id,
            tables=tables,
            join_edges=join_edges,
            metrics=metrics,
            capabilities=capabilities,
            calendar_events=calendar_events,
            rules=rules,
            value_aliases=value_aliases,
        )

    @staticmethod
    def create_anonymous_retail_context(business_id: str = "mock_retail_anon") -> InMemoryBusinessContext:
        """Create a retail context without customer identity or cost data (for UA testing)."""
        tables = (
            TableSpec(
                name="pos_receipts",
                grain="order",
                description="Bảng phiếu tính tiền tại quầy không lưu tên khách",
                aliases=("phiếu thu", "hóa đơn", "bán hàng"),
                row_count=500,
                date_coverage_start="2026-01-01",
                date_coverage_end="2026-12-31",
                columns=(
                    ColumnSpec("receipt_id", "VARCHAR", "Mã phiếu", role="id"),
                    ColumnSpec("order_date", "DATE", "Ngày bán", role="date"),
                    ColumnSpec("amount", "DOUBLE", "Tổng tiền", role="money"),
                ),
            ),
        )
        metrics = (
            MetricSpec(
                metric_id="revenue",
                aliases=("doanh thu", "tổng tiền"),
                preferred_table="pos_receipts",
                required_columns=("amount", "order_date"),
                date_role="order_date",
                unit="money_vnd",
            ),
        )
        capabilities = {
            "sales_by_product": "unsupported",
            "customers": "unsupported",
            "payments": "unsupported",
            "cost": "unsupported",
            "historical_stock": "unsupported",
        }
        return InMemoryBusinessContext(
            business_id=business_id,
            tables=tables,
            metrics=metrics,
            capabilities=capabilities,
        )


__all__ = [
    "InMemoryBusinessContext",
    "MockBusinessContextProvider",
]

