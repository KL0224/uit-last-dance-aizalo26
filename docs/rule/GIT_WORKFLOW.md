# Quy Trình Quản Lý Nhánh (Git Workflow) & Chiến Lược CI/CD Cho Dự Án AI (Zalo AI Challenge)

Tài liệu này định nghĩa quy chuẩn quản lý nhánh Git (Branching Strategy), chiến lược CI/CD phù hợp cho hạ tầng GPU đa nền tảng, và quy trình cộng tác tối ưu cho đội ngũ tham gia **Zalo AI Challenge 2026**.

---

## 1. Kiến Trúc Các Nhánh (Branching Model)

Dự án áp dụng mô hình Git Flow tinh gọn 2 nhánh dài hạn (`main` & `dev`), loại bỏ nhánh trung gian (`test`) nhằm tối đa hóa tốc độ thử nghiệm, tinh gọn quy trình và tập trung vào chu kỳ lặp nhanh (fast iteration) của bài toán AI/Data Science:

### 1.1. Các nhánh dài hạn (Long-lived Branches)

* **`main` (Production / Golden Submission)**:
  * Nhánh phản ánh mã nguồn ổn định nhất, phiên bản tạo ra các kết quả nộp bài chính thức (**Official Submission**) hoặc checkpoint mô hình có hiệu năng cao nhất (Best Score).
  * **Độ ổn định**: 100% stable, pipeline chạy mượt mà từ đầu đến cuối không lỗi (end-to-end), code tái tạo được kết quả (reproducible).
  * **Bảo vệ**: Protected Branch, nghiêm cấm commit trực tiếp. Chỉ nhận code thông qua Pull Request (PR) từ nhánh `dev` (sau khi đã nghiệm thu điểm số) hoặc từ nhánh `hotfix/*`.
  * **Tagging**: Mỗi lần merge vào `main` để nộp bài phải gắn tag phiên bản (ví dụ: `v1.0-sub`, `v1.1-sub`).

* **`dev` (Development & Integration)**:
  * Nhánh tích hợp chính hằng ngày của toàn đội ngũ lập trình viên và kỹ sư AI.
  * Nơi hội tụ các tính năng mới, module tiền xử lý dữ liệu, kiến trúc mô hình thử nghiệm sau khi dev đã test cục bộ thành công.
  * Toàn bộ việc kiểm thử tính tương thích giữa các module (pipeline integration) được thực hiện trực tiếp trên nhánh `dev`.

---

### 1.2. Các nhánh ngắn hạn (Short-lived / Temporary Branches)

* **`feature/<ten-tinh-nang>_<ten-dev>`**:
  * **Tách từ**: `dev`
  * **Mục đích**: Phát triển từng module, pipeline mới (ví dụ: data loader, augmentation, post-processing, API inference).
  * **Đích đến**: Sau khi hoàn thành và tự kiểm tra, tạo PR merge vào `dev`. Nhánh sẽ được giữ sau khi merge để đảm bảo an toàn nếu có điều chỉnh về sau.

* **`exp/<ten-thu-nghiem>_<ten-dev>`**:
  * **Tách từ**: `dev`
  * **Mục đích**: Chuyên biệt cho bài toán AI — thử nghiệm mô hình mới, loss function mới, hyperparameter tuning hoặc prompt engineering.
  * **Đích đến**: Nếu thực nghiệm chứng minh cải thiện chỉ số đánh giá (CV score / Validation metric tăng), tạo PR merge vào `dev`. Nếu thử nghiệm thất bại, có thể đóng hoặc lưu lại nhánh làm tư liệu mà không ảnh hưởng code chung.

