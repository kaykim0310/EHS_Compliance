"""
🛡️ EHS 맞춤 규제 진단 시스템 v4
MSDS PDF → CAS 자동 추출 → KOSHA API 최신 규제 조회 → 맞춤 체크리스트
+ 변경점관리: MSDS 추가/변경, 기계·시설 추가/제거, 이력 추적
"""

import streamlit as st
import time
import json
from datetime import datetime, timedelta
from msds_parser import parse_msds_pdf

# KOSHA API
try:
    from kosha_api import (get_chemical_info, get_legal_regulations,
                           get_hazard_classification, search_by_cas, get_exposure_limits)
    KOSHA_OK = True
except:
    KOSHA_OK = False

def now_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M")

# ═══════════════════════════════
#  KOSHA API 조회 (내장DB 없음)
# ═══════════════════════════════
def lookup_cas_kosha(cas_no: str) -> dict:
    info = {
        "cas": cas_no, "name": "", "source": "",
        # 산업안전보건법
        "managed": False, "special": False, "measure": False,
        "health": False, "permitted": False, "prohibited": False,
        # 화학물질관리법
        "toxic": False, "restricted": False, "prohibited_chem": False, "accident_prep": False,
        # 위험물/고압가스/기타
        "hazmat": "", "hp": False, "ozone": False, "pops": False,
        # 노출기준
        "twa": "", "stel": "",
        # GHS 분류
        "ghs_class": "", "signal": "",
        # 원본
        "raw_reg": "", "raw_items": [],
        "success": False, "error": ""
    }
    if not KOSHA_OK:
        info["error"] = "❌ KOSHA API 모듈 로드 실패. kosha_api.py 파일 확인 필요."
        return info
    try:
        search = search_by_cas(cas_no)
    except Exception as e:
        err = str(e)
        if "Proxy" in err or "Tunnel" in err:
            info["error"] = "❌ 네트워크 연결 실패 — 인터넷/방화벽 확인 필요."
        elif "Timeout" in err:
            info["error"] = "❌ KOSHA 서버 응답 시간 초과 — 잠시 후 재시도."
        else:
            info["error"] = f"❌ API 오류: {err[:120]}"
        return info

    if not search.get("success"):
        info["error"] = f"⚠️ CAS {cas_no} — KOSHA DB 미등록. CAS 번호 확인 필요."
        return info

    chem_id = search["chemId"]
    info["name"] = search.get("chemNameKor", "")
    info["source"] = "✅ KOSHA API (최신)"
    
    # ── 15번: 법적 규제현황 (전체 법률) ──
    try:
        time.sleep(0.3)
        regs = get_legal_regulations(chem_id)
        # 산업안전보건법
        info["managed"] = regs.get("managedHazard") == "O"
        info["special"] = regs.get("specialManaged") == "O"
        info["measure"] = regs.get("measurement") == "O"
        info["health"] = regs.get("healthCheck") == "O"
        info["permitted"] = regs.get("permitted") == "O"
        info["prohibited"] = regs.get("prohibited") == "O"
        # 화학물질관리법
        info["toxic"] = regs.get("toxic") == "O"
        info["restricted"] = regs.get("restricted") == "O"
        info["prohibited_chem"] = regs.get("prohibited_chem") == "O"
        info["accident_prep"] = regs.get("accident_prep") == "O"
        # 위험물/고압가스/기타
        info["hazmat"] = regs.get("hazmat_class", "")
        info["hp"] = regs.get("hp_gas") == "O"
        info["ozone"] = regs.get("ozone") == "O"
        info["pops"] = regs.get("residual_pop") == "O"
        info["raw_reg"] = regs.get("rawText", "")
        info["raw_items"] = regs.get("raw_items", [])
    except Exception as e:
        info["error"] = f"⚠️ 규제조회 실패: {str(e)[:100]}"
    
    # ── 2번: GHS 유해성·위험성 분류 ──
    try:
        time.sleep(0.3)
        haz = get_hazard_classification(chem_id)
        ghs_text = haz.get("classification", "")
        info["ghs_class"] = ghs_text
        info["signal"] = haz.get("signal", "")
        # GHS 분류로 추가 판별 (API 15번에서 놓친 경우 보완)
        if ghs_text:
            if any(k in ghs_text for k in ["발암성", "Carc"]) and not info["special"]:
                info["special"] = True
            if any(k in ghs_text for k in ["생식세포 변이원성", "Muta"]) and not info["special"]:
                info["special"] = True
            if any(k in ghs_text for k in ["생식독성", "Repr"]) and not info["special"]:
                info["special"] = True
    except:
        pass
    
    # ── 8번: 노출기준 ──
    try:
        time.sleep(0.3)
        exp = get_exposure_limits(chem_id)
        info["twa"] = exp.get("twa", "-")
        info["stel"] = exp.get("stel", "-")
    except:
        pass
    info["success"] = True
    return info


# ═══════════════════════════════
#  기계·설비 DB
# ═══════════════════════════════
MACHINES = {
    "press":{"n":"프레스","i":"🔧","cert":"안전인증","insp":"안전검사","d":"금속판 성형·절단"},
    "crane":{"n":"크레인(2톤↑)","i":"🏗️","cert":"안전인증","insp":"안전검사","d":"2톤 이상 크레인"},
    "lift":{"n":"리프트","i":"⬆️","cert":"안전인증","insp":"안전검사","d":"사람·화물 운반"},
    "pressure_vessel":{"n":"압력용기","i":"💨","cert":"안전인증","insp":"안전검사","d":"내부 압력 용기"},
    "boiler":{"n":"보일러","i":"♨️","cert":"안전인증","insp":"안전검사","d":"증기 발생 장치"},
    "gondola":{"n":"곤돌라","i":"🪟","cert":"안전인증","insp":"안전검사","d":"건물 외벽 작업대"},
    "injection":{"n":"사출성형기","i":"🏭","cert":"안전인증","insp":"","d":"플라스틱 사출"},
    "aerial":{"n":"고소작업대","i":"🔝","cert":"안전인증","insp":"","d":"높은 곳 작업"},
    "forklift":{"n":"지게차","i":"🚜","cert":"자율안전확인","insp":"","d":"화물 운반"},
    "grinder":{"n":"연삭기","i":"💎","cert":"자율안전확인","insp":"","d":"금속 연삭"},
    "conveyor":{"n":"컨베이어","i":"➡️","cert":"자율안전확인","insp":"","d":"연속 운반"},
    "robot":{"n":"산업용 로봇","i":"🤖","cert":"자율안전확인","insp":"","d":"자동화 로봇"},
    "exhaust":{"n":"국소배기장치","i":"🌀","cert":"","insp":"안전검사","d":"유해가스 흡입 배출"},
}


# ═══════════════════════════════
#  함유량 파싱 & Cut-off 기준
# ═══════════════════════════════
import re as _re

def parse_content_pct(content_str: str) -> float:
    """
    MSDS 함유량 문자열 → 숫자(%) 변환
    '10-20' → 15.0 (중간값), '~5' → 5.0, '30' → 30.0, '비공개' → -1
    """
    if not content_str or not content_str.strip():
        return -1  # 정보 없음
    s = content_str.strip().replace('%', '').replace(' ', '')
    # 범위: "10-20", "10~20", "10∼20"
    m = _re.search(r'(\d+\.?\d*)\s*[-~∼]\s*(\d+\.?\d*)', s)
    if m:
        return (float(m.group(1)) + float(m.group(2))) / 2
    # 부등호: "<5", "≤1", ">30"
    m = _re.search(r'[<≤＜]\s*(\d+\.?\d*)', s)
    if m:
        return float(m.group(1)) * 0.5  # 미만이므로 절반 추정
    m = _re.search(r'[>≥＞]\s*(\d+\.?\d*)', s)
    if m:
        return float(m.group(1))
    # 단순 숫자: "30", "5.5"
    m = _re.search(r'(\d+\.?\d*)', s)
    if m:
        return float(m.group(1))
    return -1  # 파싱 불가


# ── 함유량 기준(Cut-off Value) ──
# 고용노동부 고시 「화학물질의 분류·표시 및 MSDS에 관한 기준」 별표 1 근거
CUTOFF_RULES = {
    # 규제 항목: (일반 cut-off %, CMR cut-off %, 설명)
    'managed':  {'default': 1.0, 'cmr': 0.1, 'desc': '관리대상유해물질 (산안법)'},
    'special':  {'default': 0.1, 'cmr': 0.1, 'desc': '특별관리물질-CMR (산안법)'},
    'measure':  {'default': 1.0, 'cmr': 0.1, 'desc': '작업환경측정 대상 (산안법)'},
    'health':   {'default': 1.0, 'cmr': 0.1, 'desc': '특수건강진단 대상 (산안법)'},
    'toxic':    {'default': 1.0, 'cmr': 1.0, 'desc': '유독물질 (화관법)'},
    'restricted': {'default': 0.1, 'cmr': 0.1, 'desc': '제한물질 (화관법)'},
    'accident_prep': {'default': 1.0, 'cmr': 1.0, 'desc': '사고대비물질 (화관법)'},
}
# 허가대상·금지물질·위험물·고압가스는 함유량 cut-off 없이 물질 자체 성질로 판단


