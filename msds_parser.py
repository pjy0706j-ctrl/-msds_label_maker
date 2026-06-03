import fitz
import re
import os
import hashlib
import threading

from hcode_db import HCODE_DB
from pcode_db import PCODE_DB


# =========================
# 언어 감지 및 번역 (캐시 적용)
# =========================
_translate_cache: dict[str, str] = {}
_translate_lock = threading.Lock()


def _is_english(text: str) -> bool:
    """텍스트가 주로 영문인지 판단 (알파벳 비율 60% 초과)"""
    if not text:
        return False
    letters = re.sub(r"\s", "", text)
    if not letters:
        return False
    en = sum(1 for c in letters if "a" <= c.lower() <= "z")
    return en / len(letters) > 0.6


def translate_to_korean(text: str) -> str:
    """영문 텍스트를 한국어로 번역. 캐시 적용으로 동일 텍스트 재요청 방지."""
    if not text or not _is_english(text):
        return text

    # 캐시 확인 (해시 키)
    key = hashlib.md5(text.encode()).hexdigest()
    with _translate_lock:
        if key in _translate_cache:
            return _translate_cache[key]

    try:
        from deep_translator import GoogleTranslator
        # 4500자씩 분할 번역
        chunks = [text[i:i+4500] for i in range(0, len(text), 4500)]
        translated = "\n".join(
            GoogleTranslator(source="auto", target="ko").translate(c)
            for c in chunks
        )
    except Exception:
        translated = text  # 실패 시 원문 반환

    with _translate_lock:
        _translate_cache[key] = translated
    return translated


# =========================
# PDF 텍스트 추출
# =========================
def extract_text_from_pdf(uploaded_file):
    """업로드된 파일 객체(바이트)에서 텍스트 추출 (메모리 전용)"""
    text = ""
    pdf_bytes = uploaded_file.read()
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    for page_num, page in enumerate(doc, start=1):
        text += f"\n\n--- Page {page_num} ---\n"
        text += page.get_text()
    doc.close()
    return text


def extract_text_from_pdf_path(pdf_path):
    """파일 경로에서 텍스트 추출"""
    text = ""
    doc = fitz.open(pdf_path)
    for page_num, page in enumerate(doc, start=1):
        text += f"\n\n--- Page {page_num} ---\n"
        text += page.get_text()
    doc.close()
    return text


# =========================
# 텍스트 정리
# =========================
def clean_text(s):
    if not s:
        return ""

    s = re.sub(r"--- Page \d+ ---", "", s)
    s = re.sub(r"Page\s*\d+\s*of\s*\d+", "", s, flags=re.IGNORECASE)
    s = re.sub(r"DaejungChemicals&Metals", "", s, flags=re.IGNORECASE)
    s = re.sub(r"Samchun Chemicals", "", s, flags=re.IGNORECASE)
    s = re.sub(r"MSDS.*?페이지", "", s, flags=re.IGNORECASE)

    s = re.sub(r"([가-힣a-zA-Z])\n(P\d{3})", r"\1 \2", s)

    replacements = {
        "싞": "신", "젂": "전", "핚": "한", "안젂": "안전",
        "홖": "환", "곢": "곤", "맋": "많", "잒": "잔",
        "혺": "혼", "옦": "온", "옧": "올", "핛": "할",
        "유해 · 위험": "유해·위험", "유해ㆍ위험": "유해·위험",
        "경 고": "경고", "위 험": "위험",
        "신 호 어": "신호어", "신호 어": "신호어",
    }
    for old, new in replacements.items():
        s = s.replace(old, new)

    s = re.sub(r"\n{3,}", "\n\n", s)
    s = re.sub(r"H\s*(\d{3})", r"H\1", s)
    s = re.sub(r"P\s*(\d{3})", r"P\1", s)

    return s.strip()


def extract_between(text, start, end):
    # end 패턴을 비캡처 그룹으로 감싸 | 연산자 우선순위 문제 방지
    pattern = start + r"(.*?)(?:" + end + ")"
    match = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
    if match:
        return clean_text(match.group(1))
    return ""


