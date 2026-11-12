"""Independent NX/plan/provenance checks and conservative two-foot replay.

Only the standard library is used; neither composer nor source/legacy validators
are imported. Ledger entries are individual REDUCE_CHORD_HEAD/source_lane or
whole OMIT_ONSET/source_lanes. Geometry is a review constraint, not a rating or
proof of native-engine execution. Foot identifiers are integers 0 and 1.
"""
from __future__ import annotations
from collections import Counter
import math
from .recovery import replay as audit_recovery, valid_bracket

TAP, HEAD, BODY, TAIL = 0x43, 0x57, 0x5B, 0x5F
SINGLE = ((-1., -1.), (-1., 1.), (0., 0.), (1., 1.), (1., -1.))
DOUBLE = tuple((x - 1.5, y) for x, y in SINGLE) + tuple((x + 1.5, y) for x, y in SINGLE)
EPS = 1e-7


def _decode(nx, label, errors):
    """Decode actual cells and clocks, including mandatory hold body continuity."""
    cols = int(nx['cols'])
    flat, clock, heads = [], [], []
    beat = 0.
    max_rpb = 0
    for split, block in enumerate(nx['splits']):
        h = tuple(block['head'])
        bpm, rpb = float(h[4]), int(h[8]) & 255
        heads.append(h)
        if not math.isfinite(bpm) or bpm <= 0 or not 1 <= rpb <= 192:
            raise ValueError(f'{label}: invalid BPM/rows-per-beat at split {split}')
        if rpb > 24:
            errors.append(f'TICK_CAP: {label} split {split} uses {rpb} rows/beat (>24)')
        max_rpb = max(max_rpb, rpb)
        beat += float(h[6]) * bpm / 60000.
        for row, cells in enumerate(block['rows']):
            ms = float(h[3]) + row * 60000. / bpm / rpb
            if not math.isfinite(ms):
                raise ValueError(f'{label}: nonfinite clock at split {split}, row {row}')
            clock.append((beat + row / rpb, ms, split, row))
            if cells is None:
                flat.append((0,) * cols)
            else:
                if len(cells) != cols:
                    raise ValueError(f'{label}: row width differs from cols at split {split}, row {row}')
                flat.append(tuple(int(v) & 255 if v else 0 for v in cells))
        beat += len(block['rows']) / rpb
    events, active, raw = {}, {}, Counter()
    for index, cells in enumerate(flat):
        bt, ms, _, _ = clock[index]
        for lane, kind in enumerate(cells):
            if kind:
                raw[kind] += 1
            if lane in active and kind not in (BODY, TAIL):
                errors.append(f'HOLD_BODY: {label} lane {lane} missing/overwritten body at row {index}')
            if kind in (TAP, HEAD):
                e = events.setdefault(index, {'index': index, 'beat': bt, 'ms': ms, 'lanes': [], 'holds': []})
                e['lanes'].append(lane)
                if kind == HEAD:
                    if lane in active:
                        errors.append(f'HOLD_OVERLAP: {label} lane {lane} at row {index}')
                    active[lane] = index
            elif kind == BODY:
                if lane not in active:
                    errors.append(f'HOLD_ORPHAN: {label} body lane {lane} at row {index}')
            elif kind == TAIL:
                if lane not in active:
                    errors.append(f'HOLD_ORPHAN: {label} tail lane {lane} at row {index}')
                else:
                    start = active.pop(lane)
                    events[start]['holds'].append((index, lane))
                    if ms <= clock[start][1]:
                        errors.append(f'HOLD_DURATION: {label} lane {lane} nonpositive duration at row {index}')
            elif kind:
                errors.append(f'CELL_KIND: {label} unsupported {kind:#x} at row {index}, lane {lane}')
    if active:
        errors.append(f'HOLD_UNCLOSED: {label} open holds {sorted(active.items())}')
    return {'cols': cols, 'flat': flat, 'clock': clock, 'headers': heads,
            'events': events, 'raw': raw, 'rpb': max_rpb}


def _repeats(signatures, size):
    counts = Counter(tuple(signatures[i:i + size]) for i in range(max(0, len(signatures) - size + 1)))
    total = sum(counts.values())
    repeats = sum(n - 1 for n in counts.values())
    return {'window_onsets': size, 'windows': total, 'unique': len(counts),
            'repeated_windows': repeats, 'repeat_fraction': repeats / total if total else 0.,
            'maximum_multiplicity': max(counts.values(), default=0)}


