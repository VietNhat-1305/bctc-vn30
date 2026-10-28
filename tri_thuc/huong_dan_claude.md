# Hướng dẫn Claude trích số liệu BCTC quý (thay Gemini khi chưa có API key)

Mỗi mã chỉ cần **1 BCTC: quý mới nhất**. Báo cáo đó đã có sẵn kỳ so sánh:
- Kết quả kinh doanh: quý này năm nay và **cùng quý năm trước**, kèm cột lũy kế từ đầu năm của cả hai năm.
- Bảng cân đối: **cuối quý** và **đầu năm** (01/01).
- Lưu chuyển tiền: **lũy kế từ đầu năm** của năm nay và cùng kỳ năm trước.

Chép CHÍNH XÁC từng con số. Số sai là lỗi nghiêm trọng; để null còn hơn đoán.

## Công cụ (Bash, thư mục C:/Users/Admin/bctc-vn30, luôn đặt PYTHONIOENCODING=utf-8)
1. `python claude_trich.py ds`: danh sách BCTC cần trích.
2. `python claude_trich.py chu <MÃ> <NĂM> <QUÝ>`: chữ của các trang 3 báo cáo. Chữ lấy từ lớp chữ gốc hoặc từ OCR; OCR có thể sai dấu và sai chữ số.
   - Trang scan đọc bằng PP-OCRv6 (`đọc bằng ppocr`): chữ số đáng tin hơn Tesseract nhưng chữ hay mất dấu, và ở bảng nhiều cột có thể xếp số vào nhầm dòng (gặp ở KQKD PNJ Q2/2026). Luôn khớp dòng và cột theo ảnh.
3. `python claude_trich.py anh <MÃ> <NĂM> <QUÝ>`: xuất ảnh PNG từng trang. Dùng tool Read xem ảnh (Read không mở PDF được trên máy này). Ảnh là nguồn đúng.
4. Viết JSON ra file riêng của bạn (tool Write), rồi chạy `python claude_trich.py ghi <MÃ> <NĂM> <QUÝ> <file.json>`.
   - Lệnh kiểm tra schema và cân đối: Tổng TS = Nợ + VCSH, cả cuối quý lẫn đầu năm; LCTT thuần = KD + ĐT + TC, cả năm nay lẫn năm trước.
   - Nếu in `CẢNH BÁO` thì xem lại ảnh, sửa và ghi lại, tối đa 3 lần.

## Mẫu JSON
Ghi đủ tất cả trường; trường không có thì để null.
```json
{"ma_ck": "HPG", "ky_bao_cao": "Q2/2026", "loai_hinh": "doanh_nghiep", "don_vi": "dong",
 "doanh_thu_thuan": null, "doanh_thu_thuan_cung_ky": null, "gia_von": null, "gia_von_cung_ky": null,
 "loi_nhuan_gop": null, "loi_nhuan_gop_cung_ky": null, "lnst": null, "lnst_cung_ky": null,
 "lnst_cong_ty_me": null, "lnst_cong_ty_me_cung_ky": null,
 "doanh_thu_thuan_luy_ke": null, "doanh_thu_thuan_cung_ky_luy_ke": null, "gia_von_luy_ke": null,
 "loi_nhuan_gop_luy_ke": null, "loi_nhuan_gop_cung_ky_luy_ke": null, "lnst_luy_ke": null,
 "lnst_cung_ky_luy_ke": null, "lnst_cong_ty_me_luy_ke": null,
 "tong_tai_san": null, "no_phai_tra": null, "vay_no": null, "von_chu_so_huu": null,
 "tong_tai_san_dau_nam": null, "no_phai_tra_dau_nam": null, "vay_no_dau_nam": null, "von_chu_so_huu_dau_nam": null,
 "so_thang_luy_ke": 6, "lctt_hdkd": null, "lctt_hddt": null, "lctt_hdtc": null, "lctt_thuan": null,
 "lctt_hdkd_cung_ky": null, "lctt_hddt_cung_ky": null, "lctt_hdtc_cung_ky": null, "lctt_thuan_cung_ky": null,
 "trang_cdkt": 1, "trang_kqkd": 4, "trang_lctt": 6, "ghi_chu": "", "thong_tin": ""}
```
Ngân hàng, chứng khoán, bảo hiểm: thêm vào cùng JSON các trường khoản mục riêng của đúng loại hình (`nh_*`, `ck_*` hoặc `bh_*`, xem mục "Khoản mục riêng theo loại hình"); doanh nghiệp thường không cần.

