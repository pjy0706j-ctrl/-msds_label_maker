"""산업안전보건표지 출력 탭.

assets(safety_signs) 폴더를 스캔하여 카테고리별 표지를 자동으로 불러오고,
선택한 표지를 원하는 규격의 HTML(인쇄용)로 출력하는 독립 Flet 모듈.

새 PNG 파일을 safety_signs/<category>/ 폴더에 추가하면 코드 수정 없이
자동으로 목록에 반영됨.
"""

import os
import sys
import base64
import webbrowser
from dataclasses import dataclass, field

import flet as ft

if getattr(sys, "frozen", False):
    # PyInstaller 번들: safety_signs는 assets/ 하위에 위치 (ghs_images와 동일 규칙)
    BASE_DIR = os.path.join(sys._MEIPASS, "assets")
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SAFETY_SIGNS_DIR = os.path.join(BASE_DIR, "safety_signs")

# PDF 출력 파일은 항상 실행 파일이 위치한 폴더 기준으로 저장
APP_DIR = os.path.dirname(os.path.abspath(sys.argv[0])) if getattr(sys, "frozen", False) \
    else os.path.dirname(os.path.abspath(__file__))

BORDER = ft.Border(
    top=ft.BorderSide(1, "#DEE2E6"),
    bottom=ft.BorderSide(1, "#DEE2E6"),
    left=ft.BorderSide(1, "#DEE2E6"),
    right=ft.BorderSide(1, "#DEE2E6"),
)
BG_PANEL  = "#F8F9FA"
BG_HEADER = "#E9ECEF"

CATEGORY_LABELS = {
    "prohibition": "금지표지",
    "warning": "경고표지",
    "mandatory": "지시표지",
    "emergency": "안내표지",
}

# 파일명(확장자 제외) → 한글 표지명. 매핑이 없으면 파일명을 자동 변환하여 표시(확장 시 코드 수정 불필요).
SIGN_NAME_KR = {
    "no_entry": "출입금지",
    "no_open_flame": "화기금지",
    "do_not_use": "사용금지",
    "no_entry_unless_authorized": "관계자 외 출입금지",
    "no_pedestrians": "보행금지",

    "caution_forklift": "지게차 주의",
    "caution_gears": "기어 주의",
    "caution_hand_crush": "손 끼임 주의",
    "caution_noisy_area": "소음 주의",
    "caution_risk_of_danger": "위험 주의",
    "caution_trip_harzard": "걸림 주의",
    "caution_under_repair": "수리중 주의",
    "caution_watch_your_hand": "손 주의",
    "cold_hazard": "저온 경고",
    "corrosion_warning": "부식성물질 경고",
    "electrical_harzard": "감전 위험",
    "exploding_bomb_warning": "폭발성물질 경고",
    "falling_objects": "낙하물 주의",
    "flame_over_circle_warning": "산화성물질 경고",
    "flame_warning": "발화성물질 경고",
    "health_hazard_warning": "건강유해성 경고",
    "hot_surface": "고온 경고",
    "no_unauthorized_access": "관계자 외 출입금지",
    "radiation_harzard": "방사선 위험",
    "skull_warning": "독성물질 경고",

    "wear_dust_mask": "방진마스크 착용",
    "wear_ear_protection": "보호귀 착용",
    "wear_eye_ear_head_protection": "보안경·보호귀·안전모 착용",
    "wear_eye_protection": "보안경 착용",
    "wear_face_shield": "보호안면 착용",
    "wear_foot_pretection": "안전화 착용",
    "wear_foot_protection_gloves": "안전화·안전장갑 착용",
    "wear_gas_mask": "방독마스크 착용",
    "wear_head_protection": "안전모 착용",
    "wear_protective_clothes": "보호복 착용",
    "wear_protective_clothes_hot": "방열복 착용",
    "wear_protective_gloves": "보호장갑 착용",
    "wear_safety_harness": "안전대 착용",

    "emergency_stop_switch": "비상정지 스위치",
    "eye_wash_station": "세안장치",
    "first_exit": "비상구",
    "safety_passage": "안전통로",
    "safety_shower": "비상샤워장치",
}


