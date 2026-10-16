# bctc-vn30: tải, đọc và chấm điểm BCTC của 30 mã VN30 (HOSE)

**Web: https://vietnhat-1305.github.io/bctc-vn30/**

Web có 4 tab:
- **Bảng điểm**: mỗi công ty 1 thẻ, có lọc.
- **Thư viện BCTC**: tra cứu và tải BCTC, link thẳng về web công ty.
- **Nguồn dữ liệu**: 30 web IR và độ trễ của CafeF.
- **Phương pháp**: cách thu thập dữ liệu và công thức chấm điểm.

Web là một file HTML tĩnh (`docs/index.html`, đã chứa sẵn dữ liệu) do GitHub Pages phục vụ. Cập nhật web: `python dang_web.py`.

Rổ VN30 đang dùng là kỳ hiệu lực từ 03/08/2026, gồm 30 mã:
ACB BID BSR CTG FPT GAS GVR HDB HPG LPB MBB MCH MSN MWG SAB SHB SSB SSI STB TCB TCX VCB VHM VIB VIC VJC VNM VPB VPL VRE.

| Bước | File | Việc |
|---|---|---|
| 1 | `website_30cty.xlsx`, [LINKS.md](LINKS.md), `companies.json`, `kiem_tra_ir.py` | Danh sách web đăng BCTC của 30 công ty và kết quả kiểm tra tool đọc được từng web |
| 2 | `bctc.py`, `ir_adapters.py` | Tải BCTC **từ web công ty** (nguồn đăng sớm nhất); CafeF chỉ để dự phòng |
| 3 | `pdf2txt.py` | PDF thường hoặc PDF scan → TXT (OCR tiếng Việt, giữ hàng/cột của bảng số) |
| 4 | `phan_tich.py` | Gemini đọc BCTC → DT, LNG, LNST, Tổng tài sản, Nợ, Nợ vay, Lưu chuyển tiền: **quý này so với quý trước** → Excel |
| 5 | `cham_diem.py`, `dashboard.py` | Chấm điểm thang 10 → **dashboard** mỗi công ty 1 thẻ, lọc nhanh (VD DT tăng > 20%, nợ vay giảm > 10%) |

## Chạy nhanh

```bash
pip install -r requirements.txt     # aiohttp, pymupdf, google-genai, pydantic, openpyxl, cryptography
# Lấy API key Gemini miễn phí: https://aistudio.google.com/apikey -> dán vào file .env: GEMINI_API_KEY=...

python kiem_tra_ir.py      # (tuỳ chọn) kiểm tra 30 web công ty còn đọc được không -> website_30cty.xlsx
python phan_tich.py        # tải BCTC quý mới nhất + quý trước từ web công ty -> Gemini -> chấm điểm
                           # -> ket_qua/so_sanh_quy.xlsx + ket_qua/dashboard.html (mở bằng trình duyệt)
```

Lần sau chỉ cần chạy lại `python phan_tich.py`, rồi `python dang_web.py` để đưa kết quả lên web. BCTC và kết quả Gemini đã có được dùng lại, chỉ BCTC mới mới phải tải và hỏi Gemini.

## Bước 1: Danh sách website (website_30cty.xlsx)

`python kiem_tra_ir.py` đi vào web của từng công ty và kiểm tra 3 việc: đọc được danh sách BCTC, có BCTC quý mới nhất (hợp nhất), tải thử được file và đúng là file PDF. Kết quả ghi vào `website_30cty.xlsx`, mỗi công ty một dòng gồm: web, trang BCTC, cách tool đọc, **PASS/FAIL**, kỳ mới nhất trên web và trên CafeF, CafeF đăng chậm bao nhiêu ngày, link file mới nhất, ghi chú kỹ thuật.

Kết quả ngày 15/10/2026: **PASS 30/30, đọc xong cả 30 web trong khoảng 20–35 giây.**