* **`hotfix/<ten-loi-can-fix>`**:
  * **Tách từ**: `main`
  * **Mục đích**: Xử lý gấp các lỗi nghiêm trọng phát sinh trong mã nguồn nộp bài hoặc pipeline chính thức (ví dụ: lỗi định dạng file nộp `.csv`/`.json`, tràn bộ nhớ GPU khi inference tập test ẩn, lỗi timeout).
  * **Luồng xử lý**:
    1. Tách nhánh từ `main` -> Sửa lỗi và kiểm thử nhanh.
    2. Tạo PR merge trực tiếp vào `main` để kịp thời gian nộp bài.
    3. **BẮT BUỘC (Sync-back)**: Phải merge ngay lập tức ngược lại vào `dev` để tránh đợt release tiếp theo từ `dev` ghi đè làm tái diễn lỗi (Regression Bug).

---

## 2. Sơ Đồ Minh Họa Workflow (Dạng Thuần Markdown)

*(Sơ đồ dạng Text / ASCII thuần túy, hiển thị 100% ổn định trên mọi trình đọc Markdown, IDE và GitHub).*

### 2.1. Sơ đồ Tổng Thể Các Nhánh & Điểm Tích Hợp

```text
=======================================================================================================================================
[Nhánh]                           DÒNG THỜI GIAN & ĐIỂM CHUYỂN DỊCH CODE
=======================================================================================================================================

main (Sub)      ──(v1.0-sub)──────────────────────────────────────────(v1.1-sub)───●────────────────────────────(v1.1.1-hotfix)►
                                                                         ▲        /                    ▲
                                                      (3. Release PR)   /        / (A. Hot fix)       / (B. Merge PR)  
                                                                       /        /                    /        
dev (Dev)       ──(Init)──────●────────────────────────●──────────────●        /      ──────        / ────● (C. Merge Dev) 
                               \                      ▲                       /                    /     /
                      (1. Tạo)  \         (2. Merge) /                       /                    /     /
                                 ▼                  /                       /                    /     /
feature/* hoặc  ──────────────────[ Code & Test ]──┘                       /                    /     /
exp/* (AI Exp)                                                            /                    /     /
                                                                         /                    /     /
hotfix/*        ───────────────────────────────────────────────[ Sửa lỗi khẩn cấp ]──────────●─────● 
=======================================================================================================================================
```

---

### 2.2. Sơ đồ Chi Tiết Chu Kỳ Tính Năng Mới & Thử Nghiệm (Feature & Experiment Flow)

```text
┌─────────────────────────┐
│       Nhánh dev         │ ◄──────────────────────────────────────────────┐
└────────────┬────────────┘                                                │
             │                                                             │
             │ (1) git checkout -b feature/<tên> hoặc exp/<tên>            │ (2) Tạo PR & Merge vào dev
             ▼                                                             │     sau khi CI check PASS
┌─────────────────────────┐                                                │
│  feature/* hoặc exp/*   │ ───────────────────────────────────────────────┘
│  (Thành viên dev/train) │
└─────────────────────────┘
             │
             │ (3) Khi đạt kết quả tốt (Best Validation Score / Ready to Submit)
             │     Tạo PR: dev -> main
             ▼
┌─────────────────────────┐
│      Nhánh main       │ ──► [ ĐÓNG GÓI BẢN SUBMISSION CHÍNH THỨC (Gắn Tag Release) ]
└─────────────────────────┘
```

---

### 2.3. Sơ đồ Chi Tiết Chu Kỳ Sửa Lỗi Khẩn Cấp (Hotfix Flow)

```text
┌─────────────────────────┐       (A) Phát hiện lỗi crash tập test / sai format nộp bài
│      Nhánh main         │ ───────────────────────────────────────────────┐
└────────────▲────────────┘           git checkout -b hotfix/<tên-lỗi>     │
             │                                                             ▼
             │                                                ┌─────────────────────────┐
             │                                                │     Nhánh hotfix/*      │
             │ (B) Sửa xong, test đạt yêu cầu                 │ (Khắc phục lỗi cấp tốc) │
             │     Merge hotfix -> main                     └────────────┬────────────┘
             │     (Gắn tag vá lỗi vX.X.X)                                 │
             │                                                             │ (C) BẮT BUỘC ĐỒNG BỘ:
             │                                                             │     Merge hotfix -> dev
             │                                                             ▼
             │                                                ┌─────────────────────────┐
             └────────────────────────────────────────────────┤       Nhánh dev         │
                                                              │ (Tránh trôi bản sửa lỗi)│
                                                              └─────────────────────────┘
```

