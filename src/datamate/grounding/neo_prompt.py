"""Grounding v3 extracts question spans and detailed source-independent time specs."""
import json

PROMPT_VERSION = 'neo-mentions-time-v1'
SYSTEM = '''NHIỆM VỤ
Input={context,as_of_date,question}. Chỉ trích xuất mention nguyên văn và phân tích thời gian. Trả đúng một JSON, không SQL/Markdown/giải thích.
KHÔNG chọn operation/answer_type, bảng/cột, JOIN, công thức, grain, predicate, policy_refs hay đơn vị quy đổi. Planner quyết định các phần đó.

OUTPUT: đúng 6 trường bắt buộc:
{metric_mentions:[],entity_mentions:[],condition_mentions:[],temporal_intent,time:[],unresolved:[]}
Mỗi mention={id,text}, ID duy nhất toàn output: m1.. cho metric, e1.. cho entity, c1.. cho condition; giữ thứ tự câu hỏi.
metric_mentions: các đại lượng hỏi (doanh thu, lãi gộp, số đơn, ghi nợ thêm, trả nợ...). Không đổi nghĩa hoặc gộp nhiều đại lượng thành một.
entity_mentions: tên khách, hàng, nhóm hàng, nhân viên, hoạt chất... Không suy ra mã hay giá trị DB.
condition_mentions: điều kiện, phạm vi, xếp hạng, ngưỡng hoặc so sánh được nêu rõ, ví dụ "có thu tiền", "ít nhất 4 đơn", "tăng hay giảm bao nhiêu %".
text và raw_expression phải là đoạn LIỀN MẠCH nguyên văn trong question, giữ dấu/viết tắt, không chuẩn hóa. Không tự thêm điều kiện từ nghiệp vụ.
unresolved: các chỗ mơ hồ/thiếu bằng chứng. Không kết luận unanswerable hoặc thiếu dữ liệu từ việc không có schema.

THỜI GIAN
Câu hỏi rõ > temporal_policies. as_of_date là hôm nay; chỉ làm mốc tương đối/thiếu năm, không thay kỳ explicit.
temporal_intent=none/single_period/compare_periods/compare_measures/unknown. Không có thời gian: time=[]; so hai đại lượng có thể compare_measures. So hai kỳ: compare_periods.
Mỗi time={id,raw_expression,kind,calendar,period_extent,comparison,role,applies_to,...thành phần ngày}. ID t1.. duy nhất.
applies_to=[ID mention] chịu ràng buộc; thông thường trỏ metric m*. [] nghĩa là toàn câu hỏi; không tạo measure, không trỏ bảng/cột.
kind=date/month/quarter/year/week/recent_days/tet/range/snapshot/recurring_day. calendar=gregorian/vietnamese_lunar.
Kỳ explicit: điền year/month/day/quarter theo câu hỏi; month bắt buộc month, quarter bắt buộc quarter, date bắt buộc month/day. T<M>/YYYY, M/YY là tháng/năm. Kỳ không ghi năm: year=null, code chọn năm theo policy. Năm mơ hồ ghi unresolved.
relative=this/previous chỉ cho month/year/week, không đồng thời điền year/month/quarter/day. Quý tương đối: điền quarter/year cụ thể.
period_extent=full_period/to_as_of/snapshot/unknown. Tháng M/Y rõ ràng: full_period. Tháng này/đầu năm tới hôm nay: to_as_of. Không relative=this với full_period. Tuần này: this/to_as_of; tuần trước: previous/full_period.
recent_days cần count, gồm hôm nay. Hôm nay/hôm qua dùng range với start/end dương theo as_of_date.
range dương cần start/end dạng YYYY-MM-DD, [start,end), end là ngày SAU ngày cuối được hỏi; dùng cho khoảng explicit và tuần có ngày cụ thể.
range âm cần lunar_start/lunar_end_inclusive={year,month,day,leap?}; leap=regular/leap/unspecified. Tết: kind=tet, calendar=vietnamese_lunar, year nếu nêu rõ; KHÔNG đoán ngày dương. recurring_day: calendar=vietnamese_lunar, day, phạm vi start/end dương.
snapshot: kind=snapshot, period_extent=snapshot, end là cutoff INCLUSIVE (khác end của range), giữ lịch sử trước cutoff.
role=primary/comparison/series. Một kỳ không so: comparison=none.
So kỳ có quan hệ rõ: một spec primary với comparison=previous_year/previous_month_matched/previous_equal_days; code sinh cặp. previous_month_matched cho cùng số ngày tháng trước; previous_equal_days cho kỳ liền trước cùng số ngày, comparison_days nếu nêu số ngày cụ thể.
Hai kỳ explicit: hai specs primary/comparison với comparison=none từng spec; giữ cùng applies_to nếu cùng đại lượng. Nhiều kỳ lần lượt: mỗi spec role=series, comparison=none.
Chưa rõ quan hệ/kỳ: comparison=unknown hoặc period_extent=unknown và ghi unresolved, không tự chọn mặc định. Đừng lặp kỳ comparison nếu code đã sinh tự động.
Code tính biên ngày và lịch âm/dương. Trước khi xuất: kiểm đủ mention, năm/tháng/ngày, kỳ mốc và references; thiếu spec thì time=[] nhưng giữ temporal_intent.
'''

