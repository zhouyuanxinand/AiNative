"""Select specification grades and test conditions before numeric comparison.

Workbook Sheet1 C3:C6 and B7 are the source of this policy. A candidate's
qualification is evidence, never another measurement to fold into its value.
"""
from __future__ import annotations

import re
import unicodedata
from decimal import Decimal


def _compact(value: str) -> str:
    return re.sub(r'\s+', '', unicodedata.normalize('NFKC', str(value or ''))).replace('−', '-')


def _contact_grade_tokens(value: str) -> list[str]:
    normalized = _compact(value).replace('Φ', 'φ').replace('Ф', 'φ').replace('ф', 'φ')
    return re.findall(r'#\d+[A-Za-z]*|\d+[A-Za-z]*#|φ\d+(?:\.\d+)?', normalized)


def _contact_token_present(token: str, context: str) -> bool:
    normalized = _compact(context).replace('Φ', 'φ').replace('Ф', 'φ').replace('ф', 'φ')
    return bool(re.search(r'(?<![\dA-Za-z.])' + re.escape(token) + r'(?![\dA-Za-z.])', normalized, re.IGNORECASE))


def qualifier_matches(label: str, value: str, context: str) -> bool:
    label, value, context = _compact(label), _compact(value), _compact(context)
    if not value:
        return True
    if re.search(r'接触件|针径|规格', label) and not re.search(r'线规|AWG|壳体', label, re.IGNORECASE):
        grades = _contact_grade_tokens(value)
        if grades:
            # One row can list equivalent sizes, e.g. “Ф1.5、16#(Ф1.6)”.
            # Match an explicitly named size, never a measured numeric value.
            return any(_contact_token_present(grade, context) for grade in grades)
    escaped = re.escape(value)
    if re.search(r'线规|AWG', label, re.IGNORECASE):
        number = re.sub(r'AWG|#', '', value, flags=re.IGNORECASE)
        return bool(re.search(rf'(?:AWG|线规[:：=]?)#?{re.escape(number)}(?![\dA-Za-z])|(?<!\d){re.escape(number)}AWG', context, re.IGNORECASE))
    if '壳体' in label:
        return bool(re.search(rf'壳体(?:号|规格|尺寸)?[:：=]?{escaped}(?![\dA-Za-z])', context))
    if re.search(r'位数|芯数|孔数', label):
        return bool(re.search(rf'(?:位数|芯数|孔数)[:：=]?{escaped}(?!\d)|(?<!\d){escaped}(?:位|芯|孔)', context))
    if value.startswith('#'):
        return bool(re.search(re.escape(value) + r'(?![\dA-Za-z])', context, re.IGNORECASE))
    if re.fullmatch(r'\d+(?:\.\d+)?', value):
        return bool(re.search(rf'(?:{re.escape(label)}|规格|档位)[:：=]?{escaped}(?![\dA-Za-z.])', context))
    return bool(re.search(r'(?<![\dA-Za-z])' + escaped + r'(?![\dA-Za-z])', context, re.IGNORECASE))