def humanize_filename(stem: str) -> str:
    """매핑이 없는 파일명을 보기 좋게 변환하는 fallback."""
    return stem.replace("_", " ").strip().title()


@dataclass
class SafetySign:
    """표지 1개를 표현하는 데이터 모델 (추후 복합표지·사용자 정의 표지 확장의 기반 단위)."""

    category: str
    key: str          # 파일명(확장자 제외)
    path: str         # 절대경로
    name_kr: str = field(default="")

    def __post_init__(self):
        if not self.name_kr:
            self.name_kr = SIGN_NAME_KR.get(self.key, humanize_filename(self.key))


class SafetySignLibrary:
    """safety_signs 폴더를 스캔하여 카테고리별 표지 목록을 관리.

    PNG 파일을 추가/삭제하면 reload() 또는 재실행 시 자동으로 목록에 반영된다.
    """

    def __init__(self, root_dir: str = SAFETY_SIGNS_DIR):
        self.root_dir = root_dir
        self.signs_by_category: dict[str, list[SafetySign]] = {}
        self.reload()

    def reload(self):
        self.signs_by_category = {}
        for category in CATEGORY_LABELS:
            folder = os.path.join(self.root_dir, category)
            signs = []
            if os.path.isdir(folder):
                for fname in sorted(os.listdir(folder)):
                    if fname.lower().endswith(".png"):
                        key = os.path.splitext(fname)[0]
                        signs.append(SafetySign(category=category, key=key,
                                                 path=os.path.join(folder, fname)))
            self.signs_by_category[category] = signs

    def all_signs(self) -> list[SafetySign]:
        result = []
        for signs in self.signs_by_category.values():
            result.extend(signs)
        return result

    def search(self, keyword: str) -> list[SafetySign]:
        """추후 확장 포인트: 표지 이름/카테고리 키워드 검색."""
        keyword = (keyword or "").strip()
        if not keyword:
            return self.all_signs()
        return [s for s in self.all_signs()
                if keyword in s.name_kr or keyword in s.key]


# ── 출력 규격 ────────────────────────────────────────────────
# 아이라벨(label.kr) 실제 라벨지 규격. A4(210×297mm) 기준으로 칸·여백·간격을 정확히 반영.
#   w_mm/h_mm   : 라벨 1칸 크기
#   cols/rows   : A4 한 장당 열·행 수
#   margin_left : 좌우 여백, margin_top : 상하 여백
#   gap_x/gap_y : 칸 사이 가로·세로 간격
#   corner_r    : 라벨 모서리 라운드(mm)
PRINT_SPECS = {
    "아이라벨 424 (100×70mm · 8칸)": {
        "w_mm": 100.0, "h_mm": 70.0, "cols": 2, "rows": 4,
        "margin_left": 5.0, "margin_top": 5.5, "gap_x": 0.0, "gap_y": 2.0,
        "corner_r": 2.0,
    },
    "아이라벨 812 (196×125mm · 2칸)": {
        "w_mm": 196.0, "h_mm": 125.0, "cols": 1, "rows": 2,
        "margin_left": 7.0, "margin_top": 18.5, "gap_x": 0.0, "gap_y": 10.0,
        "corner_r": 0.0,
    },
    "아이라벨 211 (199.1×288mm · 1칸)": {
        "w_mm": 199.1, "h_mm": 288.0, "cols": 1, "rows": 1,
        "margin_left": 5.45, "margin_top": 4.5, "gap_x": 0.0, "gap_y": 0.0,
        "corner_r": 0.0,
    },
}
DEFAULT_SPEC = "아이라벨 424 (100×70mm · 8칸)"


def _img_to_base64(path: str) -> str:
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