# =========================
# 회사 감지
# =========================
def detect_company(text):
    text_upper = text.upper()
    if "OCI" in text_upper:
        return "OCI"
    elif "DAEJUNG" in text_upper:
        return "DAEJUNG"
    elif "SAMCHUN" in text_upper:
        return "SAMCHUN"
    elif "SIGMA-ALDRICH" in text_upper:
        return "SIGMA"
    return "DEFAULT"


def detect_company_from_filename(file_name):
    """파일명 기반 회사 감지. 실패 시 빈 문자열 반환."""
    name_upper = file_name.upper()
    if "OCI" in name_upper:
        return "OCI"
    elif "대정" in file_name or "DAEJUNG" in name_upper:
        return "DAEJUNG"
    elif "덕산" in file_name or "DUKSAN" in name_upper:
        return "DUKSAN"
    elif "SAMCHUN" in name_upper or "삼전" in file_name:
        return "SAMCHUN"
    elif "WAKO" in name_upper:
        return "WAKO"
    elif "KANTO" in name_upper:
        return "KANTO"
    elif "JUNSEI" in name_upper:
        return "JUNSEI"
    return ""


# =========================
# 항목별 추출 함수
# =========================
def extract_product_name(text):
    # ── OCI 포맷: "1. 화학제품과 회사에 관한 정보" 바로 다음 줄이 제품명 ──
    # "가./나." 같은 개요 마커가 아닌 첫 줄을 제품명으로 사용
    m_oci = re.search(r"1\.\s*화학제품.*?회사.*?정보\s*\n(.*)", text, re.IGNORECASE)
    if m_oci:
        for line in m_oci.group(1).split("\n"):
            c = line.strip()
            # 개요 마커(가./나./다...) 와 빈 줄, 매우 짧은 줄 건너뜀
            if not c:
                continue
            if re.match(r"^[가나다라마바사아자차카타파하]\.\s*", c):
                continue
            if re.match(r"^[a-z]\.\s*", c, re.IGNORECASE):
                continue
            if len(c) < 3 or re.match(r"^[\d\s\-\.]+$", c):
                continue
            # 라벨 헤더 자체("제품명", "Product name" 등) 건너뜀
            if re.match(r"^(제품명|상품명|화학제품명|Product\s*(?:name|identifier))$", c, re.IGNORECASE):
                continue
            return c

    patterns = [
        (r"가\.\s*제품명",  r"나\.\s*제품"),
        (r"가\.제품명",     r"나\.제품"),
        (r"제품명",         r"나\.\s*제품"),
        (r"Product\s*name", r"Recommended|Product\s*type|Reference\s*number|CAS"),
    ]
    for start, end in patterns:
        result = extract_between(text, start, end)
        if result:
            result = clean_text(result)
            if ";" in result:
                result = result.split(";")[0].strip()
            # 첫 번째 의미있는 줄 선택
            for line in result.splitlines():
                line = re.sub(r"^[:：\-]\s*", "", line.strip())
                # 개요 마커 / 너무 짧은 줄 건너뜀
                if (len(line) > 2
                    and not re.match(r"^[가나다라마바사아자차카타파하]\.\s*", line)
                    and not re.match(r"^[a-z]\.\s*", line, re.IGNORECASE)):
                    return line
    return ""