---

### 2.4. Bảng Tóm Tắt Quy Trình Các Nhánh

| Loại công việc | Tên nhánh | Tách từ nhánh | Merge vào | Kiểm thử & Triển khai |
| :--- | :--- | :--- | :--- | :--- |
| **Phát triển module mới** | `feature/<tên>_<dev>` | `dev` | `dev` | Test cục bộ, CI check tự động |
| **Thử nghiệm Model/AI** | `exp/<tên>_<dev>` | `dev` | `dev` (nếu metric tốt) | Chạy thực nghiệm trên máy GPU cá nhân/thuê |
| **Hợp nhất pipeline chung** | `dev` | - | `main` (khi sẵn sàng nộp) | Tích hợp end-to-end toàn bộ module |
| **Bản nộp chính thức (Prod)**| `main` | `dev` | `main` (gắn Tag) | Tạo file submission, lưu model checkpoint |
| **Vá lỗi cấp tốc (Hotfix)** | `hotfix/<tên-lỗi>` | `main` | `main` **VÀ** `dev` | Fix lỗi nhanh, kiểm thử định dạng nộp bài |

---

## 3. Chiến Lược CI/CD Thực Chiến Cho Bài Toán AI & Server GPU Đa Nền Tảng

### 3.1. Có nên làm CI/CD tự động deploy lên Server GPU không?

> [!IMPORTANT]
> **KHÔNG NÊN** thiết lập cơ chế **CD (Continuous Deployment) dạng Push SSH tự động** từ GitHub Actions sang server GPU khi tham gia cuộc thi AI.

**Lý do cốt lõi:**
1. **Hạ tầng GPU thuê linh hoạt, không cố định IP/Domain**: Khi thuê trên nhiều nền tảng khác nhau (Vast.ai, RunPod, Lambda Labs, Google Cloud Spot, Colab Pro...), mỗi lần khởi tạo bạn sẽ nhận một IP và cổng SSH hoàn toàn mới. Nếu dùng GitHub Actions CD truyền thống, bạn sẽ phải liên tục cập nhật IP, Port, SSH Secret vào GitHub Settings — vừa tốn công, vừa dễ lỗi.
2. **Chi phí và thời gian bật máy GPU**: Server GPU tính phí theo từng giờ/phút nên chỉ được bật khi cần train hoặc inference hàng loạt dữ liệu. Nếu server đang tắt, pipeline GitHub Actions CD sẽ thất bại.
3. **Đặc thù chạy AI Pipeline**: Huấn luyện hoặc suy luận mô hình AI cần truyền các tham số động (hyperparameters, đường dẫn weights, dataset version, WandB run name...) và cần quản lý tiến trình bằng `tmux`/`screen`, không giống như việc deploy một Web Server lắng nghe cổng 80/443 cố định.

---

### 3.2. Đề Xuất Giải Pháp CI/CD Tối Ưu Cho Cuộc Thi

Hệ thống kết hợp **CI tự động trên GitHub** và **Cơ chế triển khai 1 chạm (Pull-based Setup) trên Server GPU**:

#### A. CI (Continuous Integration) — Tự động chạy trên GitHub Actions (Runner CPU miễn phí)
Kích hoạt cho các nhánh:
* **Nhánh `dev`** (mỗi khi tạo PR vào `dev`):
  * **Code Quality & Linter**: Chạy `ruff` hoặc `flake8` kiểm tra cú pháp, format code toàn team đồng nhất.
  * **Sanity Check (Smoke Test)**: Chạy một test case nhanh mô phỏng 1 batch giả lập (dummy tensor `batch_size=1`) trên CPU.
  * *Ý nghĩa*: Đảm bảo code không bị lỗi cú pháp ngớ ngẩn (SyntaxError, NameError, thiếu import thư viện, sai shape tensor đầu vào) **TRƯỚC KHI** đem code lên server GPU thuê tốn tiền.