def _conditions(text: str, *, requirement: bool = False) -> dict[str, str]:
    text = _compact(text)
    text = re.sub(r"(?:常温|室温)状态", "常温", text)
    text = re.sub(r"kpa", "kPa", text, flags=re.IGNORECASE)
    text = re.sub(r"mpa", "MPa", text, flags=re.IGNORECASE)
    result = {}
    temperature = re.search(r'(?<![\d.])([+-]?\d+(?:\.\d+)?)(?:°C|℃)', text, re.IGNORECASE)
    if temperature:
        result['temperature'] = str(float(temperature.group(1)))
    elif re.search(r'常温|室温', text):
        result['temperature'] = 'normal'
    pressure = re.search(r'标准大气压|标准大气条件|常压', text)
    if pressure:
        result['pressure'] = 'normal'
    if re.search(r'试验前|测试前|初始', text):
        result['phase'] = 'before'
    elif re.search(r'试验后|测试后|老化后|振动后|冲击后', text):
        result['phase'] = next(m.group(0) for m in re.finditer(r'试验后|测试后|老化后|振动后|冲击后', text))
        if result['phase'] in {'试验后', '测试后'}:
            result['phase'] = 'after'
    if re.search(r'标准条件|正常条件', text):
        result['environment'] = 'normal'
    multiple_conditions = False
    for key, pattern in (
        ('humidity', r'([\d.]+%)(?:RH|相对湿度)?'),
        ('pressure_value', r'([\d.]+(?:kPa|Pa|MPa))'),
        ('frequency', r'([\d.]+(?:GHz|MHz|kHz|Hz))'),
        ('duration', r'([\d.]+(?:min|ms|s|小时|分钟|秒))'),
        ('state', r'(干态|湿态|浸水|浸油)'),
        ('waveform', r'(正弦|随机)'),
        ('current_type', r'(AC|DC|交流|直流)'),
    ):
        match = re.search(pattern, text)
        if match:
            result[key] = match.group(1)
        if len(set(re.findall(pattern, text))) > 1:
            multiple_conditions = True
    if len(set(re.findall(r'([+-]?\d+(?:\.\d+)?)(?:°C|℃)', text, re.IGNORECASE))) > 1:
        multiple_conditions = True
    if (re.search(r'试验前|测试前|初始', text) and re.search(r'试验后|测试后|老化后|振动后|冲击后', text)):
        multiple_conditions = True
    if multiple_conditions:
        result['ambiguous_conditions'] = text
    if re.search(r'(?:非|不是|不在|禁止|除)(?:常温|室温|常压|干态|湿态|浸水|浸油|试验前|试验后|测试前|测试后|交流|直流|正弦|随机)', text):
        result['negated_conditions'] = text
    for key, scales in (
        ('pressure_value', {'Pa': 1, 'kPa': 1000, 'MPa': 1000000}),
        ('frequency', {'Hz': 1, 'kHz': 1000, 'MHz': 1000000, 'GHz': 1000000000}),
        ('duration', {'ms': Decimal('0.001'), 's': 1, 'min': 60, '秒': 1, '分钟': 60, '小时': 3600}),
    ):
        if key in result:
            number = re.match(r'[\d.]+', result[key]).group(0)
            unit = result[key][len(number):]
            result[key] = str((Decimal(number) * scales[unit]).normalize())
    if not requirement and text:
        residual = re.sub(
            r'[+-]?\d+(?:\.\d+)?(?:°C|℃|kPa|MPa|Pa|GHz|MHz|kHz|Hz|min|ms|s|小时|分钟|秒|%RH|%)'
            r'|标准大气条件|标准大气压|常温|室温|常压|试验前|测试前|初始'
            r'|试验后|测试后|老化后|振动后|冲击后|标准条件|正常条件'
            r'|干态|湿态|浸水|浸油|正弦|随机|AC|DC|交流|直流'
            r'|测试条件|试验条件|相对湿度|温度|湿度|压力|频率|时间|持续|条件'
            r'|[\s,，;；:：()（）]', '', text,
        )
        if residual:
            # Unknown conditions cannot disappear merely because the same
            # clause also contains a recognizable ambient temperature.
            result['other'] = text
    return result


def validate_clarification(original: str, clarification: str, candidates: list[dict]) -> None:
    """A clarification may fill missing context, but cannot replace input facts."""
    if not clarification:
        return
    original_conditions = _conditions(original, requirement=True)
    clarified_conditions = _conditions(clarification, requirement=True)
    for key, value in clarified_conditions.items():
        if key in original_conditions and original_conditions[key] != value:
            raise ValueError('澄清条件与原技术要求冲突，请修订设计输入后重新提交。')
    fields: dict[str, set[str]] = {}
    for candidate in candidates:
        for label, value in (candidate.get('qualifiers') or {}).items():
            fields.setdefault(str(label), set()).add(str(value))
    for label, values in fields.items():
        known = {value for value in values if qualifier_matches(label, value, original)}
        added = {value for value in values if qualifier_matches(label, value, clarification)}
        if known and added and known != added:
            raise ValueError('澄清规格与原技术要求冲突，请修订设计输入后重新提交。')


