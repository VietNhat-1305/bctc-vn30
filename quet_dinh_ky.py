#!/usr/bin/env python3
"""Quét định kỳ web 30 công ty VN30, 6 tiếng/lần (0h - 6h - 12h - 18h): có BCTC mới thì tải về và phân tích ngay.

Mỗi lần quét (đo thời gian từng bước, ghi vào ket_qua/lich_su_quet.json -> timeline trên web):
  1. kham_pha_tai : đọc danh mục BCTC trên web từng công ty, tải file MỚI (manifest + sha256: bài cũ không tải lại)
  2. chuan_bi     : BCTC quý mới -> tìm trang 3 báo cáo, OCR (pdf2txt), cắt PDF nhỏ
  3. trich_so     : Gemini nếu có GEMINI_API_KEY; không có thì gọi Claude CLI (claude -p) chạy ngầm theo claude_trich.py;
                    BCTC đã trích (cùng sha256) không trích lại
  4. tong_hop     : tự đối chiếu Vietcap, chấm điểm, dựng web, đẩy GitHub Pages

    python quet_dinh_ky.py                 # quét 1 lần (Task Scheduler gọi)
    python quet_dinh_ky.py --khong-day     # quét nhưng không đẩy GitHub
    python quet_dinh_ky.py --dat-lich      # tạo lịch Windows Task Scheduler 0h, 6h, 12h, 18h
    python quet_dinh_ky.py --xoa-lich      # xoá lịch
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LOG = ROOT / "ket_qua" / "lich_su_quet.json"
KHUNG = ["00:00", "06:00", "12:00", "18:00"]
TASK = "BCTC_VN30_quet_{}"
CLAUDE_MODEL = "claude-opus-5-5"          # model Claude CLI dùng để trích số khi không có Gemini key
CLAUDE_TIMEOUT_BCTC = 900                   # giây tối đa cho mỗi BCTC; quá thì dừng, BCTC để 'chờ trích' lần sau


class Tee(io.TextIOBase):
    """In ra màn hình (log của Task Scheduler) đồng thời giữ lại để đọc kết quả từng bước."""

    def __init__(self, stream):
        self.stream, self.buf = stream, io.StringIO()

    def write(self, s):
        self.stream.write(s)
        self.buf.write(s)
        return len(s)

    def flush(self):
        self.stream.flush()


@contextlib.contextmanager
def capture():
    tee = Tee(sys.stdout)
    with contextlib.redirect_stdout(tee):
        yield tee


def manifest(data: Path) -> dict:
    p = data / "manifest.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def slot_of(now: datetime, manual: bool) -> str:
    """Khung giờ của lần quét: Task Scheduler chạy đúng giờ -> '06:00'; chạy tay -> 'thủ công 10:42'."""
    if not manual:
        for k in KHUNG:
            h = int(k[:2])
            if (now.hour - h) % 24 == 0 and now.minute < 30:
                return k
    return f"thủ công {now:%H:%M}"


def kham_pha_tai(tickers: list[str], ky: str | None = None) -> dict:
    """Bước 1: đọc danh mục web công ty + tải file mới. Trả về BCTC mới (theo manifest trước/sau) và web đọc được.
    ky (VD 'Q2/2026'): chỉ quét 1 kỳ - giai đoạn thử; bỏ trống = kỳ mới nhất của từng mã."""
    import bctc
    data = ROOT / "data"
    before = {k: r.get("sha256") for k, r in manifest(data).items()}
    per, years = (ky.split("/")[0], ky.split("/")[1]) if ky else ("Q1,Q2,Q3,Q4", None)
    with capture() as cap:
        rc = bctc.main(["--tickers", ",".join(tickers), "--periods", per, "--latest", "1", "--scope", "HN",
                        "--source", "ir-first"] + (["--years", years] if years else []))
    out = cap.buf.getvalue()
    after = manifest(data)
    moi = [{"ma": r["ticker"], "ky": f"{r.get('period')}/{r.get('year')}", "pham_vi": r.get("scope"), "file": r.get("path"),
            "nguon": "web công ty" if str(r.get("source", "")).startswith("official") else "CafeF"}
           for k, r in after.items() if k not in before or before[k] != r.get("sha256")]
    co_danh_muc = set(re.findall(r"^\[(\w+)\] \d+ BCTC trong danh mục", out, re.M))
    web_loi = sorted({m for m in re.findall(r"! (\w+): (?:web IR lỗi|không lấy được danh mục)", out)})
    web_ok = sorted(co_danh_muc - set(web_loi))      # web công ty đọc được; web lỗi nhưng vẫn có danh mục = đã dùng CafeF dự phòng
    m = re.search(r"bỏ qua \(đã có\) (\d+).*?lỗi (\d+)", out)
    return {"rc": rc, "moi": moi, "web_ok": web_ok, "web_loi": web_loi,
            "du_phong_cafef": sorted(co_danh_muc & set(web_loi)),
            "bo_qua_bai_cu": int(m[1]) if m else None, "loi_tai": int(m[2]) if m else None}


def can_trich(tickers: list[str]) -> list[tuple[str, int, int]]:
    """BCTC mới nhất mỗi mã chưa có kết quả trích cho đúng file đó (so sha256) -> cần chuẩn bị + trích."""
    import phan_tich as pt
    out = []
    for tk, v in pt.pick_reports(tickers).items():
        for (y, q), rec in v.items():
            f = pt.OUT / "json" / f"{tk}_{y}_Q{q}.json"
            c = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
            if c.get("sha256") != rec["sha256"] or not c.get("data"):
                out.append((tk, y, q))
    return sorted(out)


def chuan_bi(pending: list[tuple[str, int, int]]) -> None:
    """Bước 2: tìm trang 3 báo cáo + OCR + PDF nhỏ (phan_tich --dry-run), ghi dòng trang đã chọn cho claude_trich."""
    import phan_tich as pt
    with capture() as cap:
        pt.main(["--dry-run", "--no-download", "--khong-doi-chieu", "--tickers", ",".join(sorted({p[0] for p in pending}))])
    lines = [ln for ln in cap.buf.getvalue().splitlines() if "[dry]" in ln]
    log = pt.OUT / "debug" / "dry_run.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    with open(log, "a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def trich_so(pending: list[tuple[str, int, int]]) -> dict:
    """Bước 3: Gemini (có key) -> Claude CLI (có cài) -> để chờ. Trả về cách trích và danh sách đã/ chưa trích."""
    import phan_tich as pt
    tickers = ",".join(sorted({p[0] for p in pending}))
    info: dict = {}
    if pt.load_api_key(None):
        cach = "Gemini"
        pt.main(["--no-download", "--khong-doi-chieu", "--tickers", tickers])
    elif shutil.which("claude"):
        cach = "Claude CLI"
        ds = ", ".join(f"{t} quý {q}/{y}" for t, y, q in pending)
        tmp = pt.OUT / "claude_tmp"
        tmp.mkdir(parents=True, exist_ok=True)
        prompt = (
            f"Bạn đang chạy tự động (lịch quét BCTC) trong thư mục {ROOT}. Trích số liệu cho các BCTC: {ds}.\n"
            f"1. Chạy: python claude_trich.py huong_dan {tickers.replace(',', ' ')}  -> đọc kỹ hướng dẫn và sổ bài học, áp dụng hết.\n"
            "2. Với từng BCTC: python claude_trich.py chu MÃ NĂM QUÝ (chữ các trang) và python claude_trich.py anh MÃ NĂM QUÝ "
            "(ảnh PNG, xem bằng tool Read; số lớn phải đọc từ ảnh).\n"
            "3. Lưu kết quả bằng cách đưa JSON đủ trường theo mẫu vào stdin của lệnh ghi, VD:\n"
            "   python claude_trich.py ghi MÃ NĂM QUÝ - <<'JSON'\n   {...}\n   JSON\n"
            "   chạy lại cho đến khi in 'KIỂM TRA: OK' (tối đa 3 lần sửa). Không dùng tool Write.\n"
            "Không sửa file nào khác của dự án. Cuối cùng in mỗi BCTC 1 dòng: MÃ QUÝ/NĂM: OK hoặc lý do lỗi.")
        env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
        try:
            # acceptEdits: cho Claude ghi file JSON kết quả (chạy ngầm không có người bấm cho phép);
            # Bash chỉ được chạy claude_trich.py
            # Popen + tự tắt CẢ CÂY tiến trình khi quá giờ: trên Windows claude.cmd -> node, subprocess.run(timeout=)
            # chỉ tắt cmd còn node giữ pipe -> treo (đã gặp khi kiểm thử 17/10/2026)
            p = subprocess.Popen([shutil.which("claude"), "-p", prompt, "--model", CLAUDE_MODEL, "--output-format", "json",
                                  "--allowedTools", "Bash(python claude_trich.py:*)", "Read"],
                                 cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8")
            try:
                out, err = p.communicate(timeout=CLAUDE_TIMEOUT_BCTC * len(pending))
            except subprocess.TimeoutExpired:
                import psutil
                for c in psutil.Process(p.pid).children(recursive=True) + [psutil.Process(p.pid)]:
                    with contextlib.suppress(psutil.Error):
                        c.kill()
                out, err = "", f"quá {CLAUDE_TIMEOUT_BCTC * len(pending)} giây, đã dừng Claude CLI"
            r = subprocess.CompletedProcess(p.args, p.returncode, out, err)
            try:
                last = [ln for ln in (r.stdout or "").splitlines() if ln.strip().startswith("{")]
                res = json.loads(last[-1] if last else r.stdout)
                info["claude"] = {"luot": res.get("num_turns"), "giay": round((res.get("duration_ms") or 0) / 1000, 1),
                                  "chi_phi_usd": round(res.get("total_cost_usd") or 0, 3),
                                  "bi_tu_choi": [d.get("tool_name") for d in res.get("permission_denials") or []],
                                  "ket_qua": (res.get("result") or "")[-1500:]}
            except json.JSONDecodeError:
                info["claude"] = {"loi": (r.stdout or r.stderr)[-1500:]}
            print("Claude CLI:", json.dumps(info["claude"], ensure_ascii=False)[:2000])
        except subprocess.TimeoutExpired:
            print("Claude CLI quá 3 giờ, dừng")
    else:
        cach = "chưa có (cần GEMINI_API_KEY hoặc Claude CLI)"
    con = set(can_trich(sorted({p[0] for p in pending})))
    return {"cach": cach, **info, "da_trich": [f"{t} Q{q}/{y}" for t, y, q in pending if (t, y, q) not in con],
            "cho_trich": [f"{t} Q{q}/{y}" for t, y, q in pending if (t, y, q) in con]}


def tong_hop() -> None:
    """Bước 4: đối chiếu Vietcap + chấm điểm + dựng web (phan_tich --tong-hop)."""
    import phan_tich as pt
    pt.main(["--tong-hop"])


def ghi_log(entry: dict) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    runs = json.loads(LOG.read_text(encoding="utf-8")) if LOG.exists() else []
    runs = [r for r in runs if r["id"] != entry["id"]] + [entry]
    LOG.write_text(json.dumps(runs[-300:], ensure_ascii=False, indent=1), encoding="utf-8")


def quet(push: bool, manual: bool, tickers: list[str] | None = None, ky: str | None = None) -> dict:
    now = datetime.now()
    companies = json.loads((ROOT / "companies.json").read_text(encoding="utf-8"))["companies"]
    tickers = tickers or [c["ticker"] for c in companies]
    entry = {"id": now.strftime("%Y%m%d-%H%M%S"), "khung": slot_of(now, manual), "bat_dau": now.isoformat(timespec="seconds"),
             "so_web": len(tickers), "ky_quet": ky or "mới nhất", "giai_doan": {}, "loi": []}
    t0 = time.perf_counter()

    def step(name, fn, *a):
        t = time.perf_counter()
        try:
            return fn(*a)
        except Exception as e:  # noqa: BLE001 - 1 bước lỗi vẫn ghi log và chạy bước sau nếu được
            entry["loi"].append(f"{name}: {type(e).__name__}: {str(e)[:300]}")
            return None
        finally:
            entry["giai_doan"][name] = round(time.perf_counter() - t, 1)

    kp = step("kham_pha_tai", kham_pha_tai, tickers, ky) or {}
    entry.update({"web_doc_duoc": len(kp.get("web_ok", [])), "web_loi": kp.get("web_loi", []),
                  "du_phong_cafef": kp.get("du_phong_cafef", []),
                  "bctc_moi": kp.get("moi", []), "bo_qua_bai_cu": kp.get("bo_qua_bai_cu"), "loi_tai": kp.get("loi_tai")})
    pending = step("tim_can_trich", can_trich, tickers) or []
    entry["can_trich"] = [f"{t} Q{q}/{y}" for t, y, q in pending]
    if pending:
        step("chuan_bi", chuan_bi, pending)
        tr = step("trich_so", trich_so, pending) or {}
        entry.update({"cach_trich": tr.get("cach"), "da_trich": tr.get("da_trich", []), "cho_trich": tr.get("cho_trich", []),
                      "claude": tr.get("claude")})
    if pending or entry["bctc_moi"] or not LOG.exists():
        step("tong_hop", tong_hop)
    entry["ket_thuc"] = datetime.now().isoformat(timespec="seconds")
    entry["thoi_gian_s"] = round(time.perf_counter() - t0, 1)
    entry["trang_thai"] = ("lỗi" if entry["loi"] else "có BCTC mới" if entry.get("da_trich") or entry["bctc_moi"]
                           else "không có BCTC mới")
    ghi_log(entry)
    import dashboard
    dashboard.build()                     # web có timeline của lần quét này
    if push:
        import dang_web
        dang_web.main()
    print(f"\nQuét {entry['khung']} xong trong {entry['thoi_gian_s']}s | web đọc được {entry['web_doc_duoc']}/{len(tickers)} | "
          f"BCTC mới {len(entry['bctc_moi'])} | đã trích {len(entry.get('da_trich', []))} | chờ trích {len(entry.get('cho_trich', []))}"
          f" | lỗi {len(entry['loi'])}")
    return entry


def dat_lich(ky: str | None = None) -> None:
    """Windows Task Scheduler: 4 tác vụ hằng ngày 0h, 6h, 12h, 18h chạy quet_dinh_ky.cmd (máy cần bật, đã đăng nhập)."""
    cmd = ROOT / "quet_dinh_ky.cmd"
    extra = f" --ky {ky}" if ky else ""
    cmd.write_text("@echo off\r\ncd /d %~dp0\r\nset PYTHONIOENCODING=utf-8\r\n"
                   f"\"{sys.executable}\" quet_dinh_ky.py{extra} >> ket_qua\\quet.log 2>&1\r\n", encoding="ascii")
    for k in KHUNG:
        name = TASK.format(k.replace(":", ""))
        r = subprocess.run(["schtasks", "/Create", "/F", "/SC", "DAILY", "/ST", k, "/TN", name, "/TR", str(cmd)],
                           capture_output=True, text=True)
        print(name, "OK" if r.returncode == 0 else f"LỖI: {r.stderr.strip() or r.stdout.strip()}")


def xoa_lich() -> None:
    for k in KHUNG:
        name = TASK.format(k.replace(":", ""))
        r = subprocess.run(["schtasks", "/Delete", "/F", "/TN", name], capture_output=True, text=True)
        print(name, "đã xoá" if r.returncode == 0 else "không có")


def main(argv=None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="Quét định kỳ BCTC VN30 trên web công ty")
    ap.add_argument("--khong-day", action="store_true", help="Không đẩy GitHub")
    ap.add_argument("--thu-cong", action="store_true", help="Ghi nhãn lần quét là chạy tay")
    ap.add_argument("--tickers", type=lambda s: [x.strip().upper() for x in s.split(",") if x.strip()])
    ap.add_argument("--ky", help="Chỉ quét 1 kỳ, VD Q2/2026 (giai đoạn thử); bỏ trống = kỳ mới nhất")
    ap.add_argument("--dat-lich", action="store_true")
    ap.add_argument("--xoa-lich", action="store_true")
    a = ap.parse_args(argv)
    if a.dat_lich:
        dat_lich(a.ky)
        return 0
    if a.xoa_lich:
        xoa_lich()
        return 0
    e = quet(push=not a.khong_day, manual=a.thu_cong, tickers=a.tickers, ky=a.ky)
    return 1 if e["loi"] else 0


if __name__ == "__main__":
    sys.exit(main())