def apply_cutoff(info: dict) -> dict:
    """
    KOSHA API 규제 결과 + 함유량 → cut-off 적용
    """
    pct = info.get('content_pct', -1)
    is_cmr = info.get('special', False)
    
    for key, rule in CUTOFF_RULES.items():
        raw_val = info.get(key, False)
        cutoff = rule['cmr'] if is_cmr else rule['default']
        
        if not raw_val:
            info[f'{key}_filtered'] = False
            info[f'{key}_note'] = ''
            continue
        
        if pct < 0:
            info[f'{key}_filtered'] = True
            info[f'{key}_note'] = '⚠️ 함유량 미확인 → 해당으로 간주'
            continue
        
        if pct >= cutoff:
            info[f'{key}_filtered'] = True
            info[f'{key}_note'] = f'✅ {pct}% ≥ {cutoff}% → 해당'
        else:
            info[f'{key}_filtered'] = False
            info[f'{key}_note'] = f'💚 {pct}% < {cutoff}% → 비해당'
    
    # 허가대상·금지물질: 함유량 무관, 물질 자체 판정
    info['permitted_filtered'] = bool(info.get('permitted'))
    info['prohibited_filtered'] = bool(info.get('prohibited'))
    info['prohibited_chem_filtered'] = bool(info.get('prohibited_chem'))
    # 위험물/고압가스/오존/POPs: 물질 성질
    info['hazmat_filtered'] = bool(info.get('hazmat'))
    info['hp_filtered'] = bool(info.get('hp'))
    info['ozone_filtered'] = bool(info.get('ozone'))
    info['pops_filtered'] = bool(info.get('pops'))
    
    # 종합
    info['any_regulated'] = any([
        info.get('managed_filtered'), info.get('special_filtered'),
        info.get('measure_filtered'), info.get('health_filtered'),
        info.get('toxic_filtered'), info.get('restricted_filtered'),
        info.get('accident_prep_filtered'),
        info.get('permitted_filtered'), info.get('prohibited_filtered'),
        info.get('prohibited_chem_filtered'),
        info.get('hazmat_filtered'), info.get('hp_filtered'),
        info.get('ozone_filtered'), info.get('pops_filtered'),
    ])
    
    return info


# ═══════════════════════════════
#  규제 태그 생성 (모든 법률)
# ═══════════════════════════════
def make_tags(c, style="markdown"):
    """
    화학물질 info dict → 규제 태그 리스트 생성
    style: "markdown" → `🟡관리대상`, "plain" → 🟡관리대상
    
    전체 규제 카테고리:
      산안법: 관리대상, 특별관리(CMR), 허가대상, 금지물질
      화관법: 유독물질, 제한물질, 금지물질, 사고대비물질
      위험물법: 위험물 (류 표시)
      고압가스, 오존층, POPs
    """
    tags = []
    w = lambda icon, label: f"`{icon}{label}`" if style == "markdown" else f"{icon}{label}"
    wf = lambda icon, label: f"`💚{label}(미달)`" if style == "markdown" else f"~~{label}~~💚미달"
    
    # ── 산업안전보건법 ──
    if c.get('managed'):
        tags.append(w("🟡","관리대상") if c.get('managed_filtered', c.get('managed')) else wf("💚","관리대상"))
    if c.get('special'):
        tags.append(w("🔴","특별관리(CMR)") if c.get('special_filtered', c.get('special')) else wf("💚","CMR"))
    if c.get('permitted'):
        tags.append(w("🟣","허가대상"))  # 함유량 무관
    if c.get('prohibited'):
        tags.append(w("⛔","금지물질"))
    if c.get('measure') and not c.get('managed'):  # 관리대상이면 이미 포함
        if c.get('measure_filtered', c.get('measure')):
            tags.append(w("📏","측정대상"))
    if c.get('health') and not c.get('managed'):
        if c.get('health_filtered', c.get('health')):
            tags.append(w("🏥","특검대상"))
    
    # ── 화학물질관리법 ──
    if c.get('toxic'):
        tags.append(w("☠️","유독물질") if c.get('toxic_filtered', c.get('toxic')) else wf("💚","유독"))
    if c.get('restricted'):
        tags.append(w("🚫","제한물질") if c.get('restricted_filtered', c.get('restricted')) else wf("💚","제한"))
    if c.get('prohibited_chem'):
        tags.append(w("⛔","금지(화관법)"))
    if c.get('accident_prep'):
        tags.append(w("🚨","사고대비") if c.get('accident_prep_filtered', c.get('accident_prep')) else wf("💚","사고대비"))
    
    # ── 위험물안전관리법 ──
    if c.get('hazmat'):
        tags.append(w("🔥", f"위험물({c['hazmat']})") if c['hazmat'] else w("🔥","위험물"))
    
    # ── 기타 ──
    if c.get('hp'):
        tags.append(w("⚡","고압가스"))
    if c.get('ozone'):
        tags.append(w("🌍","오존층"))
    if c.get('pops'):
        tags.append(w("☣️","POPs"))
    
    if not tags:
        return [w("✅","규제없음")] if style == "markdown" else ["✅규제없음"]
    return tags


# ═══════════════════════════════
#  변경이력 관리
# ═══════════════════════════════
def add_log(msg, category="일반"):
    if 'change_log' not in st.session_state:
        st.session_state.change_log = []
    st.session_state.change_log.insert(0, {
        "time": now_str(), "category": category, "msg": msg
    })


