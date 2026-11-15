"""Audit reference tables by content rather than business-row lineage."""
import json

import duckdb
import pytest

from datamate.ingestion.ingestion import prepare_business
from scripts.audit_prepared_bundles import audit


def test_calendar_reference_checked_and_tampering_detected(tmp_path):
    biz=tmp_path/'biz_audit';biz.mkdir()
    (biz/'sales.csv').write_text('Mã đơn,Thành tiền\nA,10\n')
    calendar=tmp_path/'calendar.csv'
    calendar.write_text('date,weekday,lunar_day,lunar_month,lunar_year,lunar_leap,holiday\n2025-01-01,3,2,12,2024,false,New Year\n2025-01-02,4,3,12,2024,false,\n')
    first=prepare_business(biz,tmp_path/'out',calendar=calendar)
    warm=prepare_business(biz,tmp_path/'out',calendar=calendar)
    cold_record={**first.to_dict(),'wall_seconds':0,'peak_rss_mib':0}
    warm_record={**warm.to_dict(),'wall_seconds':0,'peak_rss_mib':0}
    report=tmp_path/'benchmark.json'
    report.write_text(json.dumps({'source_unchanged':True,'results':[{'business_id':biz.name,'cold':cold_record,'warm':warm_record}]}))
    assert audit(report)['business_count']==1
    with duckdb.connect(str(first.bundle_dir/'data.duckdb')) as con:
        con.execute("UPDATE calendar SET holiday='tampered' WHERE __dm_row_id=1")
    with pytest.raises(AssertionError):
        audit(report)


def test_control_totals_exclude_technical_row_ids():
    from scripts.audit_b01_b02_full import numeric_totals
    with duckdb.connect() as con:
        con.execute('CREATE TABLE "a b" (__dm_row_id BIGINT, money DECIMAL(38,2), qty INTEGER, note VARCHAR)')
        con.execute("INSERT INTO \"a b\" VALUES (100, 10.25, 2, 'x'), (200, 1.75, 3, 'y')")
        assert numeric_totals(con,'a b')=={'money':'12.00','qty':'5'}


@pytest.mark.parametrize('filename,header,row',[
    ('products.csv','Tên hàng,Đơn vị,Giá','Công tắc 1 chiều Panasonic,bộ,35000'),
    ('customers.csv','Mã khách,Tên gọi','KH01,Công ty ví dụ'),
])
def test_entity_name_cong_is_not_a_subtotal(tmp_path,filename,header,row):
    biz=tmp_path/'biz_entity';biz.mkdir()
    (biz/filename).write_text(header+'\n'+row+'\n',encoding='utf-8')
    a=prepare_business(biz,tmp_path/'out')
    with duckdb.connect(str(a.bundle_dir/'data.duckdb'),read_only=True) as con:
        tables=con.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='main'").fetchall()
        assert sum(con.execute('SELECT COUNT(*) FROM "'+t[0]+'"').fetchone()[0] for t in tables)==1
        assert con.execute("SELECT COUNT(*) FROM meta.quality_issues WHERE code='non_data_footer'").fetchone()[0]==0


def test_explicit_cong_ngay_summary_still_excluded(tmp_path):
    biz=tmp_path/'biz_marker';biz.mkdir()
    (biz/'sales.csv').write_text('Tên hàng,Số lượng,Thành tiền\nCông tắc,2,70000\nCộng ngày 01/01/2025,,70000\n',encoding='utf-8')
    a=prepare_business(biz,tmp_path/'out')
    with duckdb.connect(str(a.bundle_dir/'data.duckdb'),read_only=True) as con:
        t=con.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='main'").fetchone()[0]
        assert con.execute('SELECT COUNT(*) FROM "'+t+'"').fetchone()[0]==1
        assert con.execute("SELECT COUNT(*) FROM meta.quality_issues WHERE code='non_data_footer'").fetchone()[0]==1


def test_person_name_tong_nam_is_not_year_total(tmp_path):
    biz=tmp_path/'biz_person';biz.mkdir()
    (biz/'customers.csv').write_text('Mã khách,Tên gọi\nKH01,Tống Nam Quang\nKH02,Tong Nam Quang\n',encoding='utf-8')
    a=prepare_business(biz,tmp_path/'out')
    with duckdb.connect(str(a.bundle_dir/'data.duckdb'),read_only=True) as con:
        t=con.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='main'").fetchone()[0]
        assert con.execute('SELECT COUNT(*) FROM "'+t+'"').fetchone()[0]==2


def test_year_summary_requires_year_and_preserves_accents():
    from datamate.ingestion.ingestion.preparation import _is_summary_label
    exact={'tong nam'};prefixes=('tong nam ',)
    assert _is_summary_label('Tổng năm 2025',exact,prefixes)
    assert _is_summary_label('TONG NAM 2025',exact,prefixes)
    assert not _is_summary_label('Tống Nam 2025',exact,prefixes)
    assert not _is_summary_label('Tong Nam Quang',exact,prefixes)