def measurement_text(text: str, indicator_names: list[str], candidates: list[dict]) -> str:
    """Remove only identified labels and matched applicability context.

    The numeric comparator still rejects every remaining unknown quantitative
    condition; this never extracts just the first threshold from a paragraph.
    """
    value = unicodedata.normalize('NFKC', str(text or ''))
    for candidate in candidates:
        for label, qualifier in (candidate.get('qualifiers') or {}).items():
            if qualifier_matches(str(label), str(qualifier), value):
                q = re.escape(unicodedata.normalize('NFKC', str(qualifier)))
                grades = _contact_grade_tokens(str(qualifier)) if re.search(r'接触件|针径|规格', str(label)) else []
                if grades:
                    value = value.replace('Φ', 'φ').replace('Ф', 'φ').replace('ф', 'φ')
                    for grade in grades:
                        value = re.sub(r'(?<![\dA-Za-z.])' + re.escape(grade) + r'(?![\dA-Za-z.])', '', value, flags=re.IGNORECASE)
                elif re.search(r'线规|AWG', str(label), re.IGNORECASE):
                    q = re.escape(re.sub(r'AWG|#', '', str(qualifier), flags=re.IGNORECASE))
                    value = re.sub(rf'(?:AWG|线规[:：=]?)#?{q}(?![\dA-Za-z])|(?<!\d){q}AWG', '', value, flags=re.IGNORECASE)
                elif str(qualifier).startswith('#'):
                    value = re.sub(q + r'(?![\dA-Za-z])', '', value, flags=re.IGNORECASE)
                else:
                    value = re.sub(rf'(?:{re.escape(str(label))}|壳体(?:号|规格|尺寸)|规格|档位|位数|芯数|孔数)\s*[:：=]?\s*{q}(?![\dA-Za-z])', '', value)
        condition = unicodedata.normalize('NFKC', str(candidate.get('condition') or ''))
        if condition:
            expected = _conditions(condition)
            field_names = ' '.join(indicator_names)

            def remove_condition(match: re.Match, expected=expected, value=value, field_names=field_names) -> str:
                token = match.group(0)
                parsed = _conditions(token)
                if not parsed or not all(expected.get(key) == item for key, item in parsed.items()):
                    return token
                prefix = value[:match.start()]
                if re.search(r'(?:[<>≤≥=~～±]|min|max|不超过|不少于|不大于|不小于)\s*$', prefix, re.IGNORECASE):
                    return token
                measured_dimension = any(
                    key in parsed and re.search(pattern, field_names)
                    for key, pattern in (
                        ('temperature', r'温度|温升'), ('pressure_value', r'压力|压强'),
                        ('frequency', r'频率'), ('duration', r'时间|寿命'), ('humidity', r'湿度'),
                    )
                )
                if measured_dimension and not re.search(r'(?:在|(?:测试|试验)(?:条件|温度|压力|频率|时间)[:：]?)\s*$', prefix):
                    return token
                return ''

            # Each removal is bound to one verified condition occurrence.
            # Identical numbers elsewhere may be the actual user threshold.
            value = re.sub(
                r'(?<![\d.])[+-]?\d+(?:\.\d+)?\s*(?:°C|℃|MPa|kPa|Pa|GHz|MHz|kHz|Hz|min|ms|s|%RH)(?![A-Za-z\d])',
                remove_condition, value,
            )
            if not re.search(r'\d', condition):
                value = value.replace(condition, '')
            # Extract known context pieces from the selected specification,
            # including equivalent ambient/before-test wording.
            tokens = re.findall(r'常温|室温|试验前|测试前|初始|试验后|测试后|老化后|振动后|冲击后|常压|标准大气压|标准条件|正常条件|干态|湿态|正弦|随机|AC|DC', condition)
            for token in tokens:
                pattern = re.escape(token).replace(r'\ ', r'\s*')
                if token in {'常温', '室温'}:
                    pattern = r'常温|室温'
                elif token in {'试验前', '测试前', '初始'}:
                    pattern = r'试验前|测试前|初始'
                elif token in {'试验后', '测试后'}:
                    pattern = r'试验后|测试后'
                value = re.sub(pattern, '', value)
    for name in sorted(set(indicator_names), key=len, reverse=True):
        if name:
            value = value.replace(unicodedata.normalize('NFKC', name), '')
    # Grammar around an already identified field is not a test condition.
    value = re.sub(r'接触件|接触对|测试条件|试验条件|条件为|要求为|要求|应当|必须|应|需|须|的|在|下|时', '', value)
    # A nonempty source cannot become a missing-user-value fallback merely
    # because its labels or conditions consume the whole extracted fragment.
    return value.strip(' ：:，,；;。()（）\n') or str(text or '').strip()


def comparison_value(item: dict) -> str:
    """Carry a source column's bound and unit into the comparison expression."""
    value = str(item.get('value') or '').strip()
    unit = str(item.get('unit') or '').strip()
    if unit and unit not in value:
        value = f'{value} {unit}'
    kind = str(item.get('value_kind') or '').lower()
    if kind in {'min', 'max', 'typ'} and not re.search(r'≤|≥|<=|>=|不大于|不小于|不超过|不少于|\b(?:min|max|typ)\b', value, re.IGNORECASE):
        value = f'{kind}: {value}'
    return value