# ═══════════════════════════════
#  규제 체크리스트 엔진
# ═══════════════════════════════
def build_checklist(profile):
    w = profile.get('workers', 1)
    chems = [c for c in profile.get('chem_results', []) if c.get('status') != 'removing']
    machs_active = {k for k, v in profile.get('machines_detail', {}).items() if v.get('status') == 'active'}

    # cut-off 적용된 필터 필드 사용 (_filtered), 없으면 원본 사용 (하위호환)
    hasMng = any(c.get('managed_filtered', c.get('managed')) for c in chems)
    hasSp = any(c.get('special_filtered', c.get('special')) for c in chems)
    hasTx = any(c.get('toxic_filtered', c.get('toxic')) for c in chems)
    hasHaz = any(c.get('hazmat_filtered', c.get('hazmat')) for c in chems)
    hasHp = any(c.get('hp_filtered', c.get('hp')) for c in chems)
    hasMeasure = any(c.get('measure_filtered', c.get('measure')) for c in chems)
    hasHealth = any(c.get('health_filtered', c.get('health')) for c in chems)
    hasRestricted = any(c.get('restricted_filtered', c.get('restricted')) for c in chems)
    hasAccidentPrep = any(c.get('accident_prep_filtered', c.get('accident_prep')) for c in chems)
    hasPermitted = any(c.get('permitted_filtered', c.get('permitted')) for c in chems)
    hasProhibited = any(c.get('prohibited_filtered', c.get('prohibited')) for c in chems)
    hasChem = len(chems) > 0
    hasCert = any(MACHINES.get(m, {}).get('cert') == '안전인증' for m in machs_active)
    hasInsp = any(MACHINES.get(m, {}).get('insp') == '안전검사' for m in machs_active)

    R = {}
    # ── 산업안전보건법 ──
    items = []
    if w >= 50:
        items.append({"t": "안전보건관리책임자 선임 (법 §15)", "d": f"{w}인 → 50인 이상 선임 의무", "p": "critical"})
        items.append({"t": "안전관리자 선임 (법 §17)", "d": "50인 이상", "p": "critical"})
        items.append({"t": "보건관리자 선임 (법 §18)", "d": "50인 이상", "p": "critical"})
    if w >= 100:
        items.append({"t": "산업안전보건위원회 구성 (법 §24)", "d": "100인 이상. 분기 1회", "p": "high"})
        items.append({"t": "안전보건관리규정 작성 (법 §25)", "d": "100인 이상", "p": "high"})
    items.append({"t": "근로자 정기 안전보건교육 (법 §29)", "d": "매분기 6h(사무직 3h)", "p": "critical"})
    items.append({"t": "채용 시 교육 8시간", "d": "신규 채용 시 (일용 1시간)", "p": "critical"})
    items.append({"t": "위험성평가 실시 (법 §36)", "d": "최초+연1회+수시", "p": "critical"})
    items.append({"t": "일반건강진단 (법 §129)", "d": "비사무직 연1회 / 사무직 2년1회", "p": "critical"})
    if hasMng:
        items.append({"t": "⚗️ MSDS 비치·게시·교육 (법 §114)", "d": "관리대상 유해물질 → MSDS 비치, 경고표지, 교육", "p": "critical"})
    if hasMeasure:
        items.append({"t": "⚗️ 작업환경측정 (법 §125)", "d": "6개월1회, 특별관리물질 3개월1회", "p": "critical"})
    if hasHealth:
        items.append({"t": "⚗️ 특수건강진단 (법 §130)", "d": "유해인자 노출 근로자", "p": "critical"})
    if not hasMng and hasChem:
        items.append({"t": "MSDS 비치 (법 §114)", "d": "화학물질 사용 → MSDS 비치·게시", "p": "high"})
    if hasSp:
        items.append({"t": "⚠️ 특별관리물질(CMR) 추가 관리", "d": "발암성·변이원성·생식독성 물질 → 별도 게시, 기록 30년 보존", "p": "critical"})
    if hasPermitted:
        names_p = [c['name'] for c in chems if c.get('permitted')]
        items.append({"t": "🟣 허가대상물질 사용허가 (법 §118)", "d": f"허가대상: {', '.join(names_p[:3])} → 고용부 장관 허가 필요", "p": "critical"})
    if hasProhibited:
        names_x = [c['name'] for c in chems if c.get('prohibited')]
        items.append({"t": "⛔ 금지물질 제조·사용 금지 (법 §117)", "d": f"금지: {', '.join(names_x[:3])} → 즉시 중단 필요!", "p": "critical"})
    if hasCert:
        items.append({"t": "🔧 안전인증 대상 기계 확인 (법 §84)", "d": "안전인증 마크 확인", "p": "critical"})
    if hasInsp:
        items.append({"t": "🔧 정기 안전검사 수검 (법 §93)", "d": "검사 대상 기계", "p": "critical"})
    if profile.get('subcontract'):
        items.append({"t": "도급인 안전보건조치 (법 §63)", "d": "수급인 근로자 보호", "p": "critical"})
        if w >= 100:
            items.append({"t": "안전보건총괄책임자 선임 (법 §62)", "d": "도급+수급 100인↑", "p": "critical"})
    items.append({"t": "산업재해 기록·보고 (법 §57)", "d": "기록 3년. 중대재해 즉시보고", "p": "critical"})
    R["osha"] = {"title": "산업안전보건법", "icon": "🏭", "items": items}

    if w >= 5:
        si = []
        note = " (50인미만: '27.1.27 시행)" if w < 50 else ""
        si.append({"t": "안전보건관리체계 구축" + note, "d": "경영책임자 의무", "p": "critical"})
        si.append({"t": "안전보건 목표·방침 공표", "d": "전 종사자", "p": "critical"})
        si.append({"t": "인력·예산 확보", "d": "안전보건 자원 확보", "p": "critical"})
        si.append({"t": "유해위험요인 점검 (반기1회↑)", "d": "반기 1회 이상", "p": "critical"})
        si.append({"t": "급박한 위험 대비 매뉴얼", "d": "대피·위험제거", "p": "high"})
        if w >= 500:
            si.append({"t": "안전보건 전담조직 설치", "d": "500인↑", "p": "critical"})
        R["serious"] = {"title": "중대재해처벌법", "icon": "⚖️", "items": si}

    if hasTx or hasRestricted or hasAccidentPrep:
        chem_items = []
        if hasTx:
            names = [c['name'] for c in chems if c.get('toxic_filtered', c.get('toxic'))]
            chem_items.append({"t": "☠️ 유독물질 영업허가 (법 §28)", "d": f"유독물질: {', '.join(names[:5])}", "p": "critical"})
            chem_items.append({"t": "취급시설 설치검사 합격", "d": "검사→통지서→영업개시", "p": "critical"})
            chem_items.append({"t": "정기검사 4년마다", "d": "취급시설", "p": "critical"})
            chem_items.append({"t": "장외영향평가서 제출 (법 §23)", "d": "유해화학물질 취급시설", "p": "critical"})
            chem_items.append({"t": "안전교육 (신규16h/보수8h)", "d": "취급 종사자", "p": "critical"})
        if hasRestricted:
            names_r = [c['name'] for c in chems if c.get('restricted_filtered', c.get('restricted'))]
            chem_items.append({"t": "🚫 제한물질 취급기준 준수 (법 §27)", "d": f"제한물질: {', '.join(names_r[:3])}", "p": "critical"})
        if hasAccidentPrep:
            names_a = [c['name'] for c in chems if c.get('accident_prep_filtered', c.get('accident_prep'))]
            chem_items.append({"t": "🚨 사고대비물질 관리 (법 §39)", "d": f"사고대비: {', '.join(names_a[:3])} → 위해관리계획서 제출", "p": "critical"})
        R["chemical"] = {"title": "화학물질관리법(화관법)", "icon": "🧪", "items": chem_items}
    if hasHaz:
        names = [f"{c['name']}({c['hazmat']})" for c in chems if c.get('hazmat_filtered', c.get('hazmat'))]
        R["hazmat"] = {"title": "위험물안전관리법", "icon": "🔥", "items": [
            {"t": "제조소·저장소 설치허가 (법 §6)", "d": f"위험물: {', '.join(names[:5])}", "p": "critical"},
            {"t": "위험물안전관리자 선임 (법 §15)", "d": "선임·신고", "p": "critical"},
            {"t": "예방규정 제정 (법 §17)", "d": "지정수량 10배↑", "p": "critical"},
            {"t": "정기점검 연1회↑ (법 §18)", "d": "시설 점검", "p": "critical"},
        ]}
    if hasHp:
        names = [c['name'] for c in chems if c.get('hp_filtered', c.get('hp'))]
        R["hp"] = {"title": "고압가스 안전관리법", "icon": "⚡", "items": [
            {"t": "제조·저장 허가/신고 (법 §4)", "d": f"고압가스: {', '.join(names[:5])}", "p": "critical"},
            {"t": "완성검사·정기검사", "d": "합격 후 사용", "p": "critical"},
            {"t": "안전관리자 선임", "d": "선임·신고", "p": "critical"},
        ]}
    if profile.get('air'):
        R["air"] = {"title": "대기환경보전법", "icon": "🌫️", "items": [
            {"t": "배출시설 설치 허가/신고 (법 §23)", "d": "1·2종:허가/3~5종:신고", "p": "critical"},
            {"t": "방지시설 설치 (법 §26)", "d": "배출허용기준 준수", "p": "critical"},
            {"t": "자가측정 (법 §39)", "d": "종별 주기", "p": "critical"},
        ]}
    if profile.get('water'):
        R["water"] = {"title": "물환경보전법", "icon": "💧", "items": [
            {"t": "배출시설 허가/신고 (법 §33)", "d": "1~5종", "p": "critical"},
            {"t": "방지시설 설치 (법 §35)", "d": "수질기준 준수", "p": "critical"},
            {"t": "자가측정 (법 §46)", "d": "종별 주기", "p": "critical"},
        ]}
    if profile.get('waste') or hasMng or hasTx:
        wi = [{"t": "사업장폐기물 배출자 신고", "d": "배출시설 운영", "p": "critical"},
              {"t": "올바로시스템 인계서", "d": "폐기물 반출", "p": "critical"}]
        if hasTx or hasSp:
            wi.insert(1, {"t": "지정폐기물 분류·관리", "d": "유해물질→지정폐기물", "p": "critical"})
        R["waste"] = {"title": "폐기물관리법", "icon": "♻️", "items": wi}
    return R


# ═══════════════════════════════
#  Streamlit UI 초기화
# ═══════════════════════════════
st.set_page_config(page_title="🛡️ EHS 규제진단", page_icon="🛡️", layout="wide")
for k, v in {'step':1, 'chem_results':[], 'machines_detail':{}, 'profile':{},
             'checked':{}, 'regs':{}, 'change_log':[], 'parsed_msds':[], 'failed_files':[]}.items():
    if k not in st.session_state:
        st.session_state[k] = v if not isinstance(v, (list, dict)) else type(v)(v)

def go(n): st.session_state.step = n


# ═══════════════════════════════
#  회사별 저장/불러오기 시스템
# ═══════════════════════════════
import json as _json
import glob as _glob
from pathlib import Path as _Path

SAVE_DIR = _Path("data")
SAVE_DIR.mkdir(exist_ok=True)

# 저장 대상 키 목록
_SAVE_KEYS = ['profile', 'chem_results', 'machines_detail', 'change_log']

def _company_filename(name: str) -> _Path:
    """회사명 → 안전한 파일명"""
    safe = "".join(c if c.isalnum() or c in (' ','-','_') else '_' for c in name).strip()
    return SAVE_DIR / f"{safe}.json"