## Quy tắc cột
- **Đơn vị:** ghi `don_vi` đúng đơn vị của báo cáo: "dong", "nghin_dong", "trieu_dong" hoặc "ty_dong". Không đổi đơn vị, không làm tròn.
- **Số âm và dấu phân cách:** số trong ngoặc (1.234) là số âm -1234. Dấu chấm/phẩy là phân cách hàng nghìn.
- **KQKD:**
  - Trường quý = cột quý này năm nay; `*_cung_ky` = cột cùng quý năm trước.
  - `*_luy_ke` = lũy kế từ đầu năm năm nay; `*_cung_ky_luy_ke` = lũy kế năm trước.
  - Quý 1 không có cột lũy kế thì để null phần lũy kế.
- **CĐKT:** trường chính = cột cuối kỳ; `*_dau_nam` = cột số đầu năm (01/01).
- **LCTT:** trường chính = lũy kế năm nay; `lctt_*_cung_ky` = lũy kế cùng kỳ năm trước.
- **`thong_tin` và `ghi_chu`:** cách lấy số ghi vào `thong_tin`. `ghi_chu` chỉ dùng cho bất thường cần người xem, vì nội dung ở đây hiện lên web dưới dạng cảnh báo.

## Ánh xạ chỉ tiêu (nhận diện theo TÊN, mẫu 2026 đổi mã số)
- **Doanh nghiệp:**
  - Doanh thu thuần về bán hàng và cung cấp dịch vụ.
  - Giá vốn hàng bán.
  - Lợi nhuận gộp.
  - LNST thu nhập doanh nghiệp, và LNST của cổ đông công ty mẹ.
  - TỔNG CỘNG TÀI SẢN; NỢ PHẢI TRẢ; VỐN CHỦ SỞ HỮU (gồm cổ đông không kiểm soát).
  - Nợ vay = vay và nợ thuê tài chính ngắn hạn + dài hạn.
- **Ngân hàng** (ACB BID CTG HDB LPB MBB SHB SSB STB TCB VCB VIB VPB, mã bổ sung OCB):
  - Doanh thu = Tổng thu nhập hoạt động; lợi nhuận gộp = Thu nhập lãi thuần.
  - Giá vốn và nợ vay để null.
- **Chứng khoán** (SSI, TCX, mã bổ sung HCM):
  - Doanh thu = Cộng doanh thu hoạt động; giá vốn = Cộng chi phí hoạt động; lợi nhuận gộp để null.
  - Nợ vay = vay và nợ thuê tài sản tài chính ngắn hạn + dài hạn.
- **Bảo hiểm phi nhân thọ** (mã bổ sung MIG, PGI; BCTC theo TT 232/2012/TT-BTC, mẫu B02-DNPNT):
  - Doanh thu = Doanh thu thuần hoạt động kinh doanh bảo hiểm; giá vốn = Tổng chi phí hoạt động kinh doanh bảo hiểm;
    lợi nhuận gộp = Lợi nhuận gộp hoạt động kinh doanh bảo hiểm; nợ vay để null nếu không có dòng vay.

## Khoản mục riêng theo loại hình (dùng cho bộ chấm điểm riêng)
Chỉ điền nhóm trường đúng loại hình của báo cáo. Nhận diện theo **tên dòng**. Chi phí và dự phòng ghi **số dương**
(giá trị tuyệt đối). Trường `*_luy_ke` lấy cột lũy kế từ đầu năm (riêng nhóm này: quý 1 thì lũy kế chính là cột quý, ghi luôn). Trường `*_dau_nam` lấy cột số đầu năm.
- **Ngân hàng (nh_):**
  - `nh_cho_vay_kh` (+ `_dau_nam`): dòng "Cho vay khách hàng", tức dư nợ gốc **trước** dự phòng.
  - `nh_du_phong_cho_vay` (+ `_dau_nam`): dòng "Dự phòng rủi ro cho vay khách hàng".
  - `nh_tien_gui_kh` (+ `_dau_nam`): dòng "Tiền gửi của khách hàng".
  - `nh_giay_to_co_gia` (+ `_dau_nam`): dòng "Phát hành giấy tờ có giá" bên nợ phải trả (không có thì ghi 0 nếu dòng in "-").
  - `nh_chi_phi_hd_luy_ke` / `nh_chi_phi_hd_cung_ky_luy_ke`: dòng "Chi phí hoạt động" trên KQKD, cột lũy kế.
  - `nh_chi_phi_du_phong_luy_ke` / `nh_chi_phi_du_phong_cung_ky_luy_ke`: dòng "Chi phí dự phòng rủi ro tín dụng", cột lũy kế.
