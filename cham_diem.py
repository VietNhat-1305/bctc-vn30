"""Chấm điểm sức khỏe BCTC quý theo thang 10, riêng cho 4 loại hình, chỉ cần 1 BCTC quý (so với các cột có sẵn trong báo cáo).

Vì sao 4 bộ riêng: BCTC ngân hàng (QĐ 16/2007/QĐ-NHNN, sửa bởi TT 49/2014, 22/2017, 27/2021), công ty chứng khoán
(TT 210/2014 + 334/2016/TT-BTC), doanh nghiệp bảo hiểm phi nhân thọ (TT 232/2012/TT-BTC) và doanh nghiệp thường
(TT 99/2025/TT-BTC, trước đó TT 200/2014) khác nhau về cấu trúc, tên khoản mục và giới hạn an toàn pháp lý -> cùng một chỉ
số (VD "doanh thu", "đòn bẩy") mang nghĩa khác nhau. Nguồn: NGUON (cuối file).

Khung tham chiếu (chi tiết + nguồn: docs/cham-diem.html, docs/bao-cao-cham-diem.html):
  doanh_nghiep : tín hiệu kiểu Piotroski F-score (2000) - tăng trưởng, biên lợi nhuận, chất lượng dòng tiền, đòn bẩy, vốn
  ngan_hang    : CAMELS (FFIEC) + chỉ tiêu lành mạnh tài chính cốt lõi của IMF (FSI) - Vốn, Chất lượng tài sản, Hiệu quả,
                 Thanh khoản, Tăng trưởng; ngưỡng đối chiếu quy định NHNN (VD tỷ lệ dư nợ/tiền gửi 85%, TT 22/2019)
  chung_khoan  : Hiệu quả, Tăng trưởng, Chất lượng thu nhập (phụ thuộc tự doanh), Đòn bẩy và cho vay ký quỹ so với trần
                 pháp lý (nợ ≤ 5 lần VCSH - TT 121/2020; dư nợ ký quỹ ≤ 200% VCSH - QĐ 87/QĐ-UBCK), Vốn
  bao_hiem     : CARAMELS (IMF) cho bảo hiểm phi nhân thọ - Nghiệp vụ (tỷ lệ kết hợp, tỷ lệ bồi thường), Đầu tư, Hiệu quả,
                 Tăng trưởng, Vốn và dự phòng
Nguyên tắc: mỗi tiêu chí là 1 phép so sánh kiểm chứng lại được từ số trên BCTC (không để AI tự cho điểm); thiếu số -> 0 điểm,
ghi "thiếu dữ liệu" (không đoán); tiêu chí đặt dưới dạng dữ liệu (TIEU_CHI) dùng chung cho chấm điểm và tài liệu.
"""
from __future__ import annotations

TIERS = [(9, "Rất tốt"), (7, "Tốt"), (4, "Trung bình"), (0, "Yếu")]
LOAI_VI = {"doanh_nghiep": "Doanh nghiệp (sản xuất, thương mại, dịch vụ)", "ngan_hang": "Ngân hàng",
           "chung_khoan": "Công ty chứng khoán", "bao_hiem": "Bảo hiểm phi nhân thọ"}


def pct(a, b):
    """% thay đổi a so với b; mẫu âm dùng |b| để dấu luôn đúng chiều (lỗ ít đi = tăng)."""
    if a is None or b is None or b == 0:
        return None
    return (a - b) / abs(b)


def ratio(a, b):
    return a / b if a is not None and b not in (None, 0) else None


def avg(a, b):
    if a is None:
        return None
    return (a + (b if b is not None else a)) / 2


def _abs(x):
    return None if x is None else abs(x)