* **Nhánh `main`** (mỗi khi tạo PR hoặc merge vào `main`):
  * Chạy toàn bộ test kiểm tra tính toàn vẹn của pipeline inference.
  * (Tùy chọn): Tự động build và push Docker Image lên **GitHub Container Registry (GHCR)** kèm tag tương ứng.

#### B. Cơ chế triển khai GPU 1 chạm (Pull-based Execution)
Thay vì để GitHub tự động đẩy code sang máy GPU, team sử dụng quy trình **Pull-based** với script tự động hóa sẵn trong repo:

```text
[ Developer ] ────(git push/merge)────► [ GitHub Repo (dev/main) ]
                                                   │
                                                   ▼ (Chạy GitHub Actions CI: Linter, Dummy Test)
                                           [ Code Đã Xác Thực ]
                                                   ▲
                                                   │ git pull
[ Server GPU thuê (RunPod / Vast.ai) ] ────────────┘
     └── Chạy 1 lệnh: bash scripts/setup_env.sh
     └── Chạy train / inference trong tmux
```

* Trong repo có sẵn thư mục `scripts/`:
  * `scripts/setup_env.sh`: Tự động cài driver, requirements, tải pretrained base weights.
  * `Makefile` hoặc script chạy: `make train`, `make submit`.
* Bất cứ khi nào thuê một server GPU mới (RunPod, Vast.ai, GCP):
  1. SSH vào server.
  2. `git clone -b dev <repo-url>` (hoặc `git pull` nếu đã clone).
  3. Chạy `bash scripts/setup_env.sh` (chỉ mất 2-3 phút là môi trường sẵn sàng).
  4. Chạy huấn luyện hoặc sinh kết quả nộp bài.

---

## 4. Quy Ước Commit Message Chuẩn Hóa Cho Dự Án AI

Quy tắc **1 dòng tinh gọn**:

```bash
git commit -m "<type>(<scope>): <mô tả ngắn gọn>"
```

### 4.1. Bảng Commit Type Tối Ưu Cho AI Challenge

| Type | Ý nghĩa trong bài toán AI | Ví dụ thực tế |
| :--- | :--- | :--- |
| `feat` | Thêm tính năng, module, pipeline mới | `feat(pipeline): add two-stage ensemble pipeline` |
| `exp` | Thử nghiệm mô hình, loss, kiến trúc mới | `exp(model): test convnext backbone with focal loss` |
| `data` | Xử lý dữ liệu, augmentation, feature engineering | `data(augment): add albumentations mixup and cutmix` |
| `fix` | Sửa lỗi trong code pipeline/logic | `fix(loader): fix tensor shape mismatch in collate_fn` |
| `hotfix` | Vá lỗi khẩn cấp file nộp bài / crash test ẩn | `hotfix(sub): fix column name format in submission csv` |
| `eval` | Đánh giá, tính metric, validation | `eval(metric): add f1-macro calculation for validation` |
| `docs` | Viết tài liệu, nhật ký thí nghiệm | `docs(exp): record cv score of fold 1 to 5` |
| `refactor`| Tối ưu lại code cho gọn, tăng tốc I/O | `refactor(dataset): cache processed images in ram` |
| `chore` | Cài thêm package, cấu hình git, bash script | `chore(deps): add timm and wandb to requirements` |

### 4.2. Gợi ý Scope phổ biến

