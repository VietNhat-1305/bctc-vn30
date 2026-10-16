#!/usr/bin/env python3
"""Sổ bài học (tri_thuc/bai_hoc.json): luồng "học" từ các lần sai.

Mô hình (Gemini/Claude) không tự nhớ giữa các lần chạy, nên bài học được giữ ở đây và đưa vào prompt mỗi lần trích:
  quy_tac      - quy tắc chung rút ra từ lỗi đã gặp -> thêm vào system prompt
  theo_ma      - lưu ý riêng từng mã (mẫu báo cáo lạ, dòng không in, lỗi OCR hay gặp) -> thêm vào prompt BCTC của mã đó
  loi_da_gap   - nhật ký lỗi và cách sửa
  can_xem_xet  - doi_chieu.py tự ghi khi số đã trích lệch Vietcap > 1%; xét xong thì chuyển thành quy tắc / lưu ý

    python tri_thuc.py                              # xem sổ: quy tắc, lưu ý theo mã, việc cần xem xét
    python tri_thuc.py them-quy-tac "nội dung" [--tu "lỗi gốc"]
    python tri_thuc.py them-luu-y VCB "nội dung"
    python tri_thuc.py da-xet <số thứ tự|all> [--ket-luan "..."]   # đóng việc cần xem xét
"""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

PATH = Path(__file__).resolve().parent / "tri_thuc" / "bai_hoc.json"


def load() -> dict:
    if not PATH.exists():
        return {"phien_ban": 0, "quy_tac": [], "theo_ma": {}, "loi_da_gap": [], "can_xem_xet": []}
    return json.loads(PATH.read_text(encoding="utf-8"))


def save(d: dict) -> None:
    d["cap_nhat"] = date.today().isoformat()
    PATH.parent.mkdir(parents=True, exist_ok=True)
    PATH.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")


def phien_ban() -> int:
    return int(load().get("phien_ban", 0))


def quy_tac_text() -> str:
    """Khối 'bài học' gắn vào cuối system prompt."""
    rules = load().get("quy_tac", [])
    if not rules:
        return ""
    return ("\n\nBài học từ các lần trích trước (bắt buộc áp dụng):\n"
            + "\n".join(f"- [{r['id']}] {r['noi_dung']}" for r in rules))


def luu_y_ma(ticker: str) -> list[str]:
    return load().get("theo_ma", {}).get(ticker, [])


def them_can_xem_xet(items: list[dict]) -> int:
    """Ghi chỗ lệch nguồn ngoài cần xét (bỏ trùng theo mã + kỳ + chỉ tiêu + số của mình). -> số mục mới."""
    d = load()
    have = {(x["ma"], x["ky"], x["chi_tieu"], x.get("so_minh")) for x in d.setdefault("can_xem_xet", [])}
    new = [x for x in items if (x["ma"], x["ky"], x["chi_tieu"], x.get("so_minh")) not in have]
    if new:
        d["can_xem_xet"].extend({**x, "ngay": date.today().isoformat(), "trang_thai": "mo"} for x in new)
        save(d)
    return len(new)


def _arg(argv: list[str], flag: str) -> str | None:
    return argv[argv.index(flag) + 1] if flag in argv and argv.index(flag) + 1 < len(argv) else None


def main(argv: list[str]) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    d = load()
    if not argv:
        print(f"Sổ bài học phiên bản {d.get('phien_ban')} (cập nhật {d.get('cap_nhat')})\n\nQuy tắc:")
        for r in d.get("quy_tac", []):
            print(f"  [{r['id']}] {r['noi_dung']}")
        print(f"\nLưu ý theo mã: {len(d.get('theo_ma', {}))} mã")
        mo = [x for x in d.get("can_xem_xet", []) if x.get("trang_thai") == "mo"]
        print(f"\nCần xem xét ({len(mo)}):")
        for i, x in enumerate(d.get("can_xem_xet", []), 1):
            if x.get("trang_thai") == "mo":
                print(f"  {i}. {x['ma']} {x['ky']} {x['chi_tieu']}: mình {x.get('so_minh')} | {x.get('nguon')} {x.get('so_nguon')}"
                      f" ({x.get('chenh_lech_pct')}%) {x.get('goi_y', '')}")
        return 0
    cmd = argv[0]
    if cmd == "them-quy-tac":
        n = max([int(r["id"][1:]) for r in d.get("quy_tac", []) if r["id"][1:].isdigit()] or [0]) + 1
        d.setdefault("quy_tac", []).append({"id": f"R{n}", "tu": _arg(argv, "--tu") or "", "noi_dung": argv[1]})
        d["phien_ban"] = int(d.get("phien_ban", 0)) + 1          # quy tắc đổi -> Gemini trích lại theo quy tắc mới
        save(d)
        print(f"Đã thêm R{n}; sổ lên phiên bản {d['phien_ban']}")
        return 0
    if cmd == "them-luu-y":
        d.setdefault("theo_ma", {}).setdefault(argv[1].upper(), []).append(argv[2])
        save(d)
        print(f"Đã thêm lưu ý cho {argv[1].upper()}")
        return 0
    if cmd == "da-xet":
        items = d.get("can_xem_xet", [])
        idx = range(len(items)) if argv[1] == "all" else [int(argv[1]) - 1]
        for i in idx:
            items[i]["trang_thai"] = "da_xet"
            items[i]["ket_luan"] = _arg(argv, "--ket-luan") or items[i].get("ket_luan", "")
        save(d)
        print(f"Đã đóng {len(list(idx))} mục")
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