def metrics(cur: dict, cmp: dict | None, kind: str, quy: int = 4, v: dict | None = None) -> dict:
    """Chỉ số dùng để chấm và hiển thị (tỷ đồng). cur: số năm nay; cmp: kỳ so sánh trong cùng BCTC (KQKD cùng quý năm
    trước, CĐKT đầu năm, LCTT/lũy kế cùng kỳ năm trước). quy: quý báo cáo (để quy năm). v: toàn bộ số đã chuẩn hoá của
    BCTC (phan_tich.normalize) - cần cho chỉ số riêng từng loại hình."""
    p = cmp or {}
    v = v or {}
    m = {
        "dt": cur.get("doanh_thu_thuan"), "dt_truoc": p.get("doanh_thu_thuan"),
        "lng": cur.get("loi_nhuan_gop"), "lng_truoc": p.get("loi_nhuan_gop"),
        "lnst": cur.get("lnst"), "lnst_truoc": p.get("lnst"),
        "lnst_lk": cur.get("lnst_lk"), "lnst_lk_truoc": p.get("lnst_lk"),
        "ts": cur.get("tong_tai_san"), "ts_truoc": p.get("tong_tai_san"),
        "no": cur.get("no_phai_tra"), "no_truoc": p.get("no_phai_tra"),
        "vcsh": cur.get("von_chu_so_huu"), "vcsh_truoc": p.get("von_chu_so_huu"),
        "cfo": cur.get("lctt_hdkd"), "cfo_truoc": p.get("lctt_hdkd"),
    }
    m["dt_pct"] = pct(m["dt"], m["dt_truoc"])
    m["lng_pct"] = pct(m["lng"], m["lng_truoc"])
    m["lnst_pct"] = pct(m["lnst"], m["lnst_truoc"])
    m["lnst_lk_pct"] = pct(m["lnst_lk"], m["lnst_lk_truoc"])
    m["ts_pct"] = pct(m["ts"], m["ts_truoc"])
    m["no_pct"] = pct(m["no"], m["no_truoc"])
    m["vcsh_pct"] = pct(m["vcsh"], m["vcsh_truoc"])
    m["cfo_pct"] = pct(m["cfo"], m["cfo_truoc"])
    m["bien_gop"] = ratio(m["lng"], m["dt"])
    m["bien_gop_truoc"] = ratio(m["lng_truoc"], m["dt_truoc"])
    m["vay"], m["vay_truoc"] = cur.get("vay_no"), p.get("vay_no")
    m["vay_pct"] = pct(m["vay"], m["vay_truoc"])
    # Đòn bẩy: Nợ vay/VCSH nếu có số nợ vay cả cuối quý và đầu năm (doanh nghiệp), không thì Nợ phải trả/VCSH
    if m["vay"] is not None and m["vay_truoc"] is not None:
        m["don_bay_ten"] = "Nợ vay/VCSH"
        m["no_vcsh"], m["no_vcsh_truoc"] = ratio(m["vay"], m["vcsh"]), ratio(m["vay_truoc"], m["vcsh_truoc"])
    else:
        m["don_bay_ten"] = "Nợ phải trả/VCSH"
        m["no_vcsh"], m["no_vcsh_truoc"] = ratio(m["no"], m["vcsh"]), ratio(m["no_truoc"], m["vcsh_truoc"])
    # Quy năm: số lũy kế × 4 / số quý; mẫu số bình quân (đầu năm, cuối quý)
    k = 4 / quy if quy else 1
    lk = m["lnst_lk"] if m["lnst_lk"] is not None else m["lnst"]
    n_q = quy if m["lnst_lk"] is not None else 1
    avg_eq = avg(m["vcsh"], m["vcsh_truoc"])
    m["roe"] = (lk * 4 / n_q / avg_eq) if lk is not None and avg_eq else None
    avg_ts = avg(m["ts"], m["ts_truoc"])
    m["roa"] = (lk * 4 / n_q / avg_ts) if lk is not None and avg_ts else None
    m["vcsh_ts"], m["vcsh_ts_truoc"] = ratio(m["vcsh"], m["ts"]), ratio(m["vcsh_truoc"], m["ts_truoc"])
    dt_lk = v.get("doanh_thu_thuan_luy_ke") if v.get("doanh_thu_thuan_luy_ke") is not None else m["dt"]

    if kind == "ngan_hang":
        cv, cv0 = v.get("nh_cho_vay_kh"), v.get("nh_cho_vay_kh_dau_nam")
        dp, dp0 = _abs(v.get("nh_du_phong_cho_vay")), _abs(v.get("nh_du_phong_cho_vay_dau_nam"))
        tg, tg0 = v.get("nh_tien_gui_kh"), v.get("nh_tien_gui_kh_dau_nam")
        gt, gt0 = v.get("nh_giay_to_co_gia"), v.get("nh_giay_to_co_gia_dau_nam")
        hd = tg + gt if tg is not None and gt is not None else None          # vốn huy động = tiền gửi KH + giấy tờ có giá
        hd0 = tg0 + gt0 if tg0 is not None and gt0 is not None else None
        cp, cp_t = _abs(v.get("nh_chi_phi_hd_luy_ke")), _abs(v.get("nh_chi_phi_hd_cung_ky_luy_ke"))
        dpc = _abs(v.get("nh_chi_phi_du_phong_luy_ke"))
        m.update(cho_vay=cv, cho_vay_truoc=cv0, cho_vay_pct=pct(cv, cv0), tien_gui=tg, tien_gui_truoc=tg0,
                 tien_gui_pct=pct(tg, tg0), du_phong=dp)
        m["cir"] = ratio(cp, dt_lk)
        m["cir_truoc"] = ratio(cp_t, v.get("doanh_thu_thuan_cung_ky_luy_ke"))
        m["chi_phi_tin_dung"] = (dpc * k / avg(cv, cv0)) if dpc is not None and avg(cv, cv0) else None
        m["llr"], m["llr_truoc"] = ratio(dp, cv), ratio(dp0, cv0)
        m["ldr"], m["ldr_truoc"] = ratio(cv, hd), ratio(cv0, hd0)
        m["ldr_don"] = ratio(cv, tg)                                             # cho vay / tiền gửi KH (chỉ hiển thị)
        m["nii_lk_pct"] = pct(v.get("loi_nhuan_gop_luy_ke"), v.get("loi_nhuan_gop_cung_ky_luy_ke"))
        m["vcsh_vs_ts"] = (None if m["vcsh_pct"] is None or m["ts_pct"] is None else m["vcsh_pct"] - m["ts_pct"])
    elif kind == "chung_khoan":
        mg, lv, fv = v.get("ck_dt_moi_gioi_luy_ke"), v.get("ck_lai_cho_vay_luy_ke"), v.get("ck_lai_fvtpl_luy_ke")
        m["bien_lnst"] = ratio(lk, dt_lk)
        m["ty_trong_on_dinh"] = ratio((mg or 0) + (lv or 0), dt_lk) if mg is not None and lv is not None else None
        m["ty_trong_fvtpl"] = ratio(fv, dt_lk)
        m["cho_vay"], m["cho_vay_truoc"] = v.get("ck_cho_vay"), v.get("ck_cho_vay_dau_nam")
        m["cho_vay_pct"] = pct(m["cho_vay"], m["cho_vay_truoc"])
        m["margin_vcsh"] = ratio(m["cho_vay"], m["vcsh"])
        m["no_vcsh_ck"] = ratio(m["no"], m["vcsh"])
    elif kind == "bao_hiem":
        phi, phi_t = v.get("bh_phi_thuan_luy_ke"), v.get("bh_phi_thuan_cung_ky_luy_ke")
        bt, bt_t = _abs(v.get("bh_boi_thuong_thuan_luy_ke")), _abs(v.get("bh_boi_thuong_thuan_cung_ky_luy_ke"))
        ckd, qldn = _abs(v.get("bh_chi_phi_kdbh_luy_ke")), _abs(v.get("bh_chi_phi_qldn_luy_ke"))
        ckd_t, qldn_t = _abs(v.get("bh_chi_phi_kdbh_cung_ky_luy_ke")), _abs(v.get("bh_chi_phi_qldn_cung_ky_luy_ke"))
        dtbh_t = v.get("doanh_thu_thuan_cung_ky_luy_ke")
        m["phi_thuan"], m["phi_thuan_pct"] = phi, pct(phi, phi_t)
        # VCSH / biên KNTT tối thiểu (25% phí giữ lại, NĐ 73/2016 Điều 64), phí giữ lại ≈ phí thuần quy năm
        m["vcsh_bknt"] = ratio(m["vcsh"], 0.25 * phi * k) if phi else None
        m["combined"] = ratio(ckd + qldn, dt_lk) if ckd is not None and qldn is not None else None
        m["combined_truoc"] = ratio(ckd_t + qldn_t, dtbh_t) if ckd_t is not None and qldn_t is not None else None
        m["loss_ratio"], m["loss_ratio_truoc"] = ratio(bt, phi), ratio(bt_t, phi_t)
        dt0, dt1 = v.get("bh_dau_tu_dau_nam"), v.get("bh_dau_tu")
        ln_tc = v.get("bh_ln_hdtc_luy_ke")
        m["dau_tu"], m["dau_tu_truoc"] = dt1, dt0
        m["loi_suat_dau_tu"] = (ln_tc * k / avg(dt1, dt0)) if ln_tc is not None and avg(dt1, dt0) else None
        m["ln_hdtc_pct"] = pct(ln_tc, v.get("bh_ln_hdtc_cung_ky_luy_ke"))
        m["du_phong_nv"], m["du_phong_nv_truoc"] = v.get("bh_du_phong_nv"), v.get("bh_du_phong_nv_dau_nam")
        m["du_phong_nv_pct"] = pct(m["du_phong_nv"], m["du_phong_nv_truoc"])
    return m


CARD_FIELDS = ["doanh_thu_thuan", "loi_nhuan_gop", "lnst", "tong_tai_san", "no_phai_tra", "vay_no", "von_chu_so_huu",
               "lctt_hdkd"]
_BS = {"tong_tai_san", "no_phai_tra", "vay_no", "von_chu_so_huu"}


