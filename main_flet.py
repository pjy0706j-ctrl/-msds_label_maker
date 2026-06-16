import flet as ft
import tkinter as tk
from tkinter import filedialog
import webbrowser
import os
import threading
import fitz as _fitz

from config import label_specs
from msds_parser import (
    extract_text_from_pdf_path,
    extract_product_name,
    extract_product_name_retry,
    extract_supplier_info,
    extract_signal_word,
    extract_hazard_statements,
    extract_precautionary_statements,
    select_precautionary_statements,
    get_h_codes,
    match_pictograms,
    detect_company,
    detect_company_from_filename,
)
from label_generator import make_pictogram_html, make_label_html


PICTOGRAM_OPTIONS = {
    "exploding_bomb.png": "폭발성",
    "flame.png": "인화성",
    "flame_over_circle.png": "산화성",
    "gas_cylinder.png": "고압가스",
    "corrosion.png": "부식성",
    "skull.png": "급성독성",
    "exclamation.png": "자극성",
    "health_hazard.png": "건강유해성",
    "environment.png": "환경유해성",
}

BG_PANEL  = "#F8F9FA"
BG_HEADER = "#E9ECEF"
ACCENT    = "#2196F3"
BORDER    = ft.Border(
    top=ft.BorderSide(1, "#DEE2E6"),
    bottom=ft.BorderSide(1, "#DEE2E6"),
    left=ft.BorderSide(1, "#DEE2E6"),
    right=ft.BorderSide(1, "#DEE2E6"),
)


def panel(title: str, controls: list, width=None, expand=False,
          header_action=None) -> ft.Container:
    header_content = ft.Row([
        ft.Text(title, size=14, weight=ft.FontWeight.BOLD, color="#495057", expand=True),
        *([ header_action ] if header_action else []),
    ], vertical_alignment=ft.CrossAxisAlignment.CENTER)

    return ft.Container(
        content=ft.Column(
            controls=[
                ft.Container(
                    content=header_content,
                    bgcolor=BG_HEADER,
                    padding=ft.padding.Padding(left=12, right=8, top=6, bottom=6),
                    border_radius=ft.border_radius.BorderRadius(top_left=6, top_right=6, bottom_left=0, bottom_right=0),
                ),
                ft.Container(
                    content=ft.Column(controls=controls, scroll=ft.ScrollMode.AUTO,
                                      spacing=8, expand=True),
                    padding=10,
                    expand=True,
                ),
            ],
            spacing=0,
            expand=True,
        ),
        border=BORDER,
        border_radius=6,
        bgcolor=BG_PANEL,
        width=width,
        expand=expand,
    )


