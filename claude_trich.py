#!/usr/bin/env python3
"""Trích số BCTC bằng Claude (thay Gemini khi chưa có GEMINI_API_KEY). Dùng sau `python phan_tich.py --dry-run`.
Mỗi mã chỉ 1 BCTC (quý mới nhất): báo cáo đã có sẵn cùng kỳ năm trước / số đầu năm để so sánh.

    python claude_trich.py ds                        # danh sách BCTC cần trích (mã, kỳ, trang)
    python claude_trich.py huong_dan [VCB FPT ...]   # hướng dẫn trích + sổ bài học (quy tắc + lưu ý các mã)
    python claude_trich.py chu VCB 2026 2            # chữ của các trang 3 báo cáo (lớp chữ gốc hoặc OCR)
    python claude_trich.py anh VCB 2026 2            # ảnh PNG từng trang -> ket_qua/debug/anh/ (xem bằng tool Read)
    python claude_trich.py ghi VCB 2026 2 a.json     # kiểm tra schema + cân đối, lưu ket_qua/json/
    python claude_trich.py ghi VCB 2026 2 - < a.json # như trên, đọc JSON từ stdin

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
    tickers = [c["ticker"] for c in json.loads((pt.ROOT / "companies.json").read_text(encoding="utf-8"))["companies"]]
    sent = pages_sent()
    rows = []
    for tk, v in sorted(pt.pick_reports(tickers).items()):
        for (y, q), rec in v.items():
            done = pt.OUT / "json" / f"{tk}_{y}_Q{q}.json"
            c = json.loads(done.read_text(encoding="utf-8")) if done.exists() else {}
            rows.append({"ma": tk, "nam": y, "quy": q, "scope": rec["scope"], "file": rec["path"], "sha256": rec["sha256"],
                         "pdf_nho": str(pt.OUT / "debug" / f"{tk}_{y}_Q{q}.pdf"), "trang": sent.get((tk, y, q)),
                         "da_trich": c.get("sha256") == rec["sha256"] and c.get("prompt_version") == pt.prompt_version()})
    return rows


def find(tk: str, y: int, q: int) -> dict:
    r = next((r for r in reports() if (r["ma"], r["nam"], r["quy"]) == (tk, y, q)), None)
    if not r:
        raise SystemExit(f"Không có BCTC {tk} Q{q}/{y} trong danh sách (chỉ trích quý mới nhất của mỗi mã)")
    return r


def text_of(tk: str, y: int, q: int) -> str:
    r = find(tk, y, q)
    pdf = pt.DATA / r["file"]
    have = pdf2txt.read_txt(pdf2txt.txt_path_for(pdf, pt.TXT, pt.DATA))
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
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
