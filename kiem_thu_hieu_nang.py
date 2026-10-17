#!/usr/bin/env python3
"""Kiểm thử hiệu năng luồng BCTC VN30 - số liệu cho báo cáo benchmark (kết quả: ket_qua/kiem_thu/).

    python kiem_thu_hieu_nang.py tai-lanh --lan 2          # Test chịu tải: 30 BCTC quý 2 xử lý ĐỒNG THỜI từ đầu
                                                           # (thư mục trống, bản sao dự án riêng), lặp 2 lần để so output
    python kiem_thu_hieu_nang.py mo-phong-moi VCB,HPG,MWG  # Test theo timeline: giả lập 3 BCTC "mới đăng" rồi chạy 1 lần quét
    python kiem_thu_hieu_nang.py so-sanh-trich VCB,HPG,MWG # độ lặp lại của AI: so kết quả trích lại với bản cũ

Tải lạnh đo: thời gian từng bước (đọc web + tải, tìm trang + OCR), số BCTC tải/xử lý thành công, dung lượng, CPU/RAM đỉnh,
và so 2 lần chạy: cùng file (sha256), cùng trang được chọn, cùng chữ OCR.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

import psutil

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "ket_qua" / "kiem_thu"
WORK = ROOT.parent / "bctc-vn30-kiem-thu"          # bản sao để chạy lạnh, không đụng data/ thật
KY = ("Q2", "2026")


def run_measured(cmd: list[str], cwd: Path) -> dict:
    """Chạy lệnh con, đo thời gian + CPU/RAM đỉnh của cả cây tiến trình (lấy mẫu 0,5 giây)."""
    t0 = time.perf_counter()
    p = subprocess.Popen(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                         errors="replace", env={**__import__("os").environ, "PYTHONIOENCODING": "utf-8"})
    peak = {"ram_mb": 0.0, "cpu_pct": 0.0, "tien_trinh": 0}
    lines: list[str] = []
    reader = threading.Thread(target=lambda: lines.extend(p.stdout), daemon=True)
    reader.start()
    root = psutil.Process(p.pid)
    psutil.cpu_percent(None)
    while p.poll() is None:
        try:
            procs = [root] + root.children(recursive=True)
            ram = sum(x.memory_info().rss for x in procs if x.is_running()) / 1e6
            peak["ram_mb"] = max(peak["ram_mb"], ram)
            peak["tien_trinh"] = max(peak["tien_trinh"], len(procs))
            peak["cpu_pct"] = max(peak["cpu_pct"], psutil.cpu_percent(None))
        except psutil.Error:
            pass
        time.sleep(0.5)
    reader.join(timeout=5)
    return {"giay": round(time.perf_counter() - t0, 1), "rc": p.returncode, "dinh": {k: round(v, 1) for k, v in peak.items()},
            "log": "".join(lines)}


def chuan_bi_ban_sao(w: Path) -> None:
    if w.exists():
        shutil.rmtree(w)
    w.mkdir(parents=True)
    for f in ROOT.glob("*.py"):
        shutil.copy2(f, w / f.name)
    for f in ("companies.json",):
        shutil.copy2(ROOT / f, w / f)
    for d in ("tessdata", "tri_thuc"):
        shutil.copytree(ROOT / d, w / d)
    if (ROOT / ".chrome").exists():                 # hồ sơ Chrome cho các web có Cloudflare (VHM, VIC, VPL, SHB)
        shutil.copytree(ROOT / ".chrome", w / ".chrome", ignore=shutil.ignore_patterns("Cache", "Code Cache", "GPUCache"),
                        dirs_exist_ok=True)


def sha_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def tai_lanh(lan: int) -> list[dict]:
    """Test chịu tải: mỗi lần dựng bản sao trống, tải + xử lý đồng thời 30 BCTC quý 2."""
    OUT.mkdir(parents=True, exist_ok=True)
    res = []
    for i in range(1, lan + 1):
        w = WORK / f"lan{i}"
        print(f"== Lần {i}: bản sao trống tại {w}")
        chuan_bi_ban_sao(w)
        r = {"lan": i, "bat_dau": datetime.now().isoformat(timespec="seconds"), "may": {
            "cpu_luong": psutil.cpu_count(), "cpu_nhan": psutil.cpu_count(logical=False),
            "ram_gb": round(psutil.virtual_memory().total / 1e9, 1)}}
        # Bước 1: đọc danh mục 30 web + tải 30 BCTC quý 2 cùng lúc (30 luồng tải, tối đa 4 kết nối/host)
        b1 = run_measured([sys.executable, "bctc.py", "--periods", KY[0], "--years", KY[1], "--latest", "1", "--scope", "HN",
                           "--source", "ir-first", "--concurrency", "30"], w)
        m = re.search(r"Tải mới (\d+) file \(([\d.]+)MB.*?lỗi (\d+)", b1["log"])
        web_loi = sorted(set(re.findall(r"! (\w+): (?:web IR lỗi|không lấy được danh mục)", b1["log"])))
        man = json.loads((w / "data" / "manifest.json").read_text(encoding="utf-8")) if (w / "data" / "manifest.json").exists() else {}
        files = {rec["ticker"]: {"file": rec["path"], "sha256": rec["sha256"], "mb": round(rec["size"] / 1e6, 2),
                                 "nguon": rec.get("source")} for rec in man.values()
                 if rec.get("period") == KY[0] and str(rec.get("year")) == KY[1]}
        r["buoc1_tai"] = {"giay": b1["giay"], "dinh": b1["dinh"], "tai_moi": int(m[1]) if m else None,
                          "mb": float(m[2]) if m else None, "loi_tai": int(m[3]) if m else None, "web_loi": web_loi,
                          "so_ma_co_file": len(files)}
        # Bước 2: tìm trang 3 báo cáo + OCR + cắt PDF nhỏ cho cả 30 BCTC (song song theo số nhân CPU)
        b2 = run_measured([sys.executable, "phan_tich.py", "--dry-run", "--no-download", "--khong-doi-chieu"], w)
        sel = {mm[1]: [int(x) for x in mm[3].split(",") if x.strip()]
               for mm in re.finditer(r"\[dry\] (\w+) (Q\d/\d{4}): gửi trang \[([\d, ]*)\]", b2["log"])}
        loi2 = re.findall(r"^\s+x (.+)$", b2["log"], re.M)
        ocr = {}
        for tk, f in files.items():
            txt = w / "txt" / Path(f["file"]).with_suffix(".txt")
            if txt.exists():
                ocr[tk] = hashlib.sha256(txt.read_bytes()).hexdigest()
        r["buoc2_ocr"] = {"giay": b2["giay"], "dinh": b2["dinh"], "so_bctc_xu_ly": len(sel), "loi": loi2}
        r["tong_giay"] = round(b1["giay"] + b2["giay"], 1)
        r["file"], r["trang"], r["ocr_hash"] = files, sel, ocr
        (OUT / f"tai_lanh_lan{i}.json").write_text(json.dumps(r, ensure_ascii=False, indent=1), encoding="utf-8")
        (OUT / f"tai_lanh_lan{i}.log").write_text(b1["log"] + "\n\n" + b2["log"], encoding="utf-8")
        print(f"   tải {r['buoc1_tai']} | OCR {r['buoc2_ocr']['giay']}s, {len(sel)} BCTC | tổng {r['tong_giay']}s")
        res.append(r)
    return res


def mo_phong_moi(tickers: list[str]) -> dict:
    """Test theo timeline: coi BCTC quý 2 của vài mã như 'mới đăng' (cất file + manifest + kết quả trích), chạy 1 lần quét,
    rồi so kết quả trích mới với kết quả cũ (độ lặp lại của AI) và kiểm các mã khác không bị đụng tới."""
    import phan_tich as pt
    OUT.mkdir(parents=True, exist_ok=True)
    bk = OUT / "mo_phong_backup"
    bk.mkdir(parents=True, exist_ok=True)
    mpath = pt.DATA / "manifest.json"
    man = json.loads(mpath.read_text(encoding="utf-8"))
    shutil.copy2(mpath, bk / "manifest.json")
    other_before = {k: (r.get("sha256"), (pt.DATA / r["path"]).stat().st_mtime if (pt.DATA / r["path"]).exists() else None)
                    for k, r in man.items() if r["ticker"] not in tickers}
    json_before = {f.name: f.stat().st_mtime for f in (pt.OUT / "json").glob("*.json") if f.name.split("_")[0] not in tickers}
    cu = {}
    for k in [k for k, r in man.items() if r["ticker"] in tickers and r.get("period") == KY[0] and str(r.get("year")) == KY[1]]:
        rec = man.pop(k)
        src = pt.DATA / rec["path"]
        if src.exists():
            (bk / src.name).write_bytes(src.read_bytes())
            src.unlink()
    for tk in tickers:
        j = pt.OUT / "json" / f"{tk}_{KY[1]}_{KY[0]}.json"
        if j.exists():
            cu[tk] = json.loads(j.read_text(encoding="utf-8"))
            shutil.copy2(j, bk / j.name)
            j.unlink()
    mpath.write_text(json.dumps(man, ensure_ascii=False, indent=1), encoding="utf-8")
    import quet_dinh_ky
    entry = quet_dinh_ky.quet(push=False, manual=True, ky=f"{KY[0]}/{KY[1]}")
    man2 = json.loads(mpath.read_text(encoding="utf-8"))
    other_after = {k: (r.get("sha256"), (pt.DATA / r["path"]).stat().st_mtime if (pt.DATA / r["path"]).exists() else None)
                   for k, r in man2.items() if r["ticker"] not in tickers}
    json_after = {f.name: f.stat().st_mtime for f in (pt.OUT / "json").glob("*.json") if f.name.split("_")[0] not in tickers}
    so_sanh = {}
    for tk, old in cu.items():
        j = pt.OUT / "json" / f"{tk}_{KY[1]}_{KY[0]}.json"
        if not j.exists():
            so_sanh[tk] = {"trang_thai": "chưa trích lại"}
            continue
        new = json.loads(j.read_text(encoding="utf-8"))
        a, b = old["data"], new["data"]
        f_old, f_new = pt.UNIT[a["don_vi"]], pt.UNIT[b["don_vi"]]
        same, diff = 0, []
        for f in pt.FIELDS:
            x = None if a.get(f) is None else a[f] * f_old
            y = None if b.get(f) is None else b[f] * f_new
            if x is None and y is None:
                continue
            if x is not None and y is not None and abs(x - y) <= max(0.001, 1e-6 * abs(x)):
                same += 1
            else:
                diff.append({"truong": f, "cu_ty": x, "moi_ty": y})
        so_sanh[tk] = {"cung_file": old.get("sha256") == new.get("sha256"), "truong_giong": same,
                       "truong_khac": len(diff), "chi_tiet_khac": diff}
    r = {"thoi_diem": datetime.now().isoformat(timespec="seconds"), "ma_mo_phong": tickers, "lan_quet": entry,
         "ma_khac_khong_doi": other_before == other_after, "ket_qua_ma_khac_khong_doi": json_before == json_after,
         "so_sanh_trich_lai": so_sanh}
    (OUT / "mo_phong_moi.json").write_text(json.dumps(r, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in r.items() if k != "lan_quet"}, ensure_ascii=False, indent=1)[:3000])
    return r


def so_sanh_trich(tickers: list[str]) -> dict:
    """Độ lặp lại của tầng AI: so kết quả trích lại (ket_qua/json) với bản cũ đã cất ở mo_phong_backup, từng trường số."""
    import phan_tich as pt
    bk = OUT / "mo_phong_backup"
    out = {}
    for tk in tickers:
        name = f"{tk}_{KY[1]}_{KY[0]}.json"
        old_p, new_p = bk / name, pt.OUT / "json" / name
        if not (old_p.exists() and new_p.exists()):
            out[tk] = {"trang_thai": "thiếu bản cũ hoặc bản mới"}
            continue
        old, new = json.loads(old_p.read_text(encoding="utf-8")), json.loads(new_p.read_text(encoding="utf-8"))
        if new.get("extracted_at") == old.get("extracted_at"):
            out[tk] = {"trang_thai": "chưa trích lại"}
            continue
        a, b = old["data"], new["data"]
        fa, fb = pt.UNIT[a["don_vi"]], pt.UNIT[b["don_vi"]]
        same, diff = 0, []
        for f in pt.FIELDS:
            x = None if a.get(f) is None else a[f] * fa
            y = None if b.get(f) is None else b[f] * fb
            if x is None and y is None:
                continue
            if x is not None and y is not None and abs(abs(x) - abs(y)) <= max(1e-6, 1e-9 * abs(x)) and (x * y >= 0 or f.startswith("gia_von")):
                same += 1
            else:
                diff.append({"truong": f, "cu_ty": x, "moi_ty": y})
        out[tk] = {"truong_giong": same, "truong_khac": len(diff), "chi_tiet_khac": diff,
                   "trich_luc_cu": old.get("extracted_at"), "trich_luc_moi": new.get("extracted_at"), "model_moi": new.get("model")}
    (OUT / "so_sanh_trich.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=1)[:3000])
    return out


def main(argv: list[str]) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if not argv:
        print(__doc__)
        return 2
    if argv[0] == "tai-lanh":
        n = int(argv[argv.index("--lan") + 1]) if "--lan" in argv else 2
        tai_lanh(n)
    elif argv[0] == "mo-phong-moi":
        mo_phong_moi([t.strip().upper() for t in argv[1].split(",")])
    elif argv[0] == "so-sanh-trich":
        so_sanh_trich([t.strip().upper() for t in argv[1].split(",")])
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