Đo trên BCTC Q2/2026 ở 14 mã có đủ ngày để so: **CafeF đăng sau web công ty trung vị 1,4 ngày, chậm nhất 5,5 ngày** (GVR, SSI). Vì vậy nguồn chính là web công ty.

Chạy lại script này khi tool báo lỗi một mã, vì các web hay đổi giao diện.

## Bước 2: Tải BCTC từ web công ty (bctc.py)

```bash
python bctc.py                                   # 30 mã, 2 năm gần nhất (mặc định --source ir-first)
python bctc.py --periods Q1,Q2,Q3,Q4 --latest 2 --scope HN   # 2 BCTC quý hợp nhất gần nhất
python bctc.py --tickers VNM,FPT --years all     # toàn bộ lịch sử (năm cũ web không còn thì lấy CafeF)
python bctc.py --list-only                       # chỉ lập danh mục link (data/index.csv)
python bctc.py --source cafef                    # chỉ dùng CafeF (nhanh nhất nhưng chậm hơn web công ty 1-5 ngày)
```

Mỗi web công ty dùng một kiểu khác nhau, nên tool có nhiều cách đọc. Cách đọc từng web nằm trong `companies.json`, xem bảng đầy đủ ở [LINKS.md](LINKS.md):

| Cách đọc | Các mã | Ghi chú |
|---|---|---|
| HTML tĩnh, có thể chia theo năm/quý | BID BSR CTG FPT GVR HPG SAB SSI VJC VNM VRE MCH MSN TCX VIB | VIB dùng User-Agent curl để qua Akamai; MSN, MCH, TCX đọc bằng curl vì Cloudflare chặn TLS của Python |
| API JSON | LPB STB TCB VCB VPB SHB | SHB đi qua Chrome headless vì Cloudflare chặn mọi request thường |
| 2 bước: danh sách → bài chi tiết → file | GAS SSB | |
| Adapter riêng (`ir_adapters.py`) | ACB HDB MBB MWG | ACB: API theo mã danh mục năm; HDB: giải mã AES; MBB: token XSRF; MWG: danh mục động |
| Chrome headless (Cloudflare) | VHM VIC VPL SHB | Chrome hoặc Edge có sẵn trên máy, chạy ẩn, giữ cookie, tối đa 3 trang cùng lúc |

Luồng của một mã:

```
companies.json ──► đọc web công ty ──┐   (song song)
                └► đọc CafeF ─────────┤
                                      ▼
   phân loại: tên file + tiêu đề → (năm, kỳ Q1-Q4/6T/NAM, HN/RIENG, KT/SX); bỏ giải trình, công văn, thường niên
   gộp IR-first: mỗi kỳ giữ 1 bản từ web công ty (ưu tiên tiếng Việt, "bản tra cứu" có sẵn chữ);
                 CafeF chỉ bù kỳ web không có; bản khác cùng kỳ làm dự phòng khi link hỏng
   không nhận ra BCTC nào (web đổi giao diện) → AI dự phòng: Gemini đọc danh sách link trên trang và tự chọn
                                      ▼
   tải song song (4 kết nối/host, stream, resume, kiểm tra %PDF, bỏ file trùng sha256) → data/<mã>/<năm>/
```

Số đo ngày 15/10/2026:

| Việc | Kết quả |
|---|---|
| Đọc danh mục 30 web công ty + CafeF | khoảng 12–35 giây (5 web cần Chrome mất 5–30 giây) |
| Tải 2 BCTC quý gần nhất của 30 mã từ web công ty | 61 file, 486 MB, 75 giây, 0 lỗi |
| Chạy lại khi không có BCTC mới | 12 giây |
| BCTC dùng cho phân tích lấy từ web công ty | 60/60 |

Tên file: `data/VNM/2026/VNM_2026_Q2_HN.pdf` = `<mã>_<năm>_<kỳ>_<phạm vi>[_<kiểm toán>]`. Kỳ: `Q1`–`Q4`, `6T` (bán niên), `NAM`. Phạm vi: `HN` (hợp nhất), `RIENG`, `CHUNG` (công ty không có công ty con như LPB, TCX). Kiểm toán: `KT`, `SX` (soát xét).