class SafetySignHtmlBuilder:
    """선택된 표지를 지정 라벨 규격의 인쇄용 HTML로 출력 (GHS 라벨과 동일하게 브라우저에서 열림).

    A4 한 장에 cols×rows 칸으로 배치하며, 칸을 다 채우면 다음 페이지로 넘어간다.
    각 라벨지(아이라벨)의 실제 여백·간격을 반영해 라벨 위치가 정확히 맞도록 한다.
    추후 복합표지(여러 표지를 한 칸에 합성) 확장 시 _cell_html만 교체하면 된다.
    """

    def __init__(self, spec_key: str):
        self.spec_key = spec_key
        self.spec = PRINT_SPECS.get(spec_key, PRINT_SPECS[DEFAULT_SPEC])

    def build(self, signs: list[SafetySign], output_path: str) -> str:
        html = self._build_grid(signs)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(html)
        return output_path

    def _cell_html(self, sign: SafetySign) -> str:
        b64 = _img_to_base64(sign.path)
        return (
            f'<div class="sign">'
            f'<img src="data:image/png;base64,{b64}">'
            f'</div>'
        )

    def _build_grid(self, signs: list[SafetySign]) -> str:
        s = self.spec
        per_page = s["cols"] * s["rows"]
        # 빈 칸을 placeholder로 채워 그리드 정렬 유지
        sheets = []
        for start in range(0, len(signs), per_page):
            chunk = signs[start:start + per_page]
            cells = "".join(self._cell_html(sign) for sign in chunk)
            cells += '<div class="sign empty"></div>' * (per_page - len(chunk))
            sheets.append(f'<div class="sheet">{cells}</div>')
        sheets_html = "\n".join(sheets)

        return f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<style>
@page {{ size: 210mm 297mm; margin: 0; }}
body {{ margin:0; padding:0; font-family:'Malgun Gothic',Arial,sans-serif;
       -webkit-print-color-adjust:exact; print-color-adjust:exact; }}
