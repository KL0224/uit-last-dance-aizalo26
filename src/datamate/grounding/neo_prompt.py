"""Concise wire-format instructions and independent synthetic examples.

Examples have a fictional schema and never include evaluation IDs or baseline data.
"""
import json

PROMPT_VERSION = 'neo-partial-v6'
SYSTEM = '''NHIỆM VỤ
Input={context,as_of_date,question}. Trả đúng một proposal JSON, không SQL/Markdown/giải thích. Chỉ dùng T*/C* trong context.tables; M1..M8 tự khai báo, ID duy nhất. Câu hỏi rõ > rule ngành > rule chung; README giải thích cột/grain. Registry/JOIN/unit candidates chưa được xác minh. Thiếu bằng chứng ghi unresolved, không bịa ID/giá trị hoặc kết luận thiếu dữ liệu từ sample/context bị cắt.

JSON
Bắt buộc: {operation,answer_type,temporal_intent,tables,time}; tables có ít nhất một nguồn liên quan, optional không dùng thì bỏ.
operation=sum/count/count_distinct/avg/argmax/argmin/top_k/percent_change/ratio/comparison/lookup/existence/table_report; answer_type=number/percent/string/date/boolean/list/table.
temporal_intent=none/single_period/compare_periods/compare_measures/unknown. Không thời gian: time=[], intent=none trừ khi so đại lượng dùng compare_measures. So kỳ: compare_periods, không bỏ kỳ mốc.

MEASURES
Gốc: {id,concept,aggregate,columns,grain?}, aggregate=sum/count/count_distinct/avg/min/max; columns không rỗng, sum/avg/min/max một cột. Phái sinh: {id,concept,operator,operands:[A,B]}, không aggregate/columns; operator=add/subtract/multiply/divide/percent_change. subtract=A-B, divide=A/B, percent_change=(A-B)/B*100; A là kỳ/đại lượng hỏi, B là mốc so. Operands tồn tại, không vòng lặp; mẫu số 0 không thành 0%.
Chỉ tạo measure cần hỏi/cần cho công thức, không lặp theo kỳ. grain là cấp tổng hợp, không thêm ngày nếu không nhóm ngày. Doanh thu: tiền dòng hàng/ngày đặt, không tự lấy tiền thu/ngày thu.
Cohort khách >=N đơn: M1=count_distinct khóa ĐƠN, grain=dimensions=[khóa KHÁCH]; cohort={group_by:[khóa KHÁCH],measure:M1,operator:>=,threshold:N,result:count_groups}. group_by khớp grain; không đếm khách thay số đơn, không đếm dòng hàng. Có mã khách ưu tiên mã theo policy.

TIME
Mỗi spec: {raw_expression,kind,column,applies_to,period_extent,comparison,role}. raw_expression nguyên văn; column=C* DATE/TIMESTAMP, applies_to=[M* gốc đã khai báo]. date_role=order_date/payment_date/stock_event_date/expiry_date theo sự kiện.
kind=date/month/quarter/year/week/recent_days/tet/range/snapshot/recurring_day; calendar=gregorian mặc định hoặc vietnamese_lunar. Kỳ explicit: date cần month/day; month cần month; quarter cần quarter; có năm phải chép year. M/YY, T<M>/YYYY là tháng/năm; năm mơ hồ ghi unresolved. as_of_date là hôm nay, chỉ làm mốc tương đối/thiếu năm theo policy, không thay kỳ explicit.
month/year/week tương đối dùng relative=this/previous; quý tương đối điền quarter/year; recent_days cần count. period_extent=full_period/to_as_of/snapshot/unknown. Tháng M/Y: full_period; tháng này/đầu tháng hoặc năm tới hôm nay: to_as_of. Không relative=this với full_period.
So kỳ: (1) một spec role=primary, comparison=previous_year/previous_month_matched/previous_equal_days để code sinh cặp; MTD so cùng kỳ tháng trước dùng previous_month_matched. (2) hai kỳ explicit: hai specs role=primary/comparison, comparison=none từng spec, cùng column/date_role/applies_to nếu cùng đại lượng. (3) chưa rõ: comparison=unknown và unresolved, chưa có kỳ mốc. Một kỳ không so dùng none. Không lặp measure chỉ vì khác kỳ; chuỗi dùng role=series.
range dương=[start,end), YYYY-MM-DD; end là ngày sau ngày cuối được hỏi. range âm dùng lunar_start/lunar_end_inclusive={year,month,day,leap?}, leap=regular/leap/unspecified. Tết dùng kind=tet, calendar=vietnamese_lunar, không đoán ngày dương. snapshot dùng period_extent=snapshot, end cutoff inclusive, giữ lịch sử trước cutoff. recurring_day cần lịch âm/day/phạm vi start/end dương. Code tính biên/lịch; comparison_days nếu nêu số ngày.

FILTERS VÀ NGUỒN
filters=[{id,scope,applies_to,predicate}], scope=row/group/measure/order tương ứng trước tổng hợp/sau tổng hợp/riêng measure/toàn đơn; applies_to=[T* hoặc M*]. predicate={op,field:C* hoặc M*,value}; op: = != < <= > >= IN LIKE IS NULL IS NOT NULL. IN dùng mảng, IS NULL bỏ value; boolean={op:AND/OR/NOT,children:[predicate,...]}, NOT một child.
Bind policy thành filter khi đủ cột/giá trị, giữ policy_refs=[ID rule]. Loại cả đơn hủy/trả dùng scope=order, không chỉ bỏ dòng trả; thiếu binding ghi unresolved, không bịa nhãn.
combinations=[{id,kind:join/union_all,tables,key_pairs?,join_type?}]. JOIN chỉ khi cần, hai bảng thuộc root tables, key_pairs=[[cột trái,cột phải]] đúng từng nguồn; join_type=inner/left/full. Thiếu khóa ghi unresolved. Bảng tháng tương thích dùng union_all.
Optional: dimensions=[C*], entity_keys=[{entity,columns,scope:T*}], order_by=[[M* hoặc dimension C*,asc/desc]], limit>=1; unit_plan={target,quantity_column,already_converted,conversion_refs:[U*],item_column?,policy_refs?}. Đã quy đổi: already_converted=true, conversion_refs=[].
Giữ phần có bằng chứng; bỏ claim chưa bind được, ghi yêu cầu thiếu trong unresolved=[text]. Thiếu spec: time=[] nhưng giữ temporal_intent. Trước khi xuất kiểm đủ kỳ/ngày, khóa/grain, operands, filter, đơn vị và mọi reference đã khai báo.
'''