## Bước 3: PDF → TXT (pdf2txt.py)

```bash
python pdf2txt.py                          # mọi PDF trong data/ -> txt/ (giữ cấu trúc <mã>/<năm>/)
python pdf2txt.py data/ACB                 # một mã hoặc một file
python pdf2txt.py --pages 1-20             # chỉ 20 trang đầu (đủ chứa 3 báo cáo chính)
```

**Khoảng 90% BCTC VN30 là PDF scan** (đo trên 473 file: 427 file scan). Tool xét từng trang:
- **Trang có lớp chữ tốt**: lấy chữ trực tiếp, vài ms/trang.
- **Trang scan**, trang chỉ có chữ ký số, font lỗi (TCVN3/VNI, mất dấu kiểu "h p nh t") hoặc lớp chữ do công ty tự OCR kém (kiểm tra bằng tỷ lệ âm tiết tiếng Việt hợp lệ, ngưỡng 0,8): OCR tiếng Việt, khoảng 1–3 giây/trang.
- **Trang scan nằm ngang** (VD file trên web Vinhomes, không ghi thuộc tính xoay): khi OCR ra nhiều chữ rác, tool thử xoay 90°/270°/180° và giữ góc cho chữ giống tiếng Việt nhất. Trang không tự dò được thì theo góc đa số của file.

OCR dùng Tesseract có sẵn trong PyMuPDF, chỉ cần thư mục `tessdata/`, không phải cài gì. Bảng số giữ đúng hàng và cột. Tool chạy song song theo số nhân CPU thật; đo trên máy 6 nhân, 12 tiến trình còn chậm hơn 6.

## Bước 4: Gemini đọc BCTC (phan_tich.py)

```bash
python phan_tich.py                        # 30 mã
python phan_tich.py --tickers VNM,ACB,SSI
python phan_tich.py --dry-run              # không gọi API: tải, chọn trang, lưu PDF nhỏ vào ket_qua/debug để xem trước
```

```
2 BCTC quý cần so (quý thứ 3 chỉ khi cần tính lưu chuyển tiền trong quý)
 → quét VÙNG TIÊU ĐỀ (30% đầu trang, ~0,25 s/trang) tìm Bảng CĐKT / KQKD / LCTT, bỏ mục lục, dừng ở Thuyết minh
 → OCR đầy đủ chỉ các trang báo cáo (4–16 trang thay vì 30–97)
 → PDF nhỏ (trang scan → JPEG xám 200 dpi) + văn bản OCR làm gợi ý
 → Gemini 3.5 Flash-Lite, structured output (JSON theo schema), temperature 0
 → kiểm tra chéo: TS = Nợ + VCSH, LCTT thuần = KD + ĐT + TC, số tháng lũy kế, đúng kỳ, đơn vị hợp lý
 → cache ket_qua/json theo sha256 file (lần sau chỉ hỏi BCTC mới)
```

| Loại hình | "Doanh thu" lấy | "Lợi nhuận gộp" lấy | "Nợ vay" lấy |
|---|---|---|---|
| Doanh nghiệp | Doanh thu thuần (mã 10) | Lợi nhuận gộp (mã 20) | Vay và nợ thuê TC ngắn + dài hạn (mã 320 + 338) |
| Ngân hàng | Tổng thu nhập hoạt động | Thu nhập lãi thuần | không áp dụng (dùng Nợ phải trả) |
| Chứng khoán | Cộng doanh thu hoạt động | DT − CP hoạt động (tool tự tính) | Vay và nợ thuê TS tài chính |

BCTC chỉ ghi lưu chuyển tiền lũy kế từ đầu năm, nên tool tự trừ để ra số trong quý (quý 2 = lũy kế 6 tháng − lũy kế quý 1).