* `model`: Kiến trúc mô hình (`backbone`, `head`, `weights`).
* `data`: Quản lý dữ liệu, chia fold, augmentation.
* `pipeline`: Luồng xử lý end-to-end từ input đến output.
* `infer`: Quá trình suy luận và sinh file kết quả (`submission.csv`).
* `train`: Quá trình huấn luyện, learning rate scheduler, optimizer.
* `loss`: Hàm mất mát (`focal`, `bce`, `custom_loss`).
* `config`: File cấu hình YAML, Hydra, hyperparameters.

---

## 5. Quy Trình Thao Tác Lệnh Git Chi Tiết (SOP)

### 5.1. Kịch bản 1: Phát triển module hoặc Thử nghiệm Model (`feature/*` hoặc `exp/*`)

1. **Lấy code mới nhất từ dev:**
   ```bash
   git checkout dev
   git pull origin dev
   ```

2. **Tạo nhánh công việc:**
   ```bash
   # Nếu làm tính năng / pipeline:
   git checkout -b feature/data-augmentation_kiet

   # Nếu thử nghiệm kiến trúc model mới:
   git checkout -b exp/vit-base-experiment_kiet
   ```

3. **Code, commit và đẩy lên GitHub:**
   ```bash
   git add .
   git commit -m "feat(data): add random crop and color jitter"
   git push origin feature/data-augmentation_kiet
   ```

4. **Tạo Pull Request vào `dev`:**
   * Mở PR trên GitHub: `feature/...` → `dev`.
   * GitHub Actions CI tự động kiểm tra code syntax và sanity test.
   * Đồng đội review nhanh và merge vào `dev`.

---

### 5.2. Kịch bản 2: Triển khai chạy huấn luyện trên Server GPU thuê

1. **Trên máy GPU (kết nối qua SSH):**
   ```bash
   # Vào thư mục dự án (hoặc git clone lần đầu)
   cd uit-last-dance-aizalo26

   # Kéo mã nguồn mới nhất của nhánh dev
   git checkout dev
   git pull origin dev

   # Kích hoạt môi trường và chạy thử nghiệm trong tmux
   tmux new -s train_session
   python train.py --config configs/exp1.yaml
   ```

---

### 5.3. Kịch bản 3: Đóng gói bản nộp bài chính thức (`main`)

Khi một thử nghiệm trên `dev` mang lại kết quả CV tốt và sẵn sàng tạo file Submission:

1. **Tạo Pull Request từ `dev` sang `main` trên GitHub.**
2. **Sau khi merge, gắn thẻ (Tag) để đánh dấu phiên bản:**
   ```bash
   git checkout main
   git pull origin main
   git tag -a v1.0-sub -m "Submission v1.0 - CV score 0.892"
   git push origin v1.0-sub
   ```

---

### 5.4. Kịch bản 4: Sửa lỗi khẩn cấp trong phiên bản nộp bài (`hotfix/*`)

Nếu file nộp bài trên `main` bị lỗi định dạng (ví dụ: BTC báo lỗi file `submission.csv` rỗng hoặc sai cột):

1. **Tách nhánh khẩn cấp từ `main`:**
   ```bash
   git checkout main
   git pull origin main
   git checkout -b hotfix/fix-submission-format
   ```

2. **Sửa lỗi và commit:**
   ```bash
   git add .
   git commit -m "hotfix(sub): fix submission header and float format"
   git push origin hotfix/fix-submission-format
   ```

3. **Merge vào `main`:**
   * Tạo PR từ `hotfix/fix-submission-format` vào `main`.
   * Duyệt merge và nộp lại bài. Gắn tag mới: `git tag v1.0.1-hotfix && git push origin v1.0.1-hotfix`.

4. **BẮT BUỘC: Đồng bộ ngược lại vào `dev`:**
   ```bash
   git checkout dev
   git pull origin dev
   git merge hotfix/fix-submission-format
   git push origin dev
   ```
   *(Sau khi sync xong, xóa nhánh `hotfix/fix-submission-format` trên GitHub).*