def _replay(plan, clock, columns, speed, errors, pose_policy='balanced', drill_indices=frozenset(), level=20):
    coords = SINGLE if columns == 5 else DOUBLE
    span_limit = 2.9 if columns == 5 else 3.05
    positions = [0, 4] if columns == 5 else [3, 6]
    first_ms = clock[plan[0]['index']][1] if plan else (clock[0][1] if clock else 0.)
    last_times = [first_ms - 2000.] * 2
    held = [None, None]
    released = []
    previous_lanes, previous_ms, previous_single = None, -math.inf, None
    previous_facing, facing_ms = 0., first_ms - 2000.
    turn_window=[]
    pose_violations=[]
    metrics = {'moves': 0, 'setup_moves': 0, 'total_distance': 0., 'max_distance': 0.,
               'max_speed': 0., 'max_stance': 0., 'max_facing': 0., 'max_facing_delta': 0.,
               'travel_speed_limit': speed, 'stance_limit': span_limit,
               'geometry': 'independent foot support anchors; limited simultaneous single-foot recovery bracket candidates',
               'bracket_rows':0,
               'pose_policy':pose_policy, 'rapid_diagonal_reversals':0,
               'max_recent_turn_degrees':0.,'pose_review_events':pose_violations,
               'body_orientation_certified':False}

    def release(now, index=None):
        for foot, hold in enumerate(held):
            if hold and ((index is not None and hold[0] <= index) or
                         (index is None and hold[1] <= now + EPS)):
                end, tail_ms, tail_beat, lane = hold
                last_times[foot] = max(last_times[foot], tail_ms)
                released.append((lane, tail_ms, tail_beat, foot))
                held[foot] = None

    def geometry(new_positions, now, where):
        nonlocal previous_facing, facing_ms
        if new_positions[0] == new_positions[1]:
            errors.append(f'FOOT_COLLISION: {where} both feet on lane {new_positions[0]}')
            return
        left, right = (coords[p] for p in new_positions)
        facing = math.degrees(math.atan2(-(right[1] - left[1]), right[0] - left[0]))
        span = math.dist(left, right)
        delta = abs(facing - previous_facing)
        metrics['max_stance'] = max(metrics['max_stance'], span)
        metrics['max_facing'] = max(metrics['max_facing'], abs(facing))
        metrics['max_facing_delta'] = max(metrics['max_facing_delta'], delta)
        if span > span_limit + EPS:
            errors.append(f'FOOT_STANCE: {where} span {span:.6f} > {span_limit}')
        if abs(facing) > 60. + EPS:
            errors.append(f'FOOT_FACING: {where} facing {facing:.6f} outside +/-60 degrees')
        if now - facing_ms < 900. - EPS and delta > 90. + EPS:
            errors.append(f'FOOT_TURN: {where} facing changes {delta:.6f} degrees in {now-facing_ms:.6f} ms')
        # Independent replay of the anti-spin contact-proxy policy. This
        # detects invalid traces even if the composer is bypassed or modified.
        # The contact line is NOT a measured torso angle.
        if pose_policy not in ('strict','guarded','balanced','off'):
            errors.append(f'POSE_POLICY: unknown {pose_policy!r}')
        if previous_facing*facing < -EPS:
            metrics['rapid_diagonal_reversals'] += 1
            if len(pose_violations)<150:
                pose_violations.append({'where':where,'time_ms':now,
                    'previous_stance_angle':previous_facing,'next_stance_angle':facing,
                    'gap_ms':now-facing_ms,'manual_review_required':True})
            if pose_policy in ('strict','guarded') and now-facing_ms<(1050. if pose_policy=='strict' else 450.)-EPS:
                errors.append(f'FOOT_SPIN_DIRECT_REVERSAL: {where} opposite diagonals in {now-facing_ms:.3f} ms')
        if pose_policy in ('strict','guarded','balanced'):
            window_ms,budget={'strict':(1550.,170.),'guarded':(850.,230.),'balanced':(650.,300.)}[pose_policy]
            turn_window[:]=[(t,d) for t,d in turn_window if now-t<window_ms-EPS]
            recent_turn=sum(d for _,d in turn_window)+delta
            metrics['max_recent_turn_degrees']=max(metrics['max_recent_turn_degrees'],recent_turn)
            if recent_turn>budget+EPS:
                errors.append(f'FOOT_SPIN_OSCILLATION: {where} {recent_turn:.1f} degrees in {window_ms:.0f} ms')
            if delta>EPS:turn_window.append((now,delta))
        previous_facing, facing_ms = facing, now

    def move(foot, lane, now, where, attack):
        if held[foot] is not None:
            errors.append(f'FOOT_PINNED: {where} moves/represses foot {foot} before hold tail')
        dt = now - last_times[foot]
        distance = math.dist(coords[positions[foot]], coords[lane])
        if dt < -EPS or distance > .75 + speed * max(0., dt) / 1000. + EPS:
            errors.append(f'FOOT_TRAVEL: {where} foot {foot} travels {distance:.6f} in {dt:.6f} ms')
        drill_repeat=(attack and columns==5 and level>=17 and
                      where.startswith('row ') and int(where[4:]) in drill_indices)
        repeat_floor=180. if drill_repeat else 300.
        if attack and lane == positions[foot] and dt < repeat_floor - EPS:
            errors.append(f'FOOT_RAPID_REPEAT: {where} foot {foot} repeats lane {lane} in {dt:.6f} ms')
        metrics['moves'] += 1
        metrics['total_distance'] += distance
        metrics['max_distance'] = max(metrics['max_distance'], distance)
        if distance and dt > 0:
            metrics['max_speed'] = max(metrics['max_speed'], distance * 1000. / dt)

    for item in plan:
        index = item['index']
        bt, now, _, _ = clock[index]
        setup_floor = previous_ms
        for setup in item.get('setups', []):
            if len(setup) != 3:
                errors.append(f'PLAN_SETUP: malformed setup at row {index}')
                continue
            foot, lane, when = setup
            if type(foot) is not int or foot not in (0, 1) or type(lane) is not int or not 0 <= lane < columns:
                errors.append(f'PLAN_SETUP: invalid foot/lane at row {index}')
                continue
            when = float(when)
            if not math.isfinite(when) or when < setup_floor - EPS or when > now + EPS:
                errors.append(f'PLAN_SETUP: setup outside chronological event interval at row {index}')
                continue
            setup_floor = when
            release(when)
            move(foot, lane, when, f'setup before row {index}', False)
            positions[foot], last_times[foot] = lane, when
            metrics['setup_moves'] += 1
            geometry(positions, when, f'setup before row {index}')
        release(now, index)
        lanes = tuple(sorted(a[0] for a in item['actions']))
        if previous_lanes == lanes and now - previous_ms < 300. - EPS:
            errors.append(f'ROW_RAPID_REPEAT: row {index} repeats previous lane set within 300 ms')
        if len(item['actions']) == 1 and previous_single == item['actions'][0][1] and now - previous_ms < 650. - EPS:
            other = 1 - previous_single
            recovering = any(f == other and last_times[other] <= tail_ms + 1e-5 and
                now - tail_ms < 350. - EPS and bt - tail_bt < .5 - EPS
                for _, tail_ms, tail_bt, f in released)
            if held[other] is None and not recovering:
                errors.append(f'FOOT_ALTERNATION: row {index} repeats a foot while the other is available')
        new_positions = positions[:]
        bracket=(len(item['actions'])==2 and
                 item['actions'][0][1]==item['actions'][1][1])
        if bracket:
            if not valid_bracket(item['actions'], level=level):
                errors.append(f'FOOT_BRACKET_UNSUPPORTED: row {index} unsupported bracket form')
            elif held[item['actions'][0][1]] is not None:
                errors.append(f'FOOT_BRACKET_HELD: row {index} bracket foot pinned')
            if any(a[0]==positions[1-item['actions'][0][1]] for a in item['actions']):
                errors.append(f'FOOT_BRACKET_COLLISION: row {index} non-bracket foot occupies bracket contact')
            metrics['bracket_rows']+=1
        used_feet = set()
        for lane, foot, end in item['actions']:
            if foot in used_feet and (not bracket or not valid_bracket(item['actions'],level=level)):
                errors.append(f'FOOT_MULTIACTION: row {index} assigns multiple lanes to foot {foot}')
            used_feet.add(foot)
            for released_lane, tail_ms, tail_bt, _ in released:
                if lane == released_lane and now - tail_ms < 350. - EPS and bt - tail_bt < .5 - EPS:
                    errors.append(f'HOLD_RECOVERY: row {index} represses released lane {lane} too soon')
            # A bracket has two source-aligned TAP heads but only one
            # center-of-foot trajectory; measure travel to its anchor once.
            if not bracket or lane==item['actions'][-1][0]:
                move(foot, lane, now, f'row {index}', True)
                new_positions[foot] = lane
        geometry(new_positions, now, f'row {index}')
        positions[:] = new_positions
        for lane, foot, end in item['actions']:
            last_times[foot] = now
            if end >= 0:
                end_bt, end_ms, _, _ = clock[end]
                held[foot] = (end, end_ms, end_bt, lane)
        previous_lanes, previous_ms = lanes, now
        previous_single = item['actions'][0][1] if len(item['actions']) == 1 else None
    return metrics