def main(page: ft.Page):
    page.title = "MSDS Label Maker v1.0.0 (2026-06-16)"
    page.window.width  = 1600
    page.window.height = 960
    page.bgcolor = "#F1F3F5"
    page.padding = 10
    page.spacing = 8

    # ── 상태 변수 ──────────────────────────────────────────
    current_doc       = None
    current_page_idx  = 0
    preview_serial    = [0]
    raw_text_store    = [""]
    _debounce_timer   = [None]    # 자동 갱신 디바운스 타이머
    _render_token     = [0]       # 렌더링 취소 토큰 (새 요청 시 증가)
    _render_thread    = [None]    # 현재 렌더링 스레드

    # ── 공통 위젯 ─────────────────────────────────────────
    selected_pdf_text  = ft.Text("파일 없음", size=12, color="#6C757D", expand=True)
    page_number_text   = ft.Text("0 / 0", size=12, width=60)
    status_bar         = ft.Text("PDF 파일을 선택하세요.", size=12, color="#495057")

    pdf_image = ft.Image(src="", width=440, height=580, fit=ft.ImageFit.FIT_WIDTH
                         if hasattr(ft, "ImageFit") else None)

    raw_text_field = ft.TextField(
        multiline=True, min_lines=5, max_lines=12,
        read_only=True,
        hint_text="[원문 텍스트 보기] 버튼을 누르면 표시됩니다.",
        text_size=11,
        border_color="#CED4DA",
    )

    # ── 라벨 규격 ─────────────────────────────────────────
    selected_label_type = ft.Dropdown(
        label="라벨 규격",
        value="아이라벨_CL233MP (9칸)",
        options=[ft.dropdown.Option(k) for k in label_specs.keys()],
    )

    # ── 추출 결과 편집 필드 ────────────────────────────────
    def tf(label, multiline=False, min_lines=1, max_lines=4):
        return ft.TextField(
            label=label,
            multiline=multiline,
            min_lines=min_lines,
            max_lines=max_lines,
            border_color="#CED4DA",
            focused_border_color=ACCENT,
            text_size=13,
            # on_change는 schedule_refresh 정의 후 아래에서 일괄 연결
        )

    product_field      = tf("제품명")
    signal_field       = tf("신호어")
    hazard_field       = tf("유해·위험문구", multiline=True, min_lines=5,  max_lines=999)
    precautionary_field= tf("예방조치문구",  multiline=True, min_lines=8,  max_lines=999)
    supplier_field     = tf("공급자정보",    multiline=True, min_lines=4,  max_lines=999)

    # ── 그림문자 체크박스 ──────────────────────────────────
    pictogram_checkboxes = {}
    for fname, lname in PICTOGRAM_OPTIONS.items():
        pictogram_checkboxes[fname] = ft.Checkbox(label=lname, value=False)

    def get_selected_pictograms():
        return [f for f, cb in pictogram_checkboxes.items() if cb.value]

    # ── 폰트 설정 ─────────────────────────────────────────
    def fld(label, key):
        return ft.TextField(label=label,
                            value=str(label_specs["아이라벨_CL233MP (9칸)"][key]),
                            width=140, text_size=12, border_color="#CED4DA")

    font_product    = fld("시약명(px)",    "product_font")
    font_signal     = fld("신호어(px)",    "signal_font")
    font_title      = fld("제목(px)",      "title_font")
    font_hazard     = fld("유해문구(px)",  "text_font")
    font_precaution = fld("예방문구(px)",  "small_font")
    font_supplier   = fld("공급자(px)",    "supplier_font")
    font_msds       = ft.TextField(label="MSDS참고(px)", value="4.0",  width=140, text_size=12, border_color="#CED4DA")
    font_pic_scale  = ft.TextField(label="그림문자배율",  value="1.0",  width=140, text_size=12, border_color="#CED4DA")

    def update_font_defaults(e=None):
        spec = label_specs[selected_label_type.value]
        font_product.value    = str(spec["product_font"])
        font_signal.value     = str(spec["signal_font"])
        font_title.value      = str(spec["title_font"])
        font_hazard.value     = str(spec["text_font"])
        font_precaution.value = str(spec["small_font"])
        font_supplier.value   = str(spec["supplier_font"])
        page.update()


    # ── 라벨 미리보기 ─────────────────────────────────────
    label_preview = ft.Column(spacing=0)

    def get_font_settings():
        spec = label_specs[selected_label_type.value]
        def _f(tf_widget, fb):
            try:    return float(tf_widget.value)
            except: return float(fb)
        return {
            "product_font":    _f(font_product,    spec["product_font"]),
            "signal_font":     _f(font_signal,     spec["signal_font"]),
            "title_font":      _f(font_title,      spec["title_font"]),
            "hazard_font":     _f(font_hazard,     spec["text_font"]),
            "precaution_font": _f(font_precaution, spec["small_font"]),
            "supplier_font":   _f(font_supplier,   spec["supplier_font"]),
            "msds_font":       _f(font_msds,       4.0),
            "pictogram_scale": _f(font_pic_scale,  1.0),
        }

    def build_html():
        spec = label_specs[selected_label_type.value]
        return make_label_html(
            product_name=product_field.value or "",
            supplier_info=supplier_field.value or "",
            signal_word=signal_field.value or "",
            hazard_statements=hazard_field.value or "",
            short_precautionary_statements=precautionary_field.value or "",
            pictogram_html=make_pictogram_html(get_selected_pictograms()),
            spec=spec, offset_x=0, offset_y=0,
            font_settings=get_font_settings(),
        )

    # Edge 실행 경로 (Windows 기본 설치 위치)
    EDGE_PATHS = [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    ]
    edge_exe = next((p for p in EDGE_PATHS if os.path.exists(p)), None)

    def render_html_to_image(html: str) -> str | None:
        """HTML을 Edge 헤드리스로 PNG 렌더링. 실패 시 None 반환."""
        if not edge_exe:
            return None
        import subprocess
        base_dir = os.path.dirname(os.path.abspath(__file__))
        html_path = os.path.join(base_dir, "label_render.html")
        preview_serial[0] += 1
        png_path = os.path.join(base_dir, f"label_render_{preview_serial[0]}.png")
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(html)
        try:
            subprocess.run(
                [edge_exe,
                 "--headless", "--disable-gpu", "--no-sandbox",
                 f"--screenshot={png_path}",
                 "--window-size=794,1123",   # A4 비율
                 f"file:///{html_path.replace(os.sep, '/')}"],
                capture_output=True, timeout=15,
            )
        except Exception:
            return None
        return png_path if os.path.exists(png_path) else None

    label_render_image = ft.Image(src="", width=520, visible=False)

    # 헤더에 표시할 "변경중" 상태 위젯
    render_indicator = ft.Row([
        ft.ProgressRing(width=14, height=14, stroke_width=2, color=ft.Colors.ORANGE),
        ft.Text("변경중", size=11, color=ft.Colors.ORANGE, weight=ft.FontWeight.BOLD),
    ], visible=False, spacing=4)

    render_spinner = ft.Row([
        ft.ProgressRing(width=16, height=16, stroke_width=2, color=ft.Colors.BLUE_400),
        ft.Text("인쇄 레이아웃 렌더링 중...", size=11, color="#6C757D"),
    ], visible=False, spacing=6)

    def _set_rendering(active: bool):
        render_indicator.visible = active
        render_spinner.visible   = active and bool(edge_exe)
        page.update()

    def refresh_label():
        """① 즉시 네이티브 미리보기 → ② 백그라운드 Edge 렌더링 → ③ 완료 시 교체"""
        _render_token[0] += 1
        my_token = _render_token[0]

        # 즉시 네이티브 미리보기 + 변경중 표시
        label_preview.controls.clear()
        label_preview.controls.append(_build_flet_preview())
        _set_rendering(True)

        if not edge_exe:
            _set_rendering(False)
            return

        def _render():
            html = build_html()
            png  = render_html_to_image(html)
            if _render_token[0] != my_token:
                return            # 더 최신 요청이 있으면 폐기
            _set_rendering(False)
            if png:
                label_preview.controls.clear()
                label_render_image.src = ""
                page.update()
                label_render_image.src = png
                label_render_image.visible = True
                label_preview.controls.append(label_render_image)
            page.update()

        threading.Thread(target=_render, daemon=True).start()

    def _build_flet_preview():
        """Edge 없을 때 사용하는 Flet 네이티브 미리보기"""
        ghs_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ghs_images")
        pics = [ft.Image(src=os.path.join(ghs_dir, f), width=46, height=46)
                for f in get_selected_pictograms()
                if os.path.exists(os.path.join(ghs_dir, f))]
        signal_val   = signal_field.value or ""
        signal_color = "#C0392B" if signal_val in ("위험", "경고") else "#212529"

        def sec(title, body):
            return ft.Column([
                ft.Container(
                    content=ft.Text(title, size=11, weight=ft.FontWeight.BOLD, color="#495057"),
                    border=ft.Border(bottom=ft.BorderSide(1, "#DEE2E6")),
                    padding=ft.padding.Padding(0, 0, 0, 2),
                ),
                ft.Text(body or "", size=11, selectable=True),
            ], spacing=3)

        return ft.Container(
            content=ft.Column([
                ft.Text(product_field.value or "", size=15,
                        weight=ft.FontWeight.BOLD, text_align=ft.TextAlign.CENTER),
                ft.Row([ft.Row(pics, wrap=True, spacing=4),
                        ft.Text(signal_val, size=22, weight=ft.FontWeight.W_900, color=signal_color)],
                       alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                ft.Divider(height=1, color="#DEE2E6"),
                sec("[유해·위험문구]", hazard_field.value),
                sec("[예방조치문구]", precautionary_field.value),
                sec("[공급자정보]",   supplier_field.value),
                ft.Text("* 자세한 내용은 물질안전보건자료(MSDS) 참조 하시오",
                        size=9, italic=True, color="#6C757D", text_align=ft.TextAlign.CENTER),
            ], spacing=6),
            padding=14, border=BORDER, border_radius=6, bgcolor="white",
        )

    def on_show_raw(e):
        raw_text_field.value = raw_text_store[0][:8000] if raw_text_store[0] else "원문 없음"
        page.update()

    def on_print_html(e):
        """인쇄 전 확인 다이얼로그 표시 후 HTML 생성"""

        def _do_cancel(e):
            page.dialog.open = False
            page.update()

        def _do_print(e):
            page.dialog.open = False
            page.update()
            html = build_html()
            path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "print_label.html")
            with open(path, "w", encoding="utf-8") as f:
                f.write(html)
            threading.Thread(target=webbrowser.open, args=(path,), daemon=True).start()
            status_bar.value = f"🖨 인쇄 창 열기: {path}"
            page.update()

        page.dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("⚠  인쇄 전 필수 확인사항", size=15, weight=ft.FontWeight.BOLD,
                          color="#C0392B"),
            content=ft.Container(
                content=ft.Column([
                    ft.Text(
                        "본 프로그램은 MSDS PDF에서 경고표지 항목을 자동으로 추출하며,\n"
                        "추출 결과의 정확성을 100% 보장하지 않습니다.",
                        size=12, color="#212529",
                    ),
                    ft.Divider(height=10, color="#DEE2E6"),
                    ft.Text("인쇄 전 아래 항목을 반드시 직접 확인하세요.", size=12,
                            weight=ft.FontWeight.BOLD, color="#343A40"),
                    ft.Column([
                        ft.Text("✔  제품명이 원본 MSDS와 일치하는지 확인", size=11, color="#495057"),
                        ft.Text("✔  신호어(위험 / 경고)가 올바르게 적용됐는지 확인", size=11, color="#495057"),
                        ft.Text("✔  유해·위험문구(H코드) 누락 또는 오기재 여부 확인", size=11, color="#495057"),
                        ft.Text("✔  예방조치문구(P코드) 누락 또는 오기재 여부 확인", size=11, color="#495057"),
                        ft.Text("✔  GHS 그림문자가 해당 물질에 맞게 선택됐는지 확인", size=11, color="#495057"),
                        ft.Text("✔  공급자 정보(회사명·주소·긴급연락처)가 정확한지 확인", size=11, color="#495057"),
                        ft.Text("✔  선택한 라벨 규격이 실제 라벨지(아이라벨)와 일치하는지 확인", size=11, color="#495057"),
                    ], spacing=4),
                    ft.Divider(height=10, color="#DEE2E6"),
                    ft.Text(
                        "※ 본 프로그램은 경고표지 작성을 보조하는 도구입니다.\n"
                        "   법적 효력이 있는 최종 경고표지의 정확성에 대한 책임은\n"
                        "   출력자 본인에게 있습니다.",
                        size=11, color="#6C757D", italic=True,
                    ),
                ], spacing=8, tight=True),
                width=480,
            ),
            actions=[
                ft.TextButton("취소", on_click=_do_cancel,
                              style=ft.ButtonStyle(color="#6C757D")),
                ft.ElevatedButton(
                    "확인 완료 — 인쇄 진행",
                    on_click=_do_print,
                    style=ft.ButtonStyle(bgcolor="#C0392B", color="white"),
                ),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        page.dialog.open = True
        page.update()

    def schedule_refresh(e=None):
        """필드 변경 시 0.5초 후 자동 갱신 (디바운스)"""
        if _debounce_timer[0]:
            _debounce_timer[0].cancel()
        _debounce_timer[0] = threading.Timer(0.5, refresh_label)
        _debounce_timer[0].start()

    # ── on_change 일괄 연결 ────────────────────────────────
    for _fld in [product_field, signal_field, hazard_field,
                 precautionary_field, supplier_field,
                 font_product, font_signal, font_title,
                 font_hazard, font_precaution, font_supplier,
                 font_msds, font_pic_scale]:
        _fld.on_change = schedule_refresh
    for _cb in pictogram_checkboxes.values():
        _cb.on_change = schedule_refresh
    selected_label_type.on_select = lambda e: (update_font_defaults(), schedule_refresh())

    # ── PDF 미리보기 ──────────────────────────────────────
    def load_pdf_preview(pdf_path):
        nonlocal current_doc, current_page_idx
        current_doc = _fitz.open(pdf_path)
        current_page_idx = 0
        show_pdf_page()

    def show_pdf_page():
        if not current_doc:
            return
        pg  = current_doc[current_page_idx]
        pix = pg.get_pixmap(matrix=_fitz.Matrix(1.5, 1.5))
        preview_serial[0] += 1
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            f"temp_preview_{preview_serial[0]}.png")
        pix.save(path)
        pdf_image.src = ""
        page.update()
        pdf_image.src = path
        page_number_text.value = f"{current_page_idx+1} / {len(current_doc)}"
        page.update()

    def prev_page(e):
        nonlocal current_page_idx
        if current_doc and current_page_idx > 0:
            current_page_idx -= 1
            show_pdf_page()

    def next_page(e):
        nonlocal current_page_idx
        if current_doc and current_page_idx < len(current_doc) - 1:
            current_page_idx += 1
            show_pdf_page()


    def select_file(e):
        root = tk.Tk()
        root.attributes("-topmost", True)
        root.withdraw()
        file_path = filedialog.askopenfilename(
            parent=root, filetypes=[("PDF", "*.pdf")])
        root.destroy()
        if not file_path:
            return
        selected_pdf_text.value = os.path.basename(file_path)
        page.update()

        def _load_all():
            # PDF 미리보기 먼저 (fitz는 스레드 내에서 안전)
            load_pdf_preview(file_path)
            # 분석 (별도 스레드 내부에서 inline 실행)
            file_name = os.path.basename(file_path)
            status_bar.value = "⏳ PDF 분석 중..."
            page.update()
            try:
                text       = extract_text_from_pdf_path(file_path)
                raw_text_store[0] = text
                company    = detect_company_from_filename(file_name) or detect_company(text)
                product    = extract_product_name(text) or extract_product_name_retry(text)
                supplier   = extract_supplier_info(text)
                signal     = extract_signal_word(text)
                hazard     = extract_hazard_statements(text)
                prec       = extract_precautionary_statements(text)
                spec       = label_specs[selected_label_type.value]
                short_prec = select_precautionary_statements(prec, company_type=company, spec=spec)
                auto_pics  = match_pictograms(get_h_codes(hazard))

                product_field.value       = product    or "직접 입력 필요"
                signal_field.value        = signal     or "없음"
                hazard_field.value        = hazard     or "직접 입력 필요"
                precautionary_field.value = short_prec or "직접 입력 필요"
                supplier_field.value      = supplier   or "직접 입력 필요"
                for fname, cb in pictogram_checkboxes.items():
                    cb.value = fname in auto_pics

                status_bar.value = f"✅ 완료  |  회사: {company}"
                page.update()
                refresh_label()
            except Exception as ex:
                import traceback
                status_bar.value = f"❌ 오류: {ex}"
                page.update()

        threading.Thread(target=_load_all, daemon=True).start()

    # ── 레이아웃 조립 ─────────────────────────────────────

    # 왼쪽: 원본 PDF
    col_pdf = panel(
        "📄 원본 MSDS PDF",
        [
            ft.Row([
                ft.Button("📂 PDF 선택", on_click=select_file),
                selected_pdf_text,
            ]),
            ft.Row([
                ft.Button("◀", on_click=prev_page, width=50),
                page_number_text,
                ft.Button("▶", on_click=next_page, width=50),
                ft.Button("📋 원문 텍스트", on_click=on_show_raw),
            ]),
            pdf_image,
            raw_text_field,
        ],
        width=480,
    )

    # ── 작성 가이드 (토글) ──────────────────────────────────
    GUIDES = {
        "아이라벨_CL233MP (9칸)": {
            "색상": "#FFF3CD", "테두리": "#FFC107", "아이콘": "📌",
            "제목": "9칸 라벨 작성 가이드 (100ml 초과)",
            "항목": [
                "유해위험문구 : 해당 문구 모두 기재",
                "중복·유사 문구는 생략/조합 가능",
                "예방·대응·저장·폐기 문구 각 1개 이상 포함",
                "예방조치문구 총 6개 이상 권장",
            ],
        },
        "아이라벨_CL812MP (2칸)": {
            "색상": "#FFF3CD", "테두리": "#FFC107", "아이콘": "📌",
            "제목": "2칸 라벨 작성 가이드 (100ml 초과)",
            "항목": [
                "100ml 초과 용기 전용",
                "예방·대응·저장·폐기 문구 포함",
                "공급자 정보 전체 기재",
                "유해위험문구 해당 문구 모두 기재",
            ],
        },
        "아이라벨_CL835MP (24칸)": {
            "색상": "#D1ECF1", "테두리": "#17A2B8", "아이콘": "ℹ",
            "제목": "24칸 라벨 작성 가이드 (100ml 이하 소용량)",
            "항목": [
                "100ml 이하 소용량 용기 전용",
                "그림문자·신호어·제품명·공급자 정보 표시",
                "유해위험문구 표시 (생략 가능)",
                "세부 예방조치문구 생략 가능",
            ],
        },
    }

    guide_body = ft.Column(visible=False, spacing=4)
    guide_container = ft.Container(
        content=guide_body,
        visible=False,
        border_radius=6,
        padding=10,
    )

    def _update_guide():
        key = selected_label_type.value
        g = GUIDES.get(key, GUIDES["아이라벨_CL233MP (9칸)"])
        guide_container.bgcolor = g["색상"]
        guide_container.border = ft.Border(
            top=ft.BorderSide(1, g["테두리"]),
            bottom=ft.BorderSide(1, g["테두리"]),
            left=ft.BorderSide(3, g["테두리"]),
            right=ft.BorderSide(1, g["테두리"]),
        )
        guide_body.controls.clear()
        guide_body.controls.append(
            ft.Text(f"{g['아이콘']} {g['제목']}",
                    size=13, weight=ft.FontWeight.BOLD, color="#495057")
        )
        for item in g["항목"]:
            guide_body.controls.append(
                ft.Text(f"  • {item}", size=12, color="#333")
            )

    def on_toggle_guide(e):
        is_visible = not guide_container.visible
        guide_container.visible = is_visible
        guide_body.visible = is_visible
        guide_btn.text = "📖 작성 가이드 닫기" if is_visible else "📖 작성 가이드"
        guide_btn.style = ft.ButtonStyle(
            color=ft.Colors.WHITE if is_visible else ft.Colors.BLACK,
            bgcolor=ft.Colors.BLUE_700 if is_visible else None,
        )
        if is_visible:
            _update_guide()
        page.update()

    guide_btn = ft.Button("📖 작성 가이드", on_click=on_toggle_guide)
    _update_guide()

    # 라벨 규격 변경 시 가이드도 갱신
    _orig_on_select = selected_label_type.on_select
    def _on_spec_with_guide(e):
        if _orig_on_select:
            _orig_on_select(e)
        if guide_container.visible:
            _update_guide()
        page.update()
    selected_label_type.on_select = _on_spec_with_guide

    # 가운데: 추출 결과 편집
    cb_rows = [
        ft.Row([pictogram_checkboxes[k] for k in list(PICTOGRAM_OPTIONS)[:5]], wrap=True),
        ft.Row([pictogram_checkboxes[k] for k in list(PICTOGRAM_OPTIONS)[5:]], wrap=True),
    ]

    col_edit = panel(
        "📋 추출 결과 편집",
        [
            ft.Row([selected_label_type, guide_btn],
                   alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
            guide_container,
            product_field,
            ft.Row([signal_field]),
            hazard_field,
            precautionary_field,
            supplier_field,
            ft.Divider(color="#DEE2E6"),
            ft.Text("🖼 그림문자", size=13, weight=ft.FontWeight.BOLD, color="#495057"),
            *cb_rows,
            ft.Divider(color="#DEE2E6"),
            ft.Text("⚙ 글자 크기", size=13, weight=ft.FontWeight.BOLD, color="#495057"),
            ft.Row([font_product, font_signal, font_title], wrap=True),
            ft.Row([font_hazard, font_precaution, font_supplier], wrap=True),
            ft.Row([font_msds, font_pic_scale]),
            ft.Divider(color="#DEE2E6"),
        ],
        expand=True,
    )

    # 오른쪽: 경고표지 미리보기
    col_preview = panel(
        "🏷 경고표지 미리보기",
        [render_spinner, label_render_image, label_preview],
        expand=True,
        header_action=ft.Row([
            render_indicator,
            ft.Button("🖨 인쇄 HTML 생성", on_click=on_print_html),
        ], spacing=8),
    )

    # 상단 헤더 바
    header = ft.Container(
        content=ft.Row([
            ft.Column([
                ft.Text("🧪 MSDS Label Maker v1.0.0",
                        size=20, weight=ft.FontWeight.BOLD, color="white"),
                ft.Text("👨‍💻 박재영  |  🏢 LX글라스 연구기획팀  |  📅 2026-06-16",
                        size=11, color="#ADB5BD"),
            ], spacing=2),
            ft.Container(expand=True),
            status_bar,
        ]),
        bgcolor="#343A40",
        padding=ft.padding.Padding(left=16, right=16, top=10, bottom=10),
        border_radius=6,
    )

    page.add(
        header,
        ft.Row(
            controls=[col_pdf, col_edit, col_preview],
            spacing=10,
            expand=True,
            vertical_alignment=ft.CrossAxisAlignment.START,
        ),
    )


import sys

_APP_DIR = os.path.dirname(os.path.abspath(__file__))

# PyInstaller 번들 실행 시 번들된 flet 클라이언트를 사용 (인터넷 다운로드 방지)
if getattr(sys, "frozen", False):
    os.environ.setdefault("FLET_VIEW_PATH", os.path.join(sys._MEIPASS, "flet_client"))

# 회사 보안망 환경: localhost DNS 조회 차단 대응
# getaddrinfo failed (Errno 11001) 방지 → IP 직접 지정
import socket
_orig_getaddrinfo = socket.getaddrinfo
def _patched_getaddrinfo(host, *args, **kwargs):
    if host == "localhost":
        host = "127.0.0.1"
    return _orig_getaddrinfo(host, *args, **kwargs)
socket.getaddrinfo = _patched_getaddrinfo

ft.run(main, assets_dir=_APP_DIR)