def _save_company(name: str = None) -> str:
    """현재 세션 데이터를 회사 파일로 저장"""
    if not name:
        name = st.session_state.profile.get('name', '').strip()
    if not name:
        return "❌ 회사명이 없습니다. Step 1에서 회사명을 먼저 입력하세요."
    
    data = {"_saved_at": now_str(), "_version": "v4.1"}
    for k in _SAVE_KEYS:
        data[k] = st.session_state.get(k, {} if k in ('profile','machines_detail') else [])
    
    fpath = _company_filename(name)
    try:
        with open(fpath, 'w', encoding='utf-8') as f:
            _json.dump(data, f, ensure_ascii=False, indent=2)
        return f"✅ **{name}** 저장 완료 ({fpath.name})"
    except Exception as e:
        return f"❌ 저장 실패: {e}"

def _load_company(fpath: _Path) -> str:
    """파일에서 세션으로 불러오기"""
    try:
        with open(fpath, 'r', encoding='utf-8') as f:
            data = _json.load(f)
        for k in _SAVE_KEYS:
            if k in data:
                st.session_state[k] = data[k]
        # 불러온 후 Step 1으로
        st.session_state.step = 1
        st.session_state.failed_files = []
        name = data.get('profile', {}).get('name', fpath.stem)
        return f"✅ **{name}** 불러오기 완료"
    except Exception as e:
        return f"❌ 불러오기 실패: {e}"