Đo bằng `--dry-run` trên 60 BCTC lấy từ web công ty: khâu chuẩn bị (quét tiêu đề, dò trang scan nằm ngang, OCR) mất 572 giây, khoảng 9,5 giây/BCTC. Mỗi BCTC gửi Gemini 4–16 trang, khoảng 9k token với bản có sẵn chữ và 15–35k token với bản scan. Lần chạy đầu cho 30 mã cần 60 request, mất khoảng 10 phút vì khâu chuẩn bị và Gemini chạy chồng lên nhau. Các quý sau chỉ còn khoảng 30 BCTC mới, mất khoảng 5 phút. Quota miễn phí khoảng 15 request/phút và 500 request/ngày (Google không công bố chính thức), tool tự giới hạn ở 12 request/phút.

## Bước 5: Chấm điểm và dashboard

`phan_tich.py` chạy xong sẽ tự tạo:
- **`ket_qua/dashboard.html`**: mở bằng trình duyệt, không cần mạng.
- **`ket_qua/so_sanh_quy.xlsx`**: gồm 3 sheet là *Chấm điểm*, *So sánh quý* và *Dữ liệu từng BCTC*.

Muốn dựng lại dashboard mà không gọi API thì chạy `python dashboard.py`.

Dashboard gồm:
- **Chỉ số tổng hợp**: số mã đạt 10/10, điểm trung bình, số mã có DT tăng, LNST tăng, nợ vay giảm, số mã có cảnh báo dữ liệu.
- **Bộ lọc**: tìm mã/tên, loại hình, điểm tối thiểu, DT tăng ≥ X%, LNST tăng ≥ X%, nợ vay giảm ≥ X%, dòng tiền kinh doanh dương, sắp xếp. Nút lọc nhanh: *Đạt 10/10*, *Từ 8 điểm*, *Doanh thu tăng > 20%*, *Nợ vay giảm > 10%*, *LNST tăng + dòng tiền dương*.
- **Thẻ từng công ty**: điểm /10, xếp loại, các chỉ số quý này kèm % so với quý trước (▲▼ có dấu, không chỉ dựa vào màu), chi tiết từng tiêu chí, cảnh báo, link BCTC gốc và web IR.
- Có thể chuyển sang dạng bảng, và đổi giao diện sáng/tối.

### Công thức chấm điểm (thang 10)

Điểm do code tính từ số liệu nên kiểm chứng lại được, không phải AI tự cho. BCTC ngân hàng và công ty chứng khoán khác doanh nghiệp: dòng tiền của họ phản ánh tiền gửi và cho vay chứ không đo chất lượng lợi nhuận. Vì vậy mỗi loại hình có một bộ tiêu chí riêng, bộ nào cũng tối đa 10 điểm.

| Doanh nghiệp, bảo hiểm | Điểm | Ngân hàng | Điểm | Chứng khoán | Điểm |
|---|---|---|---|---|---|
| DT thuần tăng so với quý trước | tăng 1, tăng ≥20% thì 2 | Tổng thu nhập HĐ tăng | tăng 1, tăng ≥10% thì 2 | DT hoạt động tăng | tăng 1, tăng ≥20% thì 2 |
| LNST tăng so với quý trước | tăng 1, tăng ≥20% hoặc lỗ → lãi thì 2 | LNST tăng | tăng 1, tăng ≥15% hoặc lỗ → lãi thì 2 | LNST tăng | tăng 1, tăng ≥20% hoặc lỗ → lãi thì 2 |
| LNST tăng ≥10% so với cùng kỳ năm trước | 1 | LNST tăng ≥15% so với cùng kỳ | 1 | LNST tăng ≥10% so với cùng kỳ | 1 |
| Biên LN gộp cải thiện | 1 | Thu nhập lãi thuần tăng | 1 | Biên LN hoạt động cải thiện | 1 |
| Dòng tiền kinh doanh trong quý dương | 1 | Tổng tài sản tăng | 1 | ROE quý quy năm ≥12% | 1 |
| LCTT kinh doanh ≥ LNST (lợi nhuận ra tiền thật) | 1 | ROE quý quy năm ≥15% | 1 | VCSH tăng | 1 |
| Đòn bẩy Nợ vay/VCSH không tăng | 1 | VCSH tăng | 1 | Đòn bẩy Nợ vay/VCSH không tăng | 1 |
| VCSH tăng | 1 | Đòn bẩy Nợ/VCSH không tăng | 1 | Tổng tài sản tăng | 1 |

