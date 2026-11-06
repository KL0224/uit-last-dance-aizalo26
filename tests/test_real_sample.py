import io
import os
import zipfile
import duckdb
import pandas as pd
import pytest

from datamate.b0.b04 import ExecutionRequest, execute_query


def test_real_biz_104_query(tmp_path):
    """
    Validates B0.4 executor on real Zalo AI Challenge train data (biz_104).
    Question q_00eadfc5c599: 'đếm số đơn đã huỷ trong tháng 12/2025' -> Expected 64.
    """
    train_zip = None
    for candidate in ["train.zip", "data/train.zip", "../train.zip", os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "train.zip")]:
        if os.path.exists(candidate):
            train_zip = candidate
            break

    if not train_zip:
        pytest.skip("train.zip not found in workspace")

    duckdb_path = str(tmp_path / "biz_104_sample.duckdb")
    with zipfile.ZipFile(train_zip) as z:
        b = z.read("train/data/biz_104/DonHang_ChiTiet.xlsx")
        df = pd.read_excel(io.BytesIO(b))
        con = duckdb.connect(duckdb_path)
        con.register("df", df)
        con.execute('CREATE TABLE donhang AS SELECT * FROM df')
        con.close()

    # Query using DuckDB SQL
    sql = """
    ```sql
    SELECT COUNT(DISTINCT "Mã đơn hàng") AS canceled_orders_count
    FROM donhang
    WHERE "Trạng thái đơn hàng" = 'Đã hủy'
      AND strptime("Ngày đặt hàng", '%d/%m/%Y') >= '2025-12-01'
      AND strptime("Ngày đặt hàng", '%d/%m/%Y') <= '2025-12-31';
    ```
    """
    req = ExecutionRequest(
        question_id="q_00eadfc5c599",
        db_path=duckdb_path,
        sql_query=sql,
        answer_type="number",
        retry_count=0,
    )

    res = execute_query(req)

    assert res.is_valid is True
    assert res.route == "yes"
    assert res.row_count == 1
    assert res.rows[0]["canceled_orders_count"] == 64