def tu_bctc(v: dict, kind: str, quy: int) -> dict:
    """Số đã chuẩn hoá của 1 BCTC (phan_tich.normalize()["v"]) -> chỉ số: năm nay so với kỳ so sánh trong cùng báo cáo."""
    cur = {f: v.get(f) for f in CARD_FIELDS}
    cur["lnst_lk"] = v.get("lnst_luy_ke")
    cmp = {f: v.get(f + ("_dau_nam" if f in _BS else "_cung_ky")) for f in CARD_FIELDS}
    cmp["lnst_lk"] = v.get("lnst_cung_ky_luy_ke")
    return metrics(cur, cmp, kind, quy, v)


# ------------------------------------------------------------------ bộ tiêu chí (dữ liệu dùng chung: chấm điểm + tài liệu)
# kieu: "tang" (tăng trưởng, chuyển lỗ -> lãi được điểm tối đa), "ge" (giá trị >= ngưỡng), "le" (giá trị <= ngưỡng),
#       "gt0" (> 0), "ge_truoc" (>= kỳ so sánh), "le_truoc" (<= kỳ so sánh), "cfo_ge_lnst", "tien_lai" (dòng tiền ≥ LNST)
# bac: [(ngưỡng, điểm)...] xếp từ mức cao nhất; fmt: cách hiện giá trị ("pct", "pct_dau", "x", "ty")
TIEU_CHI = {
    "doanh_nghiep": [
        dict(nhom="Tăng trưởng", ma="G1", ten="Doanh thu thuần tăng so với cùng kỳ (≥20%: 2đ)", chi_so="dt_pct",
             kieu="tang", bac=[(0.20, 2), (0, 1)], toi_da=2, goc=("dt_truoc", "dt"),
             cong_thuc="(DT thuần quý này − DT thuần cùng quý năm trước) / |DT cùng kỳ|",
             ly_do="Tăng trưởng doanh thu là tín hiệu đầu tiên về sức cầu; ngưỡng 20% phân biệt tăng trưởng mạnh.", nguon=["piotroski"]),
        dict(nhom="Tăng trưởng", ma="G2", ten="LNST quý tăng so với cùng kỳ (≥20%: 2đ)", chi_so="lnst_pct", kieu="tang",
             bac=[(0.20, 2), (0, 1)], toi_da=2, goc=("lnst_truoc", "lnst"),
             cong_thuc="(LNST quý − LNST cùng quý năm trước) / |LNST cùng kỳ|; lỗ → lãi = tối đa",
             ly_do="Lợi nhuận tăng (ΔROA > 0) là 1 trong 9 tín hiệu F-score.", nguon=["piotroski"]),
        dict(nhom="Lợi nhuận", ma="P1", ten="LNST lũy kế từ đầu năm tăng so với cùng kỳ", chi_so="lnst_lk_pct", kieu="gt0",
             toi_da=1, cong_thuc="LNST lũy kế năm nay − cùng kỳ năm trước > 0",
             ly_do="Lũy kế làm mượt biến động một quý.", nguon=["piotroski"]),
        dict(nhom="Hiệu quả hoạt động", ma="E1", ten="Biên lợi nhuận gộp cải thiện so với cùng kỳ", chi_so="bien_gop",
             kieu="gt_truoc", so_sanh="bien_gop_truoc", toi_da=1, cong_thuc="LN gộp / DT thuần quý này > cùng quý năm trước",
             ly_do="Tín hiệu F-score ΔMargin: biên gộp cải thiện cho thấy sức định giá hoặc chi phí đầu vào tốt hơn.", nguon=["piotroski"]),
        dict(nhom="Dòng tiền", ma="CF1", ten="Dòng tiền kinh doanh lũy kế dương", chi_so="cfo", kieu="gt0", toi_da=1,
             cong_thuc="LCTT thuần từ HĐKD lũy kế > 0", ly_do="Tín hiệu F-score CFO > 0.", nguon=["piotroski"]),
        dict(nhom="Dòng tiền", ma="CF2", ten="Lợi nhuận ra tiền: LCTT kinh doanh lũy kế ≥ LNST lũy kế", chi_so="cfo",
             kieu="tien_lai", toi_da=1, cong_thuc="LCTT HĐKD lũy kế ≥ LNST lũy kế (và LNST > 0)",
             ly_do="Tín hiệu F-score Accrual: lợi nhuận đi kèm tiền thật, ít dồn tích.", nguon=["piotroski"]),
        dict(nhom="Đòn bẩy & vốn", ma="L1", ten="Đòn bẩy (Nợ vay/VCSH) không tăng so với đầu năm", chi_so="no_vcsh",
             kieu="le_truoc", so_sanh="no_vcsh_truoc", toi_da=1,
             cong_thuc="Nợ vay/VCSH cuối quý ≤ đầu năm (thiếu nợ vay: Nợ phải trả/VCSH)",
             ly_do="Tín hiệu F-score ΔLeverage: đòn bẩy giảm là dấu hiệu tài chính lành mạnh hơn.", nguon=["piotroski"]),
        dict(nhom="Đòn bẩy & vốn", ma="C1", ten="Vốn chủ sở hữu tăng so với đầu năm", chi_so="vcsh_pct", kieu="gt0", toi_da=1,
             cong_thuc="VCSH cuối quý > VCSH đầu năm", ly_do="Vốn tích luỹ từ lợi nhuận giữ lại.", nguon=["piotroski"]),
    ],
    "ngan_hang": [
        dict(nhom="C – Vốn", ma="C1", ten="VCSH / Tổng tài sản ≥ 8%", chi_so="vcsh_ts", kieu="ge", bac=[(0.08, 1), (0.06, 0.5)],
             toi_da=1, fmt="pct", cong_thuc="Vốn chủ sở hữu / Tổng tài sản cuối quý (≥8%: 1đ; ≥6%: 0,5đ)",
             ly_do="Đại diện cho tỷ lệ an toàn vốn (CAR ≥8% theo TT 41/2016 và TT 14/2025, không có trong BCTC quý). "
                   "Basel III yêu cầu tỷ lệ đòn bẩy ≥3% (vốn cấp 1/tổng tài sản đòn bẩy); VCSH/TS ≥8% là đệm vốn dày.",
             nguon=["camels", "imf_fsi", "basel3_lev", "car_vn"]),
        dict(nhom="C – Vốn", ma="C2", ten="Vốn tăng không chậm hơn tài sản (so với đầu năm)", chi_so="vcsh_vs_ts", kieu="ge",
             bac=[(0, 0.5)], toi_da=0.5, fmt="pp", cong_thuc="Tăng trưởng VCSH − tăng trưởng Tổng TS (so đầu năm) ≥ 0",
             ly_do="Tài sản (chủ yếu tín dụng) tăng nhanh hơn vốn làm mỏng đệm vốn.", nguon=["camels"]),
        dict(nhom="A – Chất lượng tài sản", ma="A1", ten="Chi phí tín dụng quy năm ≤ 1%", chi_so="chi_phi_tin_dung", kieu="le",
             bac=[(0.010, 1), (0.015, 0.5)], toi_da=1, fmt="pct",
             cong_thuc="Chi phí dự phòng rủi ro tín dụng lũy kế × 4/số quý / Dư nợ cho vay KH bình quân (≤1%: 1đ; ≤1,5%: 0,5đ)",
             ly_do="Phản ánh nợ xấu phát sinh mới (tỷ lệ nợ xấu chỉ có trong thuyết minh, mục tiêu toàn hệ thống < 3% "
                   "theo QĐ 689/QĐ-TTg); chi phí tín dụng cao báo hiệu chất lượng tài sản xấu đi.",
             nguon=["camels", "imf_fsi", "npl_vn"]),
        dict(nhom="A – Chất lượng tài sản", ma="A2", ten="Bộ đệm dự phòng (Dự phòng/Dư nợ) không mỏng đi so với đầu năm",
             chi_so="llr", kieu="ge_truoc", so_sanh="llr_truoc", toi_da=1, fmt="pct",
             cong_thuc="Dự phòng rủi ro cho vay KH / Dư nợ cho vay KH cuối quý ≥ đầu năm",
             ly_do="Ngân hàng giảm trích lập để làm đẹp lợi nhuận sẽ làm tỷ lệ này giảm.", nguon=["camels", "imf_fsi"]),
        dict(nhom="E – Hiệu quả", ma="E1", ten="ROE quy năm ≥ 18%", chi_so="roe", kieu="ge", bac=[(0.18, 1), (0.14, 0.5)],
             toi_da=1, fmt="pct", cong_thuc="LNST lũy kế × 4/số quý / VCSH bình quân (≥18%: 1đ; ≥14%: 0,5đ)",
             ly_do="Chỉ tiêu lợi nhuận cốt lõi của IMF FSI và CAMELS (Earnings). So với nhóm ngân hàng niêm yết (cách giám sát "
                   "CAMELS vẫn làm): 1đ ≈ nửa trên (trung vị Q2/2026 17,6%), 0,5đ ≈ trên phân vị 25% (14,7%).",
             nguon=["camels", "imf_fsi"]),
        dict(nhom="E – Hiệu quả", ma="E2", ten="ROA quy năm ≥ 1,8%", chi_so="roa", kieu="ge", bac=[(0.018, 1), (0.012, 0.5)],
             toi_da=1, fmt="pct", cong_thuc="LNST lũy kế × 4/số quý / Tổng TS bình quân (≥1,8%: 1đ; ≥1,2%: 0,5đ)",
             ly_do="ROA không bị phóng đại bởi đòn bẩy như ROE. 1đ ≈ nhóm dẫn đầu (phân vị 75% Q2/2026: 2,0%), 0,5đ ≈ trên "
                   "phân vị 25% (1,1%).", nguon=["camels", "imf_fsi"]),
        dict(nhom="E – Hiệu quả", ma="E3", ten="Tỷ lệ chi phí/thu nhập (CIR) ≤ 30%", chi_so="cir", kieu="le",
             bac=[(0.30, 1), (0.35, 0.5)], toi_da=1, fmt="pct",
             cong_thuc="Chi phí hoạt động lũy kế / Tổng thu nhập hoạt động lũy kế (≤30%: 1đ; ≤35%: 0,5đ)",
             ly_do="IMF FSI: chi phí ngoài lãi / tổng thu nhập. CIR bình quân ngân hàng Việt Nam 34,7% (World Bank, 2021): "
                   "≤35%: ngang mặt bằng (0,5đ); ≤30%: tốt hơn rõ rệt (1đ).", nguon=["imf_fsi", "cir_wb"]),
        dict(nhom="E – Hiệu quả", ma="E4", ten="Thu nhập lãi thuần lũy kế tăng so với cùng kỳ", chi_so="nii_lk_pct", kieu="gt0",
             toi_da=0.5, cong_thuc="Thu nhập lãi thuần lũy kế năm nay > cùng kỳ năm trước",
             ly_do="Nguồn thu cốt lõi của ngân hàng (IMF FSI: thu nhập lãi / tổng thu nhập).", nguon=["imf_fsi"]),
        dict(nhom="L – Thanh khoản", ma="L1", ten="Cho vay / Vốn huy động (LDR) ≤ 95%", chi_so="ldr", kieu="le",
             bac=[(0.95, 1), (1.0, 0.5)], toi_da=1, fmt="pct",
             cong_thuc="Dư nợ cho vay KH / (Tiền gửi của KH + Phát hành giấy tờ có giá) cuối quý (≤95%: 1đ; ≤100%: 0,5đ)",
             ly_do="Trần pháp lý 85% (TT 22/2019/TT-NHNN), từ 01/12/2026 là 95% theo cách tính mới (TT 50/2026). Mẫu số pháp "
                   "lý rộng hơn số trên BCTC (còn gồm vốn vay, một phần tiền gửi Kho bạc...) nên tỷ lệ tính từ BCTC luôn cao "
                   "hơn: lấy 95% làm mức 1đ, 100% (cho vay không vượt vốn huy động) làm mức 0,5đ.", nguon=["camels", "ldr_vn"]),
        dict(nhom="Tăng trưởng", ma="G1", ten="Tổng thu nhập hoạt động quý tăng so với cùng quý năm trước", chi_so="dt_pct",
             kieu="tang", bac=[(0.15, 1), (0, 0.5)], toi_da=1, goc=("dt_truoc", "dt"),
             cong_thuc="Tăng > 0: 0,5đ; tăng ≥15%: 1đ", ly_do="Ngân hàng tăng 15%/năm đã là mạnh (tăng trưởng tín dụng bị NHNN giao hạn mức).",
             nguon=["camels"]),
        dict(nhom="Tăng trưởng", ma="G2", ten="LNST quý tăng so với cùng quý năm trước", chi_so="lnst_pct", kieu="tang",
             bac=[(0.15, 1), (0, 0.5)], toi_da=1, goc=("lnst_truoc", "lnst"),
             cong_thuc="Tăng > 0: 0,5đ; tăng ≥15% hoặc lỗ → lãi: 1đ", ly_do="Đo hướng đi của lợi nhuận.", nguon=["camels"]),
    ],
    "chung_khoan": [
        dict(nhom="Hiệu quả", ma="E1", ten="ROE quy năm", chi_so="roe", kieu="ge", bac=[(0.15, 1.5), (0.10, 1), (0, 0.5)],
             toi_da=1.5, fmt="pct", cong_thuc="LNST lũy kế × 4/số quý / VCSH bình quân (≥15%: 1,5đ; ≥10%: 1đ; >0: 0,5đ)",
             ly_do="Hiệu quả sử dụng vốn - thước đo chính với CTCK vì vốn là \"nguyên liệu\" của cho vay ký quỹ và tự doanh.",
             nguon=["imf_fsi"]),
        dict(nhom="Hiệu quả", ma="E2", ten="Biên LNST trên doanh thu hoạt động", chi_so="bien_lnst", kieu="ge",
             bac=[(0.30, 1.5), (0.20, 1), (0, 0.5)], toi_da=1.5, fmt="pct",
             cong_thuc="LNST lũy kế / Cộng doanh thu hoạt động lũy kế (≥30%: 1,5đ; ≥20%: 1đ; >0: 0,5đ)",
             ly_do="Đo khả năng giữ lại lợi nhuận sau chi phí hoạt động, lãi vay và quản lý.", nguon=["imf_fsi"]),
        dict(nhom="Tăng trưởng", ma="G1", ten="Doanh thu hoạt động quý tăng so với cùng quý năm trước", chi_so="dt_pct",
             kieu="tang", bac=[(0.20, 1), (0, 0.5)], toi_da=1, goc=("dt_truoc", "dt"), cong_thuc="Tăng > 0: 0,5đ; ≥20%: 1đ",
             ly_do="Doanh thu CTCK biến động theo thanh khoản thị trường.", nguon=[]),
        dict(nhom="Tăng trưởng", ma="G2", ten="LNST quý tăng so với cùng quý năm trước", chi_so="lnst_pct", kieu="tang",
             bac=[(0.20, 1), (0, 0.5)], toi_da=1, goc=("lnst_truoc", "lnst"), cong_thuc="Tăng > 0: 0,5đ; ≥20% hoặc lỗ → lãi: 1đ",
             ly_do="Hướng đi của lợi nhuận.", nguon=[]),
        dict(nhom="Chất lượng thu nhập", ma="Q1", ten="Thu nhập ổn định (môi giới + lãi cho vay) chiếm ≥ 50% doanh thu",
             chi_so="ty_trong_on_dinh", kieu="ge", bac=[(0.50, 1), (0.35, 0.5)], toi_da=1, fmt="pct",
             cong_thuc="(DT môi giới + Lãi từ các khoản cho vay và phải thu) lũy kế / Cộng DT hoạt động lũy kế",
             ly_do="Lãi tự doanh (FVTPL) phụ thuộc giá thị trường và dễ đảo chiều; thu nhập phí và lãi cho vay bền hơn.",
             nguon=["iosco"]),
        dict(nhom="Chất lượng thu nhập", ma="Q2", ten="LNST lũy kế từ đầu năm tăng so với cùng kỳ", chi_so="lnst_lk_pct",
             kieu="gt0", toi_da=1, cong_thuc="LNST lũy kế năm nay > cùng kỳ", ly_do="Làm mượt biến động một quý.", nguon=[]),
        dict(nhom="Đòn bẩy & rủi ro", ma="L1", ten="Nợ phải trả / VCSH ≤ 2 lần", chi_so="no_vcsh_ck", kieu="le",
             bac=[(2.0, 1), (3.0, 0.5)], toi_da=1, fmt="x",
             cong_thuc="Tổng nợ phải trả / VCSH cuối quý (≤2x: 1đ; ≤3x: 0,5đ); trần pháp lý 5 lần",
             ly_do="Còn khoảng cách an toàn lớn so với trần tổng nợ ≤ 5 lần VCSH (Điều 26 TT 121/2020/TT-BTC).",
             nguon=["ck_no_vn", "iosco"]),
        dict(nhom="Đòn bẩy & rủi ro", ma="L2", ten="Dư nợ cho vay (ký quỹ) / VCSH ≤ 100%", chi_so="margin_vcsh", kieu="le",
             bac=[(1.0, 1), (1.5, 0.5)], toi_da=1, fmt="pct",
             cong_thuc="Các khoản cho vay cuối quý / VCSH (≤100%: 1đ; ≤150%: 0,5đ); trần pháp lý 200%",
             ly_do="Trần pháp lý: tổng dư nợ ký quỹ ≤ 200% VCSH (Điều 9 Quy chế kèm QĐ 87/QĐ-UBCK). Cho vay sát trần làm "
                   "tăng rủi ro khi thị trường giảm mạnh (bán giải chấp dây chuyền).", nguon=["margin_vn"]),
        dict(nhom="Vốn", ma="C1", ten="Vốn chủ sở hữu tăng so với đầu năm", chi_so="vcsh_pct", kieu="gt0", toi_da=1,
             cong_thuc="VCSH cuối quý > đầu năm", ly_do="Vốn quyết định hạn mức cho vay ký quỹ (≤200% VCSH) và tỷ lệ vốn khả dụng (≥180%, TT 91/2020).",
             nguon=["vkd_vn"]),
    ],
    "bao_hiem": [
        dict(nhom="Nghiệp vụ bảo hiểm", ma="U1", ten="Tỷ lệ kết hợp (combined ratio) < 100%", chi_so="combined", kieu="lt",
             bac=[(0.95, 2), (1.0, 1)], toi_da=2, fmt="pct",
             cong_thuc="(Tổng chi phí HĐKD bảo hiểm + Chi phí quản lý DN) lũy kế / DT thuần HĐKD bảo hiểm lũy kế (<95%: 2đ; <100%: 1đ)",
             ly_do="Dưới 100% là có lãi từ chính nghiệp vụ bảo hiểm, không phải trông vào đầu tư.", nguon=["combined", "caramels"]),
        dict(nhom="Nghiệp vụ bảo hiểm", ma="U2", ten="Tỷ lệ bồi thường không tăng so với cùng kỳ", chi_so="loss_ratio",
             kieu="le_truoc", so_sanh="loss_ratio_truoc", toi_da=1, fmt="pct",
             cong_thuc="Tổng chi bồi thường bảo hiểm (mã 15) / Doanh thu phí bảo hiểm thuần (lũy kế) ≤ cùng kỳ",
             ly_do="Chất lượng chọn lọc rủi ro (underwriting) và giá phí; bồi thường tính theo phát sinh (gồm thay đổi dự "
                   "phòng bồi thường) như định nghĩa của IMF.", nguon=["caramels", "combined"]),
        dict(nhom="Đầu tư", ma="A1", ten="Lợi suất đầu tư quy năm ≥ 6%", chi_so="loi_suat_dau_tu", kieu="ge",
             bac=[(0.06, 1), (0.04, 0.5)], toi_da=1, fmt="pct",
             cong_thuc="LN hoạt động tài chính lũy kế × 4/số quý / Đầu tư tài chính bình quân (≥6%: 1đ; ≥4%: 0,5đ)",
             ly_do="Doanh nghiệp bảo hiểm VN đầu tư chủ yếu tiền gửi và trái phiếu; lợi suất thấp hơn lãi tiền gửi là kém.",
             nguon=["caramels"]),
        dict(nhom="Đầu tư", ma="A2", ten="Lợi nhuận hoạt động tài chính lũy kế tăng so với cùng kỳ", chi_so="ln_hdtc_pct",
             kieu="gt0", toi_da=1, cong_thuc="LN HĐTC lũy kế > cùng kỳ", ly_do="Thu nhập đầu tư là trụ cột lợi nhuận thứ hai.",
             nguon=["caramels"]),
        dict(nhom="Hiệu quả", ma="E1", ten="ROE quy năm ≥ 12%", chi_so="roe", kieu="ge", bac=[(0.12, 1), (0.08, 0.5)],
             toi_da=1, fmt="pct", cong_thuc="LNST lũy kế × 4/số quý / VCSH bình quân (≥12%: 1đ; ≥8%: 0,5đ)",
             ly_do="Chỉ tiêu Earnings trong CARAMELS.", nguon=["caramels"]),
        dict(nhom="Hiệu quả", ma="E2", ten="LNST lũy kế từ đầu năm tăng so với cùng kỳ", chi_so="lnst_lk_pct", kieu="gt0",
             toi_da=1, cong_thuc="LNST lũy kế năm nay > cùng kỳ", ly_do="Hướng đi của lợi nhuận.", nguon=["caramels"]),
        dict(nhom="Tăng trưởng", ma="G1", ten="Doanh thu phí bảo hiểm thuần lũy kế tăng", chi_so="phi_thuan_pct", kieu="tang",
             bac=[(0.10, 1), (0, 0.5)], toi_da=1, cong_thuc="Tăng > 0: 0,5đ; ≥10%: 1đ",
             ly_do="Thị phần và quy mô nghiệp vụ.", nguon=[]),
        dict(nhom="Tăng trưởng", ma="G2", ten="LNST quý tăng so với cùng quý năm trước", chi_so="lnst_pct", kieu="tang",
             bac=[(0, 0.5)], toi_da=0.5, goc=("lnst_truoc", "lnst"), cong_thuc="Tăng > 0 hoặc lỗ → lãi: 0,5đ",
             ly_do="Hướng đi lợi nhuận quý.", nguon=[]),
        dict(nhom="Vốn & dự phòng", ma="C1", ten="Vốn chủ sở hữu ≥ 2 lần biên khả năng thanh toán tối thiểu", chi_so="vcsh_bknt",
             kieu="ge", bac=[(2.0, 0.5)], toi_da=0.5, fmt="x",
             cong_thuc="VCSH cuối quý / (25% × phí bảo hiểm thuần lũy kế × 4/số quý) ≥ 2 lần",
             ly_do="Biên KNTT tối thiểu của bảo hiểm phi nhân thọ = 25% phí giữ lại (NĐ 73/2016, Điều 64); CARAMELS dùng tỷ lệ "
                   "phí thuần/vốn. Biên thực tế bằng VCSH trừ tài sản bị loại trừ, nên đòi VCSH ≥ 2 lần mức tối thiểu để còn đệm.",
             nguon=["bknt_bh", "caramels"]),
        dict(nhom="Vốn & dự phòng", ma="C2", ten="Vốn chủ sở hữu tăng so với đầu năm", chi_so="vcsh_pct", kieu="gt0",
             toi_da=0.5, cong_thuc="VCSH cuối quý > đầu năm", ly_do="Vốn làm đệm cho nghĩa vụ bảo hiểm.", nguon=["bh_vn"]),
        dict(nhom="Vốn & dự phòng", ma="R1", ten="Dự phòng nghiệp vụ không giảm so với đầu năm", chi_so="du_phong_nv_pct",
             kieu="ge", bac=[(0, 0.5)], toi_da=0.5, fmt="pct_dau",
             cong_thuc="Dự phòng nghiệp vụ cuối quý ≥ đầu năm",
             ly_do="Chữ R (Reinsurance & actuarial) trong CARAMELS: dự phòng theo kịp quy mô trách nhiệm.", nguon=["caramels"]),
    ],
}


