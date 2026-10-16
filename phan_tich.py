#!/usr/bin/env python3
"""Bước 4: dùng Gemini đọc BCTC, lấy DT, LNG, LNST, Tổng tài sản, Nợ phải trả, Lưu chuyển tiền
và so sánh QUÝ NÀY với QUÝ TRƯỚC cho các mã VN30. Kết quả: ket_qua/so_sanh_quy.xlsx (+ .csv).

Luồng mỗi mã (các mã chạy chồng nhau - OCR dùng CPU, Gemini dùng mạng):
  bctc.py --source ir-first: BCTC quý cần so sánh, tải từ WEB CÔNG TY (đăng sớm nhất), CafeF dự phòng
  -> quét vùng tiêu đề 25 trang đầu (~0,1 s/trang) -> tìm trang Bảng CĐKT / KQKD / LCTT
  -> OCR đầy đủ CHỈ các trang đó (pdf2txt, có cache txt/), cắt thành PDF nhỏ (~8-14 trang thay vì 30-90)
  -> Gemini (gemini-3.5-flash-lite): ảnh trang + văn bản OCR -> JSON theo schema cố định
  -> kiểm tra cân đối (TS = Nợ + VCSH, LCTT thuần = KD + ĐT + TC) -> so sánh -> Excel
Kết quả Gemini được cache theo sha256 của file PDF: chạy lại chỉ gọi API cho BCTC mới.

Ví dụ:
    set GEMINI_API_KEY=...        (hoặc ghi GEMINI_API_KEY=... vào file .env cạnh script)
    python phan_tich.py                          # 30 mã VN30
    python phan_tich.py --tickers VNM,FPT,ACB
    python phan_tich.py --dry-run                # không gọi API: chỉ tải, OCR, chọn trang, lưu PDF nhỏ
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import json
import os
import re
import sys
import time
from collections import defaultdict, deque
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Literal, Optional

import httpx
import pymupdf
from pydantic import BaseModel, Field

import bctc
import pdf2txt
import tri_thuc

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
TXT = ROOT / "txt"
OUT = ROOT / "ket_qua"
PROMPT_VERSION = 3          # đổi prompt/schema -> tăng số để bỏ cache cũ (3: trường lũy kế, thong_tin, sổ bài học)
UNIT = {"dong": 1e-9, "nghin_dong": 1e-6, "trieu_dong": 1e-3, "ty_dong": 1.0}   # -> tỷ đồng
TOKENS_PER_PAGE = {"low": 280, "medium": 560, "high": 1120}


# ------------------------------------------------------------------ schema trả về
class BCTC(BaseModel):
    ma_ck: str = Field(description="Mã chứng khoán")
    ky_bao_cao: str = Field(description="Kỳ của báo cáo, dạng Q1/2026")
    loai_hinh: Literal["doanh_nghiep", "ngan_hang", "chung_khoan", "bao_hiem"]
    don_vi: Literal["dong", "nghin_dong", "trieu_dong", "ty_dong"] = Field(
        description="Đơn vị tiền ghi trên báo cáo (VND/đồng -> dong)")
    doanh_thu_thuan: Optional[float] = Field(description="Doanh thu thuần của RIÊNG quý này (3 tháng)")
    doanh_thu_thuan_cung_ky: Optional[float] = Field(description="Doanh thu thuần cùng quý năm trước")
    gia_von: Optional[float] = Field(description="Giá vốn hàng bán (DN) hoặc Cộng chi phí hoạt động (CK) của quý này")
    loi_nhuan_gop: Optional[float] = Field(description="Lợi nhuận gộp quý này (NH: thu nhập lãi thuần)")
    loi_nhuan_gop_cung_ky: Optional[float]
    lnst: Optional[float] = Field(description="Lợi nhuận sau thuế TNDN quý này")
    lnst_cung_ky: Optional[float]
    lnst_cong_ty_me: Optional[float] = Field(description="LNST của cổ đông công ty mẹ quý này, nếu có")
    tong_tai_san: Optional[float] = Field(description="Tổng cộng tài sản tại NGÀY CUỐI QUÝ")
    no_phai_tra: Optional[float] = Field(description="Tổng nợ phải trả tại ngày cuối quý")
    vay_no: Optional[float] = Field(description="Nợ vay = vay và nợ thuê tài chính ngắn hạn + dài hạn tại ngày cuối quý (doanh nghiệp mã 320 + 338); ngân hàng để null")
    von_chu_so_huu: Optional[float] = Field(description="Tổng vốn chủ sở hữu tại ngày cuối quý")
    so_thang_luy_ke: Optional[int] = Field(description="Số tháng lũy kế của báo cáo lưu chuyển tiền tệ (3/6/9/12)")
    lctt_hdkd: Optional[float] = Field(description="Lưu chuyển tiền thuần từ hoạt động kinh doanh, lũy kế từ đầu năm")
    lctt_hddt: Optional[float] = Field(description="Lưu chuyển tiền thuần từ hoạt động đầu tư, lũy kế từ đầu năm")
    lctt_hdtc: Optional[float] = Field(description="Lưu chuyển tiền thuần từ hoạt động tài chính, lũy kế từ đầu năm")
    lctt_thuan: Optional[float] = Field(description="Lưu chuyển tiền thuần trong kỳ, lũy kế từ đầu năm")
    # Kỳ so sánh có sẵn TRONG CÙNG 1 BCTC (không cần BCTC quý trước): KQKD cùng quý năm trước, CĐKT đầu năm,
    # LCTT lũy kế cùng kỳ năm trước.
    gia_von_cung_ky: Optional[float] = Field(None, description="Giá vốn / cộng chi phí hoạt động cùng quý năm trước")
    lnst_cong_ty_me_cung_ky: Optional[float] = Field(None, description="LNST cổ đông công ty mẹ cùng quý năm trước")
    tong_tai_san_dau_nam: Optional[float] = Field(None, description="Tổng tài sản cột SỐ ĐẦU NĂM (01/01) trên Bảng CĐKT")
    no_phai_tra_dau_nam: Optional[float] = Field(None, description="Nợ phải trả cột số đầu năm")
    vay_no_dau_nam: Optional[float] = Field(None, description="Nợ vay (vay + nợ thuê tài chính ngắn + dài hạn) cột số đầu năm")
    von_chu_so_huu_dau_nam: Optional[float] = Field(None, description="Vốn chủ sở hữu cột số đầu năm")
    lctt_hdkd_cung_ky: Optional[float] = Field(None, description="LCTT thuần từ HĐ kinh doanh, lũy kế cùng kỳ NĂM TRƯỚC")
    lctt_hddt_cung_ky: Optional[float] = Field(None, description="LCTT thuần từ HĐ đầu tư, lũy kế cùng kỳ năm trước")
    lctt_hdtc_cung_ky: Optional[float] = Field(None, description="LCTT thuần từ HĐ tài chính, lũy kế cùng kỳ năm trước")
    lctt_thuan_cung_ky: Optional[float] = Field(None, description="LCTT thuần trong kỳ, lũy kế cùng kỳ năm trước")
    # Cột LŨY KẾ từ đầu năm của KQKD (quý 2-4): so sánh lũy kế năm nay với lũy kế cùng kỳ năm trước.
    doanh_thu_thuan_luy_ke: Optional[float] = Field(None, description="Doanh thu thuần LŨY KẾ từ đầu năm, năm nay")
    doanh_thu_thuan_cung_ky_luy_ke: Optional[float] = Field(None, description="Doanh thu thuần lũy kế cùng kỳ năm trước")
    gia_von_luy_ke: Optional[float] = Field(None)
    loi_nhuan_gop_luy_ke: Optional[float] = Field(None)
    loi_nhuan_gop_cung_ky_luy_ke: Optional[float] = Field(None)
    lnst_luy_ke: Optional[float] = Field(None)
    lnst_cung_ky_luy_ke: Optional[float] = Field(None)
    lnst_cong_ty_me_luy_ke: Optional[float] = Field(None)
    trang_cdkt: Optional[int] = Field(description="Trang (trong file đính kèm, bắt đầu từ 1) có Bảng cân đối kế toán")
    trang_kqkd: Optional[int]
    trang_lctt: Optional[int]
    ghi_chu: str = Field(description="CHỈ ghi điểm bất thường cần người kiểm tra (báo cáo tự lệch, sai kỳ, thiếu trang); để trống nếu không")
    thong_tin: str = Field("", description="Giải thích cách lấy số (VD tự cộng tổng thu nhập hoạt động, dùng số trình bày lại); không phải cảnh báo")


SYSTEM = """Bạn là chuyên viên phân tích BCTC Việt Nam (chuẩn mực VAS). Nhiệm vụ: đọc 3 báo cáo chính trong file
đính kèm (Bảng cân đối kế toán, Báo cáo kết quả hoạt động kinh doanh, Báo cáo lưu chuyển tiền tệ) và trả JSON.