.sheet {{
    width:210mm; height:297mm; box-sizing:border-box;
    padding:{s['margin_top']}mm {s['margin_left']}mm;
    display:grid;
    grid-template-columns:repeat({s['cols']}, {s['w_mm']}mm);
    grid-template-rows:repeat({s['rows']}, {s['h_mm']}mm);
    column-gap:{s['gap_x']}mm; row-gap:{s['gap_y']}mm;
    page-break-after:always;
}}
.sign {{
    width:{s['w_mm']}mm; height:{s['h_mm']}mm; box-sizing:border-box;
    border:1px solid #999; border-radius:{s['corner_r']}mm;
    display:flex; align-items:center; justify-content:center;
    overflow:hidden;
}}
.sign.empty {{ border:1px dashed #ddd; }}
.sign img {{ width:90%; height:90%; object-fit:contain; }}
</style></head><body>
{sheets_html}
</body></html>"""


# ── Flet UI ──────────────────────────────────────────────────
def build_safety_sign_tab(page: ft.Page) -> ft.Row:
    """'산업안전보건표지 출력' 탭 콘텐츠를 생성. main_flet.py 의 Tabs 에 연결해서 사용."""

    library = SafetySignLibrary()
    sign_by_path = {s.path: s for s in library.all_signs()}
    quantities: dict[str, int] = {}   # path → 출력 수량(부수). 0/없음 = 미선택
    checkbox_by_path: dict[str, ft.Checkbox] = {}

    preview_grid = ft.GridView(
        expand=True, max_extent=240,
        child_aspect_ratio=0.72, spacing=12, run_spacing=12,
    )
    spec_radio = ft.RadioGroup(
        value=DEFAULT_SPEC,
        content=ft.Column(
            [ft.Radio(value=k, label=k) for k in PRINT_SPECS],
            spacing=4,
        ),
    )
    status_text = ft.Text("", size=12, color="#6C757D")
    count_text = ft.Text("", size=13, weight=ft.FontWeight.BOLD, color="#343A40")

    def cells_per_sheet() -> int:
        s = PRINT_SPECS.get(spec_radio.value, PRINT_SPECS[DEFAULT_SPEC])
        return s["cols"] * s["rows"]

    def total_qty() -> int:
        return sum(q for q in quantities.values() if q > 0)

    def update_count_label():
        per = cells_per_sheet()
        total = total_qty()
        sheets = (total + per - 1) // per if total else 0
        count_text.value = f"선택 수량: {total}개  /  한 장 {per}칸  →  {sheets}장 출력"
        page.update()

    def set_qty(path: str, qty: int):
        qty = max(0, qty)
        if qty == 0:
            quantities.pop(path, None)
            cb = checkbox_by_path.get(path)
            if cb:
                cb.value = False
        else:
            quantities[path] = qty
            cb = checkbox_by_path.get(path)
            if cb:
                cb.value = True
        refresh_preview()

    def refresh_preview():
        preview_grid.controls.clear()
        for sign in library.all_signs():
            qty = quantities.get(sign.path, 0)
            if qty > 0:
                preview_grid.controls.append(
                    ft.Container(
                        content=ft.Column([
                            ft.Image(src=sign.path, width=150, height=150,
                                     fit=ft.BoxFit.CONTAIN),
                            ft.Text(sign.name_kr, size=13, weight=ft.FontWeight.BOLD,
                                    text_align=ft.TextAlign.CENTER),
                            ft.Row([
                                ft.ElevatedButton(
                                    "−", width=42, height=36, tooltip="수량 -",
                                    style=ft.ButtonStyle(
                                        bgcolor="#E9ECEF", color="#212529",
                                        text_style=ft.TextStyle(size=18, weight=ft.FontWeight.BOLD),
                                        padding=0),
                                    on_click=lambda e, p=sign.path: set_qty(p, quantities.get(p, 0) - 1)),
                                ft.Container(
                                    content=ft.Text(f"{qty}", size=16, weight=ft.FontWeight.BOLD),
                                    width=40, alignment=ft.Alignment(0, 0),
                                ),
                                ft.ElevatedButton(
                                    "+", width=42, height=36, tooltip="수량 +",
                                    style=ft.ButtonStyle(
                                        bgcolor="#1971C2", color="white",
                                        text_style=ft.TextStyle(size=18, weight=ft.FontWeight.BOLD),
                                        padding=0),
                                    on_click=lambda e, p=sign.path: set_qty(p, quantities.get(p, 0) + 1)),
                            ], alignment=ft.MainAxisAlignment.CENTER, spacing=4),
                        ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=4),
                        padding=10, border=BORDER, border_radius=6, bgcolor="white",
                    )
                )
        update_count_label()

    def on_toggle(sign: SafetySign, value: bool):
        set_qty(sign.path, 1 if value else 0)

    def build_category_block(category: str) -> ft.Column:
        signs = library.signs_by_category.get(category, [])
        checkboxes = []
        for sign in signs:
            cb = ft.Checkbox(
                label=sign.name_kr, value=False,
                on_change=lambda e, s=sign: on_toggle(s, e.control.value),
            )
            checkbox_by_path[sign.path] = cb
            checkboxes.append(cb)
        return ft.Column([
            ft.Text(f"[{CATEGORY_LABELS[category]}]", size=13,
                    weight=ft.FontWeight.BOLD, color="#495057"),
            *checkboxes,
            ft.Divider(color="#DEE2E6"),
        ], spacing=2)

    selection_column = ft.Column(
        [build_category_block(cat) for cat in CATEGORY_LABELS],
        scroll=ft.ScrollMode.AUTO, spacing=6, expand=True,
    )

    def fill_sheet(e):
        """현재 선택된 표지들로 한 장(칸 수)을 균등하게 꽉 채움.
        - 1종만 선택 → 그 표지로 모든 칸을 채움 (동일 표지 N개)
        - 여러 종 선택 → 칸을 종류 수로 나눠 균등 분배 (나머지는 앞쪽부터 +1)
        - 아무것도 선택 안 함 → 안내 메시지
        """
        chosen_paths = [p for p, q in quantities.items() if q > 0]
        if not chosen_paths:
            status_text.value = "⚠ 먼저 표지를 1개 이상 선택하세요."
            page.update()
            return
        per = cells_per_sheet()
        n = len(chosen_paths)
        base, extra = divmod(per, n)
        # 라이브러리 순서대로 정렬해 분배가 일관되게
        ordered = [s.path for s in library.all_signs() if s.path in chosen_paths]
        for i, path in enumerate(ordered):
            quantities[path] = base + (1 if i < extra else 0)
        refresh_preview()
        status_text.value = f"✅ 한 장({per}칸)을 선택 표지로 채웠습니다."
        page.update()

    def clear_all(e):
        for path in list(quantities.keys()):
            quantities.pop(path, None)
            cb = checkbox_by_path.get(path)
            if cb:
                cb.value = False
        refresh_preview()
        status_text.value = "전체 선택을 해제했습니다."
        page.update()

    def on_generate_html(e):
        # 라이브러리 순서대로, 각 표지를 수량만큼 반복하여 칸 채우기
        chosen = []
        for sign in library.all_signs():
            qty = quantities.get(sign.path, 0)
            chosen.extend([sign] * qty)
        if not chosen:
            status_text.value = "⚠ 출력할 표지를 1개 이상 선택하세요."
            page.update()
            return
        out_path = os.path.join(APP_DIR, "safety_signs_print.html")
        SafetySignHtmlBuilder(spec_radio.value).build(chosen, out_path)
        status_text.value = f"🖨 인쇄 창 열기: {out_path}"
        page.update()
        webbrowser.open(out_path)

    spec_radio.on_change = lambda e: update_count_label()

    def panel(title, content, expand=1):
        return ft.Container(
            content=ft.Column([
                ft.Container(
                    content=ft.Text(title, size=14, weight=ft.FontWeight.BOLD, color="#495057"),
                    bgcolor=BG_HEADER,
                    padding=ft.padding.Padding(left=12, right=8, top=6, bottom=6),
                    border_radius=ft.border_radius.BorderRadius(
                        top_left=6, top_right=6, bottom_left=0, bottom_right=0),
                ),
                ft.Container(content=content, padding=10, expand=True),
            ], spacing=0, expand=True),
            border=BORDER, border_radius=6, bgcolor=BG_PANEL,
            expand=expand,
        )

    selection_panel = panel("🚧 표지 선택", selection_column)
    preview_panel = panel("🖼 미리보기 (각 표지 수량 조절)", preview_grid)
    spec_panel = panel(
        "📐 출력 규격 / 수량",
        ft.Column([
            spec_radio,
            ft.Divider(color="#DEE2E6"),
            count_text,
            ft.Container(height=6),
            ft.ElevatedButton("🧩 선택 표지로 한 장 꽉 채우기", on_click=fill_sheet,
                              width=10000,
                              style=ft.ButtonStyle(bgcolor="#1971C2", color="white")),
            ft.OutlinedButton("🗑 전체 해제", on_click=clear_all, width=10000),
            ft.Container(height=12),
            ft.ElevatedButton("🖨 인쇄 HTML 생성", on_click=on_generate_html,
                              width=10000,
                              style=ft.ButtonStyle(bgcolor="#343A40", color="white")),
            ft.Container(height=8),
            status_text,
        ], spacing=6),
    )

    update_count_label()

    return ft.Row(
        controls=[selection_panel, preview_panel, spec_panel],
        spacing=10, expand=True, vertical_alignment=ft.CrossAxisAlignment.STRETCH,
    )