def _fmt(x, fmt: str | None) -> str:
    if x is None:
        return "-"
    if fmt == "x":
        return f"{x:.2f}x"
    if fmt == "pp":
        return f"{x * 100:+.1f} điểm %"
    if fmt == "pct":
        return f"{x:.1%}"
    if fmt == "pct_dau":
        return f"{x:+.1%} so đầu năm"
    if fmt == "ty":
        return f"{x:,.0f} tỷ"
    return f"{x:+.1%}"


def cham_1(tc: dict, m: dict) -> tuple:
    """1 tiêu chí -> (tên, điểm, tối đa, chi tiết)."""
    ten, mx, kieu, x = tc["ten"], tc["toi_da"], tc["kieu"], m.get(tc["chi_so"])
    if kieu == "tang":
        g = tc.get("goc")
        if g and m.get(g[0]) is not None and m.get(g[1]) is not None and m[g[0]] <= 0 < m[g[1]]:
            return (ten, mx, mx, "chuyển từ lỗ sang lãi")
        if x is None:
            return (ten, 0, mx, "thiếu dữ liệu")
        pts = next((p for nguong, p in tc["bac"] if (x >= nguong if nguong > 0 else x > nguong)), 0)
        return (ten, pts, mx, f"{x:+.1%}")
    if kieu == "tien_lai":
        lk = m["lnst_lk"] if m.get("lnst_lk") is not None else m.get("lnst")
        if x is None or lk is None:
            return (ten, 0, mx, "thiếu dữ liệu")
        return (ten, mx if lk > 0 and x >= lk else 0, mx, f"{x:,.0f} tỷ vs {lk:,.0f} tỷ")
    if x is None:
        return (ten, 0, mx, "thiếu dữ liệu")
    fmt = tc.get("fmt")
    if kieu in ("gt0",):
        return (ten, mx if x > 0 else 0, mx, _fmt(x, fmt or ("ty" if tc["chi_so"] == "cfo" else None)))
    if kieu in ("ge", "le", "lt"):
        op = {"ge": lambda a, b: a >= b, "le": lambda a, b: a <= b, "lt": lambda a, b: a < b}[kieu]
        pts = next((p for nguong, p in tc["bac"] if op(x, nguong)), 0)
        return (ten, pts, mx, _fmt(x, fmt))
    y = m.get(tc["so_sanh"])
    if y is None:
        return (ten, 0, mx, "thiếu dữ liệu")
    ok = {"ge_truoc": x >= y, "le_truoc": x <= y, "gt_truoc": x > y}[kieu]
    f = (lambda z: f"{z:.2f}x") if tc["chi_so"] == "no_vcsh" else (lambda z: f"{z:.1%}")
    return (ten, mx if ok else 0, mx, f"{f(x)} so với {f(y)}")