Quy tắc bắt buộc:
1. Chép số ĐÚNG như in trên báo cáo, đúng đơn vị của báo cáo (ghi vào don_vi); KHÔNG tự đổi đơn vị, KHÔNG làm tròn.
   Số trong ngoặc (1.234) là số âm -1234. Dấu chấm/phẩy là phân cách hàng nghìn kiểu Việt Nam.
2. Báo cáo kết quả kinh doanh: các trường quý lấy cột "Quý này năm nay" (3 tháng của riêng quý báo cáo), *_cung_ky lấy
   cột "Quý này năm trước" (riêng quý 1 thì quý = lũy kế 3 tháng). Quý 2-4 có cột lũy kế từ đầu năm: điền thêm
   *_luy_ke (năm nay) và *_cung_ky_luy_ke (năm trước).
3. Bảng cân đối kế toán: trường chính lấy cột số CUỐI KỲ (ngày cuối quý báo cáo); các trường *_dau_nam lấy cột SỐ ĐẦU NĂM.
4. Lưu chuyển tiền tệ: trường chính lấy cột lũy kế từ đầu năm đến cuối quý của NĂM NAY; các trường lctt_*_cung_ky lấy
   cột lũy kế cùng kỳ NĂM TRƯỚC; ghi số tháng lũy kế.
5. Ánh xạ chỉ tiêu theo loại hình. Từ 2026 BCTC theo mẫu mới (Thông tư 99/2025) nên MÃ SỐ có thể khác mẫu cũ:
   nhận diện theo TÊN dòng, mã số dưới đây chỉ để tham khảo (mẫu Thông tư 200).
   - doanh_nghiep: doanh_thu_thuan = "Doanh thu thuần về bán hàng và cung cấp dịch vụ" (mã số 10); gia_von = mã 11;
     loi_nhuan_gop = mã 20; lnst = mã 60; lnst_cong_ty_me = mã 61; tong_tai_san = mã 270;
     no_phai_tra = mã 300; vay_no = mã 320 + mã 338 (vay và nợ thuê tài chính ngắn hạn + dài hạn);
     von_chu_so_huu = mã 400 (gồm cả lợi ích cổ đông không kiểm soát).
   - ngan_hang: doanh_thu_thuan = "Tổng thu nhập hoạt động"; loi_nhuan_gop = "Thu nhập lãi thuần";
     gia_von = null; tong_tai_san = "Tổng tài sản"; no_phai_tra = "Tổng nợ phải trả"; von_chu_so_huu = "Vốn chủ sở hữu" (tổng);
     vay_no = null.
   - chung_khoan: doanh_thu_thuan = "Cộng doanh thu hoạt động"; gia_von = "Cộng chi phí hoạt động"; loi_nhuan_gop = null;
     vay_no = "Vay và nợ thuê tài sản tài chính ngắn hạn" + "dài hạn".
   - bao_hiem: doanh_thu_thuan = "Doanh thu thuần hoạt động kinh doanh bảo hiểm";
     loi_nhuan_gop = "Lợi nhuận gộp hoạt động kinh doanh bảo hiểm".
   - Lưu chuyển tiền: lctt_hdkd = mã 20, lctt_hddt = mã 30, lctt_hdtc = mã 40, lctt_thuan = mã 50.