def validate(source_nx, output_nx, plan, timeline, source_events, columns, level,
             tier, ledger, travel_speed=None, pose_policy='balanced', recovery_policy='strict'):
    """Return evidence and errors; no provenance or physical failure is repaired.

    HARD retains every source attack. All tiers preserve every source hold and
    its exact end index. Chord reductions require one ledger row per removed
    source tap. Lower-tier whole-onset omissions require one explicit ledger row.
    Raw counts/entropy/repeats describe output cells; no engine scoring is claimed.
    """
    errors = []
    result = {'pass': False, 'errors': errors, 'sourceonsets': {}, 'heads': {},
              'holds': {}, 'retention': {}, 'timing': {}, 'footmetrics': {}, 'scorehealth': {}}
    tier = str(tier).upper()
    try:
        if columns not in (5, 10) or tier not in ('EASY', 'MEDIUM', 'HARD'):
            raise ValueError('Single/Double columns and EASY/MEDIUM/HARD tier required')
        speed = float(travel_speed if travel_speed is not None else 5 + level * .10)
        if not math.isfinite(speed) or speed <= 0:
            raise ValueError('positive finite travel_speed required')
        src, out = _decode(source_nx, 'source', errors), _decode(output_nx, 'output', errors)
        if out['cols'] != columns:
            errors.append('OUTPUT_COLUMNS: output cols differs from requested columns')
        headers_exact = src['headers'] == out['headers']
        if not headers_exact:
            errors.append('TIMING_HEADERS: output split timing headers differ from source')
        if len(src['clock']) != len(out['clock']):
            errors.append('TIMING_ROWS: source/output row counts differ')
        if len(timeline) != len(src['clock']):
            errors.append('TIMELINE: supplied source timeline has wrong row count')
        else:
            for i, (given, actual) in enumerate(zip(timeline, src['clock'])):
                if (len(given) != 4 or tuple(given[2:]) != actual[2:] or
                        abs(float(given[0]) - actual[0]) > EPS or abs(float(given[1]) - actual[1]) > 1e-5):
                    errors.append(f'TIMELINE: supplied source clock differs at row {i}')
                    break
        event_map = {int(e['index']): e for e in source_events}
        if len(event_map) != len(source_events) or set(event_map) != set(src['events']):
            errors.append('SOURCE_EVENTS: supplied events do not match decoded source onset indices')
        for i, actual in src['events'].items():
            e = event_map.get(i)
            if e is None:
                continue
            if (sorted(e['lanes']) != sorted(actual['lanes']) or
                    Counter(tuple(h) for h in e['holds']) != Counter(actual['holds']) or
                    abs(float(e['ms']) - actual['ms']) >= .1 or
                    abs(float(e['beat']) - actual['beat']) > EPS):
                errors.append(f'SOURCE_EVENTS: supplied event differs from decoded source at row {i}')
            for end, _ in actual['holds']:
                for key, offset in (('hold_ends_ms', 1), ('hold_ends_beat', 0)):
                    ends = e.get(key, {})
                    supplied = ends.get(end, ends.get(str(end)))
                    limit = .1 if offset else EPS
                    if supplied is None or abs(float(supplied) - src['clock'][end][offset]) >= limit:
                        errors.append(f'SOURCE_EVENTS: incorrect {key} at row {i}, tail {end}')
        expected = [[0] * columns for _ in src['clock']]
        normalized, plan_map = [], {}
        for item in plan:
            i = item['index']
            if type(i) is not int or not 0 <= i < len(expected) or i in plan_map:
                errors.append(f'PLAN_INDEX: invalid/duplicate row {i}')
                continue
            if normalized and i <= normalized[-1]['index']:
                errors.append(f'PLAN_ORDER: non-increasing row {i}')
            if not item['actions']:
                errors.append(f'PLAN_ACTIONS: empty onset at row {i}')
            actions = []
            for action in item['actions']:
                if len(action) != 3:
                    errors.append(f'PLAN_ACTIONS: malformed action at row {i}')
                    continue
                lane, foot, end = action
                if (any(type(x) is not int for x in action) or not 0 <= lane < columns or
                        foot not in (0, 1) or not (end == -1 or i < end < len(expected))):
                    errors.append(f'PLAN_ACTIONS: invalid lane/foot/tail at row {i}')
                    continue
                actions.append((lane, foot, end))
                for j in range(i, (end if end >= 0 else i) + 1):
                    kind = TAP if end == -1 else HEAD if j == i else TAIL if j == end else BODY
                    if expected[j][lane]:
                        errors.append(f'PLAN_OVERLAP: row {j}, lane {lane}')
                    expected[j][lane] = kind
            clean = dict(item, actions=actions)
            normalized.append(clean)
            plan_map[i] = clean
        if len(out['flat']) == len(expected):
            for i, (actual, wanted) in enumerate(zip(out['flat'], expected)):
                if tuple(actual) != tuple(wanted):
                    errors.append(f'CELL_PLAN: decoded output differs from plan at row {i}')
        src_events, out_events = src['events'], out['events']
        for i in set(out_events) - set(src_events):
            errors.append(f'INVENTED_ONSET: output attack at non-source row {i}')
        records = list(ledger or [])
        consumed = set()
        for i, e in src_events.items():
            target = out_events.get(i)
            matching = [(j, entry) for j, entry in enumerate(records) if entry.get('index') == i]
            if target is None:
                if tier == 'HARD':
                    errors.append(f'ONSET_LOSS: HARD source onset absent at row {i}')
                if e['holds']:
                    errors.append(f'HOLD_LOSS: source hold onset omitted at row {i}')
                omissions = [(j, entry) for j, entry in matching if entry.get('kind') == 'OMIT_ONSET']
                if tier == 'HARD' or len(omissions) != 1:
                    errors.append(f'LEDGER_OMISSION: row {i} needs exactly one permitted omission record')
                else:
                    j, entry = omissions[0]
                    if sorted(entry.get('source_lanes', [])) != sorted(e['lanes']):
                        errors.append(f'LEDGER_OMISSION: source lanes differ at row {i}')
                    consumed.add(j)
            else:
                lost = len(e['lanes']) - len(target['lanes'])
                reductions = [(j, entry) for j, entry in matching if entry.get('kind') == 'REDUCE_CHORD_HEAD']
                removed = [entry.get('source_lane') for _, entry in reductions]
                taps = set(e['lanes']) - {lane for _, lane in e['holds']}
                if lost < 0:
                    errors.append(f'HEAD_INVENTED: output has excess heads at row {i}')
                if columns == 10 and tier == 'HARD' and lost:
                    errors.append(f'DOUBLE_HARD_CARDINALITY: row {i} must preserve every source head')
                if len(reductions) != max(0, lost) or len(set(removed)) != len(removed) or any(l not in taps for l in removed):
                    errors.append(f'LEDGER_REDUCTION: row {i} head loss lacks exact individual source-tap records')
                else:
                    consumed.update(j for j, _ in reductions)
                if Counter(end for end, _ in e['holds']) != Counter(end for end, _ in target['holds']):
                    errors.append(f'HOLD_ENDS: row {i} source/output hold tail multiset differs')
        for j, entry in enumerate(records):
            if j not in consumed:
                errors.append(f'LEDGER_UNUSED: record {j} does not justify an actual permitted change')
            if not entry.get('reason') or entry.get('tier', tier) != tier:
                errors.append(f'LEDGER_METADATA: record {j} lacks reason or has wrong tier')
        head_errors, tail_errors = [], []
        for i, target in out_events.items():
            if i in src_events:
                head_errors.append(abs(target['ms'] - src_events[i]['ms']))
                source_ends = sorted(end for end, _ in src_events[i]['holds'])
                output_ends = sorted(end for end, _ in target['holds'])
                tail_errors.extend(abs(out['clock'][b][1] - src['clock'][a][1]) for a, b in zip(source_ends, output_ends))
        if max(head_errors + tail_errors + [0.]) >= .1:
            errors.append('TIMING_ERROR: source/output attack or tail error is >=0.1 ms')
        if any(abs(a[1] - b[1]) >= .1 or abs(a[0] - b[0]) > EPS for a, b in zip(src['clock'], out['clock'])):
            errors.append('TIMING_GRID: output row clock differs from source')
        drill_indices=set()
        ordered_src=[src_events[i] for i in sorted(src_events)]
        for d in range(len(ordered_src)-3):
            group=ordered_src[d:d+4]
            if any(len(e['lanes'])!=1 or e['holds'] for e in group):continue
            keys=[e['lanes'][0] for e in group]
            gaps=[group[j+1]['beat']-group[j]['beat'] for j in range(3)]
            if (keys[0]==keys[2] and keys[1]==keys[3] and keys[0]!=keys[1]
                and all(0<g<=.8 for g in gaps)):
                drill_indices.update(e['index'] for e in group)
        if recovery_policy not in ('strict','off'):
            errors.append('RECOVERY_POLICY: unknown recovery policy')
        if columns==5 and recovery_policy=='strict' and normalized:
            recovery=audit_recovery(normalized,src['clock'],level=level)
            result['recovery'] = recovery
            for issue in recovery['errors']:
                errors.append(f"RECOVERY_CONTRACT: row {issue['index']} {issue['reason']}")
            for row in normalized:
                declared=row.get('recovery_event')
                actual=next((x['event'] for x in recovery['decisions'] if x['index']==row['index']), 'NORMAL')
                if declared is not None and declared!=actual:
                    errors.append(f"RECOVERY_ANNOTATION: row {row['index']} declared {declared} actual {actual}")
        if out['cols'] == columns and normalized and all(normalized[n]['index'] < normalized[n + 1]['index'] for n in range(len(normalized) - 1)):
            result['footmetrics'] = _replay(normalized, src['clock'], columns, speed, errors,
                                           pose_policy if columns==5 else 'off', drill_indices, level)
        source_heads = sum(len(e['lanes']) for e in src_events.values())
        output_heads = sum(len(e['lanes']) for e in out_events.values())
        source_holds = sum(len(e['holds']) for e in src_events.values())
        output_holds = sum(len(e['holds']) for e in out_events.values())
        retained = len(set(src_events) & set(out_events))
        result['sourceonsets'] = {'source': len(src_events), 'output': len(out_events), 'retained': retained}
        result['heads'] = {'source': source_heads, 'output': output_heads, 'removed': source_heads - output_heads}
        result['holds'] = {'source': source_holds, 'output': output_holds, 'all_preserved': source_holds == output_holds and not any(x.startswith(('HOLD_ENDS:', 'HOLD_LOSS:')) for x in errors)}
        result['retention'] = {'onset_fraction': retained / len(src_events) if src_events else 1.,
            'head_fraction': output_heads / source_heads if source_heads else 1.,
            'hold_fraction': output_holds / source_holds if source_holds else 1.,
            'ledger_entries': len(records), 'onset_omissions': sum(e.get('kind') == 'OMIT_ONSET' for e in records),
            'head_reductions': sum(e.get('kind') == 'REDUCE_CHORD_HEAD' for e in records)}
        result['timing'] = {'headers_exact': headers_exact, 'max_head_error_ms': max(head_errors, default=0.),
            'max_tail_error_ms': max(tail_errors, default=0.), 'source_rows': len(src['clock']),
            'output_rows': len(out['clock']), 'max_rows_per_beat': max(src['rpb'], out['rpb'])}
        lane_counts = Counter(lane for e in out_events.values() for lane in e['lanes'])
        entropy = -sum((n / output_heads) * math.log2(n / output_heads) for n in lane_counts.values()) if output_heads else 0.
        signatures = [tuple(sorted(e['lanes'])) for _, e in sorted(out_events.items())]
        result['scorehealth'] = {'tap_heads': out['raw'][TAP], 'hold_heads': out['raw'][HEAD],
            'hold_body_ticks': out['raw'][BODY], 'hold_tail_ticks': out['raw'][TAIL],
            'raw_nonempty_cells': sum(out['raw'].values()), 'head_lane_counts': [lane_counts[i] for i in range(columns)],
            'lane_entropy_bits': entropy, 'lane_entropy_normalized': entropy / math.log2(columns),
            'repeated4windows': _repeats(signatures, 4), 'repeated8windows': _repeats(signatures, 8),
            'interpretation': 'raw decoded-cell statistics; no native score or difficulty calibration claimed'}
    except (KeyError, TypeError, ValueError, IndexError, OverflowError) as exc:
        errors.append(f'INVALID_INPUT: {exc}')
    result['pass'] = not errors
    return result