- Xếp loại: **9–10 Rất tốt**, 7–8 Tốt, 4–6 Trung bình, 0–3 Yếu.
- Thiếu số liệu thì tiêu chí đó được 0 điểm và thẻ ghi rõ số điểm bị thiếu dữ liệu.
- **10/10** nghĩa là trong quý vừa công bố, công ty tăng cả doanh thu lẫn lợi nhuận mạnh, lãi hơn cùng kỳ, biên lợi nhuận tốt lên, lợi nhuận thu về bằng tiền, đòn bẩy không tăng và vốn chủ sở hữu tăng.
- Đây là điểm sức khỏe của **một quý BCTC**, chưa phải khuyến nghị đầu tư. Nên xem kèm định giá và xu hướng nhiều quý.
- Muốn đổi ngưỡng hay trọng số thì sửa `cham_diem.py`.

## Thêm hoặc sửa nguồn web của một công ty (companies.json)

```jsonc
{"ticker": "VNM", "fetch_mode": "static_html", "year_url": "https://...financial?year={year}"}      // chia theo năm
{"ticker": "VIB", "fetch_mode": "static_html", "ua": "curl/8.4.0",
 "year_url": "https://.../thong-tin-tai-chinh/{year}/bao-cao-quy-{q}?..."}                          // năm + quý
{"ticker": "SAB", "fetch_mode": "static_html", "bctc_url": "...", "year_links": "href=\"([^\"]*/(20\\d\\d)[^\"]*)\""}
{"ticker": "STB", "fetch_mode": "json_api", "api": {"url": "...json", "params": {"year": "{year}"}}}
{"ticker": "GAS", "fetch_mode": "two_step", "bctc_pages": ["<API danh sách>"], "follow_regex": "...", "href_regex": "..."}
{"ticker": "VHM", "fetch_mode": "static_html", "fetcher": "browser"}                                 // Cloudflare
{"ticker": "HDB", "fetch_mode": "custom", "adapter": "hdb"}                                          // ir_adapters.py
```

Các tuỳ chọn khác:
- `link_regex`: link nằm trong JSON/JS, nhóm 1 là link.
- `href_regex`: link tải không có đuôi `.pdf`.
- `page_is_bctc`: trang chỉ đăng BCTC.
- `title_from_row`: lấy tiêu đề theo hàng chứa link.
- `bctc_pages`: liệt kê nhiều trang, có thể dùng `{year}`.
- `fetcher`: `http` (mặc định), `curl` hoặc `browser`.

## Lưu ý

- Hãy đối chiếu thành phần VN30 với thông báo của HOSE (hsx.vn) ở mỗi kỳ review (tháng 1 và tháng 7), rồi sửa `companies.json`.
- Đường dẫn API nội bộ của web công ty (khoá AES của HDB, mã danh mục MWG, tham số ACB, fragment VIB...) có thể đổi khi web cập nhật. Chạy `kiem_tra_ir.py` để phát hiện. Khi luật không còn nhận ra BCTC nào, AI dự phòng sẽ tự chọn link (cần API key).
- Hãy xem cột **Cảnh báo** trước khi dùng số liệu. Cảnh báo nghĩa là AI có thể đã đọc sai dòng hoặc cột; mở BCTC gốc (link trên thẻ) để đối chiếu.
- Chỉ dùng cho mục đích học tập và nghiên cứu, với tốc độ truy cập vừa phải (tool đã giới hạn số kết nối).

Ghi nguồn: `tessdata/` (vie, eng) lấy từ [tesseract-ocr/tessdata_fast](https://github.com/tesseract-ocr/tessdata_fast), giấy phép Apache-2.0.
