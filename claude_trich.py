#!/usr/bin/env python3
"""Trích số BCTC bằng Claude (thay Gemini khi chưa có GEMINI_API_KEY). Dùng sau `python phan_tich.py --dry-run`.

    python claude_trich.py ds                    # danh sách BCTC cần trích (mã, kỳ, PDF nhỏ, trang)
    python claude_trich.py chu VCB 2026 3        # chữ của các trang 3 báo cáo (lớp chữ gốc hoặc OCR)
    python claude_trich.py ghi VCB 2026 3 a.json # kiểm tra theo schema BCTC + cân đối, lưu ket_qua/json/

Kết quả lưu cùng định dạng cache của phan_tich.py (model = claude) -> `python phan_tich.py --tong-hop` chấm điểm + dựng web.
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

MODEL = "claude-opus-5-5"
DRY_LOG = pt.OUT / "debug" / "dry_run.log"


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
        for (y, q), rec in sorted(v.items(), reverse=True):
            done = pt.OUT / "json" / f"{tk}_{y}_Q{q}.json"
            ok = done.exists() and json.loads(done.read_text(encoding="utf-8")).get("sha256") == rec["sha256"]
            rows.append({"ma": tk, "nam": y, "quy": q, "scope": rec["scope"], "file": rec["path"],
                         "pdf_nho": str(pt.OUT / "debug" / f"{tk}_{y}_Q{q}.pdf"),
                         "trang": sent.get((tk, y, q)), "da_trich": ok})
    return rows


def text_of(tk: str, y: int, q: int) -> str:
    r = next((r for r in reports() if (r["ma"], r["nam"], r["quy"]) == (tk, y, q)), None)
    if not r:
        raise SystemExit(f"Không có BCTC {tk} Q{q}/{y} trong danh sách")
    pdf = pt.DATA / r["file"]
    have = pdf2txt.read_txt(pdf2txt.txt_path_for(pdf, pt.TXT, pt.DATA))
    out = [f"# {tk} Q{q}/{y} - BCTC {'hợp nhất' if r['scope'] == 'HN' else 'riêng/chung'} - file gốc {r['file']}",
           f"# PDF nhỏ (xem ảnh trang khi chữ OCR không rõ): {r['pdf_nho']}"]
    with pymupdf.open(pdf) as d:
        for i, p in enumerate(r["trang"] or [], 1):
            if p in have:
                how, txt = have[p]
            else:
                how, txt = "text", d[p - 1].get_text()
            out.append(f"\n=== Trang {i} của PDF nhỏ (trang {p} file gốc, đọc bằng {how}) ===\n{txt.strip()}")
    return "\n".join(out)


def save(tk: str, y: int, q: int, path: str) -> int:
    r = next((r for r in reports() if (r["ma"], r["nam"], r["quy"]) == (tk, y, q)), None)
    if not r:
        raise SystemExit(f"Không có BCTC {tk} Q{q}/{y} trong danh sách")
    data = pt.BCTC.model_validate_json(Path(path).read_text(encoding="utf-8")).model_dump()
    rec = next(x for x in json.loads((pt.DATA / "manifest.json").read_text(encoding="utf-8")).values()
               if x.get("path") == r["file"])
    res = {"ticker": tk, "ky": f"Q{q}/{y}", "file": r["file"], "sha256": rec["sha256"], "scope": r["scope"],
           "pages_sent": r["trang"] or [], "prompt_version": pt.PROMPT_VERSION, "model": MODEL,
           "extracted_at": datetime.now().isoformat(timespec="seconds"), "data": data}
    n = pt.normalize(res)
    out = pt.OUT / "json" / f"{tk}_{y}_Q{q}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    v = n["v"]
    print(f"Đã lưu {out.name} | DT {v['doanh_thu_thuan']} | LNST {v['lnst']} | TS {v['tong_tai_san']} | Nợ {v['no_phai_tra']}"
          f" | VCSH {v['von_chu_so_huu']} | LCTT KD {v['lctt_hdkd']} (tỷ đồng)")
    print("KIỂM TRA: " + ("OK - cân đối khớp" if not n["warn"] else "CẢNH BÁO: " + " | ".join(n["warn"])))
    return 0 if not n["warn"] else 1


def main(argv: list[str]) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if not argv or argv[0] == "ds":
        for r in reports():
            print(f"{r['ma']:4} Q{r['quy']}/{r['nam']} {r['scope']:5} trang={r['trang']} {'ĐÃ TRÍCH' if r['da_trich'] else ''}")
        return 0
    if argv[0] == "chu":
        print(text_of(argv[1].upper(), int(argv[2]), int(argv[3])))
        return 0
    if argv[0] == "ghi":
        return save(argv[1].upper(), int(argv[2]), int(argv[3]), argv[4])
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