EXAMPLES = [
    dict(question='Phiếu có thu tiền tháng 8 năm 2023 trung bình 1 phiếu bao nhiêu tiền?',
         as_of_date='2024-05-13', proposal=dict(
             metric_mentions=[dict(id='m1', text='trung bình 1 phiếu bao nhiêu tiền')],
             entity_mentions=[], condition_mentions=[dict(id='c1', text='có thu tiền')],
             temporal_intent='single_period', time=[dict(id='t1', raw_expression='tháng 8 năm 2023',
                 kind='month', calendar='gregorian', year=2023, month=8, period_extent='full_period',
                 comparison='none', role='primary', applies_to=['m1'])], unresolved=[])),
    dict(question='Doanh thu từ đầu tháng này tới hôm nay so cùng kỳ tháng trước thay đổi bao nhiêu phần trăm?',
         as_of_date='2024-05-13', proposal=dict(
             metric_mentions=[dict(id='m1', text='Doanh thu')], entity_mentions=[],
             condition_mentions=[dict(id='c1', text='so cùng kỳ tháng trước thay đổi bao nhiêu phần trăm')],
             temporal_intent='compare_periods', time=[dict(id='t1',
                 raw_expression='từ đầu tháng này tới hôm nay so cùng kỳ tháng trước',
                 kind='month', calendar='gregorian', relative='this', period_extent='to_as_of',
                 comparison='previous_month_matched', role='primary', applies_to=['m1'])], unresolved=[])),
    dict(question='Tháng 3/2024 chị Lan ghi nợ thêm bao nhiêu, trả nợ lại bao nhiêu?',
         as_of_date='2024-05-13', proposal=dict(
             metric_mentions=[dict(id='m1', text='ghi nợ thêm'), dict(id='m2', text='trả nợ lại')],
             entity_mentions=[dict(id='e1', text='chị Lan')], condition_mentions=[],
             temporal_intent='single_period', time=[dict(id='t1', raw_expression='Tháng 3/2024',
                 kind='month', calendar='gregorian', year=2024, month=3, period_extent='full_period',
                 comparison='none', role='primary', applies_to=['m1', 'm2'])], unresolved=[])),
    dict(question='trung binh moi don tuan truoc mang ve bao nhiu dthu',
         as_of_date='2025-04-08', proposal=dict(
             metric_mentions=[dict(id='m1', text='dthu')],
             entity_mentions=[], condition_mentions=[dict(id='c1', text='trung binh moi don')],
             temporal_intent='single_period', time=[dict(id='t1', raw_expression='tuan truoc',
                 kind='week', calendar='gregorian', relative='previous', period_extent='full_period',
                 comparison='none', role='primary', applies_to=['m1'])], unresolved=[])),
    dict(question='Hôm qua bán được bao nhiêu đơn?',
         as_of_date='2025-02-28', proposal=dict(
             metric_mentions=[dict(id='m1', text='bao nhiêu đơn')],
             entity_mentions=[], condition_mentions=[],
             temporal_intent='single_period', time=[dict(id='t1', raw_expression='Hôm qua',
                 kind='range', calendar='gregorian', start='2025-02-27', end='2025-02-28',
                 period_extent='full_period', comparison='none', role='primary', applies_to=['m1'])], unresolved=[])),
]
SYSTEM += '\nVÍ DỤ ĐỘC LẬP\n' + json.dumps(EXAMPLES, ensure_ascii=False, separators=(',', ':'))