def _list_saved() -> list:
    """저장된 회사 목록"""
    files = sorted(SAVE_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    result = []
    for f in files:
        try:
            with open(f, 'r', encoding='utf-8') as fp:
                d = _json.load(fp)
            name = d.get('profile', {}).get('name', f.stem)
            saved_at = d.get('_saved_at', '?')
            workers = d.get('profile', {}).get('workers', '?')
            chems = len(d.get('chem_results', []))
            result.append({'name': name, 'file': f, 'saved_at': saved_at, 
                          'workers': workers, 'chems': chems})
        except:
            result.append({'name': f.stem, 'file': f, 'saved_at': '?', 'workers': '?', 'chems': 0})
    return result

def _delete_company(fpath: _Path) -> str:
    """회사 데이터 삭제"""
    try:
        name = fpath.stem
        fpath.unlink()
        return f"🗑️ **{name}** 삭제 완료"
    except Exception as e:
        return f"❌ 삭제 실패: {e}"

def _new_session():
    """세션 초기화 (새 회사)"""
    for k, v in {'step':1, 'chem_results':[], 'machines_detail':{}, 'profile':{},
                 'checked':{}, 'regs':{}, 'change_log':[], 'parsed_msds':[], 'failed_files':[]}.items():
        st.session_state[k] = v if not isinstance(v, (list, dict)) else type(v)(v)


# ── 사이드바: 회사 관리 ──
with st.sidebar:
    st.markdown("## 📂 회사별 데이터 관리")
    
    # 현재 세션 정보
    cur_name = st.session_state.profile.get('name', '')
    if cur_name:
        chems_n = len([c for c in st.session_state.chem_results if c.get('status') != 'removing'])
        machs_n = len([k for k,v in st.session_state.machines_detail.items() if v.get('status') == 'active'])
        st.info(f"📌 현재: **{cur_name}**  \n화학물질 {chems_n}종 · 기계 {machs_n}종")
    else:
        st.caption("현재 회사가 선택되지 않았습니다.")
    
    st.markdown("---")
    
    # 저장
    col_s1, col_s2 = st.columns(2)
    if col_s1.button("💾 저장", use_container_width=True, disabled=not cur_name):
        msg = _save_company()
        if "✅" in msg:
            st.success(msg)
            add_log(f"💾 데이터 저장됨", "시스템")
        else:
            st.error(msg)
    
    if col_s2.button("🆕 새 회사", use_container_width=True):
        if cur_name:
            _save_company()  # 현재 데이터 자동 저장
        _new_session()
        st.rerun()
    
    st.markdown("---")
    
    # 저장된 회사 목록
    saved = _list_saved()
    if saved:
        st.markdown(f"### 💼 저장된 회사 ({len(saved)}개)")
        
        for i, s in enumerate(saved):
            with st.container():
                st.markdown(
                    f"**{s['name']}**  \n"
                    f"<small style='color:#888'>👥{s['workers']}명 · 🧪{s['chems']}종 · 💾{s['saved_at']}</small>",
                    unsafe_allow_html=True
                )
                lc, dc = st.columns(2)
                if lc.button("📂 불러오기", key=f"load_{i}", use_container_width=True):
                    # 현재 세션 자동 저장
                    if cur_name:
                        _save_company()
                    msg = _load_company(s['file'])
                    if "✅" in msg:
                        st.success(msg)
                        add_log(f"📂 데이터 불러옴: {s['name']}", "시스템")
                        st.rerun()
                    else:
                        st.error(msg)
                if dc.button("🗑️", key=f"del_{i}", use_container_width=True):
                    st.session_state[f'confirm_del_{i}'] = True
                
                # 삭제 확인
                if st.session_state.get(f'confirm_del_{i}'):
                    st.warning(f"⚠️ **{s['name']}** 데이터를 삭제할까요?")
                    yc, nc = st.columns(2)
                    if yc.button("✅ 삭제", key=f"yes_del_{i}", type="primary"):
                        msg = _delete_company(s['file'])
                        st.session_state[f'confirm_del_{i}'] = False
                        st.success(msg)
                        st.rerun()
                    if nc.button("취소", key=f"no_del_{i}"):
                        st.session_state[f'confirm_del_{i}'] = False
                        st.rerun()
                
                st.markdown("<hr style='margin:8px 0;border-color:#eee'>", unsafe_allow_html=True)
    else:
        st.caption("💡 저장된 회사가 없습니다.  \n회사명 입력 후 '💾 저장' 버튼을 눌러주세요.")
    
    st.markdown("---")
    
    # 내보내기/가져오기
    with st.expander("📤 내보내기 / 📥 가져오기"):
        st.caption("다른 PC로 데이터를 이동할 때 사용합니다.")
        
        # 내보내기: 전체 회사 데이터를 하나의 JSON으로
        if saved and st.button("📤 전체 백업 다운로드"):
            all_data = {}
            for s in saved:
                try:
                    with open(s['file'], 'r', encoding='utf-8') as f:
                        all_data[s['name']] = _json.load(f)
                except:
                    pass
            backup_json = _json.dumps(all_data, ensure_ascii=False, indent=2)
            st.download_button(
                "💾 backup.json 다운로드",
                data=backup_json,
                file_name=f"EHS_backup_{now_str()[:10]}.json",
                mime="application/json"
            )
        
        # 가져오기
        uploaded_backup = st.file_uploader("📥 백업 파일 업로드", type=['json'], key="backup_upload")
        if uploaded_backup:
            try:
                backup = _json.loads(uploaded_backup.read().decode('utf-8'))
                count = 0
                for cname, cdata in backup.items():
                    if isinstance(cdata, dict) and 'profile' in cdata:
                        fpath = _company_filename(cname)
                        with open(fpath, 'w', encoding='utf-8') as f:
                            _json.dump(cdata, f, ensure_ascii=False, indent=2)
                        count += 1
                st.success(f"✅ {count}개 회사 데이터 가져오기 완료!")
                st.rerun()
            except Exception as e:
                st.error(f"❌ 가져오기 실패: {e}")

# Header
st.markdown("""
<div style="background:linear-gradient(135deg,#0D1B2A,#2C3E50);padding:20px 28px;border-radius:16px;color:white;margin-bottom:16px">
  <h1 style="margin:0;font-size:24px">🛡️ EHS 맞춤 규제 진단 시스템</h1>
  <p style="margin:4px 0 0;opacity:0.7;font-size:13px">MSDS PDF → KOSHA API 최신 조회 → 맞춤 체크리스트 + 변경점관리</p>
</div>
""", unsafe_allow_html=True)

# Steps bar — 2줄 배치 + 큰 글씨 + 클릭 가능
cur = st.session_state.step
step_data = [
    (1,"📌","기본정보"), (2,"📄","MSDS"), (3,"🔧","기계·설비"), (4,"🏗️","시설"),
    (5,"📊","진단결과"), (6,"📈","대시보드"), (7,"📋","변경이력")
]

def _step_html(n, icon, label):
    if n < cur:
        return f"<div style='text-align:center;padding:8px 4px;background:#E3F2FD;border-radius:10px;font-size:14px;font-weight:700;color:#1565C0;cursor:pointer'>✅ {label}</div>"
    elif n == cur:
        return f"<div style='text-align:center;padding:8px 4px;background:#1565C0;border-radius:10px;font-size:14px;font-weight:700;color:white;box-shadow:0 2px 8px rgba(21,101,192,0.4)'>👉 {icon} {label}</div>"
    else:
        return f"<div style='text-align:center;padding:8px 4px;background:#F5F5F5;border-radius:10px;font-size:14px;color:#999'>{icon} {label}</div>"

# 상단 4개
row1 = st.columns(4)
for i, (n, icon, label) in enumerate(step_data[:4]):
    row1[i].markdown(_step_html(n, icon, label), unsafe_allow_html=True)

# 하단 3개
row2 = st.columns([1,1,1,1])
for i, (n, icon, label) in enumerate(step_data[4:]):
    row2[i].markdown(_step_html(n, icon, label), unsafe_allow_html=True)

st.markdown("---")


# ═══════════════════════════════════════════
#  STEP 1: 기본정보
# ═══════════════════════════════════════════
if st.session_state.step == 1:
    st.subheader("📌 기본 정보")
    st.caption("화학물질·기계 같은 건 다음 단계에서 확인합니다!")
    c1,c2 = st.columns(2)
    name = c1.text_input("회사명", value=st.session_state.profile.get('name',''))
    workers = c2.number_input("직원 수 (전체)", min_value=1, value=st.session_state.profile.get('workers',10))
    industry = st.selectbox("업종", ["-- 선택 --","🏭 제조업","🔨 건설업","🚛 운수·창고","🏪 도소매","💼 서비스업","🏥 보건업","🔧 기타"])
    sub = st.checkbox("🤝 하청업체가 같은 장소에서 일합니다", value=st.session_state.profile.get('subcontract',False))
    if st.button("다음 → MSDS 관리", type="primary", use_container_width=True):
        if industry == "-- 선택 --":
            st.error("업종을 선택해 주세요!")
        else:
            st.session_state.profile = {'name':name,'workers':workers,'industry':industry,'subcontract':sub}
            go(2); st.rerun()


# ═══════════════════════════════════════════
#  STEP 2: MSDS 관리 (추가 / 변경 / 삭제)
# ═══════════════════════════════════════════
elif st.session_state.step == 2:
    st.subheader("📄 MSDS(화학물질) 관리")

    active = [c for c in st.session_state.chem_results if c.get('status') != 'removing']
    removing = [c for c in st.session_state.chem_results if c.get('status') == 'removing']

    # ── 현재 등록 목록 ──
    if active:
        st.markdown(f"### 📋 현재 등록 ({len(active)}종)")
        for c in active:
            tag_str = " ".join(make_tags(c, "markdown"))
            
            pct_info = ""
            if c.get('content_pct', -1) >= 0:
                pct_info = f" | 함유량: **{c['content_str']}%** ({c['content_pct']}%)"
            elif c.get('content_str'):
                pct_info = f" | 함유량: {c['content_str']}"
            
            st.markdown(
                f"**{c['name']}** ({c['cas']}) — {tag_str}  \n"
                f"<small style='color:#888'>📅 {c.get('added_date','?')}{pct_info} | "
                f"{c.get('source','')}"
                f"{' | 📎 '+c.get('msds_file','') if c.get('msds_file') else ''}</small>",
                unsafe_allow_html=True)

    if removing:
        st.markdown(f"### ⏳ 삭제 예정 ({len(removing)}종)")
        for c in removing:
            st.info(f"⏳ **{c['name']}** ({c['cas']}) — 삭제 예정일: **{c.get('remove_date','?')}**  \n"
                     f"<small>이전 MSDS: {c.get('msds_file','?')}</small>", icon="🗓️")

    # ── MSDS 업로드 ──
    st.markdown("---")
    st.markdown("### 📤 MSDS 업로드")

    upload_mode = st.radio(
        "업로드 유형",
        ["📥 **신규 추가** — 새로운 화학물질", "🔄 **변경(갱신)** — 기존 MSDS 업데이트"],
        horizontal=True, key="upload_mode"
    )
    is_update = "변경" in upload_mode

    # 변경 모드일 때: 기존 MSDS 처리 옵션
    old_handling = "즉시"
    if is_update:
        if not active:
            st.warning("등록된 화학물질이 없습니다. '신규 추가'를 선택해 주세요.")
        else:
            st.info("🔄 **변경 모드**: 같은 CAS 번호의 기존 데이터를 새 MSDS로 교체합니다.")
            old_handling = st.radio(
                "⚙️ 이전(구) MSDS 데이터 처리",
                ["🗑️ 즉시 삭제 — 바로 새 데이터로 교체",
                 "📅 1개월 후 삭제 — 이전 데이터 30일간 보관",
                 "📅 2개월 후 삭제 — 이전 데이터 60일간 보관"],
                key="old_handling"
            )

    uploaded = st.file_uploader("MSDS PDF (여러 개 가능)", type=["pdf"], accept_multiple_files=True, key="msds_up")

    if uploaded and st.button("📊 MSDS 분석 시작!", type="primary", use_container_width=True):
        progress = st.progress(0)
        for idx, file in enumerate(uploaded):
            st.markdown(f"#### 📖 {file.name}")
            with st.spinner("PDF 파싱 중..."):
                parsed = parse_msds_pdf(file)
            if not parsed['success']:
                st.error(f"❌ **{file.name}** — 자동 파싱 실패")
                st.warning(f"{parsed['error']}")
                st.info("👇 아래 **'✍️ 수동 CAS 입력'** 에서 직접 입력할 수 있습니다.  \n"
                         "MSDS 3항(구성성분)에 적힌 **CAS 번호**를 찾아서 입력해 주세요.  \n"
                         "예: `108-88-3, 1330-20-7`")
                if parsed.get('full_text'):
                    with st.expander(f"📄 {file.name} — 추출된 텍스트 (CAS 번호 직접 찾기용)"):
                        st.text(parsed['full_text'][:3000])
                # 실패 파일 기록
                if 'failed_files' not in st.session_state:
                    st.session_state.failed_files = []
                if file.name not in st.session_state.failed_files:
                    st.session_state.failed_files.append(file.name)
                continue
            st.success(f"✅ 제품: **{parsed['product_name'] or '(미확인)'}** / {len(parsed['components'])}종 발견")

            for comp in parsed['components']:
                cas = comp['cas']
                name_pdf = comp.get('name', '')
                content_str = comp.get('content', '')
                content_pct = parse_content_pct(content_str)

                # 기존 동일 CAS 찾기
                existing_idx = None
                for ei, ec in enumerate(st.session_state.chem_results):
                    if ec['cas'] == cas and ec.get('status') != 'removing':
                        existing_idx = ei; break

                # ── 변경 모드: 기존 데이터 처리 ──
                if is_update and existing_idx is not None:
                    old = st.session_state.chem_results[existing_idx]
                    if "즉시" in old_handling:
                        add_log(f"🔄 {old['name']}({cas}) MSDS 변경 → 이전 데이터 즉시 삭제", "MSDS변경")
                        st.session_state.chem_results.pop(existing_idx)
                    else:
                        days = 30 if "1개월" in old_handling else 60
                        old['status'] = 'removing'
                        old['remove_date'] = (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d")
                        add_log(f"🔄 {old['name']}({cas}) MSDS 변경 → 이전 데이터 {old['remove_date']}까지 보관", "MSDS변경")

                # ── 신규 모드: 중복 건너뛰기 ──
                elif not is_update:
                    if any(r['cas']==cas and r.get('status')!='removing' for r in st.session_state.chem_results):
                        st.write(f"  ↳ {name_pdf or cas} — 이미 등록됨 ✅"); continue

                # ── KOSHA API 조회 ──
                with st.spinner(f"🔍 {name_pdf or cas} → KOSHA API 조회..."):
                    info = lookup_cas_kosha(cas)
                if not info['name'] and name_pdf:
                    info['name'] = name_pdf
                if not info.get('success'):
                    st.error(f"  ↳ **{name_pdf or cas}** — 조회 실패")
                    st.warning(info.get('error', '')); continue

                # ── 함유량 & Cut-off 적용 ──
                info['content_str'] = content_str
                info['content_pct'] = content_pct
                info = apply_cutoff(info)

                info['status'] = 'active'
                info['added_date'] = now_str()
                info['msds_file'] = file.name
                st.session_state.chem_results.append(info)

                # 규제 태그 (cut-off 적용 결과)
                tag_str = " / ".join(make_tags(info, "plain"))
                
                cutoff_msg = ""
                if content_pct >= 0:
                    cutoff_msg = f"  (함유량 {content_pct}%)"
                elif content_str:
                    cutoff_msg = f"  (함유량: {content_str})"
                st.write(f"  ↳ **{info['name']}** ({cas}){cutoff_msg} → {tag_str}")

                label = "변경(갱신)" if is_update else "신규 추가"
                add_log(f"📥 {info['name']}({cas}) {label} — {file.name}", "MSDS추가" if not is_update else "MSDS변경")
                time.sleep(0.2)
            progress.progress((idx+1)/len(uploaded))

        act_count = len([c for c in st.session_state.chem_results if c.get('status')!='removing'])
        if act_count:
            st.balloons()
            st.success(f"🎉 완료! 현재 등록: {act_count}종 (KOSHA API 최신)")
        else:
            st.warning("⚠️ 등록된 화학물질이 없습니다.")

    # ── 개별 삭제 ──
    if active:
        st.markdown("---")
        with st.expander("🗑️ 화학물질 개별 삭제", expanded=False):
            del_target = st.selectbox("삭제할 물질", ["-- 선택 --"]+[f"{c['name']} ({c['cas']})" for c in active], key="del_c")
            if del_target != "-- 선택 --":
                del_opt = st.radio("삭제 방법", ["🗑️ 즉시 삭제","📅 1개월 후 삭제","📅 2개월 후 삭제"], key="del_o")
                if st.button("❌ 삭제 실행", key="del_btn"):
                    target_cas = del_target.split("(")[-1].rstrip(")")
                    for c in st.session_state.chem_results:
                        if c['cas']==target_cas and c.get('status')!='removing':
                            if "즉시" in del_opt:
                                st.session_state.chem_results.remove(c)
                                add_log(f"🗑️ {c['name']}({target_cas}) 즉시 삭제", "MSDS삭제")
                            else:
                                days = 30 if "1개월" in del_opt else 60
                                c['status']='removing'
                                c['remove_date']=(datetime.now()+timedelta(days=days)).strftime("%Y-%m-%d")
                                add_log(f"🗓️ {c['name']}({target_cas}) → {c['remove_date']} 삭제 예정", "MSDS삭제예정")
                            st.rerun()

    # ── 수동 CAS 입력 (파싱 실패 시 + 언제든 사용 가능) ──
    st.markdown("---")
    failed = st.session_state.get('failed_files', [])

    if failed:
        st.markdown("### ✍️ 수동 CAS 입력")
        st.error(f"🚨 아래 **{len(failed)}개 파일**의 자동 파싱이 실패했습니다. CAS 번호를 직접 입력해 주세요.")
        st.markdown("**파싱 실패 파일 목록:**")
        for fi, fn in enumerate(failed, 1):
            st.markdown(f"  {fi}. 📄 **{fn}** — MSDS 3항(구성성분) 표에서 CAS 번호를 찾아 입력")
        st.caption("💡 CAS 번호 찾는 법: MSDS를 열어서 **\"3. 구성성분의 명칭 및 함유량\"** 표를 보면 `108-88-3` 같은 번호가 있습니다.")
    else:
        st.markdown("### ✍️ 수동 CAS 입력")
        st.caption("PDF 파싱이 안 되거나, MSDS 없이 CAS 번호만 아는 경우 직접 입력할 수 있습니다.")

    # 파싱 실패 파일이 있으면 셀렉트박스로 어떤 파일인지 선택
    if failed:
        manual_file = st.selectbox(
            "어떤 MSDS 파일의 성분인가요?",
            failed + ["기타 (직접입력)"],
            key="manual_ref"
        )
        if manual_file == "기타 (직접입력)":
            manual_file = st.text_input("제품명/파일명", placeholder="예: ○○신너", key="manual_ref2")
    else:
        manual_file = st.text_input("참고: 어떤 제품/MSDS의 성분인가요? (선택사항)",
                                    placeholder="예: ○○신너, △△세정제",
                                    key="manual_ref")

    cas_input = st.text_input(
        "CAS 번호 (쉼표로 여러 개 가능)",
        placeholder="예: 108-88-3, 1330-20-7, 67-64-1",
        key="manual_cas"
    )
    content_input = st.text_input(
        "함유량 (%, CAS 순서대로 쉼표 구분 — 선택사항)",
        placeholder="예: 30, 10-20, 5  (모르면 비워두세요)",
        key="manual_content"
    )
    st.caption("💡 함유량을 입력하면 cut-off 기준으로 실제 규제 해당 여부를 판정합니다. 비워두면 보수적으로 '해당'처리.")

    if cas_input and st.button("🔍 수동 입력 조회", type="primary", key="manual_btn"):
        import re
        cas_list = [c.strip() for c in cas_input.replace('，', ',').split(',') if c.strip()]
        # 함유량도 파싱
        content_list_raw = [c.strip() for c in content_input.replace('，', ',').split(',')] if content_input else []
        valid, invalid = [], []
        for c in cas_list:
            (valid if re.match(r'^\d{2,7}-\d{2}-\d$', c) else invalid).append(c)

        if invalid:
            st.error(f"❌ CAS 형식 오류: {', '.join(invalid)}  \n올바른 형식: `108-88-3` (숫자-숫자-숫자)")

        for idx_v, cas in enumerate(valid):
            if any(r['cas'] == cas and r.get('status') != 'removing' for r in st.session_state.chem_results):
                st.write(f"  ↳ {cas} — 이미 등록됨 ✅"); continue

            with st.spinner(f"🔍 CAS {cas} → KOSHA API 조회..."):
                info = lookup_cas_kosha(cas)
            if not info.get('success'):
                st.error(f"  ↳ **{cas}** — 조회 실패")
                st.warning(info.get('error', '')); continue

            # 함유량 매칭
            content_str = content_list_raw[idx_v] if idx_v < len(content_list_raw) else ''
            content_pct = parse_content_pct(content_str)
            info['content_str'] = content_str
            info['content_pct'] = content_pct
            info = apply_cutoff(info)

            info['status'] = 'active'
            info['added_date'] = now_str()
            info['msds_file'] = manual_file or '(수동 입력)'
            st.session_state.chem_results.append(info)

            tag_str = " / ".join(make_tags(info, "plain"))
            pct_note = f"  (함유량 {content_pct}%)" if content_pct >= 0 else ""
            st.write(f"  ↳ **{info['name']}** ({cas}){pct_note} → {tag_str}")
            add_log(f"✍️ {info['name']}({cas}) 수동 입력{pct_note} — {manual_file or '직접입력'}", "MSDS추가(수동)")

        if valid:
            act_count = len([c for c in st.session_state.chem_results if c.get('status') != 'removing'])
            st.success(f"✅ 완료! 현재 등록: {act_count}종")
            # 해당 파일을 실패 목록에서 제거
            if manual_file and manual_file in st.session_state.get('failed_files', []):
                st.session_state.failed_files.remove(manual_file)

    st.markdown("---")
    c1,c2 = st.columns(2)
    if c1.button("← 이전", use_container_width=True): go(1); st.rerun()
    if c2.button("다음 → 기계·설비", type="primary", use_container_width=True): go(3); st.rerun()
    if not uploaded and not active:
        st.caption("💡 화학물질을 사용하지 않으면 바로 '다음'을 눌러주세요.")


# ═══════════════════════════════════════════
#  STEP 3: 기계·설비 관리 (추가/제거)
# ═══════════════════════════════════════════
elif st.session_state.step == 3:
    st.subheader("🔧 기계·설비 관리")
    md = st.session_state.machines_detail

    active_m = {k:v for k,v in md.items() if v.get('status')=='active'}
    removing_m = {k:v for k,v in md.items() if v.get('status')=='removing'}

    # ── 현재 보유 ──
    if active_m:
        st.markdown(f"### 📋 현재 보유 ({len(active_m)}종)")
        for k,v in active_m.items():
            m = MACHINES.get(k,{})
            tags=""
            if m.get('cert'): tags+=f" 🏷️{m['cert']}"
            if m.get('insp'): tags+=f" 🔍{m['insp']}"
            st.markdown(f"- {m.get('i','')} **{m.get('n',k)}**{tags} <small style='color:#888'>(등록: {v.get('added_date','?')})</small>", unsafe_allow_html=True)

    if removing_m:
        st.markdown(f"### ⏳ 제거 예정 ({len(removing_m)}종)")
        for k,v in removing_m.items():
            m = MACHINES.get(k,{})
            st.info(f"⏳ {m.get('i','')} **{m.get('n',k)}** — 제거 예정: **{v.get('remove_date','?')}**")

    # ── 기계 추가 ──
    st.markdown("---")
    st.markdown("### ➕ 기계·설비 추가")
    available = {k:m for k,m in MACHINES.items() if k not in active_m}
    if available:
        add_keys = []
        for k,m in available.items():
            tags=""
            if m['cert']: tags+=f" → 🏷️**{m['cert']}**"
            if m['insp']: tags+=f" / 🔍**{m['insp']}**"
            if st.checkbox(f"{m['i']} {m['n']}{tags}  _{m['d']}_", key=f"add_m_{k}"):
                add_keys.append(k)
        if add_keys and st.button("✅ 선택한 기계 추가", type="primary", key="add_m_btn"):
            for k in add_keys:
                md[k] = {'status':'active','added_date':now_str()}
                add_log(f"➕ {MACHINES[k]['n']} 추가", "기계추가")
            st.rerun()
    else:
        st.caption("모든 기계가 이미 등록되어 있습니다.")

    # ── 기계 제거 ──
    if active_m:
        st.markdown("---")
        with st.expander("➖ 기계·설비 제거", expanded=False):
            rm_choices = [f"{MACHINES[k]['i']} {MACHINES[k]['n']}" for k in active_m]
            rm_sel = st.selectbox("제거할 기계", ["-- 선택 --"]+rm_choices, key="rm_m")
            if rm_sel != "-- 선택 --":
                rm_opt = st.radio("제거 방법", ["🗑️ 즉시 제거","📅 1개월 후 제거","📅 2개월 후 제거"], key="rm_m_opt")
                if st.button("❌ 제거 실행", key="rm_m_btn"):
                    target_k = None
                    for k in active_m:
                        if f"{MACHINES[k]['i']} {MACHINES[k]['n']}" == rm_sel:
                            target_k = k; break
                    if target_k:
                        if "즉시" in rm_opt:
                            del md[target_k]
                            add_log(f"🗑️ {MACHINES[target_k]['n']} 즉시 제거", "기계제거")
                        else:
                            days = 30 if "1개월" in rm_opt else 60
                            md[target_k]['status']='removing'
                            md[target_k]['remove_date']=(datetime.now()+timedelta(days=days)).strftime("%Y-%m-%d")
                            add_log(f"🗓️ {MACHINES[target_k]['n']} → {md[target_k]['remove_date']} 제거 예정", "기계제거예정")
                        st.rerun()

    st.markdown("---")
    c1,c2 = st.columns(2)
    if c1.button("← 이전", use_container_width=True): go(2); st.rerun()
    if c2.button("다음 → 시설현황", type="primary", use_container_width=True): go(4); st.rerun()


# ═══════════════════════════════════════════
#  STEP 4: 시설 현황
# ═══════════════════════════════════════════
elif st.session_state.step == 4:
    st.subheader("🏗️ 시설·환경 현황")

    # 시설도 변경 추적
    fac_detail = st.session_state.profile.get('facilities', {})
    def fac_status(key):
        return fac_detail.get(key, {}).get('status', 'inactive')
    def fac_active(key):
        return fac_status(key) == 'active'

    st.markdown("### 현재 시설")
    air = st.checkbox("🌫️ 굴뚝/배기구 있음", value=fac_active('air'))
    water = st.checkbox("💧 폐수 발생", value=fac_active('water'))
    waste = st.checkbox("♻️ 사업장 폐기물 발생", value=fac_active('waste'))

    new_fac = {}
    changes = []
    for key, label, val in [('air','대기배출시설',air),('water','폐수배출',water),('waste','폐기물발생',waste)]:
        old_active = fac_active(key)
        if val and not old_active:
            new_fac[key] = {'status':'active','added_date':now_str()}
            changes.append(f"➕ {label} 추가")
        elif not val and old_active:
            changes.append(f"➖ {label} 해당사항 변경")
        elif val:
            new_fac[key] = fac_detail.get(key, {'status':'active','added_date':now_str()})

    # 시설 제거 시 옵션
    removed_facs = []
    for key, label in [('air','대기배출시설'),('water','폐수배출'),('waste','폐기물발생')]:
        if fac_active(key) and not {'air':air,'water':water,'waste':waste}[key]:
            removed_facs.append((key, label))

    fac_rm_opt = "즉시"
    if removed_facs:
        st.markdown("---")
        st.warning(f"⚠️ 시설 제거 감지: {', '.join([l for _,l in removed_facs])}")
        fac_rm_opt = st.radio("시설 제거 처리 방법", [
            "🗑️ 즉시 제거", "📅 1개월 후 제거", "📅 2개월 후 제거"
        ], key="fac_rm_opt")

    # 제거 예정 시설 표시
    fac_removing = {k:v for k,v in fac_detail.items() if v.get('status')=='removing'}
    if fac_removing:
        st.markdown("### ⏳ 제거 예정 시설")
        for k,v in fac_removing.items():
            label = {'air':'대기배출시설','water':'폐수배출','waste':'폐기물발생'}.get(k,k)
            st.info(f"⏳ {label} — 제거 예정: **{v.get('remove_date','?')}**")
            # 제거 예정 시설은 유지
            new_fac[k] = v

    st.session_state.profile['air'] = air or any(fac_detail.get('air',{}).get('status')=='removing' for _ in [1])
    st.session_state.profile['water'] = water or fac_detail.get('water',{}).get('status')=='removing'
    st.session_state.profile['waste'] = waste or fac_detail.get('waste',{}).get('status')=='removing'

    st.markdown("---")
    c1,c2 = st.columns(2)
    if c1.button("← 이전", use_container_width=True): go(3); st.rerun()
    if c2.button("🔍 규제 진단 시작!", type="primary", use_container_width=True):
        # 시설 변경 처리
        for key, label in removed_facs:
            if "즉시" in fac_rm_opt:
                add_log(f"🗑️ {label} 즉시 제거", "시설제거")
            else:
                days = 30 if "1개월" in fac_rm_opt else 60
                new_fac[key] = {'status':'removing','remove_date':(datetime.now()+timedelta(days=days)).strftime("%Y-%m-%d"),
                                'added_date':fac_detail.get(key,{}).get('added_date','')}
                add_log(f"🗓️ {label} → {new_fac[key]['remove_date']} 제거 예정", "시설제거예정")
        for ch in changes:
            if "추가" in ch: add_log(f"🏗️ 시설 — {ch}", "시설추가")
        st.session_state.profile['facilities'] = new_fac
        go(5); st.rerun()


# ═══════════════════════════════════════════
#  STEP 5: 진단결과
# ═══════════════════════════════════════════
elif st.session_state.step == 5:
    profile = st.session_state.profile.copy()
    profile['chem_results'] = st.session_state.chem_results
    profile['machines_detail'] = st.session_state.machines_detail
    regs = build_checklist(profile)
    st.session_state.regs = regs

    total = sum(len(r['items']) for r in regs.values())
    act_chems = [c for c in st.session_state.chem_results if c.get('status')!='removing']
    act_machs = {k for k,v in st.session_state.machines_detail.items() if v.get('status')=='active'}
    pending = len([c for c in st.session_state.chem_results if c.get('status')=='removing'])
    pending += len({k for k,v in st.session_state.machines_detail.items() if v.get('status')=='removing'})
    reg_chems = len([c for c in act_chems if c.get('any_regulated', True)])
    below_chems = len(act_chems) - reg_chems

    st.markdown(f"""
    <div style="background:linear-gradient(135deg,#1A237E,#3F51B5);padding:24px;border-radius:16px;color:white;margin-bottom:20px">
      <h2 style="margin:0">📊 {profile.get('name','사업장')} 규제 진단 결과</h2>
      <p style="margin:10px 0 0;opacity:0.8">
        적용 법규 <b>{len(regs)}개</b> · 체크항목 <b>{total}개</b> ·
        직원 {profile.get('workers',0)}명 · 기계 {len(act_machs)}종 ·
        화학물질 <b>{len(act_chems)}종</b> (규제해당 <span style="color:#FF8A80">{reg_chems}</span> / 함유량미달 <span style="color:#B9F6CA">{below_chems}</span>)
        {f' · <span style="color:#FFD54F">⏳삭제예정 {pending}건</span>' if pending else ''}
      </p>
    </div>
    """, unsafe_allow_html=True)

    if act_chems:
        regulated = [c for c in act_chems if c.get('any_regulated', True)]
        below_cutoff = [c for c in act_chems if not c.get('any_regulated', True)]
        
        with st.expander(f"🧪 규제 해당 화학물질 ({len(regulated)}종)", expanded=True):
            if regulated:
                for c in regulated:
                    tag_str = " ".join(make_tags(c, "markdown"))
                    pct = f" [{c.get('content_str','')}%]" if c.get('content_str') else ""
                    st.markdown(f"- **{c['name']}** ({c['cas']}){pct} → {tag_str}")
            else:
                st.info("규제 해당 물질 없음")

        if below_cutoff:
            with st.expander(f"💚 함유량 미달 — 규제 비해당 ({len(below_cutoff)}종)", expanded=False):
                st.caption("KOSHA 등록 물질이나, 제품 내 함유량이 법적 기준(cut-off) 미만이라 규제 대상에서 제외됩니다.")
                for c in below_cutoff:
                    notes = []
                    for k in ['managed','special','toxic','measure','health','restricted','accident_prep']:
                        note = c.get(f'{k}_note','')
                        if '미달' in note or '비해당' in note:
                            notes.append(note)
                    pct = f" [{c.get('content_str','')}%]" if c.get('content_str') else ""
                    st.markdown(f"- **{c['name']}** ({c['cas']}){pct} → 💚규제 비해당")
                    if notes:
                        st.caption(f"  {' | '.join(notes[:2])}")

    for key, reg in regs.items():
        crit = sum(1 for i in reg['items'] if i['p']=='critical')
        st.markdown(f"### {reg['icon']} {reg['title']} — {len(reg['items'])}개 (필수 {crit}건)")
        for it in reg['items']:
            em = {'critical':'🔴','high':'🟠'}.get(it['p'],'⚪')
            st.write(f"  {em} {it['t']}")

    st.markdown("---")
    c1,c2 = st.columns(2)
    if c1.button("← 처음부터", use_container_width=True): go(1); st.rerun()
    if c2.button("✅ 대시보드 →", type="primary", use_container_width=True):
        # 진단 완료 → 자동 저장
        name = st.session_state.profile.get('name','')
        if name:
            _save_company(name)
            add_log("💾 진단 완료 → 자동 저장", "시스템")
        go(6); st.rerun()


# ═══════════════════════════════════════════
#  STEP 6: 대시보드
# ═══════════════════════════════════════════
elif st.session_state.step == 6:
    regs = st.session_state.get('regs',{})
    if not regs:
        st.warning("진단을 먼저 완료해 주세요.")
        if st.button("처음부터"): go(1); st.rerun()
    else:
        profile = st.session_state.profile
        all_items = [i for r in regs.values() for i in r['items']]
        total = len(all_items)
        done = sum(1 for i in all_items if st.session_state.checked.get(i['t']))
        pct = round(done/total*100) if total else 0
        pending = len([c for c in st.session_state.chem_results if c.get('status')=='removing'])
        pending += len({k for k,v in st.session_state.machines_detail.items() if v.get('status')=='removing'})

        st.markdown(f"""
        <div style="background:linear-gradient(135deg,#0D1B2A,#2C3E50);padding:24px;border-radius:16px;color:white;margin-bottom:20px">
          <h2 style="margin:0;font-size:20px">🏢 {profile.get('name','')} 규제 대시보드</h2>
          <div style="margin-top:14px;display:flex;gap:30px;flex-wrap:wrap">
            <div><span style="font-size:36px;font-weight:800">{pct}%</span> <span style="opacity:0.6">이행률</span></div>
            <div><span style="font-size:22px;font-weight:700">{done}/{total}</span> <span style="opacity:0.6">완료</span></div>
            <div><span style="font-size:22px;font-weight:700">{len(st.session_state.change_log)}</span> <span style="opacity:0.6">변경이력</span></div>
            {f'<div><span style="font-size:22px;font-weight:700;color:#FFD54F">⏳{pending}</span> <span style="opacity:0.6">삭제예정</span></div>' if pending else ''}
          </div>
        </div>
        """, unsafe_allow_html=True)

        tabs = st.tabs([f"{r['icon']} {r['title']}" for r in regs.values()])
        for tab, (key,reg) in zip(tabs, regs.items()):
            with tab:
                rd = sum(1 for i in reg['items'] if st.session_state.checked.get(i['t']))
                rt = len(reg['items'])
                rp = round(rd/rt*100) if rt else 0
                st.progress(rp/100, text=f"{rp}% ({rd}/{rt})")
                for it in reg['items']:
                    pri = {'critical':'🔴필수','high':'🟠중요'}.get(it['p'],'⚪')
                    ck = st.checkbox(f"{pri} {it['t']}", value=st.session_state.checked.get(it['t'],False),
                                     key=f"ck_{key}_{it['t'][:30]}", help=it['d'])
                    st.session_state.checked[it['t']] = ck

        st.markdown("---")
        c1,c2,c3,c4 = st.columns(4)
        if c1.button("← 진단결과", use_container_width=True): go(5); st.rerun()
        if c2.button("📝 변경이력", use_container_width=True): go(7); st.rerun()
        if c3.button("🔄 MSDS 업데이트", use_container_width=True): go(2); st.rerun()
        if c4.button("🗑 체크초기화", use_container_width=True): st.session_state.checked={}; st.rerun()


# ═══════════════════════════════════════════
#  STEP 7: 변경이력
# ═══════════════════════════════════════════
elif st.session_state.step == 7:
    st.subheader("📝 변경이력 관리")
    st.caption("MSDS, 기계·설비, 시설 모든 변경사항이 자동 기록됩니다.")

    log = st.session_state.change_log
    pending_c = [c for c in st.session_state.chem_results if c.get('status')=='removing']
    pending_m = {k:v for k,v in st.session_state.machines_detail.items() if v.get('status')=='removing'}
    pending_f = {k:v for k,v in st.session_state.profile.get('facilities',{}).items() if v.get('status')=='removing'}

    # ── 삭제 예정 관리 ──
    if pending_c or pending_m or pending_f:
        st.markdown("### ⏳ 삭제/제거 예정 항목")
        st.warning("예정일에 삭제됩니다. '즉시삭제' 버튼으로 앞당길 수 있습니다.")

        for c in pending_c:
            col1,col2 = st.columns([7,1])
            col1.write(f"🧪 **{c['name']}** ({c['cas']}) — 삭제 예정: {c.get('remove_date','?')}")
            if col2.button("즉시삭제", key=f"now_c_{c['cas']}"):
                st.session_state.chem_results.remove(c)
                add_log(f"🗑️ {c['name']}({c['cas']}) 즉시 삭제 (예정 취소)", "MSDS삭제")
                st.rerun()

        for k,v in pending_m.items():
            m = MACHINES.get(k,{})
            col1,col2 = st.columns([7,1])
            col1.write(f"🔧 **{m.get('n',k)}** — 제거 예정: {v.get('remove_date','?')}")
            if col2.button("즉시제거", key=f"now_m_{k}"):
                del st.session_state.machines_detail[k]
                add_log(f"🗑️ {m.get('n',k)} 즉시 제거 (예정 취소)", "기계제거")
                st.rerun()

        for k,v in pending_f.items():
            label = {'air':'대기배출시설','water':'폐수배출','waste':'폐기물발생'}.get(k,k)
            col1,col2 = st.columns([7,1])
            col1.write(f"🏗️ **{label}** — 제거 예정: {v.get('remove_date','?')}")
            if col2.button("즉시제거", key=f"now_f_{k}"):
                del st.session_state.profile['facilities'][k]
                st.session_state.profile[k] = False
                add_log(f"🗑️ {label} 즉시 제거 (예정 취소)", "시설제거")
                st.rerun()
        st.markdown("---")

    # ── 전체 이력 ──
    st.markdown(f"### 📋 전체 변경이력 ({len(log)}건)")
    if log:
        categories = sorted(set(l['category'] for l in log))
        cat_f = st.selectbox("카테고리 필터", ["전체"]+categories, key="log_f")
        filtered = log if cat_f=="전체" else [l for l in log if l['category']==cat_f]

        icons = {"MSDS추가":"🟢","MSDS변경":"🔵","MSDS삭제":"🔴","MSDS삭제예정":"🟡",
                 "기계추가":"🟢","기계제거":"🔴","기계제거예정":"🟡",
                 "시설추가":"🟢","시설제거":"🔴","시설제거예정":"🟡","일반":"⚪"}
        for l in filtered:
            ic = icons.get(l['category'],'⚪')
            st.markdown(f"{ic} **{l['time']}** `{l['category']}` — {l['msg']}")
    else:
        st.info("아직 변경이력이 없습니다. MSDS 업로드, 기계 추가/제거 등을 수행하면 자동 기록됩니다.")

    st.markdown("---")
    c1,c2,c3 = st.columns(3)
    if c1.button("← 대시보드", use_container_width=True): go(6); st.rerun()
    if c2.button("🔄 MSDS 업데이트", use_container_width=True): go(2); st.rerun()
    if c3.button("🔧 기계 관리", use_container_width=True): go(3); st.rerun()

    if log:
        st.markdown("---")
        log_txt = f"# {st.session_state.profile.get('name','사업장')} EHS 변경이력\n# 출력일: {now_str()}\n\n"
        for l in log:
            log_txt += f"[{l['time']}] [{l['category']}] {l['msg']}\n"
        st.download_button("📥 변경이력 다운로드 (TXT)", log_txt, file_name="EHS_변경이력.txt", mime="text/plain")


st.markdown("---")
st.caption("📚 KOSHA API 실시간 규제 조회 (최신 데이터만 사용) | ⚠️ 참고용이며 최종 확인은 관할 행정기관에 문의하세요")
