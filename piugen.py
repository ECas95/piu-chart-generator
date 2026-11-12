#!/usr/bin/env python3
"""Genera charts PIU (Single + Double, 4 niveles cada uno) a partir de OTRO chart.

  python piugen.py CANCION.sm|.ssc|.bms|.bme|.NX --out SALIDA [--title T] [--artist A] [--djmax] [--lead-in-ms N]

Entrada  : SM/SSC (dance-single/double o pump-*), BMS/BME 5 teclas (BPM constante), o NX PRIME ya convertido.
Salida   : SALIDA/<id>/{Single,Double}_T0..T3.NX (+ .json con recibo y gate) y SALIDA/<id>/song.ssc (StepMania 5).
Variante : F (por defecto, la elegida por el usuario). Cambiar con --variant A|B|C|D|E|F.
Requisitos: Python >= 3.11 y numpy (solo para estimar el nivel con data/official_chart_metrics.json).
"""
import argparse, hashlib, inspect, json, os, re, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
LIB = HERE / 'lib'
sys.path[:0] = [str(LIB), str(LIB / 'engine')]


def to_nx(path, chart_pick=None):
    """Devuelve (nx_dict, info) con el chart fuente en el formato interno NX (5 columnas)."""
    ext = path.suffix.lower()
    raw = path.read_bytes()
    from hybrid import nx20
    if ext == '.nx':
        nx = nx20.parse(raw)
        if nx['cols'] not in (5, 10):
            raise SystemExit('El NX de entrada debe ser Single (5 columnas) o Double (10).')
        return nx, dict(kind='NX')
    if ext in ('.bms', '.bme', '.bml'):
        from hybrid import bms_adapter
        res = bms_adapter.adapt_bytes(raw)
        return res[0], dict(kind='BMS', audit=res[1] if len(res) > 1 else None)
    if ext in ('.sm', '.ssc'):
        import nx_adapter as A
        SM = A.SM
        meta, charts = SM.parse(raw, extension=ext)
        # fuente: el Single mas dificil; solo si no hay ningun Single, el Double mas dificil
        pool = [c for c in charts if c['mode'] in ('dance-single', 'pump-single')] or                [c for c in charts if c['mode'] in ('dance-double', 'pump-double')]
        if not pool:
            raise SystemExit('El simfile no tiene charts single ni double (dance-/pump-).')
        chart = max(pool, key=lambda c: (float(c['meter']), sum(c['note_symbols'].get(ch, 0) for ch in '124')))
        print(f"Fuente: {chart['mode']} meter {chart['meter']} ({chart.get('difficulty', '')})")
        for field in ('SPEEDS', 'SCROLLS'):
            if any(v != 1 for _, v in SM.pairs(chart['timing'].get(field, ''))):
                print(f'AVISO: el chart fuente tiene {field} variables; solo cambian la velocidad visual, no el tiempo de las notas. '
                      'Los charts generados salen con velocidad constante.')
        # igual que produccion: source_grid sin su auditoria final (devuelve nx, musical)
        code = inspect.getsource(A.source_grid).split('\n    actual=sorted')[0] + '\n    return nx,musical\n'
        env = dict(A.__dict__)
        exec(compile(code, '<source_grid_sin_auditoria>', 'exec'), env)
        nx, _ = env['source_grid'](chart)
        return nx, dict(kind='SM', meter=int(float(chart['meter'])), chart=chart['mode'] + ' ' + str(chart['meter']), meta={k: meta.get(k) for k in ('TITLE', 'ARTIST', 'MUSIC') if isinstance(meta, dict)})
    raise SystemExit(f'Extension no soportada: {ext}')


TIMING_TAGS = {'VERSION', 'OFFSET', 'BPMS', 'STOPS', 'DELAYS', 'WARPS', 'TIMESIGNATURES', 'TICKCOUNTS', 'COMBOS',
               'SPEEDS', 'SCROLLS', 'FAKES', 'LABELS'}
TAG = re.compile(r'#([A-Za-z0-9_]+):(.*?);', re.S)


def header_tags(text):
    """Etiquetas globales de un simfile (todo lo anterior al primer #NOTEDATA / #NOTES), en orden."""
    text = re.sub(r'(?<!:)//[^\r\n]*', '', text)
    end = min([m.start() for m in (re.search(r'#NOTEDATA\s*:', text), re.search(r'#NOTES\s*:', text)) if m] or [len(text)])
    return [(k.upper(), v) for k, v in TAG.findall(text[:end])]