def score(m: dict, kind: str) -> dict:
    """-> {"diem": tổng /10, "xep_loai": ..., "tieu_chi": [(tên, điểm, tối đa, chi tiết)], "nhom": {nhóm: (điểm, tối đa)}}"""
    bo = TIEU_CHI.get(kind, TIEU_CHI["doanh_nghiep"])
    items = [cham_1(tc, m) for tc in bo]
    if kind == "doanh_nghiep":                                        # giữ đúng tên tiêu chí đòn bẩy theo số có sẵn
        items[6] = (f"Đòn bẩy ({m.get('don_bay_ten', 'Nợ vay/VCSH')}) không tăng so với đầu năm", *items[6][1:])
    total = round(sum(i[1] for i in items), 1)
    total = int(total) if total == int(total) else total
    missing = sum(i[2] for i in items if i[3] == "thiếu dữ liệu")
    nhom: dict = {}
    for tc, i in zip(bo, items):
        a, b = nhom.get(tc["nhom"], (0, 0))
        nhom[tc["nhom"]] = (a + i[1], b + i[2])
    return {"diem": total, "xep_loai": next(n for t, n in TIERS if total >= t), "thieu": missing,
            "tieu_chi": items, "nhom": nhom}


# ------------------------------------------------------------------ nguồn tham chiếu (khoá dùng trong TIEU_CHI[...]["nguon"])
# Đã kiểm chứng ngày 28-29/10/2026: văn bản gốc hoặc bản hợp nhất/bản dịch nguyên văn; xem docs/bao-cao-cham-diem.html.
NGUON = {
    "piotroski": dict(ten="Value Investing: The Use of Historical Financial Statement Information to Separate Winners from Losers",
                      tac_gia="Joseph D. Piotroski", nam=2000, noi="Journal of Accounting Research, 38 (Supplement), tr. 1-41",
                      url="https://doi.org/10.2307/2672906",
                      y="F-score: 9 tín hiệu nhị phân từ BCTC (lợi nhuận, dòng tiền, dồn tích, đòn bẩy, thanh khoản, biên gộp...)."),
    "camels": dict(ten="Uniform Financial Institutions Rating System (CAMELS)", tac_gia="FFIEC / Federal Reserve",
                   nam=1996, noi="Fed SR 96-38: FFIEC thông qua UFIRS 13/11/1979; bản sửa thêm chữ S hiệu lực 01/01/1997",
                   url="https://www.federalreserve.gov/boarddocs/srletters/1996/sr9638.htm",
                   y="Capital, Asset quality, Management, Earnings, Liquidity, Sensitivity to market risk."),
    "imf_fsi": dict(ten="Financial Soundness Indicators Compilation Guide 2019", tac_gia="IMF", nam=2019,
                    noi="Quỹ Tiền tệ Quốc tế, Chương 7 (tổ chức nhận tiền gửi)", url="https://www.imf.org/-/media/Files/Data/2019/2019-fsi-guide.ashx",
                    y="17 chỉ tiêu cốt lõi của tổ chức nhận tiền gửi: vốn cấp 1/tài sản, nợ xấu, dự phòng/nợ xấu, ROA, ROE, chi phí ngoài lãi/tổng thu nhập, thanh khoản."),
    "basel3_lev": dict(ten="Basel III leverage ratio framework and disclosure requirements", tac_gia="Basel Committee on Banking Supervision",
                       nam=2014, noi="BIS", url="https://www.bis.org/publ/bcbs270.htm",
                       y="Tỷ lệ đòn bẩy tối thiểu 3% = vốn cấp 1 / tổng tài sản đòn bẩy."),
    "car_vn": dict(ten="Thông tư 14/2025/TT-NHNN quy định tỷ lệ an toàn vốn đối với NHTM (thay dần TT 41/2016/TT-NHNN)",
                   tac_gia="Ngân hàng Nhà nước", nam=2025, noi="Ban hành 30/6/2025, hiệu lực 15/9/2025",
                   url="https://luatvietnam.vn/tai-chinh/thong-tu-14-2025-tt-nhnn-cua-ngan-hang-nha-nuoc-viet-nam-quy-dinh-ty-le-an-toan-von-doi-voi-ngan-hang-thuong-mai-chi-nhanh-ngan-hang-nuoc-ngoai-405700-d1.html",
                   y="CET1 ≥4,5%, vốn cấp 1 ≥6%, CAR ≥8%, cộng bộ đệm bảo toàn vốn tăng dần tới 2,5%; TT 41/2016 áp dụng chuyển tiếp đến hết 2029."),
    "ldr_vn": dict(ten="Thông tư 22/2019/TT-NHNN về giới hạn, tỷ lệ bảo đảm an toàn (VBHN 114/2026/VBHN-NHNN)",
                   tac_gia="Ngân hàng Nhà nước", nam=2019, noi="Điều 20; sửa bởi TT 26/2022, 09/2024, 25/2026, 50/2026",
                   url="https://datafiles.chinhphu.vn/cpp/files/vbpq/2026/10/114-vbhn-nhnn.signed.pdf",
                   y="Tỷ lệ dư nợ cho vay so với tổng tiền gửi tối đa 85% với NHTM; TT 50/2026 (hiệu lực 01/12/2026) đổi cách tính, trần 95%."),
    "npl_vn": dict(ten="Quyết định 689/QĐ-TTg phê duyệt Đề án cơ cấu lại hệ thống TCTD gắn với xử lý nợ xấu 2021-2025",
                   tac_gia="Thủ tướng Chính phủ", nam=2022, noi="Ban hành 08/6/2022",
                   url="https://datafiles.chinhphu.vn/cpp/files/vbpq/2022/06/689-ttg.signed.pdf",
                   y="Mục tiêu nợ xấu (nội bảng + VAMC chưa xử lý + tiềm ẩn) dưới 3% đến cuối 2025."),
    "cir_wb": dict(ten="Global Financial Development Database: Bank cost to income ratio (%)", tac_gia="World Bank", nam=2022,
                   noi="Chỉ tiêu GFDD.EI.07", url="https://www.worldbank.org/en/publication/gfdr/data/global-financial-development-database",
                   y="Chi phí hoạt động / tổng thu nhập hoạt động; Việt Nam 48,3% (2017) giảm còn 34,7% (2021)."),
    "iosco": dict(ten="Objectives and Principles of Securities Regulation", tac_gia="IOSCO", nam=2017,
                  noi="Bản tháng 5/2017, Principle 30 về vốn của trung gian thị trường",
                  url="https://api.iosco.org/library/pubdocs/pdf/IOSCOPD561.pdf",
                  y="Trung gian thị trường phải duy trì vốn tương xứng với rủi ro; vốn là đệm cho khách hàng khi công ty gặp khó."),
    "ck_no_vn": dict(ten="Thông tư 121/2020/TT-BTC quy định về hoạt động của công ty chứng khoán", tac_gia="Bộ Tài chính", nam=2020,
                     noi="Điều 26 khoản 1; ban hành 31/12/2020, hiệu lực 15/02/2021",
                     url="https://english.luatvietnam.vn/circular-no-121-2020-tt-btc-dated-december-31-2020-of-the-ministry-of-finance-providing-regulations-on-operation-of-securities-companies-197224-doc1.html",
                     y="Tổng nợ của công ty chứng khoán không vượt quá 5 lần vốn chủ sở hữu."),
    "margin_vn": dict(ten="Quyết định 87/QĐ-UBCK ban hành Quy chế hướng dẫn giao dịch ký quỹ chứng khoán", tac_gia="Ủy ban Chứng khoán Nhà nước",
                      nam=2017, noi="Điều 9 khoản 1; sửa bởi QĐ 1205/QĐ-UBCK",
                      url="https://mbs.com.vn/files/uploads/2025/04/qd-87_2017_ubck-vv-ban-hanh-quy-che-huong-dan-giao-dich-ky-quy-ck.pdf",
                      y="Tổng dư nợ cho vay giao dịch ký quỹ không vượt quá 200% vốn chủ sở hữu."),
    "vkd_vn": dict(ten="Thông tư 91/2020/TT-BTC về chỉ tiêu an toàn tài chính của tổ chức kinh doanh chứng khoán", tac_gia="Bộ Tài chính",
                   nam=2020, noi="Sửa bởi TT 102/2025/TT-BTC (hiệu lực 15/12/2025)",
                   url="https://english.luatvietnam.vn/circular-no-91-2020-tt-btc-dated-november-13-2020-of-the-ministry-of-finance-prescribing-prudential-ratios-and-remedies-to-be-taken-by-securities-t-194994-doc1.html",
                   y="Tỷ lệ vốn khả dụng tối thiểu 180%; 150-180% bị cảnh báo, 120-150% bị kiểm soát, dưới 120% kiểm soát đặc biệt."),
    "combined": dict(ten="Financial Soundness Indicators Compilation Guide 2019: Combined ratio (bảo hiểm phi nhân thọ)", tac_gia="IMF",
                     nam=2019, noi="Chương 9 (công ty bảo hiểm)", url="https://www.imf.org/-/media/Files/Data/2019/2019-fsi-guide.ashx",
                     y="Combined ratio = (bồi thường phát sinh thuần + chi phí khai thác) / phí thực hưởng thuần; thị trường lành mạnh thì dưới 100%."),
    "caramels": dict(ten="Insurance and Issues in Financial Soundness (IMF Working Paper WP/03/138)",
                     tac_gia="Udaibir S. Das, Nigel Davies, Richard Podpiera", nam=2003, noi="Quỹ Tiền tệ Quốc tế, tháng 7/2003, Table 3",
                     url="https://www.imf.org/external/pubs/ft/wp/2003/wp03138.pdf",
                     y="Khung CARAMELS cho bảo hiểm: Capital, Asset quality, Reinsurance & actuarial, Management, Earnings, Liquidity, Sensitivity."),
    "bh_vn": dict(ten="Luật Kinh doanh bảo hiểm 08/2022/QH15 (sửa bởi Luật 139/2025/QH15) và Nghị định 46/2023/NĐ-CP",
                  tac_gia="Quốc hội; Chính phủ", nam=2022, noi="VBHN 31/VBHN-VPQH (2026)",
                  url="https://datafiles.chinhphu.vn/cpp/files/vbpq/2026/3/31-vbhn-vpqh.pdf",
                  y="Khả năng thanh toán = trích lập đủ dự phòng nghiệp vụ + biên khả năng thanh toán; khung vốn theo rủi ro lùi đến 2031."),
    "bknt_bh": dict(ten="Nghị định 73/2016/NĐ-CP, Điều 64 (biên khả năng thanh toán tối thiểu, còn hiệu lực đến hết 2027)",
                    tac_gia="Chính phủ", nam=2016, noi="Áp dụng song song NĐ 46/2023/NĐ-CP",
                    url="https://caselaw.vn/van-ban-phap-luat/116541-nghi-dinh-73-2016-nd-cp-huong-dan-luat-kinh-doanh-bao-hiem-va-luat-kinh-doanh-bao-hiem-sua-doi",
                    y="Biên KNTT tối thiểu của DNBH phi nhân thọ = max(25% tổng phí giữ lại; 12,5% phí gốc + phí nhận tái)."),
    "bctc_dn": dict(ten="Thông tư 99/2025/TT-BTC hướng dẫn Chế độ kế toán doanh nghiệp", tac_gia="Bộ Tài chính", nam=2025,
                    noi="Ban hành 27/10/2025, hiệu lực 01/01/2026, thay TT 200/2014", url="https://assets.kpmg.com/content/dam/kpmg/vn/pdf/2025/11/circular-99-vi.pdf",
                    y="Mẫu B01-DN (Báo cáo tình hình tài chính), B02-DN, B03-DN; TCTD theo chế độ riêng của NHNN."),
    "bctc_nh": dict(ten="Quyết định 16/2007/QĐ-NHNN về Chế độ BCTC đối với TCTD, sửa bởi TT 49/2014, TT 22/2017, TT 27/2021",
                    tac_gia="Ngân hàng Nhà nước", nam=2014, noi="Mẫu giữa niên độ B02a/TCTD, B03a/TCTD, B04a/TCTD",
                    url="https://caselaw.vn/van-ban-phap-luat/264126-thong-tu-49-2014-tt-nhnn-sua-doi-che-do-bao-cao-tai-chinh-doi-voi-to-chuc-tin-dung-kem-theo-quyet-dinh-16-2007-qd-nhnn-va-he-thong-tai-khoan-ke-toan-cac-to-chuc-tin-dung-kem-theo-quyet-dinh-479-2004-qd-nhnn-do-thong-doc-ngan-hang-nha-nuoc-ban-hanh",
                    y="BCTC ngân hàng không có doanh thu/giá vốn: thu nhập lãi thuần, tổng thu nhập hoạt động, chi phí dự phòng rủi ro tín dụng."),
    "bctc_ck": dict(ten="Thông tư 210/2014/TT-BTC hướng dẫn kế toán công ty chứng khoán, sửa bởi TT 334/2016/TT-BTC", tac_gia="Bộ Tài chính",
                    nam=2016, noi="Mẫu B01-CTCK, B02-CTCK, B03b-CTCK",
                    url="https://luatvietnam.vn/chung-khoan/thong-tu-334-2016-tt-btc-bo-tai-chinh-113702-d1.html",
                    y="Tài sản tài chính FVTPL/HTM/AFS, các khoản cho vay; doanh thu và chi phí trình bày theo từng nghiệp vụ."),
    "bctc_bh": dict(ten="Thông tư 232/2012/TT-BTC hướng dẫn kế toán doanh nghiệp bảo hiểm phi nhân thọ", tac_gia="Bộ Tài chính",
                    nam=2012, noi="Hiệu lực 01/01/2014; mẫu B01-DNPNT, B02-DNPNT",
                    url="https://luatvietnam.vn/ke-toan/thong-tu-232-2012-tt-btc-bo-tai-chinh-76949-d1.html",
                    y="KQKD 2 phần; doanh thu phí, nhượng tái, bồi thường, dự phòng nghiệp vụ; hoạt động tài chính tách riêng."),
}

assert all(abs(sum(tc["toi_da"] for tc in bo) - 10) < 1e-9 for bo in TIEU_CHI.values()), "mỗi bộ phải đủ 10 điểm"
assert all(k in NGUON for bo in TIEU_CHI.values() for tc in bo for k in tc["nguon"]), "nguồn chưa khai báo trong NGUON"

CRITERIA_DOC = {k: [(tc["ten"], tc["cong_thuc"]) for tc in bo] for k, bo in TIEU_CHI.items()}   # dashboard + README
