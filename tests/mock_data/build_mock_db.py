import os
import zipfile
import io
import duckdb

MOCK_DIR = os.path.dirname(os.path.abspath(__file__))
MOCK_DB_PATH = os.path.join(MOCK_DIR, "sample_cache.duckdb")
MOCK_FOLDER_PATH = os.path.join(MOCK_DIR, "sample_folder")


def build_mock_database(output_path: str = MOCK_DB_PATH) -> str:
    """
    Builds a mock DuckDB file for testing B0.4 executor.
    Includes 'customers', 'transactions', and 'calendar' tables.
    If 'train.zip' is found in the workspace root, also incorporates real sample calendar data.
    """
    if os.path.exists(output_path):
        try:
            os.remove(output_path)
        except OSError:
            pass

    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    con = duckdb.connect(database=output_path)

    # 1. Customers table
    con.execute("""
        CREATE TABLE customers (
            customer_id VARCHAR PRIMARY KEY,
            customer_name VARCHAR,
            city VARCHAR,
            total_spent DECIMAL(15, 2),
            is_active BOOLEAN,
            registered_date DATE
        );
    """)

    con.execute("""
        INSERT INTO customers VALUES
            ('CUST_001', 'Nguyen Van A', 'Ha Noi', 1500000.00, true, '2025-01-15'),
            ('CUST_002', 'Tran Thi B', 'Ho Chi Minh', 3200000.50, true, '2025-02-20'),
            ('CUST_003', 'Le Van C', 'Da Nang', 450000.00, false, '2025-03-10'),
            ('CUST_004', 'Pham Minh D', 'Can Tho', 8900000.00, true, '2025-04-05'),
            ('CUST_005', 'Hoang Thu E', 'Hai Phong', 0.00, false, '2025-05-12');
    """)

    # 2. Transactions table
    con.execute("""
        CREATE TABLE transactions (
            transaction_id VARCHAR PRIMARY KEY,
            customer_id VARCHAR,
            amount DECIMAL(15, 2),
            status VARCHAR,
            transaction_date DATE
        );
    """)

    con.execute("""
        INSERT INTO transactions VALUES
            ('TX_1001', 'CUST_001', 500000.00, 'COMPLETED', '2025-10-01'),
            ('TX_1002', 'CUST_001', 1000000.00, 'COMPLETED', '2025-10-15'),
            ('TX_1003', 'CUST_002', 3200000.50, 'COMPLETED', '2025-10-18'),
            ('TX_1004', 'CUST_003', 450000.00, 'CANCELLED', '2025-11-01'),
            ('TX_1005', 'CUST_004', 5000000.00, 'COMPLETED', '2025-11-05'),
            ('TX_1006', 'CUST_004', 3900000.00, 'PENDING', '2025-11-20'),
            ('TX_1007', 'CUST_001', 250000.00, 'FAILED', '2025-11-25');
    """)

    # 3. Check for real calendar data from train.zip if available
    train_zip_path = os.path.join(os.path.dirname(os.path.dirname(MOCK_DIR)), "train.zip")
    loaded_real_calendar = False

    if os.path.isfile(train_zip_path):
        try:
            with zipfile.ZipFile(train_zip_path) as z:
                if "train/calendar.csv" in z.namelist():
                    cal_data = z.read("train/calendar.csv").decode("utf-8")
                    con.execute("CREATE TABLE calendar AS SELECT * FROM read_csv(?, header=true, auto_detect=true)", [cal_data])
                    loaded_real_calendar = True
        except Exception:
            pass

    if not loaded_real_calendar:
        con.execute("""
            CREATE TABLE calendar (
                date DATE,
                day_of_week VARCHAR,
                month INT,
                year INT,
                is_holiday BOOLEAN
            );
        """)
        con.execute("""
            INSERT INTO calendar VALUES
                ('2025-10-01', 'Wednesday', 10, 2025, false),
                ('2025-10-18', 'Saturday', 10, 2025, false),
                ('2025-12-25', 'Thursday', 12, 2025, true),
                ('2026-01-01', 'Thursday', 1, 2026, true);
        """)

    con.close()
    return output_path


def build_mock_folder(output_dir: str = MOCK_FOLDER_PATH) -> str:
    """
    Builds a directory containing CSV files to test folder-based execution.
    """
    os.makedirs(output_dir, exist_ok=True)
    csv_file = os.path.join(output_dir, "orders.csv")
    with open(csv_file, "w", encoding="utf-8") as f:
        f.write("order_id,customer_name,total_amount,status\n")
        f.write("ORD_1,Nguyen Van A,150000,Delivered\n")
        f.write("ORD_2,Tran Thi B,250000,Processing\n")
        f.write("ORD_3,Le Van C,90000,Cancelled\n")
    return output_dir


if __name__ == "__main__":
    db_file = build_mock_database()
    print(f"Mock database created at: {db_file}")
    folder = build_mock_folder()
    print(f"Mock folder created at: {folder}")