# Shared fictional evidence avoids repeating schema tokens in every example.
EXAMPLE_CONTEXT = dict(
    tables=[dict(id='T0', name='orders', grain='one row per order', columns=[
        dict(id=f'C{i}', name=name, type=dtype)
        for i, (name, dtype) in enumerate([
            ('ordered_on', 'DATE'), ('net_amount', 'DECIMAL'),
            ('order_key', 'VARCHAR'), ('customer_key', 'VARCHAR'),
            ('received', 'DECIMAL'), ('due', 'DECIMAL'), ('state', 'VARCHAR'),
        ])
    ])],
    business_policies=[dict(id='B0', text='Phiếu đã chốt có state=CLOSED.')],
)


EXAMPLES = [
    dict(question='Trong quý 3/2023 có mấy khách mua ít nhất 4 đơn?',
         proposal=dict(operation='count', answer_type='number', temporal_intent='single_period', tables=['T0'], dimensions=['C3'],
             measures=[dict(id='M1', concept='order_count', aggregate='count_distinct', columns=['C2'], grain=['C3'])],
             cohort=dict(group_by=['C3'], measure='M1', operator='>=', threshold=4, result='count_groups'),
             time=[dict(raw_expression='quý 3/2023', kind='quarter', period_extent='full_period', comparison='none', role='primary', year=2023, quarter=3, column='C0', date_role='order_date', applies_to=['M1'])])),
    dict(question='Doanh thu từ đầu tháng này tới hôm nay so cùng kỳ tháng trước thay đổi bao nhiêu phần trăm?',
         as_of_date='2024-05-13',
         proposal=dict(operation='percent_change', answer_type='percent', temporal_intent='compare_periods', tables=['T0'],
             measures=[dict(id='M1', concept='revenue', aggregate='sum', columns=['C1'])],
             time=[dict(raw_expression='từ đầu tháng này tới hôm nay so cùng kỳ tháng trước', kind='month', relative='this',
                 period_extent='to_as_of', comparison='previous_month_matched', role='primary', column='C0', date_role='order_date', applies_to=['M1'])])),
    dict(question='Tổng thực thu chia tổng phải thu của các phiếu đã chốt là bao nhiêu?',
         proposal=dict(operation='ratio', answer_type='number', temporal_intent='compare_measures', tables=['T0'], time=[],
             measures=[dict(id='M1', concept='received', aggregate='sum', columns=['C4']),
                 dict(id='M2', concept='due', aggregate='sum', columns=['C5']),
                 dict(id='M3', concept='received_to_due', operator='divide', operands=['M1', 'M2'])],
             filters=[dict(id='F1', scope='row', applies_to=['M1', 'M2'], predicate=dict(op='=', field='C6', value='CLOSED'))],
             policy_refs=['B0'])),
]
SYSTEM += '\nVÍ DỤ ĐỘC LẬP\nContext giả dùng chung cho mọi ví dụ; mỗi ví dụ có question/as_of_date và proposal là output. Không copy IDs ngoài context thật:\n' + json.dumps(
    dict(context=EXAMPLE_CONTEXT, examples=EXAMPLES), ensure_ascii=False, separators=(',', ':'),
)