def merge_header(generated, original_text, original_ext):
    """song.ssc final = cabecera ORIGINAL + charts originales intactos + los 8 generados (marcados Edit para no pisar
    las casillas de dificultad de los originales). Cada chart generado lleva su propio timing."""
    NL = '\n'
    head, sep, body = generated.partition(NL + '//---------------')
    gen = dict(TAG.findall(head))
    tags = header_tags(original_text)
    if not any(k == 'VERSION' for k, _ in tags):
        tags.insert(0, ('VERSION', gen['VERSION']))
    body = re.sub(r'#DIFFICULTY:[^;]*;', '#DIFFICULTY:Edit;', body)
    text = NL.join(f'#{k}:{v};' for k, v in tags) + NL
    i = original_text.find('#NOTEDATA')
    if original_ext == '.ssc' and i >= 0:
        text += NL + '//--------------- charts originales ---------------' + NL + original_text[i:].strip(NL) + NL
    elif original_ext == '.sm':
        print('AVISO: el original es .sm; sus charts no se copian al .ssc (conviertelo a .ssc para conservarlos).')
    return text + NL + '//--------------- charts generados (piugen) ---------------' + sep + body


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('input', type=Path)
    p.add_argument('--out', required=True, type=Path)
    p.add_argument('--id', help='nombre de la carpeta de salida (por defecto el nombre del archivo)')
    p.add_argument('--title'); p.add_argument('--artist', default='')
    p.add_argument('--music', help='archivo de audio que escribir en #MUSIC del .ssc (por defecto el del simfile o Song.ogg)')
    p.add_argument('--djmax', action='store_true', help='fuente de teclado DJMAX: acordes dentro de streams pasan a nota simple')
    p.add_argument('--lead-in-ms', type=int, default=0, help='descarta notas originales antes de este tiempo y empieza en el primer beat fuerte')
    p.add_argument('--variant', default='F', choices=list('ABCDEF'))
    p.add_argument('--no-ssc', action='store_true')
    p.add_argument('--no-keep-metadata', action='store_true', help='con SM/SSC de entrada, NO copiar su cabecera ni sus charts originales')
    a = p.parse_args()
    if a.input.is_dir():     # carpeta de cancion: usa su unico .ssc/.sm (ignorando salidas "REVIEW" de generaciones previas)
        found = sorted(f for ext in ('.ssc', '.sm') for f in a.input.glob('*' + ext))
        # fuera: salidas de piugen (llevan CREDIT piugen) y las "REVIEW" de generaciones previas
        found = [f for f in found if not re.search(r'review', f.stem, re.I) and b'piugen' not in f.read_bytes()] or found
        if len(found) > 1 and any(f.suffix.lower() == '.ssc' for f in found):
            found = [f for f in found if f.suffix.lower() == '.ssc']
        if len(found) != 1:
            raise SystemExit('La carpeta debe tener un solo .ssc/.sm; pasa el archivo. Candidatos: ' + ', '.join(f.name for f in found))
        print('Usando', found[0])
        a.id = a.id or re.sub(r'[^\w.-]+', '_', a.input.name)
        a.input = found[0]

    os.environ['PIU_VARIANT'] = a.variant          # lo leen hybrid.composer / hybrid.musical al importarse
    gid = re.sub(r'[^\w.-]+', '_', a.id or a.input.stem)
    work = a.out / '_fuente'; work.mkdir(parents=True, exist_ok=True)

    nx, info = to_nx(a.input)
    from hybrid import nx20
    data = nx20.build(nx)
    nx_path = work / f'{gid}_Single.NX'; nx_path.write_bytes(data)
    ref_path = work / f'{gid}_Single.json'
    ref_path.write_text(json.dumps(dict(game_song_id=gid, title=a.title or a.input.stem, mode='Single', file=str(nx_path),
                                        sha256=hashlib.sha256(data).hexdigest(), source=info), default=str), encoding='utf8')

    import faithful
    faithful.LEVEL_CAP = info.get('meter')   # nada generado por encima del nivel del original (sin meter: el estimado del Single completo)
    res = faithful.song(dict(gid=gid, ref=str(ref_path), out=str(a.out), lead_in_ms=a.lead_in_ms, djmax=a.djmax))
    print(f"{gid}: {len(res['charts'])} charts, {len(res['errors'])} errores, {res.get('seconds', 0):.0f}s")
    for c in res['charts']:
        print(f"  {c['mode']:6} T{c['tier']} nivel {c['level']:>2}  notas {c['rows']:>5}  ({c['reduction']})")
    for e in res['errors']:
        print('  ERROR', e)

    keep = info['kind'] == 'SM' and not a.no_keep_metadata
    if not a.no_ssc and res['charts']:
        import nx_ssc
        charts = [(nx20.parse(Path(c['nx']).read_bytes()), f"{c['mode'][0]}{c['level']}_T{c['tier']}", c['level'],
                   f"T{c['tier']} ({c['reduction']})", 'piugen') for c in res['charts']]
        worst = max(nx_ssc.check(c[0]) for c in charts)
        music = a.music or (info.get('meta') or {}).get('MUSIC') or 'Song.ogg'
        out = a.out / gid / 'song.ssc'
        text = nx_ssc.song_ssc(a.title or a.input.stem, a.artist, music, '', 0.0, charts)
        if keep:
            text = merge_header(text, a.input.read_bytes().decode('utf-8-sig', 'replace'), a.input.suffix.lower())
            for k, v in (('TITLE', a.title), ('ARTIST', a.artist or None), ('MUSIC', a.music)):   # solo si se pasan explicitamente
                if v:
                    text = re.sub(rf'#{k}:[^;]*;', lambda m: f'#{k}:{v};', text, count=1)
        out.write_text(text, encoding='utf8')
        print(f'SSC: {out}  (desvio de reloj max {worst:.2f} ms)')


if __name__ == '__main__':
    main()