def _formal_measurement(item: dict) -> str:
    """Render one guaranteed value without its repeated applicability labels."""
    value = str(item.get('value') or '').strip()
    unit = str(item.get('unit') or '').strip()
    if unit and unit not in value:
        value = f'{value} {unit}'
    kind = str(item.get('value_kind') or '').lower()
    if kind in {'min', 'max'} and not re.search(
        r'≤|≥|<=|>=|不大于|不小于|不超过|不少于|\b(?:min|max)\b',
        value,
        re.IGNORECASE,
    ):
        value = f'{kind}：{value}'
    return value


def _formal_context(item: dict) -> tuple[tuple[str, str], ...]:
    """Return stable labels that scope a group of specification values."""
    parts = sorted(
        (
            (str(label).strip(), str(value).strip())
            for label, value in (item.get('qualifiers') or {}).items()
            if str(label).strip() and str(value).strip()
        ),
        key=lambda pair: pair[0],
    )
    scope = str(item.get('scope') or '').strip()
    condition = str(item.get('condition') or '').strip()
    if scope:
        parts.append(('适用型号/系列', scope))
    if condition:
        parts.append(('条件', condition))
    return tuple(parts)


def _formal_annotations(item: dict, measurement: str) -> list[str]:
    """Keep source notes/methods while removing labels owned by the group."""
    display = str(item.get('display_value') or '').strip()
    if not display:
        return []
    for label, value in _formal_context(item):
        display = display.replace(f'{label}：{value}', '')
        display = display.replace(f'{label}:{value}', '')
    display = re.sub(r'[；;]{2,}', '；', display).strip(' ；;')
    if not display:
        return []

    # spec_extractor writes the measurement first and then source notes and
    # the test method.  Pull the first part out so common annotations can be
    # emitted once after all min/max guarantees in this applicability group.
    alternatives = [measurement]
    kind = str(item.get('value_kind') or '').lower()
    if kind in {'min', 'max'}:
        alternatives.append(measurement.replace(f'{kind}：', f'{kind}:', 1))
    for prefix in alternatives:
        if prefix and display.startswith(prefix):
            remainder = display[len(prefix):].strip(' ；;')
            return [part.strip() for part in re.split(r'[；;]', remainder) if part.strip()]
    # Hand-authored/legacy candidates may not use the extractor's standard
    # prefix.  Their complete text remains evidence instead of being dropped.
    return [display] if display != measurement else []


def formal_display_value(items: list[dict]) -> str:
    """Project selected candidates into a compact formal requirement.

    Full candidate rows remain in the audit payload.  The taskbook table gets
    only guaranteed values, grouped by grade/model/test condition so those
    labels occur once per group.  ``typ`` is reference evidence and therefore
    never enters the formal requirement.
    """
    groups: dict[tuple[tuple[str, str], ...], dict[str, list[str]]] = {}
    for item in items:
        if str(item.get('value_kind') or '').lower() == 'typ':
            continue
        measurement = _formal_measurement(item)
        if not measurement:
            continue
        context = _formal_context(item)
        group = groups.setdefault(context, {'values': [], 'annotations': []})
        if measurement not in group['values']:
            group['values'].append(measurement)
        for annotation in _formal_annotations(item, measurement):
            if annotation not in group['annotations']:
                group['annotations'].append(annotation)

    rendered = []
    for context, group in groups.items():
        payload = '；'.join([*group['values'], *group['annotations']])
        labels = '；'.join(f'{label}：{value}' for label, value in context)
        if labels and payload:
            rendered.append(f'{labels}（{payload}）')
        elif labels or payload:
            rendered.append(labels or payload)
    return '；'.join(rendered)