- **Chứng khoán (ck_), mẫu B02-CTCK:**
  - `ck_dt_moi_gioi_luy_ke` / `_cung_ky_luy_ke`: dòng "Doanh thu nghiệp vụ môi giới chứng khoán".
  - `ck_lai_cho_vay_luy_ke` / `_cung_ky_luy_ke`: dòng "Lãi từ các khoản cho vay và phải thu".
  - `ck_lai_fvtpl_luy_ke` / `_cung_ky_luy_ke`: dòng "Lãi từ các tài sản tài chính ghi nhận thông qua lãi/lỗ (FVTPL)".
  - `ck_cho_vay` (+ `_dau_nam`): dòng "Các khoản cho vay" trên CĐKT (ký quỹ + ứng trước tiền bán), **trước** dự phòng.
- **Bảo hiểm (bh_), mẫu B02-DNPNT:**
  - `bh_phi_thuan_luy_ke` / `_cung_ky_luy_ke`: dòng "Doanh thu phí bảo hiểm thuần".
  - `bh_boi_thuong_thuan_luy_ke` / `_cung_ky_luy_ke`: dòng "Tổng chi bồi thường bảo hiểm" (mã 15 = chi bồi thường − thu bồi
    thường nhượng tái ± tăng/giảm dự phòng bồi thường), tức bồi thường phát sinh thuần như định nghĩa của IMF.
  - `bh_chi_phi_kdbh_luy_ke` / `_cung_ky_luy_ke`: dòng "Tổng chi phí hoạt động kinh doanh bảo hiểm".
  - `bh_chi_phi_qldn_luy_ke` / `_cung_ky_luy_ke`: dòng "Chi phí quản lý doanh nghiệp".
  - `bh_ln_hdtc_luy_ke` / `_cung_ky_luy_ke`: dòng "Lợi nhuận hoạt động tài chính", bằng doanh thu HĐTC trừ chi phí HĐTC.
  - `bh_dau_tu` (+ `_dau_nam`): "Đầu tư tài chính ngắn hạn" cộng "Đầu tư tài chính dài hạn" trên CĐKT.
  - `bh_du_phong_nv` (+ `_dau_nam`): dòng "Dự phòng nghiệp vụ" (tổng) trên CĐKT.
- **Quý 2 trở đi mà báo cáo không có cột lũy kế** (chỉ có cột quý): để null, không tự cộng.
- **Lệnh ghi:**
  - BCTC đã trích đủ phần chung, chỉ thiếu khoản mục riêng: ghi JSON chỉ gồm các trường riêng, rồi chạy
    `python claude_trich.py bo_sung <MÃ> <NĂM> <QUÝ> <file.json>`.
  - Lệnh in điểm mới và các tỷ lệ. Nếu báo **CẢNH BÁO** (ví dụ LDR, CIR, tỷ lệ kết hợp nằm ngoài khoảng hợp lý) thì xem lại ảnh.

Lệnh `python claude_trich.py huong_dan <MÃ...>` in hướng dẫn này kèm **sổ bài học**, gồm quy tắc rút ra từ các lần sai trước và lưu ý riêng từng mã. Phải áp dụng đủ các quy tắc đó.

## Báo cáo cuối
Mỗi BCTC một dòng: `MÃ Qx/NĂM: OK | DT x tỷ (cùng kỳ y), LNST ..., TS ...`, hoặc nêu cảnh báo còn lại và lý do.
