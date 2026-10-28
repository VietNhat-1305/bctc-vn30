#!/usr/bin/env python3
"""Trích số BCTC bằng Claude (thay Gemini khi chưa có GEMINI_API_KEY). Dùng sau `python phan_tich.py --dry-run`.
Mỗi mã chỉ 1 BCTC (quý mới nhất): báo cáo đã có sẵn cùng kỳ năm trước / số đầu năm để so sánh.

    python claude_trich.py ds                        # danh sách BCTC cần trích (mã, kỳ, trang)
    python claude_trich.py huong_dan [VCB FPT ...]   # hướng dẫn trích + sổ bài học (quy tắc + lưu ý các mã)
    python claude_trich.py chu VCB 2026 2            # chữ của các trang 3 báo cáo (lớp chữ gốc hoặc OCR)
    python claude_trich.py anh VCB 2026 2            # ảnh PNG từng trang -> ket_qua/debug/anh/ (xem bằng tool Read)
    python claude_trich.py ghi VCB 2026 2 a.json     # kiểm tra schema + cân đối, lưu ket_qua/json/
    python claude_trich.py ghi VCB 2026 2 - < a.json # như trên, đọc JSON từ stdin
    python claude_trich.py bo_sung VCB 2026 2 b.json # chỉ ghép khoản mục riêng loại hình (nh_*/ck_*/bh_*) vào kết quả đã có

Kết quả lưu cùng định dạng cache của phan_tich.py (model = claude) -> `python phan_tich.py --tong-hop` chấm điểm,
tự đối chiếu Vietcap và dựng web.
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime
from pathlib import Path

import pymupdf

import ocr_so
import pdf2txt
import phan_tich as pt
import tri_thuc

MODEL = "claude-opus-5-5"
DRY_LOG = pt.OUT / "debug" / "dry_run.log"
GUIDE = pt.ROOT / "tri_thuc" / "huong_dan_claude.md"


def pages_sent() -> dict[tuple[str, int, int], list[int]]:
    """Trang đã chọn ở bước dry-run (dòng '[dry] VCB Q3/2026: gửi trang [..]')."""
    out = {}
    if DRY_LOG.exists():
        for m in re.finditer(r"\[dry\] (\w+) Q(\d)/(\d{4}): gửi trang \[([\d, ]*)\]", DRY_LOG.read_text(encoding="utf-8")):
            out[(m[1], int(m[3]), int(m[2]))] = [int(x) for x in m[4].split(",") if x.strip()]
    return out


def reports() -> list[dict]:
    import dashboard
    tickers = [c["ticker"] for c in dashboard.all_companies()]      # 30 mã VN30 + mã bổ sung (BCTC scan)
    sent = pages_sent()
    rows = []
    for tk, v in sorted(pt.pick_reports(tickers).items()):
        for (y, q), rec in v.items():
            done = pt.OUT / "json" / f"{tk}_{y}_Q{q}.json"
            c = json.loads(done.read_text(encoding="utf-8")) if done.exists() else {}
            rows.append({"ma": tk, "nam": y, "quy": q, "scope": rec["scope"], "file": rec["path"], "sha256": rec["sha256"],
                         "pdf_nho": str(pt.OUT / "debug" / f"{tk}_{y}_Q{q}.pdf"), "trang": sent.get((tk, y, q)),
                         "da_trich": c.get("sha256") == rec["sha256"] and bool(c.get("data"))})
    return rows


def find(tk: str, y: int, q: int) -> dict:
    r = next((r for r in reports() if (r["ma"], r["nam"], r["quy"]) == (tk, y, q)), None)
    if not r:
        raise SystemExit(f"Không có BCTC {tk} Q{q}/{y} trong danh sách (chỉ trích quý mới nhất của mỗi mã)")
    return r


def text_of(tk: str, y: int, q: int) -> str:
    r = find(tk, y, q)
    pdf = pt.DATA / r["file"]
    txt = pdf2txt.txt_path_for(pdf, pt.TXT, pt.DATA)
    have = pdf2txt.read_txt(txt)
    scan = [p for p in r["trang"] or [] if p in have and have[p][0] != "text"]
    if scan and ocr_so.available():      # trang scan: lấy chữ PP-OCRv6 (số chính xác hơn Tesseract)
        have.update(ocr_so.pages(pdf, txt, scan, {p: pdf2txt.rot_of(have[p][0]) for p in scan}))
    out = [f"# {tk} Q{q}/{y} - BCTC {'hợp nhất' if r['scope'] == 'HN' else 'riêng/chung'} - file gốc {r['file']}",
           f"# Ảnh trang: python claude_trich.py anh {tk} {y} {q}"]
    notes = tri_thuc.luu_y_ma(tk)
    if notes:
        out.append("# Lưu ý riêng của mã (sổ bài học):\n" + "\n".join(f"#  - {x}" for x in notes))
    with pymupdf.open(pdf) as d:
        for i, p in enumerate(r["trang"] or [], 1):
            how, txt = have[p] if p in have else ("text", d[p - 1].get_text())
            out.append(f"\n=== Trang {i} của PDF nhỏ (trang {p} file gốc, đọc bằng {how}) ===\n{txt.strip()}")
    return "\n".join(out)


def render(tk: str, y: int, q: int, dpi: int = 150) -> list[Path]:
    """Ảnh PNG từng trang của PDF nhỏ - tên riêng theo mã/kỳ để nhiều agent chạy song song không ghi đè nhau."""
    r = find(tk, y, q)
    out_dir = pt.OUT / "debug" / "anh"
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    with pymupdf.open(r["pdf_nho"]) as d:
        for i, page in enumerate(d, 1):
            path = out_dir / f"{tk}_{y}_Q{q}_trang{i}.png"
            page.get_pixmap(dpi=dpi).save(str(path))
            paths.append(path)
    return paths


def guide(tickers: list[str]) -> str:
    out = [GUIDE.read_text(encoding="utf-8"), tri_thuc.quy_tac_text()]
    for tk in tickers:
        notes = tri_thuc.luu_y_ma(tk)
        if notes:
            out.append(f"\nLưu ý {tk}:\n" + "\n".join(f"- {x}" for x in notes))
    return "\n".join(out)


def save(tk: str, y: int, q: int, path: str) -> int:
    r = find(tk, y, q)
    raw = sys.stdin.read() if path == "-" else Path(path).read_text(encoding="utf-8")   # "-": JSON qua stdin (lịch quét chạy ngầm)
    data = pt.BCTC.model_validate_json(raw).model_dump()
    res = {"ticker": tk, "ky": f"Q{q}/{y}", "file": r["file"], "sha256": r["sha256"], "scope": r["scope"],
           "pages_sent": r["trang"] or [], "prompt_version": pt.prompt_version(), "model": MODEL,
           "extracted_at": datetime.now().isoformat(timespec="seconds"), "data": data}
    n = pt.normalize(res)
    out = pt.OUT / "json" / f"{tk}_{y}_Q{q}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    v = n["v"]
    f = lambda x: "-" if x is None else f"{x:,.1f}"  # noqa: E731
    print(f"Đã lưu {out.name} (tỷ đồng) | DT {f(v['doanh_thu_thuan'])} / cùng kỳ {f(v['doanh_thu_thuan_cung_ky'])}"
          f" | LNST {f(v['lnst'])} / cùng kỳ {f(v['lnst_cung_ky'])} | TS {f(v['tong_tai_san'])} / đầu năm {f(v['tong_tai_san_dau_nam'])}"
          f" | LCTT KD {f(v['lctt_hdkd'])} / cùng kỳ {f(v['lctt_hdkd_cung_ky'])}")
    if n["info"]:
        print("THÔNG TIN: " + " | ".join(n["info"]))
    print("KIỂM TRA: " + ("OK - cân đối khớp" if not n["warn"] else "CẢNH BÁO: " + " | ".join(n["warn"])))
    return 0 if not n["warn"] else 1


TIEN_TO = {"ngan_hang": "nh_", "chung_khoan": "ck_", "bao_hiem": "bh_"}
# Khoảng hợp lý của tỷ lệ: ra ngoài -> nhiều khả năng đọc nhầm dòng/cột/đơn vị, cần xem lại ảnh
KHOANG = {"ngan_hang": {"ldr": (0.4, 1.3), "cir": (0.1, 0.8), "chi_phi_tin_dung": (0, 0.06), "llr": (0.003, 0.08)},
          "chung_khoan": {"ty_trong_on_dinh": (0, 1.0), "margin_vcsh": (0, 2.5), "ty_trong_fvtpl": (-0.5, 1.0)},
          "bao_hiem": {"combined": (0.6, 1.4), "loss_ratio": (0.1, 1.2), "loi_suat_dau_tu": (0, 0.2)}}


def bo_sung(tk: str, y: int, q: int, path: str) -> int:
    """Ghép khoản mục riêng của loại hình (nh_*/ck_*/bh_*) vào kết quả trích đã có (đã kiểm), không đụng số cũ."""
    import cham_diem
    r = find(tk, y, q)
    out = pt.OUT / "json" / f"{tk}_{y}_Q{q}.json"
    if not out.exists():
        raise SystemExit("Chưa có kết quả trích chính của BCTC này: dùng lệnh ghi trước")
    res = json.loads(out.read_text(encoding="utf-8"))
    if res.get("sha256") != r["sha256"]:
        raise SystemExit("File BCTC đã đổi so với lần trích trước: trích lại toàn bộ bằng lệnh ghi")
    kind = res["data"]["loai_hinh"]
    tien_to = TIEN_TO.get(kind)
    if not tien_to:
        raise SystemExit(f"Loại hình {kind} không có khoản mục riêng")
    raw = sys.stdin.read() if path == "-" else Path(path).read_text(encoding="utf-8")
    moi = json.loads(raw)
    sai = [k for k in moi if k not in pt.RIENG or not k.startswith(tien_to)]
    if sai:
        raise SystemExit(f"Trường không hợp lệ cho {kind}: {sai}. Chỉ nhận: {[f for f in pt.RIENG if f.startswith(tien_to)]}")
    res["data"] = pt.BCTC.model_validate({**res["data"], **moi}).model_dump()
    res.update(prompt_version=pt.prompt_version(), bo_sung_at=datetime.now().isoformat(timespec="seconds"), bo_sung_model=MODEL)
    out.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    n = pt.normalize(res)
    m = cham_diem.tu_bctc(n["v"], kind, q)
    s = cham_diem.score(m, kind)
    thieu = [f for f in pt.RIENG if f.startswith(tien_to) and res["data"].get(f) is None]
    print(f"Đã bổ sung {out.name}: {len(moi)} trường | điểm mới {s['diem']}/10")
    for ten, diem, mx, ct in s["tieu_chi"]:
        print(f"  {diem}/{mx}  {ten}: {ct}")
    canh = [f"{k} = {m[k]:.1%} ngoài khoảng hợp lý {a:.0%}-{b:.0%}" for k, (a, b) in KHOANG[kind].items()
            if m.get(k) is not None and not a <= m[k] <= b]
    if thieu:
        print("CÒN THIẾU: " + ", ".join(thieu))
    print("KIỂM TRA: " + ("OK" if not canh else "CẢNH BÁO (xem lại ảnh): " + " | ".join(canh)))
    return 1 if canh else 0


def main(argv: list[str]) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if not argv or argv[0] == "ds":
        for r in reports():
            print(f"{r['ma']:4} Q{r['quy']}/{r['nam']} {r['scope']:5} trang={r['trang']} {'ĐÃ TRÍCH' if r['da_trich'] else ''}")
        return 0
    cmd = argv[0]
    if cmd == "huong_dan":
        print(guide([t.upper() for t in argv[1:]]))
        return 0
    if cmd == "chu":
        print(text_of(argv[1].upper(), int(argv[2]), int(argv[3])))
        return 0
    if cmd == "anh":
        for p in render(argv[1].upper(), int(argv[2]), int(argv[3])):
            print(p)
        return 0
    if cmd == "ghi":
        return save(argv[1].upper(), int(argv[2]), int(argv[3]), argv[4])
    if cmd == "bo_sung":
        return bo_sung(argv[1].upper(), int(argv[2]), int(argv[3]), argv[4])
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