def select_applicable_candidates(
    candidates: list[dict],
    *,
    user_requirement: str = '',
    source_context: str = '',
    indicator_name: str = '',
) -> dict:
    """Resolve grades, environmental defaults and guaranteed value columns.

    Product/model scope is selected by the caller using its controlled product
    selection. This function never guesses that a numeric measurement is a
    contact size, shell size or wire gauge.
    """
    context = f'{source_context}\n{user_requirement}'
    result = {
        'candidate_items': candidates, 'reference_items': [],
        'manual_review_required': False, 'default_conditions_applied': False,
        'status': 'SPEC_APPLICABLE', 'reason': '', 'items': [], 'value': '',
    }

    def clarify(status: str, reason: str) -> dict:
        return {**result, 'status': status, 'reason': reason, 'manual_review_required': True}

    qualified = []
    for item in candidates:
        qualifiers = item.get('qualifiers') or {}
        if all(qualifier_matches(str(label), str(value), context) for label, value in qualifiers.items()):
            qualified.append(item)
    if not qualified:
        return clarify('SPEC_GRADE_UNSPECIFIED', '需澄清具体规格、档位、线规、壳体号或位数；各档规范值分别列示。')
    if any(item.get('qualifiers') for item in candidates):
        specific = [item for item in qualified if item.get('qualifiers')]
        if not specific:
            return clarify('SPEC_GRADE_UNSPECIFIED', '规范含分档要求，通用行不能代替缺失的规格信息；需逐档澄清。')
        qualified = specific
    contact_qualifiers = [str(value) for item in candidates
        for label, value in (item.get('qualifiers') or {}).items()
        if re.search(r'接触件|针径|规格', str(label)) and _contact_grade_tokens(str(value))]
    requested_grades = _contact_grade_tokens(user_requirement)
    if contact_qualifiers and any(not any(_contact_token_present(grade, value)
        for value in contact_qualifiers) for grade in requested_grades):
        return clarify('SPEC_GRADE_NOT_APPLICABLE', '规范没有与输入全部接触件规格对应的指标组，需逐档确认。')
    distinct_qualifiers = {
        tuple(sorted((str(k), str(v)) for k, v in (item.get('qualifiers') or {}).items()))
        for item in qualified
    }
    if len(distinct_qualifiers) > 1:
        # Multiple explicitly paired clauses can be checked independently.
        # A shared/between-grades clause or an unscoped leftover is ambiguous;
        # do not invent a pairing or drop part of the original requirement.
        clauses = [part.strip() for part in re.split(r'[；;\n]', user_requirement) if part.strip()]
        grouped = {key: [] for key in sorted(distinct_qualifiers)}
        for item in qualified:
            key = tuple(sorted((str(k), str(v)) for k, v in (item.get('qualifiers') or {}).items()))
            grouped[key].append(item)
        pairs = {}
        for clause in clauses:
            matched = [key for key in grouped if all(qualifier_matches(k, v, clause) for k, v in key)]
            if len(matched) != 1 or matched[0] in pairs:
                return clarify('SPEC_MULTIPLE_GRADES', '输入同时命中多个规格或档位，需要逐档确认对应的用户指标。')
            pairs[matched[0]] = clause
        if set(pairs) != set(grouped):
            return clarify('SPEC_MULTIPLE_GRADES', '输入同时命中多个规格或档位，需要逐档确认对应的用户指标。')
        resolved_groups = []
        for key, clause in pairs.items():
            selected = select_applicable_candidates(grouped[key], user_requirement=clause,
                source_context=source_context, indicator_name=indicator_name)
            if selected['manual_review_required']:
                return selected
            resolved_groups.append({'qualifiers': dict(key), 'user_requirement': clause,
                'items': selected['items'], 'value': selected['value']})
        selected_items = [item for group in resolved_groups for item in group['items']]
        return {**result, 'status': 'SPEC_MULTIPLE_GRADES_RESOLVED', 'items': selected_items,
            'value': '；'.join(group['value'] for group in resolved_groups), 'grade_groups': resolved_groups}

    # Do not treat a working-temperature threshold as its own test condition.
    conditional = any(item.get('condition') for item in qualified)
    requested = _conditions(user_requirement, requirement=True) if conditional else {}
    # A measured pressure/temperature/frequency is not a test condition.
    # Explicit test context, headings and separately supplied clarification
    # remain eligible evidence for those same dimensions.
    for name_pattern, condition_key, explicit in (
        (r'温度|温升', 'temperature', r'(?:试验|测试)温度|在\s*[+-]?\d+(?:\.\d+)?\s*(?:℃|°C)'),
        (r'压力|压强', 'pressure_value', r'(?:试验|测试)压力|在\s*\d+(?:\.\d+)?\s*(?:MPa|kPa|Pa)'),
        (r'频率', 'frequency', r'(?:试验|测试)频率|在\s*\d+(?:\.\d+)?\s*(?:kHz|Hz)'),
        (r'时间|寿命', 'duration', r'(?:试验|测试)时间'),
    ):
        if re.search(name_pattern, indicator_name) and not re.search(explicit, user_requirement):
            requested.pop(condition_key, None)
    if conditional:
        requested.update(_conditions(source_context, requirement=True))
    if any(key in requested for key in ('ambiguous_conditions', 'negated_conditions')):
        return clarify('SPEC_CONDITION_AMBIGUOUS', '包含多组或否定测试条件，需逐组明确适用范围，不能仅按首组条件比较。')
    applicable = []
    unmatched_default = False
    for item in qualified:
        available = _conditions(str(item.get('condition') or ''))
        if any(key in available for key in ('ambiguous_conditions', 'negated_conditions')):
            unmatched_default = True
            continue
        if available.get('other') and re.search(
            r'(?<![\dA-Za-z.])' + re.escape(available['other']) + r'(?![\dA-Za-z.])', _compact(context),
        ):
            available.pop('other')
        if any(available.get(key) != value for key, value in requested.items()):
            continue
        extra = {key: value for key, value in available.items() if key not in requested}
        if extra:
            # The only workbook-authorized implicit choices are ambient /
            # standard atmospheric / pre-test conditions, never a grade.
            normal = {'temperature': 'normal', 'pressure': 'normal', 'phase': 'before', 'environment': 'normal'}
            if any(normal.get(key) != value for key, value in extra.items()):
                unmatched_default = True
                continue
            result['default_conditions_applied'] = True
        applicable.append(item)
    if not applicable:
        if requested:
            durations = {_conditions(str(item.get('condition') or '')).get('duration') for item in qualified}
            durations.discard(None)
            if requested.get('duration') and durations and requested['duration'] not in durations:
                seconds = lambda value: format(Decimal(value), 'f')
                return clarify('SPEC_CONDITION_MISMATCH',
                    f"测试持续时间不符（输入{seconds(requested['duration'])} s；规范"
                    + '、'.join(seconds(value) + ' s' for value in sorted(durations)) + "），不可比。")
            return clarify('SPEC_CONDITION_MISMATCH', '条件不符，不可比：产品规范没有与输入测试条件对应的指标组。')
        if unmatched_default:
            return clarify('SPEC_CONDITION_UNSPECIFIED', '需澄清测试条件：规范没有明确的常温、标准大气压或试验前默认组。')
        return clarify('SPEC_CONDITION_MISMATCH', '条件不符，不可比。')

    result['reference_items'] = [item for item in applicable if str(item.get('value_kind', '')).lower() == 'typ']
    guaranteed = [item for item in applicable if str(item.get('value_kind', '')).lower() != 'typ']
    if not guaranteed:
        return clarify('SPEC_TYPICAL_ONLY', '规范仅提供 typ 参考值，不能据此判定符合。')
    groups: dict[str, set[str]] = {}
    for item in guaranteed:
        groups.setdefault(str(item.get('value_kind') or ''), set()).add(comparison_value(item))
    if any(len(values) > 1 for values in groups.values()):
        return clarify('SPEC_MULTIPLE_VALUES', '同一适用范围仍有多个不同保证值，需设计逐项确认。')
    result['items'] = guaranteed
    result['value'] = '；'.join(dict.fromkeys(comparison_value(item) for item in guaranteed))
    return result