def extract_product_name_retry(text):
    text = clean_text(text)
    patterns = [
        r"제품명\s*[:：]?\s*(.+)",
        r"Product\s*Name\s*[:：]?\s*(.+)",
        r"상품명\s*[:：]?\s*(.+)",
        r"화학제품명\s*[:：]?\s*(.+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            result = match.group(1).split("\n")[0].strip()
            if len(result) > 3:
                return result
    return ""


def _clean_supplier_result(raw: str) -> str:
    """추출된 공급자정보에서 H/P코드, 목차 플레이스홀더, 불필요 항목을 제거한다."""
    # 끝 잘라내기: 관련 없는 섹션 시작 전에서 자름
    cut = re.search(
        r"\bH\d{3}\b"
        r"|신호어|예방조치문구"
        r"|유해\s*위험\s*문구|유해·위험문구"
        r"|그림문자|GHS"
        r"|권장\s*용도|사용\s*제한|Recommended\s*use|Restrictions?\s*on\s*use"
        r"|참조\s*번호|Reference\s*No|Reference\s*number"
        r"|For\s*research\s*use",
        raw,
        re.IGNORECASE,
    )
    if cut:
        raw = raw[:cut.start()]

    # 플레이스홀더 줄 제거 (줄 전체 또는 일부가 placeholder 패턴이면 제거)
    PLACEHOLDER_CONTAINS = re.compile(
        r"^회사명$|^상호$|^주소$|^긴급전화번호$|^신호어$|^예방조치문구$"
        r"|수입품의\s*경우|국내\s*공급자\s*정보\s*기재"
        r"|^\(.*\)$",          # 괄호로만 이루어진 줄
        re.IGNORECASE,
    )
    lines = [l for l in raw.splitlines()
             if l.strip() and not PLACEHOLDER_CONTAINS.search(l.strip())]

    result = "\n".join(lines).strip()

    # 결과가 너무 짧으면(플레이스홀더만 있었던 경우) 실패로 간주
    return result if len(result) > 10 else ""


def extract_supplier_info(text):
    patterns = [
        # ── 한국어 패턴 ──
        (r"c\.\s*회사명",          r"d\.\s*|항\s*2"),          # Sigma 한국어
        (r"다\.\s*공급자\s*정보",  r"2\.\s*유해"),
        (r"다\.\s*공급자정보",     r"2\.\s*유해"),
        (r"다\.\s*제조자.*?정보",  r"2\.\s*유해"),
        (r"다\.\s*공급자\s*정보",  r"Section\s*2"),
        (r"다\.공급자\s*정보",     r"Section\s*2"),
        (r"다\.\s*공급자정보",     r"Section\s*2"),
        (r"다\.공급자정보",        r"Section\s*2"),
        (r"공급자\s*정보",         r"2\.\s*유해"),
        (r"공급자\s*정보",         r"Section\s*2"),
        (r"회사에\s*관한\s*정보",  r"2\.\s*유해"),
        (r"회사에\s*관한\s*정보",  r"Section\s*2"),
        (r"공급자",                r"2\.\s*유해"),
        # ── 영문 패턴 ──
        (r"Company\s*information", r"2\.\s*Hazard|Section\s*2"),
        (r"Details?\s*of\s*the\s*supplier", r"2\.\s*Hazard|Section\s*2"),
        (r"Manufacturer\s*/\s*Supplier",    r"2\.\s*Hazard|Section\s*2"),
        (r"Supplier\s*information",         r"2\.\s*Hazard|Section\s*2"),
    ]

    for start, end in patterns:
        raw = extract_between(text, start, end)
        if not raw:
            continue
        raw = re.split(
            r"가\.\s*유해성|가\.유해성|가\.\s*유해·위험성"
            r"|나\.\s*예방조치문구|나\.예방조치문구|Section\s*2",
            raw,
        )[0]
        result = _clean_supplier_result(clean_text(raw))
        if result:
            return translate_to_korean(result)  # 영문이면 자동 번역

    # ── Fallback: 섹션2 바로 앞 600자에서 회사 정보 추출 (OCI 등) ──
    sec2_match = re.search(r"2\.\s*유해", text)
    if sec2_match:
        # 섹션2 직전 600자만 사용 (TOC 플레이스홀더 영역 제외)
        before_sec2 = text[max(0, sec2_match.start() - 600):sec2_match.start()]
        # ㈜ 또는 Tel 포함 블록 탐색
        all_matches = list(re.finditer(
            r"([^\n]*(?:㈜|주식회사|Tel\s*:)[^\n]*(?:\n[^\n]*){0,8})",
            before_sec2,
            re.IGNORECASE,
        ))
        # 가장 마지막 매치(섹션2에 가장 가까운 것)를 사용
        if all_matches:
            raw = all_matches[-1].group(0)
            result = _clean_supplier_result(clean_text(raw))
            if result:
                return result

    return ""


def extract_section_2(text):
    patterns = [
        (r"2\.\s*유해·위험성", r"3\.\s*구성성분"),
        (r"2\.\s*유해\s*위험성", r"3\.\s*구성성분"),
        (r"2\.\s*유해성.*?위험성", r"3\.\s*구성성분"),
        (r"Section\s*2\s*[–\-]\s*유해성.*?위험성", r"Section\s*3"),
        (r"Section\s*2", r"Section\s*3"),
        (r"2\.\s*Hazards", r"3\.\s*Composition"),
        (r"Section\s*2\s*[–\-]\s*Hazards", r"Section\s*3"),
    ]
    for start, end in patterns:
        result = extract_between(text, start, end)
        if result:
            return clean_text(result)
    return ""


def extract_signal_word(parse_text):
    text = clean_text(parse_text)
    normalized = text
    normalized = normalized.replace("경 고", "경고")
    normalized = normalized.replace("위 험", "위험")
    normalized = normalized.replace("신 호 어", "신호어")
    normalized = normalized.replace("신호 어", "신호어")
    normalized = normalized.replace("유해 · 위험", "유해·위험")
    normalized = normalized.replace("유해ㆍ위험", "유해·위험")

    patterns = [
        r"신호어\s*[:：]?\s*(위험|경고)",
        r"신호어\s*[:：]?\s*\n\s*(위험|경고)",
        r"\d\)\s*신호어\s*[\n\s]*-?\s*(위험|경고)",   # Chlorine: 2) 신호어\n - 위험
        r"신호어\s*[:：]?\s*([가-힣\s]{1,10})\s*유해",
        r"Signal\s*word\s*[:：]?\s*(Danger|Warning)",
    ]
    for pattern in patterns:
        match = re.search(pattern, normalized, re.IGNORECASE)
        if match:
            result = match.group(1).strip()
            result = re.sub(r"\s+", "", result)
            result = result.replace("Danger", "위험")
            result = result.replace("Warning", "경고")
            if "위험" in result:
                return "위험"
            if "경고" in result:
                return "경고"

    lines = [line.strip() for line in normalized.splitlines() if line.strip()]
    for i, line in enumerate(lines):
        compact = re.sub(r"\s+", "", line)
        if compact == "신호어":
            for next_line in lines[i + 1:i + 6]:
                next_compact = re.sub(r"\s+", "", next_line)
                if next_compact in ["위험", "경고"]:
                    return next_compact
        if compact in ["위험", "경고"]:
            nearby = "\n".join(lines[i:i + 6])
            if "유해" in nearby or re.search(r"H\d{3}", nearby):
                return compact

    return ""


# ── 영문 H코드 문구 → 코드 역매핑 (코드 없는 영문 SDS 대응) ──
_HCODE_EN_REVERSE = {
    r"fatal if swallowed":                          "H300",
    r"toxic if swallowed":                          "H301",
    r"harmful if swallowed":                        "H302",
    r"fatal in contact with skin":                  "H310",
    r"toxic in contact with skin":                  "H311",
    r"harmful in contact with skin":                "H312",
    r"fatal if inhaled":                            "H330",
    r"toxic if inhaled":                            "H331",
    r"harmful if inhaled":                          "H332",
    r"causes severe skin burns? and eye damage":    "H314",
    r"causes skin corrosion":                       "H314",
    r"causes serious eye damage":                   "H318",
    r"causes skin irritation":                      "H315",
    r"may cause skin sensitization":                "H317",
    r"causes serious eye irritation":               "H319",
    r"may cause drowsiness or dizziness":           "H336",
    r"causes damage to organs":                     "H370",
    r"may cause damage to organs.*prolonged":       "H373",
    r"suspected of causing cancer":                 "H351",
    r"may cause cancer":                            "H350",
    r"very toxic to aquatic life.*long":            "H410",
    r"very toxic to aquatic life":                  "H400",
    r"toxic to aquatic life.*long":                 "H411",
    r"harmful to aquatic life.*long":               "H412",
    r"harmful to aquatic life":                     "H402",
    r"flammable liquid":                            "H226",
    r"highly flammable liquid":                     "H225",
    r"extremely flammable":                         "H224",
}


def extract_h_codes(text):
    """PDF 전체 텍스트에서 H코드 번호만 추출 (중복 제거, 순서 유지).
    코드가 없으면 영문 문구 역매핑으로 보완."""
    text_norm = re.sub(r"H\s*(\d{3})", r"H\1", text)
    codes = re.findall(r"H\d{3}", text_norm)
    seen = set()
    unique = []
    for c in codes:
        if c not in seen:
            seen.add(c)
            unique.append(c)

    # H코드 없으면 영문 텍스트 역매핑 시도
    if not unique:
        text_lower = text.lower()
        for pattern, code in _HCODE_EN_REVERSE.items():
            if re.search(pattern, text_lower) and code not in seen:
                seen.add(code)
                unique.append(code)

    return unique


def extract_hazard_statements(parse_text):
    """H코드 번호를 추출하고 HCODE_DB에서 문구를 조회하여 반환.
    가능하면 유해위험문구 섹션 내에서만 추출해 오추출 방지."""

    # ── 유해위험문구 섹션 추출 시도 ──
    section_text = ""
    sec_start = re.search(
        r"유해\s*·?\s*위험\s*문구|Hazard\s+statements?|HAZARD\s+STATEMENT",
        parse_text, re.IGNORECASE,
    )
    if sec_start:
        chunk = parse_text[sec_start.start():]
        sec_end = re.search(
            r"예방\s*조치\s*문구|Precautionary\s+statements?|PRECAUTIONARY\s+STATEMENT"
            r"|3\.\s*구성성분|Section\s*3",
            chunk, re.IGNORECASE,
        )
        section_text = chunk[:sec_end.start()] if sec_end else chunk[:3000]

    # 섹션을 찾았고 H코드가 있으면 섹션 내에서만 추출
    codes_from_section = extract_h_codes(section_text) if section_text else []
    codes = codes_from_section if codes_from_section else extract_h_codes(parse_text)

    lines = []
    for code in codes:
        desc = HCODE_DB.get(code)
        if desc:
            lines.append(f"{code} {desc}")
    return "\n".join(lines)


def extract_p_codes(text):
    """PDF 전체 텍스트에서 P코드 번호만 추출 (중복 제거, 순서 유지)
    복합 코드(P301+P310) 포함 처리"""
    text = re.sub(r"P\s*(\d{3})", r"P\1", text)
    # 복합코드 우선 탐색 후 단일코드
    raw = re.findall(r"P\d{3}(?:\+P\d{3})+|P\d{3}", text)
    seen = set()
    unique = []
    for c in raw:
        if c not in seen:
            seen.add(c)
            unique.append(c)
    return unique


def _lookup_p_code(code):
    """PCODE_DB에서 코드 조회. 복합코드(P301+P310)는 합성키 우선, 없으면 앞 코드."""
    if code in PCODE_DB:
        return PCODE_DB[code]
    # 복합코드인 경우 첫 번째 코드로 fallback
    first = code.split("+")[0]
    return PCODE_DB.get(first)


def extract_precautionary_statements(parse_text):
    """P코드 번호를 추출하고 PCODE_DB에서 문구를 조회, 섹션별로 구성하여 반환.
    P코드가 없으면 영문 PRECAUTIONARY 텍스트를 섹션별로 파싱 후 번역."""
    codes = extract_p_codes(parse_text)

    prevention, response, storage, disposal = [], [], [], []

    for code in codes:
        desc = _lookup_p_code(code)
        if not desc:
            continue
        line = f"{code} {desc}"
        first_num = int(re.search(r"P(\d{3})", code).group(1))
        if 200 <= first_num < 300:
            prevention.append(line)
        elif 300 <= first_num < 400:
            response.append(line)
        elif 400 <= first_num < 500:
            storage.append(line)
        elif 500 <= first_num < 600:
            disposal.append(line)

    if prevention or response or storage or disposal:
        output = ""
        if prevention:
            output += "<예방>\n" + "\n".join(prevention) + "\n"
        if response:
            output += "<대응>\n" + "\n".join(response) + "\n"
        if storage:
            output += "<저장>\n" + "\n".join(storage) + "\n"
        if disposal:
            output += "<폐기>\n" + "\n".join(disposal) + "\n"
        return output.strip()

    # ── Fallback: 영문 PRECAUTIONARY 텍스트 파싱 ──
    return _extract_precautionary_from_english_text(parse_text)


def _extract_precautionary_from_english_text(text: str) -> str:
    """P코드 없는 영문 SDS에서 Prevention/Response/Storage/Disposal 섹션을 추출하고 번역"""
    m = re.search(r"PRECAUTIONARY\s+STATEMENT|Precautionary\s+[Ss]tatements?", text, re.IGNORECASE)
    if not m:
        return ""

    block = text[m.end():]

    # 다음 주요 섹션 헤더에서 잘라냄
    end_m = re.search(
        r"\n\s*\d+\.\s+[A-Z]|\n\s*Section\s+\d|\n\s*3\.\s*Compos",
        block, re.IGNORECASE
    )
    if end_m:
        block = block[:end_m.start()]

    EN_SECTIONS = {
        "예방": re.compile(r"\bPrevention\b", re.IGNORECASE),
        "대응": re.compile(r"\bResponse\b",   re.IGNORECASE),
        "저장": re.compile(r"\bStorage\b",    re.IGNORECASE),
        "폐기": re.compile(r"\bDisposal\b",   re.IGNORECASE),
    }

    # 섹션 위치를 찾아 순서대로 잘라냄
    positions = []
    for sec_name, pat in EN_SECTIONS.items():
        mm = pat.search(block)
        if mm:
            positions.append((mm.start(), sec_name, mm.end()))
    positions.sort(key=lambda x: x[0])

    sec_data = []
    for idx, (pos, sec_name, content_start) in enumerate(positions):
        end_pos = positions[idx + 1][0] if idx + 1 < len(positions) else len(block)
        raw = block[content_start:end_pos].strip()
        lines = [l.strip() for l in raw.splitlines() if len(l.strip()) > 5]
        if not lines:
            continue
        selected = lines[:2]
        sec_data.append((sec_name, selected))

    if not sec_data:
        return ""

    # 섹션별 내용을 모아서 한 번에 번역 (줄바꿈으로 구분, 번호 접두사로 위치 추적)
    all_lines = [l for _, ls in sec_data for l in ls]
    # 번호 접두사(1. 2. 3. ...)를 붙여 번역 후 파싱
    numbered = "\n".join(f"{i+1}. {l}" for i, l in enumerate(all_lines))
    translated_batch = translate_to_korean(numbered)

    # 번역 결과에서 번호 접두사 기준으로 파싱
    translated_lines = []
    for line in translated_batch.splitlines():
        line = line.strip()
        if not line:
            continue
        # "1. 텍스트" 형식 파싱
        m = re.match(r"^\d+\.\s*(.*)", line)
        translated_lines.append(m.group(1).strip() if m else line)

    # 개수 맞추기 (번역 API가 줄을 합칠 수 있어 부족하면 원문 사용)
    while len(translated_lines) < len(all_lines):
        translated_lines.append(all_lines[len(translated_lines)])

    ptr = 0
    output = ""
    for sec_name, selected in sec_data:
        chunk = translated_lines[ptr:ptr + len(selected)]
        ptr += len(selected)
        output += f"<{sec_name}>\n" + "\n".join(chunk) + "\n"

    return output.strip()


def extract_precautionary_statements_retry(parse_text):
    """fallback: extract_precautionary_statements와 동일"""
    return extract_precautionary_statements(parse_text)


# =========================
# 회사별 예방조치문구 추출 (래퍼)
# =========================
def extract_precautionary_statements_oci(text):
    return extract_precautionary_statements(text)

def extract_precautionary_statements_sigma(text):
    return extract_precautionary_statements(text)

def extract_precautionary_statements_daejung(text):
    return extract_precautionary_statements(text)

def extract_precautionary_statements_duksan(text):
    return extract_precautionary_statements(text)

def extract_precautionary_statements_samchun(text):
    return extract_precautionary_statements(text)

def extract_precautionary_statements_sk(text):
    return extract_precautionary_statements(text)

def extract_precautionary_statements_noru(text):
    return extract_precautionary_statements(text)

def extract_precautionary_statements_soil(text):
    return extract_precautionary_statements(text)

def extract_precautionary_statements_kanto(text):
    return extract_precautionary_statements(text)


# =========================
# 예방조치문구 섹션 분리
# =========================
def split_p_statements_by_section(text):
    text = clean_text(text)
    text = text.replace("＜", "<").replace("＞", ">")
    text = text.replace("〈", "<").replace("〉", ">")
    text = re.sub(r"\n+", "\n", text)

    sections = {"예방": [], "대응": [], "저장": [], "폐기": []}
    current_section = None
    current_statement = ""

    for line in text.splitlines():
        line = line.strip()
        # "- P210 ..." 형식 → "P210 ..." 로 정규화 (Chlorine 등)
        line = re.sub(r"^-\s*(P\d{3})", r"\1", line)
        if not line:
            continue

        if re.search(
            r"Section\s*3|3\.\s*구성성분"
            r"|보건\s*화재|※\s*0\s*=\s*불충분"
            r"|(제품\s*)?NFPA"
            r"|기타\s*유해|포함되지\s*않는\s*기타|분류되지\s*않은\s*유해",
            line, re.IGNORECASE
        ):
            if current_statement and current_section:
                sections[current_section].append(current_statement.strip())
            break

        normalized = re.sub(r"\s+", "", line)
        normalized = normalized.replace("•", "").replace("·", "")
        normalized = normalized.replace("●", "").replace("▪", "")
        # ① ② ③ ④ 원문자 및 숫자/기호 접두어 제거 후 섹션 감지
        normalized_no_space = re.sub(r"^[0-9가-힣A-Za-z\.\)\(①②③④⑤\-]+", "", normalized)

        if re.search(r"예방|취급", normalized_no_space):
            if "예방조치문구" not in normalized_no_space:
                if current_statement and current_section:
                    sections[current_section].append(current_statement.strip())
                current_section = "예방"
                current_statement = ""
                p_match = re.search(r"(P\d{3}.*)", line)
                if p_match:
                    current_statement = p_match.group(1)
                continue

        elif re.search(r"대응|응급|처치", normalized_no_space):
            if current_statement and current_section:
                sections[current_section].append(current_statement.strip())
            current_section = "대응"
            current_statement = ""
            p_match = re.search(r"(P\d{3}.*)", line)
            if p_match:
                current_statement = p_match.group(1)
            continue

        elif re.search(r"저장|보관", normalized_no_space):
            if current_statement and current_section:
                sections[current_section].append(current_statement.strip())
            current_section = "저장"
            current_statement = ""
            p_match = re.search(r"(P\d{3}.*)", line)
            if p_match:
                current_statement = p_match.group(1)
            continue

        elif re.search(r"폐기", normalized_no_space):
            if "유해위험성" in line:
                continue
            if current_statement and current_section:
                sections[current_section].append(current_statement.strip())
            current_section = "폐기"
            current_statement = ""
            continue

        if re.match(r"^P\d{3}", line):
            # P코드 번호로 섹션 자동 판별
            if re.match(r"^P2\d{2}", line):
                auto_section = "예방"
            elif re.match(r"^P3\d{2}", line):
                auto_section = "대응"
            elif re.match(r"^P4\d{2}", line):
                auto_section = "저장"
            elif re.match(r"^P5\d{2}", line):
                auto_section = "폐기"
            else:
                auto_section = current_section  # P1xx 등 예외는 현재 섹션 유지

            # 섹션이 바뀌었으면 이전 문장 저장 후 섹션 전환
            if auto_section and auto_section != current_section:
                if current_statement and current_section:
                    sections[current_section].append(current_statement.strip())
                current_section = auto_section
                current_statement = line
            else:
                if current_statement and current_section:
                    sections[current_section].append(current_statement.strip())
                current_statement = line
        else:
            if re.search(r"(유해위험성|분류기준|예방조치문구|기타유해성|NFPA)", line):
                continue
            if current_statement:
                line = line.strip()
                if re.search(
                    r"기타유해|유해위험성|포함되지않는기타|분류되지않은유해"
                    r"|보건\s*화재|※\s*0\s*=\s*불충분",
                    line
                ):
                    continue
                if line not in current_statement:
                    current_statement += " " + line

    if current_statement and current_section:
        sections[current_section].append(current_statement.strip())

    for key in sections:
        unique = []
        for item in sections[key]:
            item = re.sub(r"\s+", " ", item).strip()
            if item not in unique:
                unique.append(item)
        sections[key] = unique

    return sections


def split_p_statements_by_section_oci(text):
    text = clean_text(text)
    text = text.replace("＜", "<").replace("＞", ">")
    text = text.replace("〈", "<").replace("〉", ">")
    text = re.sub(r"P\s*(\d{3})", r"P\1", text)

    sections = {"예방": [], "대응": [], "저장": [], "폐기": []}
    current_section = None

    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if re.search(r"NFPA|3\.\s*구성성분|Section\s*3", line, re.IGNORECASE):
            break
        normalized = line.replace(" ", "")
        if normalized == "예방":
            current_section = "예방"
        elif normalized == "대응":
            current_section = "대응"
        elif normalized == "저장":
            current_section = "저장"
        elif normalized == "폐기":
            current_section = "폐기"
        elif re.match(r"^P\d{3}", line) and current_section:
            sections[current_section].append(line)

    return sections


split_function_map = {
    "OCI": split_p_statements_by_section_oci,
    "SIGMA": split_p_statements_by_section,
    "DAEJUNG": split_p_statements_by_section,
    "DUKSAN": split_p_statements_by_section,
    "SAMCHUN": split_p_statements_by_section,
    "SK": split_p_statements_by_section,
    "NORU": split_p_statements_by_section,
    "SOIL": split_p_statements_by_section,
    "KANTO": split_p_statements_by_section,
    "DEFAULT": split_p_statements_by_section,
}


def select_precautionary_statements(text, company_type="DEFAULT", total_count=9, spec=None):
    """extract_precautionary_statements() 출력(<섹션> 형식)에서 규격별 개수로 선택"""
    sections = {"예방": [], "대응": [], "저장": [], "폐기": []}
    current = None

    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        # <예방> / <대응> / <저장> / <폐기> 헤더 감지
        m = re.match(r"<(예방|대응|저장|폐기)>", line)
        if m:
            current = m.group(1)
            continue
        if current:
            sections[current].append(line)  # P코드·번역 텍스트 모두 허용

    # 규격별 선택 개수
    if spec and spec["label_h"] >= 120:
        limits = {"예방": 2, "대응": 3, "저장": 1, "폐기": 1}
    else:
        limits = {"예방": 2, "대응": 2, "저장": 2, "폐기": 1}

    output = ""
    for key in ["예방", "대응", "저장", "폐기"]:
        items = sections[key][:limits[key]]
        if items:
            output += f"<{key}>\n" + "\n".join(items) + "\n"

    return output.strip()


# =========================
# H코드 및 그림문자
# =========================
def get_h_codes(text):
    """hazard 문구 또는 원문 텍스트에서 H코드 리스트 반환"""
    return re.findall(r"H\d{3}", text)


def match_pictograms(h_codes):
    pictograms = set()
    for h in h_codes:
        # 폭발성
        if h in ["H200", "H201", "H202", "H203", "H204", "H205"]:
            pictograms.add("exploding_bomb.png")
        # 인화성
        if h in ["H220", "H221", "H222", "H223", "H224", "H225", "H226",
                 "H228", "H240", "H241", "H242", "H250", "H251", "H252",
                 "H260", "H261"]:
            pictograms.add("flame.png")
        # 산화성
        if h in ["H270", "H271", "H272"]:
            pictograms.add("flame_over_circle.png")
        # 고압가스
        if h in ["H280", "H281"]:
            pictograms.add("gas_cylinder.png")
        # 부식성 (금속, 피부, 눈)
        if h in ["H290", "H314", "H318"]:
            pictograms.add("corrosion.png")
        # 급성독성 (치명·유독 수준)
        if h in ["H300", "H301", "H310", "H311", "H330", "H331"]:
            pictograms.add("skull.png")
        # 자극성·유해 (skull 이하 수준)
        if h in ["H302", "H312", "H315", "H316", "H317", "H319",
                 "H320", "H332", "H335", "H336"]:
            pictograms.add("exclamation.png")
        # 건강 유해성
        if h in ["H304", "H305", "H334",
                 "H340", "H341", "H350", "H351",
                 "H360", "H361", "H362",
                 "H370", "H371", "H372", "H373"]:
            pictograms.add("health_hazard.png")
        # 환경 유해성
        if h in ["H400", "H410", "H411", "H412", "H413",
                 "H420"]:
            pictograms.add("environment.png")
    return sorted(list(pictograms))