6. Không thấy chỉ tiêu thì để null, KHÔNG đoán. Có văn bản OCR kèm theo: dùng để đọc chữ số; nếu khác ảnh thì nhìn kỹ ảnh."""


def system_prompt() -> str:
    """Prompt gốc + quy tắc rút ra từ các lần sai trước (tri_thuc/bai_hoc.json) - sửa sổ là lần sau áp dụng ngay."""
    return SYSTEM + tri_thuc.quy_tac_text()


# ------------------------------------------------------------------ chọn BCTC
def quarter_key(rec) -> tuple[int, int]:
    return int(rec["year"]), int(rec["period"][1])


def prev_q(key: tuple[int, int]) -> tuple[int, int]:
    y, q = key
    return (y, q - 1) if q > 1 else (y - 1, 4)


def pick_reports(tickers: list[str]) -> dict[str, dict[tuple[int, int], dict]]:
    """Mỗi mã: CHỈ 1 BCTC - quý mới nhất (hợp nhất, công ty không có công ty con thì BCTC chung).
    Một BCTC quý đã chứa sẵn kỳ so sánh: KQKD cùng quý năm trước, CĐKT đầu năm, LCTT lũy kế cùng kỳ năm trước."""
    manifest = json.loads((DATA / "manifest.json").read_text(encoding="utf-8"))
    rank = {"HN": 2, "CHUNG": 1}
    by: dict[str, dict] = defaultdict(dict)
    for rec in manifest.values():
        if (rec["ticker"] not in tickers or rec.get("period") not in ("Q1", "Q2", "Q3", "Q4")
                or rec.get("scope") not in rank or not rec.get("year") or not (DATA / rec["path"]).exists()):
            continue
        k = quarter_key(rec)
        cur = by[rec["ticker"]].get(k)
        # ưu tiên: hợp nhất > chung; bản quý thường (có cột riêng quý) > bản ghi "soát xét" (VPL: thực chất bán niên,
        # chỉ có cột 6 tháng - bài học R11); web công ty (nguồn gốc, mới nhất) > CafeF
        key = lambda x: (rank[x["scope"]], not x.get("audit"), x["source"].startswith("official"), x["size"])  # noqa: E731
        if cur is None or key(rec) > key(cur):
            by[rec["ticker"]][k] = rec
    return {t: {max(v): v[max(v)]} for t, v in by.items()}


# ------------------------------------------------------------------ tìm trang báo cáo
def _norm(s: str) -> str:
    return re.sub(r"[^a-z]", "", bctc.unaccent(s))


TITLES = {"cdkt": ("candoiketoan", "tinhhinhtaichinh", "financialposition", "balancesheet"),
          "kqkd": ("ketquahoatdongkinhdoanh", "ketquakinhdoanh", "incomestatement", "profitorloss"),
          "lctt": ("luuchuyentiente", "cashflow")}


def find_statement_pages(pages: dict[int, tuple[str, str]], max_pages: int, fallback: int = 16) -> list[int]:
    """pages: {trang: (cách đọc, chữ vùng đầu trang)}. Trang có tiêu đề CĐKT/KQKD/LCTT -> lấy liền mạch
    từ báo cáo đầu tiên tới trước phần Thuyết minh."""
    starts, notes = locate(pages)
    if not starts:
        return sorted(pages)[:fallback]
    # Thứ tự BCTC VN luôn là CĐKT -> KQKD -> LCTT: "tiêu đề" xuất hiện trước CĐKT là câu văn trong công văn
    # giải trình ("...tại báo cáo kết quả kinh doanh...", VD VHM) -> bỏ.
    first = starts.get("cdkt", min(starts.values()))
    after = [p for p in starts.values() if p >= first]
    last = (notes - 1) if notes else max(after) + 2
    return [p for p in sorted(pages) if first <= p <= last][:max_pages]


def locate(pages: dict[int, tuple[str, str]]) -> tuple[dict[str, int], int | None]:
    """-> ({báo cáo: trang bắt đầu}, trang bắt đầu Thuyết minh hoặc None)."""
    starts: dict[str, int] = {}
    notes = None
    for p in sorted(pages):
        top = _norm("\n".join(pages[p][1].splitlines()[:15]))
        found = [key for key, ts in TITLES.items() if any(t in top for t in ts)]
        if re.search(r"mucluc|noidungtrang|tableofcontents", top) or len(found) >= 2:
            continue              # mục lục ("MỤC LỤC" / "NỘI DUNG ... TRANG") liệt kê nhiều báo cáo cùng lúc
        for key in found:
            starts.setdefault(key, p)
        # Phần thuyết minh (hoặc báo cáo biến động vốn chủ sở hữu của công ty chứng khoán) bắt đầu -> dừng.
        # Chỉ khớp "Thuyết minh báo cáo tài chính", KHÔNG khớp cột "Thuyết minh" có sẵn trong bảng CĐKT/KQKD.
        if starts and p > max(starts.values()) and re.search(
                r"thuyetminhbaocaotaichinh|thuyetminhbctc|notestothe|biendongvonchusohuu|changesinequity", top):
            notes = p
            break
    return starts, notes


def build_pdf(pdf: Path, pages: list[int], methods: dict[int, str], dpi: int = 200) -> bytes:
    """PDF nhỏ chỉ gồm các trang cần. Trang scan -> ảnh JPEG xám 200 dpi (nhẹ hơn ảnh gốc nhiều lần)."""
    src = pymupdf.open(pdf)
    out = pymupdf.open()
    for p in pages:
        page = src[p - 1]
        if methods.get(p) == "text":
            out.insert_pdf(src, from_page=p - 1, to_page=p - 1)      # giữ lớp chữ gốc cho Gemini
        else:
            rot = pdf2txt.rot_of(methods.get(p, ""))                  # trang scan nằm ngang -> xoay cho đúng chiều
            if rot:
                page.set_rotation((page.rotation + rot) % 360)
            pix = page.get_pixmap(dpi=dpi, colorspace=pymupdf.csGRAY)
            np_ = out.new_page(width=page.rect.width, height=page.rect.height)
            np_.insert_image(np_.rect, stream=pix.tobytes("jpeg", jpg_quality=75))
    return out.tobytes(garbage=3, deflate=True)


# ------------------------------------------------------------------ giới hạn API
class Limiter:
    """Cửa sổ trượt 60 giây cho cả số request (RPM) lẫn token (TPM) - tránh lỗi 429 của bản miễn phí."""

    def __init__(self, rpm: int, tpm: int):
        self.rpm, self.tpm, self.hist, self.lock = rpm, tpm, deque(), asyncio.Lock()

    async def acquire(self, tokens: int):
        async with self.lock:
            while True:
                now = time.monotonic()
                while self.hist and now - self.hist[0][0] > 60:
                    self.hist.popleft()
                if len(self.hist) < self.rpm and sum(t for _, t in self.hist) + tokens <= self.tpm:
                    self.hist.append((now, tokens))
                    return
                await asyncio.sleep(60 - (now - self.hist[0][0]) + 0.2)


class QuotaExhausted(Exception):
    pass


async def ask_gemini(client, args, limiter: Limiter, sem: asyncio.Semaphore, pdf_bytes: bytes,
                     prompt: str, est_tokens: int) -> tuple[BCTC, dict]:
    from google.genai import errors, types

    res = getattr(types.MediaResolution, f"MEDIA_RESOLUTION_{args.media_resolution.upper()}")
    use_thinking = True
    for attempt in range(6):
        cfg = types.GenerateContentConfig(
            system_instruction=system_prompt(), temperature=0, response_mime_type="application/json",
            response_schema=BCTC, media_resolution=res,
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
            thinking_config=types.ThinkingConfig(thinking_level=args.thinking.upper()) if use_thinking else None)
        await limiter.acquire(est_tokens)
        try:
            async with sem:
                resp = await client.aio.models.generate_content(
                    model=args.model, config=cfg,
                    contents=[types.Part.from_bytes(data=pdf_bytes, mime_type="application/pdf"), prompt])
            data = resp.parsed if isinstance(resp.parsed, BCTC) else BCTC.model_validate_json(resp.text)
            u = resp.usage_metadata
            usage = {"input": getattr(u, "prompt_token_count", None), "output": getattr(u, "candidates_token_count", None),
                     "thinking": getattr(u, "thoughts_token_count", None)}
            return data, usage
        except errors.APIError as e:
            msg = str(e)
            if e.code == 429 and re.search(r"PerDay|per day|daily", msg, re.I):
                raise QuotaExhausted(msg[:300]) from e
            if e.code == 400 and use_thinking and "thinking" in msg.lower():
                use_thinking = False                       # model không nhận thinking_level -> bỏ
                continue
            if e.code in (429, 500, 502, 503, 504) and attempt < 5:
                m = re.search(r"retryDelay['\"]?\s*:\s*['\"]?(\d+)", msg)
                await asyncio.sleep(int(m.group(1)) + 1 if m else 2 ** attempt * 3)
                continue
            raise
        except ValueError:                                  # JSON hỏng (hiếm) -> hỏi lại
            if attempt >= 2:
                raise
        except (httpx.HTTPError, asyncio.TimeoutError):     # mất mạng / timeout -> chờ rồi thử lại
            if attempt >= 4:
                raise
            await asyncio.sleep(2 ** attempt * 3)
    raise RuntimeError("Gemini không trả kết quả")


# ------------------------------------------------------------------ xử lý 1 BCTC
def prompt_version() -> str:
    """Phiên bản prompt = schema + sổ bài học: thêm quy tắc mới thì BCTC đã trích được hỏi lại theo quy tắc mới."""
    return f"{PROMPT_VERSION}.{tri_thuc.phien_ban()}"


def report_prompt(ticker: str, key: tuple[int, int], rec: dict, n_pages: int) -> str:
    """Lời dặn cho 1 BCTC + lưu ý riêng của mã từ sổ bài học."""
    hn = "hợp nhất" if rec["scope"] == "HN" else "riêng/chung"
    notes = tri_thuc.luu_y_ma(ticker)
    return (f"Mã {ticker}, BCTC {hn} quý {key[1]} năm {key[0]} (Q{key[1]}/{key[0]}). File đính kèm gồm {n_pages} trang "
            f"trích từ báo cáo gốc. Trích xuất theo schema, gồm cả các cột so sánh (cùng kỳ năm trước, số đầu năm)."
            + ("\nLưu ý riêng của mã này (từ các lần trích trước):\n" + "\n".join(f"- {x}" for x in notes) if notes else ""))


async def select_pages(ctx, pdf: Path) -> tuple[list[int], dict[int, str]]:
    """Pha 1: chỉ quét vùng tiêu đề của n trang đầu (~0,1 s/trang) để biết 3 báo cáo nằm ở trang nào."""
    args = ctx["args"]
    with pymupdf.open(pdf) as d:
        n = d.page_count
    pages = list(range(1, min(n, args.scan_pages) + 1))
    tops: dict[int, tuple[str, str]] = {}
    # Quét từng đợt 6 trang (3 cụm song song), dừng ngay khi đã gặp phần Thuyết minh: 3 báo cáo thường
    # nằm ở trang 3-12 nên hay chỉ phải quét 12-18 trang thay vì 25.
    for b in range(0, len(pages), 6):
        batch = pages[b:b + 6]
        futs = [ctx["loop"].run_in_executor(ctx["pool"], pdf2txt.scan_titles, str(pdf), batch[i:i + 2],
                                            str(ROOT / "tessdata")) for i in range(0, len(batch), 2)]
        for r in await asyncio.gather(*futs):
            tops.update(r)
        if locate(tops)[1]:
            break
    sel = find_statement_pages(tops, args.max_pages)
    methods = {p: tops[p][0] for p in sel}
    # File scan nằm ngang: trang tiếp nối (vùng đầu ít chữ) không tự dò được góc -> theo góc đa số của file
    rots = [pdf2txt.rot_of(m) for m, _ in tops.values() if "@" in m]
    if rots:
        maj = max(set(rots), key=rots.count)
        if rots.count(maj) >= 2:
            for p in sel:
                if methods[p] == "ocr" and pdf2txt.vn_score(tops[p][1]) < 3:
                    methods[p] = f"ocr@{maj}"
    return sel, methods


async def ocr_pages(ctx, pdf: Path, pages: list[int], rots: dict[int, int]) -> dict[int, tuple[str, str]]:
    """Pha 2: OCR đầy đủ các trang đã chọn (dùng lại txt/ của bước 3 nếu có) và lưu vào txt/.
    rots: góc xoay đã dò ở pha 1 -> OCR đúng chiều; cache txt OCR sai chiều thì làm lại."""
    out = pdf2txt.txt_path_for(pdf, TXT, DATA)
    have = pdf2txt.read_txt(out)
    if have and out.stat().st_mtime < pdf.stat().st_mtime:
        have = {}
    todo = [p for p in pages if p not in have or (have[p][0] != "text" and pdf2txt.rot_of(have[p][0]) != rots.get(p, 0))]
    if todo:
        futs = [ctx["loop"].run_in_executor(ctx["pool"], pdf2txt.convert_pages, str(pdf), todo[i:i + 2], "auto",
                                            200, str(ROOT / "tessdata"), "vie+eng",
                                            {p: rots.get(p, 0) for p in todo[i:i + 2]})
                for i in range(0, len(todo), 2)]
        for _, res in await asyncio.gather(*futs):
            have.update(res)
        with pymupdf.open(pdf) as d:
            pdf2txt.write_txt(out, out.relative_to(TXT).with_suffix(".pdf").as_posix(), d.page_count, have)
    return have


async def process_report(ticker: str, key: tuple[int, int], rec: dict, ctx: dict) -> dict:
    args = ctx["args"]
    pdf = DATA / rec["path"]
    ky = f"Q{key[1]}/{key[0]}"
    cache = OUT / "json" / f"{ticker}_{key[0]}_Q{key[1]}.json"
    if cache.exists() and not args.force:
        c = json.loads(cache.read_text(encoding="utf-8"))
        if c.get("sha256") == rec["sha256"] and c.get("prompt_version") == prompt_version() and c.get("model") == args.model:
            return c
    # Chỉ vài BCTC tiền xử lý cùng lúc: BCTC đầu xong sau vài giây và gửi Gemini ngay, trong khi CPU
    # xử lý tiếp BCTC sau (nếu cho cả 60 BCTC xếp hàng OCR cùng lúc, Gemini phải chờ tới khi gần xong hết).
    async with ctx["prep"]:
        sel, methods = await select_pages(ctx, pdf)
        pdf_bytes = await asyncio.to_thread(build_pdf, pdf, sel, methods)
        ocr_txt = ""
        scanned = [p for p in sel if methods[p] != "text"]
        if args.ocr_hint and scanned:
            full = await ocr_pages(ctx, pdf, scanned, {p: pdf2txt.rot_of(methods[p]) for p in scanned})
            ocr_txt = "\n\n".join(f"=== Trang {i} của file đính kèm ===\n{full[p][1]}"
                                  for i, p in enumerate(sel, 1) if p in scanned and p in full)
    prompt = report_prompt(ticker, key, rec, len(sel))
    if ocr_txt:
        prompt += "\n\nVăn bản OCR của các trang scan (có thể sai dấu tiếng Việt):\n" + ocr_txt
    est = len(sel) * TOKENS_PER_PAGE[args.media_resolution] + len(prompt) // 3 + 2500
    base = {"ticker": ticker, "ky": ky, "file": rec["path"], "sha256": rec["sha256"], "scope": rec["scope"],
            "pages_sent": sel, "est_tokens": est, "pdf_kb": len(pdf_bytes) // 1024}
    if args.dry_run:
        dbg = OUT / "debug" / f"{ticker}_{key[0]}_Q{key[1]}.pdf"
        dbg.parent.mkdir(parents=True, exist_ok=True)
        dbg.write_bytes(pdf_bytes)
        print(f"  [dry] {ticker} {ky}: gửi trang {sel} ({len(pdf_bytes) // 1024} KB, ~{est} token) -> {dbg.name}")
        return {**base, "data": None}
    t0 = time.perf_counter()
    data, usage = await ask_gemini(ctx["client"], args, ctx["limiter"], ctx["sem"], pdf_bytes, prompt, est)
    result = {**base, "prompt_version": prompt_version(), "model": args.model, "usage": usage,
              "extracted_at": datetime.now().isoformat(timespec="seconds"), "data": data.model_dump()}
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"  + {ticker} {ky}: {len(sel)} trang, {usage.get('input')} token vào, {time.perf_counter() - t0:.1f}s")
    return result


# ------------------------------------------------------------------ chuẩn hoá + kiểm tra
# Trường lấy từ 1 BCTC quý. Kỳ so sánh nằm ngay trong báo cáo: KQKD *_cung_ky (cùng quý năm trước),
# CĐKT *_dau_nam (số đầu năm), LCTT *_cung_ky (lũy kế cùng kỳ năm trước), KQKD lũy kế *_luy_ke / *_cung_ky_luy_ke.
LUY_KE = ["doanh_thu_thuan", "doanh_thu_thuan_cung_ky", "gia_von", "loi_nhuan_gop", "loi_nhuan_gop_cung_ky",
          "lnst", "lnst_cung_ky", "lnst_cong_ty_me"]
BS = ["tong_tai_san", "no_phai_tra", "vay_no", "von_chu_so_huu"]
CF = ["lctt_hdkd", "lctt_hddt", "lctt_hdtc", "lctt_thuan"]
FIELDS = (["doanh_thu_thuan", "doanh_thu_thuan_cung_ky", "gia_von", "gia_von_cung_ky", "loi_nhuan_gop",
           "loi_nhuan_gop_cung_ky", "lnst", "lnst_cung_ky", "lnst_cong_ty_me", "lnst_cong_ty_me_cung_ky"]
          + BS + [f + "_dau_nam" for f in BS] + CF + [f + "_cung_ky" for f in CF] + [f + "_luy_ke" for f in LUY_KE])
CF_TEN = {"lctt_hdkd": "LCTT kinh doanh", "lctt_hddt": "LCTT đầu tư", "lctt_hdtc": "LCTT tài chính"}


def normalize(r: dict) -> dict:
    """Đổi sang tỷ đồng, tự tính LNG cho công ty chứng khoán, tự sửa các lỗi đã gặp (sổ bài học), gắn cảnh báo kiểm tra chéo.
    warn = bất thường cần người xem; info = giải thích cách lấy số (không tính là cảnh báo)."""
    d = r["data"]
    f = UNIT.get(d["don_vi"], 1e-9)
    v = {k: (d[k] * f if d.get(k) is not None else None) for k in FIELDS}
    q = int(r["ky"][1])
    if q == 1:            # quý 1: lũy kế = quý
        for k in LUY_KE:
            if v[k + "_luy_ke"] is None:
                v[k + "_luy_ke"] = v[k]
    info = [d["thong_tin"]] if d.get("thong_tin") else []
    for sx in ("", "_cung_ky", "_luy_ke", "_cung_ky_luy_ke"):          # chứng khoán: LN hoạt động = DT − chi phí
        g, dt, gv = "loi_nhuan_gop" + sx, "doanh_thu_thuan" + sx, "gia_von" + sx
        if v.get(g) is None and v.get(dt) is not None and v.get(gv) is not None:
            v[g] = v[dt] - abs(v[gv])
    # R6: báo cáo không tách LNST cổ đông mẹ (không có cổ đông không kiểm soát / báo cáo riêng) -> bằng LNST
    filled = False
    for a, b in (("lnst_cong_ty_me", "lnst"), ("lnst_cong_ty_me_cung_ky", "lnst_cung_ky"),
                 ("lnst_cong_ty_me_luy_ke", "lnst_luy_ke")):
        if v[a] is None and v[b] is not None:
            v[a], filled = v[b], True
    if filled:
        info.append("Báo cáo không tách LNST cổ đông công ty mẹ: lấy bằng LNST")
    # R5: đúng 1 dòng LCTT trống mà 2 dòng kia đã cộng ra LCTT thuần -> dòng đó in "-" = 0
    for sx in ("", "_cung_ky"):
        miss = [k for k in CF_TEN if v[k + sx] is None]
        if len(miss) == 1 and v["lctt_thuan" + sx] is not None:
            rest = sum(v[k + sx] for k in CF_TEN if k != miss[0])
            if abs(rest - v["lctt_thuan" + sx]) <= max(1.0, 0.005 * abs(v["lctt_thuan" + sx])):
                v[miss[0] + sx] = 0.0
                info.append(CF_TEN[miss[0]] + (" năm trước" if sx else "") + " không có số trên báo cáo: tính là 0")
    warn = []
    ts = v["tong_tai_san"]
    if ts is not None and not 100 <= abs(ts) <= 5_000_000:      # VN30: tổng tài sản ~10^3 - 3.10^6 tỷ
        warn.append(f"Tổng tài sản {ts:,.1f} tỷ bất thường - nghi sai đơn vị ({d['don_vi']})")
    for sx, ten in (("", ""), ("_dau_nam", " đầu năm")):
        ts, no, vc = v["tong_tai_san" + sx], v["no_phai_tra" + sx], v["von_chu_so_huu" + sx]
        if None not in (ts, no, vc) and ts and abs(ts - no - vc) / abs(ts) > 0.002:
            warn.append(f"TS{ten} lệch Nợ+VCSH {abs(ts - no - vc):,.1f} tỷ")
    for sx, ten in (("", ""), ("_cung_ky", " năm trước")):
        parts = [v[k + sx] for k in CF_TEN]
        if None not in parts and v["lctt_thuan" + sx] is not None:
            diff = abs(sum(parts) - v["lctt_thuan" + sx])
            if diff > max(1.0, 0.005 * max(abs(x) for x in parts + [v["lctt_thuan" + sx]])):
                warn.append(f"LCTT thuần{ten} lệch tổng 3 hoạt động {diff:,.1f} tỷ")
    if d.get("so_thang_luy_ke") and d["so_thang_luy_ke"] != 3 * q:
        warn.append(f"LCTT lũy kế {d['so_thang_luy_ke']} tháng (cần {3 * q})")
    if d.get("ky_bao_cao") and d["ky_bao_cao"].replace(" ", "") != r["ky"]:
        warn.append(f"AI đọc kỳ {d['ky_bao_cao']}")
    if d.get("ghi_chu"):
        warn.append(d["ghi_chu"])
    return {"v": v, "warn": warn, "info": info, "loai_hinh": d["loai_hinh"], "don_vi": d["don_vi"]}


def ky_so_sanh(key: tuple[int, int]) -> dict[str, tuple[str, str]]:
    """Nhãn kỳ: q = quý (so cùng quý năm trước), bs = cuối quý (so đầu năm), cf/lk = lũy kế (so cùng kỳ năm trước)."""
    y, q = key
    lk = f"{3 * q}T" if q > 1 else "Q1"
    return {"q": (f"Q{q}/{y}", f"Q{q}/{y - 1}"), "bs": (f"cuối Q{q}/{y}", f"đầu năm {y}"),
            "cf": (f"{lk}/{y}", f"{lk}/{y - 1}"), "lk": (f"{lk}/{y}", f"{lk}/{y - 1}")}


ROWS = [  # (nhãn, trường năm nay, trường kỳ so sánh, kiểu kỳ)
    ("Doanh thu thuần", "doanh_thu_thuan", "doanh_thu_thuan_cung_ky", "q"),
    ("Lợi nhuận gộp", "loi_nhuan_gop", "loi_nhuan_gop_cung_ky", "q"),
    ("LNST", "lnst", "lnst_cung_ky", "q"),
    ("LNST cổ đông công ty mẹ", "lnst_cong_ty_me", "lnst_cong_ty_me_cung_ky", "q"),
    ("Doanh thu thuần lũy kế", "doanh_thu_thuan_luy_ke", "doanh_thu_thuan_cung_ky_luy_ke", "lk"),
    ("LNST lũy kế", "lnst_luy_ke", "lnst_cung_ky_luy_ke", "lk"),
    ("Tổng tài sản", "tong_tai_san", "tong_tai_san_dau_nam", "bs"),
    ("Nợ phải trả", "no_phai_tra", "no_phai_tra_dau_nam", "bs"),
    ("Nợ vay", "vay_no", "vay_no_dau_nam", "bs"),
    ("Vốn chủ sở hữu", "von_chu_so_huu", "von_chu_so_huu_dau_nam", "bs"),
    ("LCTT từ HĐ kinh doanh (lũy kế)", "lctt_hdkd", "lctt_hdkd_cung_ky", "cf"),
    ("LCTT từ HĐ đầu tư (lũy kế)", "lctt_hddt", "lctt_hddt_cung_ky", "cf"),
    ("LCTT từ HĐ tài chính (lũy kế)", "lctt_hdtc", "lctt_hdtc_cung_ky", "cf"),
    ("LCTT thuần (lũy kế)", "lctt_thuan", "lctt_thuan_cung_ky", "cf"),
]


def latest(results_tk: dict) -> tuple[tuple[int, int], dict] | None:
    """BCTC mới nhất của 1 mã (cache có thể còn các quý cũ)."""
    ks = [k for k, r in results_tk.items() if r.get("data")]
    return (max(ks), results_tk[max(ks)]) if ks else None


def compare(results: dict[str, dict[tuple[int, int], dict]]) -> tuple[list[list], list[list]]:
    """Mỗi mã 1 BCTC: năm nay so với kỳ so sánh trong chính báo cáo đó."""
    long_rows, raw_rows = [], []
    for tk in sorted(results):
        lt = latest(results[tk])
        if not lt:
            continue
        key, r = lt
        n = normalize(r)
        raw_rows.append([tk, r["ky"], n["loai_hinh"], n["don_vi"]] + [n["v"][f] for f in FIELDS]
                        + ["; ".join(n["warn"]), "; ".join(n["info"]), r["file"], ",".join(map(str, r["pages_sent"]))])
        lab = ky_so_sanh(key)
        for label, f_now, f_cmp, kind in ROWS:
            a, b = n["v"][f_now], n["v"][f_cmp]
            if a is None and b is None:
                continue
            delta = a - b if None not in (a, b) else None
            pct = delta / abs(b) if delta is not None and b else None
            long_rows.append([tk, n["loai_hinh"], label, lab[kind][0], lab[kind][1], a, b, delta, pct, "; ".join(n["warn"])])
    return long_rows, raw_rows


LONG_HEAD = ["Mã", "Loại hình", "Chỉ tiêu", "Kỳ này", "Kỳ so sánh", "Giá trị kỳ này (tỷ đ)",
             "Giá trị kỳ so sánh (tỷ đ)", "Chênh lệch (tỷ đ)", "% thay đổi", "Cảnh báo kiểm tra"]
RAW_HEAD = ["Mã", "Kỳ", "Loại hình", "Đơn vị gốc"] + [f"{f} (tỷ đ)" for f in FIELDS] + ["Cảnh báo", "Thông tin", "File", "Trang gửi"]


def write_outputs(long_rows, raw_rows, score: tuple | None = None):
    OUT.mkdir(parents=True, exist_ok=True)
    with open(OUT / "so_sanh_quy.csv", "w", newline="", encoding="utf-8-sig") as f:
        csv.writer(f).writerows([LONG_HEAD] + long_rows)
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill
    except ImportError:
        return OUT / "so_sanh_quy.csv"
    wb = Workbook()
    sheets = [(wb.active, LONG_HEAD, long_rows, range(6, 9), [9]),
              (wb.create_sheet(), RAW_HEAD, raw_rows, range(5, 5 + len(FIELDS)), [])]
    if score:                      # sheet chấm điểm đặt đầu tiên: nhìn nhanh mã nào BCTC tốt
        sheets.insert(0, (wb.create_sheet(index=0), score[0], score[1], [14], range(8, 14)))
    for ws, head, rows, num_cols, pct_cols in sheets:
        ws.append(head)
        for row in rows:
            ws.append(row)
        for c in ws[1]:
            c.font = Font(bold=True, color="FFFFFF")
            c.fill = PatternFill("solid", fgColor="1F4E78")
        for col in num_cols:
            for cell in ws.iter_cols(min_col=col, max_col=col, min_row=2):
                for c in cell:
                    c.number_format = "#,##0.0;[Red]-#,##0.0"
        for col in pct_cols:
            for cell in ws.iter_cols(min_col=col, max_col=col, min_row=2):
                for c in cell:
                    c.number_format = "[Color10]+0.0%;[Red]-0.0%;0.0%"
        for i, h in enumerate(head, 1):
            ws.column_dimensions[ws.cell(1, i).column_letter].width = max(10, min(36, len(h) + 4))
        ws.freeze_panes = "D2"
        ws.auto_filter.ref = ws.dimensions
    for ws, title in zip(wb.worksheets, (["Chấm điểm"] if score else []) + ["So sánh quý", "Dữ liệu từng BCTC"]):
        ws.title = title
    path = OUT / "so_sanh_quy.xlsx"
    wb.save(path)
    return path


# ------------------------------------------------------------------ main
def load_api_key(arg: str | None) -> str | None:
    if arg:
        return arg
    for k in ("GEMINI_API_KEY", "GOOGLE_API_KEY"):
        if os.environ.get(k):
            return os.environ[k]
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            k, _, v = line.partition("=")
            if k.strip() in ("GEMINI_API_KEY", "GOOGLE_API_KEY") and v.strip():
                return v.strip().strip('"').strip("'")
    return None


async def run(args, tickers: list[str]) -> int:
    reports = pick_reports(tickers)
    missing = [t for t in tickers if t not in reports]
    if missing:
        print(f"! Không có BCTC quý trong data/ cho: {', '.join(missing)}")
    ctx = {"args": args, "loop": asyncio.get_running_loop(), "limiter": Limiter(args.rpm, args.tpm),
           "sem": asyncio.Semaphore(args.concurrency), "prep": asyncio.Semaphore(3), "client": None}
    if not args.dry_run:
        from google import genai
        ctx["client"] = genai.Client(api_key=load_api_key(args.api_key))
    n = sum(len(v) for v in reports.values())
    print(f"Phân tích {n} BCTC của {len(reports)} mã bằng {args.model if not args.dry_run else '(dry-run)'}...")
    t0 = time.perf_counter()
    results: dict[str, dict] = defaultdict(dict)
    errors_: list[str] = []
    with ProcessPoolExecutor(max_workers=pdf2txt.default_workers(), initializer=pdf2txt._init_worker) as pool:
        ctx["pool"] = pool

        async def one(tk, key, rec):
            try:
                results[tk][key] = await process_report(tk, key, rec, ctx)
            except QuotaExhausted as e:
                errors_.append(f"{tk} Q{key[1]}/{key[0]}: hết quota ngày ({e})")
            except Exception as e:  # noqa: BLE001 - lỗi 1 BCTC không dừng cả lô
                errors_.append(f"{tk} Q{key[1]}/{key[0]}: {type(e).__name__}: {str(e)[:200]}")

        # Quý mới nhất xếp trước để các mã đầu tiên có kết quả sớm
        jobs = sorted(((tk, k, r) for tk, v in reports.items() for k, r in v.items()), key=lambda x: x[1], reverse=True)
        await asyncio.gather(*(one(*j) for j in jobs))
    for e in errors_:
        print("  x", e)
    if args.dry_run:
        print(f"\nDry-run xong trong {time.perf_counter() - t0:.0f}s. PDF nhỏ sẽ gửi Gemini: {OUT / 'debug'}")
        return 0
    import dashboard
    if args.doi_chieu:              # tự đối chiếu Vietcap: chỗ lệch > 1% vào sổ bài học để lần sau tránh
        import doi_chieu
        doi_chieu.run(results)
    long_rows, raw_rows = compare(results)
    path = write_outputs(long_rows, raw_rows, dashboard.score_rows(dashboard.build_cards(results)))
    dash = dashboard.build(results)
    tok = sum((r.get("usage") or {}).get("input") or 0 for v in results.values() for r in v.values())
    print(f"\nXong trong {time.perf_counter() - t0:.0f}s | {len(long_rows)} dòng so sánh -> {path}"
          f" | token vào lần này ~{tok:,} | lỗi {len(errors_)}")
    print(f"Dashboard: {dash}")
    return 1 if errors_ else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Gemini đọc BCTC VN30 và so sánh quý này với quý trước.")
    ap.add_argument("--tickers", type=lambda s: [x.strip().upper() for x in s.split(",") if x.strip()])
    ap.add_argument("--model", default="gemini-3.5-flash-lite")
    ap.add_argument("--api-key", help="Mặc định đọc GEMINI_API_KEY (biến môi trường hoặc file .env)")
    ap.add_argument("--rpm", type=int, default=12, help="Request/phút (free tier flash-lite ~15)")
    ap.add_argument("--tpm", type=int, default=200_000, help="Token/phút (free tier ~250k)")
    ap.add_argument("--concurrency", type=int, default=4)
    ap.add_argument("--media-resolution", choices=["low", "medium", "high"], default="high",
                    help="Độ nét ảnh trang gửi Gemini (high: đọc số chính xác hơn)")
    ap.add_argument("--thinking", choices=["minimal", "low", "medium", "high"], default="low")
    ap.add_argument("--scan-pages", type=int, default=25, help="OCR bao nhiêu trang đầu để tìm 3 báo cáo")
    ap.add_argument("--max-pages", type=int, default=16, help="Tối đa số trang gửi Gemini mỗi BCTC")
    ap.add_argument("--no-ocr-hint", dest="ocr_hint", action="store_false",
                    help="Không gửi kèm văn bản OCR của trang scan (tiết kiệm token, chỉ dùng ảnh)")
    ap.add_argument("--no-download", action="store_true", help="Không gọi bctc.py tải BCTC thiếu")
    ap.add_argument("--dry-run", action="store_true", help="Không gọi Gemini: chỉ tải, OCR, chọn trang")
    ap.add_argument("--force", action="store_true", help="Bỏ cache, hỏi Gemini lại")
    ap.add_argument("--khong-doi-chieu", dest="doi_chieu", action="store_false",
                    help="Bỏ bước tự đối chiếu với Vietcap IQ sau khi trích")
    ap.add_argument("--tong-hop", action="store_true",
                    help="Không tải, không gọi AI: chỉ so sánh + chấm điểm + dựng web từ ket_qua/json (VD số do claude_trich.py ghi)")
    args = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if args.tong_hop:
        import dashboard
        results = dashboard.load_results()
        if args.doi_chieu:
            import doi_chieu
            doi_chieu.run(results)
        long_rows, raw_rows = compare(results)
        path = write_outputs(long_rows, raw_rows, dashboard.score_rows(dashboard.build_cards(results)))
        print(f"{len(results)} mã | {len(long_rows)} dòng so sánh -> {path}\nDashboard: {dashboard.build(results)}")
        return 0

    companies = json.loads((ROOT / "companies.json").read_text(encoding="utf-8"))["companies"]
    tickers = args.tickers or [c["ticker"] for c in companies]
    if not args.dry_run and not load_api_key(args.api_key):
        print("Chưa có API key. Lấy key miễn phí tại https://aistudio.google.com/apikey rồi chạy:\n"
              "  setx GEMINI_API_KEY \"<key>\"   (mở terminal mới)  hoặc ghi GEMINI_API_KEY=<key> vào file .env")
        return 2
    if not args.no_download:      # đảm bảo có 3 BCTC quý gần nhất (tải tăng dần, file đã có thì bỏ qua)
        print("== Kiểm tra / tải BCTC quý ==")
        bctc.main(["--tickers", ",".join(tickers), "--periods", "Q1,Q2,Q3,Q4", "--latest", "1",
                   "--scope", "HN", "--source", "ir-first"])
        print()
    try:
        return asyncio.run(run(args, tickers))
    except KeyboardInterrupt:
        print("\nĐã dừng. Kết quả Gemini đã nhận được lưu trong ket_qua/json/ - chạy lại sẽ không hỏi lại.")
        return 130


if __name__ == "__main__":
    sys.exit(main())