def compare_applicable_values(user_requirement: str, indicator_names: list[str], hit: dict):
    """Compare every explicitly paired grade; never compare the first value only."""
    from .indicator_comparison import IndicatorComparison, compare_indicator_values

    groups = hit.get('grade_groups') or []
    if not groups:
        return compare_indicator_values(measurement_text(user_requirement, indicator_names,
            hit.get('items') or []), str(hit.get('value') or ''))
    comparisons = [compare_indicator_values(measurement_text(group['user_requirement'],
        indicator_names, group['items']), group['value']) for group in groups]
    statuses = {comparison.status for comparison in comparisons}
    notes = '；'.join(comparison.audit_note for comparison in comparisons if comparison.audit_note)
    if any(comparison.manual_review_required for comparison in comparisons):
        return IndicatorComparison(user_requirement, notes, True, 'manual_review')
    if statuses <= {'equal', 'stricter_user'}:
        return IndicatorComparison(user_requirement, notes, False,
            'equal' if statuses == {'equal'} else 'stricter_user')
    if statuses <= {'equal', 'stricter_standard'}:
        return IndicatorComparison(str(hit.get('display_value') or hit.get('value') or ''), notes,
            False, 'stricter_standard')
    return IndicatorComparison(user_requirement, '[人工复核] 各档择严方向不同，需逐档确认。', True, 'manual_review')
